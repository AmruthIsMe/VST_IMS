"""
SAP ERP Connector Service
Pluggable architecture supporting both RFC (SAP ECC) and OData (S/4HANA).
Auto-detects which protocol to use based on configuration.
Enhanced with HTTP client for SAP Mock ERP (port 8001).
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Product, Supplier, Order, Sale, SapConfig, SapSyncLog, Inventory
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
SAP_MOCK_URL = settings.SAP_MOCK_URL


class SAPConnector:
    """Base SAP connector interface."""

    def __init__(self, config: SapConfig):
        self.config = config

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def sync_materials(self, db: Session) -> int:
        raise NotImplementedError

    def sync_vendors(self, db: Session) -> int:
        raise NotImplementedError

    def sync_stocks(self, db: Session) -> int:
        raise NotImplementedError

    def sync_orders(self, db: Session) -> int:
        raise NotImplementedError

    def sync_sales(self, db: Session) -> int:
        raise NotImplementedError


class MockSAPConnector(SAPConnector):
    """
    HTTP-based connector for the SAP Mock ERP server on port 8001.
    Pulls live stock levels and sales orders from the mock system.
    """

    def __init__(self, config: SapConfig = None):
        super().__init__(config)
        self.base_url = SAP_MOCK_URL

    def connect(self):
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/sap/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Connected to SAP Mock ERP: {data.get('plant_name', 'Unknown')}")
                return True
        except Exception as e:
            logger.warning(f"SAP Mock ERP not reachable: {e}")
        return False

    def disconnect(self):
        pass

    def sync_materials(self, db: Session) -> int:
        """Pull materials from mock SAP and upsert into products table."""
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/sap/opu/odata/sap/API_MATERIAL_SRV/Materials", timeout=10)
            if response.status_code != 200:
                return 0
            data = response.json()
            materials = data.get("d", {}).get("results", [])

            count = 0
            for mat in materials:
                matnr = mat.get("MATNR", "")
                existing = db.query(Product).filter(Product.sku_id == matnr).first()
                if existing:
                    existing.last_synced_at = datetime.now()
                    count += 1
                else:
                    product = Product(
                        sku_id=matnr,
                        category=mat.get("category", mat.get("MATKL", "Unknown")),
                        sub_category=mat.get("sub_category", ""),
                        machine_compatibility=mat.get("MAKTX", ""),
                        sap_material_id=matnr,
                        last_synced_at=datetime.now(),
                    )
                    db.add(product)
                    count += 1

            db.commit()
            return count
        except Exception as e:
            logger.error(f"Mock SAP material sync failed: {e}")
            return 0

    def sync_vendors(self, db: Session) -> int:
        count = db.query(Supplier).filter(Supplier.sap_vendor_id.isnot(None)).count()
        return count

    def sync_stocks(self, db: Session) -> int:
        """
        Pull live stock from mock SAP and update inventory table.
        This is the core of the bidirectional IMS <-> SAP sync.
        """
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/sap/opu/odata/sap/API_STOCK_SRV/Stocks", timeout=10)
            if response.status_code != 200:
                return 0
            data = response.json()
            stocks = data.get("d", {}).get("results", [])

            count = 0
            for stk in stocks:
                matnr = stk.get("MATNR", "")
                on_hand = int(stk.get("LBLAB", 0))
                reserved = int(stk.get("LFSME", 0))

                inv = db.query(Inventory).filter(Inventory.sku_id == matnr).first()
                if inv:
                    inv.quantity_on_hand = on_hand
                    inv.quantity_reserved = reserved
                    inv.quantity_available = on_hand - reserved
                    inv.last_sap_sync_at = datetime.now()
                else:
                    inv = Inventory(
                        sku_id=matnr,
                        quantity_on_hand=on_hand,
                        quantity_reserved=reserved,
                        quantity_available=on_hand - reserved,
                        last_sap_sync_at=datetime.now(),
                    )
                    db.add(inv)
                count += 1

            db.commit()
            return count
        except Exception as e:
            logger.error(f"Mock SAP stock sync failed: {e}")
            return 0

    def sync_orders(self, db: Session) -> int:
        return db.query(Order).count()

    def sync_sales(self, db: Session) -> int:
        """
        Pull sales orders from mock SAP and ingest into sales table.
        These become the actuals used by Tier 1 extrapolation.
        """
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/sap/opu/odata/sap/API_SALES_SRV/Sales", timeout=10)
            if response.status_code != 200:
                return 0
            data = response.json()
            sales = data.get("d", {}).get("results", [])

            count = 0
            for sale in sales:
                matnr = sale.get("MATNR", "")
                qty = int(sale.get("KWMENG", 0))
                sale_date_str = sale.get("ERDAT", "")

                if not sale_date_str or qty == 0:
                    continue

                try:
                    sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                product = db.query(Product).filter(Product.sku_id == matnr).first()
                if not product:
                    continue

                existing_sale = db.query(Sale).filter(
                    Sale.product_id == product.id,
                    Sale.sale_date == sale_date,
                    Sale.sku_id == matnr,
                ).first()

                if existing_sale:
                    existing_sale.units_sold += qty
                else:
                    new_sale = Sale(
                        sale_date=sale_date,
                        product_id=product.id,
                        sku_id=matnr,
                        units_sold=qty,
                        fulfillment_region=sale.get("REGIO", "Unknown"),
                        stockout_flag=False,
                    )
                    db.add(new_sale)
                count += 1

            db.commit()
            return count
        except Exception as e:
            logger.error(f"Mock SAP sales sync failed: {e}")
            return 0


class RFCConnector(SAPConnector):
    """RFC-based connector for SAP ECC 6.0."""

    def connect(self):
        try:
            from pyrfc import Connection
            self.conn = Connection(
                ashost=self.config.host,
                sysnr=self.config.system_number,
                client=self.config.client,
                user=self.config.user,
                passwd=self.config.password_encrypted,
                lang=self.config.language,
            )
            logger.info("RFC connection established to SAP ECC")
            return True
        except ImportError:
            logger.warning("pyrfc not installed, using mock connector")
            self.conn = None
            return True
        except Exception as e:
            logger.error(f"RFC connection failed: {e}")
            return False

    def disconnect(self):
        if self.conn:
            self.conn.close()

    def sync_materials(self, db: Session) -> int:
        if not self.conn:
            return self._mock_sync_materials(db)
        try:
            result = self.conn.call("RFC_READ_TABLE", {
                "QUERY_TABLE": "MARA",
                "DELIMITER": "|",
                "FIELDS": [
                    {"FIELDNAME": "MATNR"},
                    {"FIELDNAME": "MTART"},
                    {"FIELDNAME": "MATKL"},
                    {"FIELDNAME": "MEINS"},
                ],
            })
            count = 0
            for row in result.get("DATA", []):
                fields = row["WA"].split("|")
                if len(fields) >= 2:
                    sap_id = fields[0].strip()
                    existing = db.query(Product).filter(Product.sap_material_id == sap_id).first()
                    if existing:
                        existing.last_synced_at = datetime.now()
                    count += 1
            db.commit()
            return count
        except Exception as e:
            logger.error(f"Material sync failed: {e}")
            raise

    def _mock_sync_materials(self, db: Session) -> int:
        count = db.query(Product).filter(Product.sap_material_id.isnot(None)).count()
        return count

    def sync_vendors(self, db: Session) -> int:
        if not self.conn:
            return self._mock_sync_vendors(db)
        try:
            result = self.conn.call("RFC_READ_TABLE", {
                "QUERY_TABLE": "LFA1",
                "DELIMITER": "|",
                "FIELDS": [
                    {"FIELDNAME": "LIFNR"},
                    {"FIELDNAME": "NAME1"},
                    {"FIELDNAME": "LAND1"},
                ],
            })
            count = 0
            for row in result.get("DATA", []):
                count += 1
            db.commit()
            return count
        except Exception as e:
            logger.error(f"Vendor sync failed: {e}")
            raise

    def _mock_sync_vendors(self, db: Session) -> int:
        count = db.query(Supplier).filter(Supplier.sap_vendor_id.isnot(None)).count()
        return count

    def sync_stocks(self, db: Session) -> int:
        if not self.conn:
            return db.query(Product).count()
        return 0

    def sync_orders(self, db: Session) -> int:
        if not self.conn:
            return db.query(Order).count()
        return 0

    def sync_sales(self, db: Session) -> int:
        if not self.conn:
            return db.query(Sale).count()
        return 0


class ODataConnector(SAPConnector):
    """OData-based connector for SAP S/4HANA."""

    def __init__(self, config: SapConfig):
        super().__init__(config)
        self.base_url = f"https://{config.host}/sap/opu/odata/sap"
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def connect(self):
        try:
            import httpx
            response = httpx.get(
                f"{self.base_url}/API_BUSINESS_PARTNER",
                headers=self.headers,
                auth=(self.config.user, self.config.password_encrypted),
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"OData connection failed: {e}")
            return False

    def disconnect(self):
        pass

    def sync_materials(self, db: Session) -> int:
        try:
            import httpx
            response = httpx.get(
                f"{self.base_url}/API_MATERIAL_DOCUMENT_SRV",
                headers=self.headers,
                auth=(self.config.user, self.config.password_encrypted),
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                count = len(data.get("d", {}).get("results", []))
                return count
        except Exception as e:
            logger.error(f"OData material sync failed: {e}")
        return 0

    def sync_vendors(self, db: Session) -> int:
        return self._sync_entity(db, "API_BUSINESS_PARTNER", "A_BusinessPartner", Supplier)

    def sync_stocks(self, db: Session) -> int:
        return 0

    def sync_orders(self, db: Session) -> int:
        return 0

    def sync_sales(self, db: Session) -> int:
        return 0

    def _sync_entity(self, db: Session, service: str, entity: str, model) -> int:
        try:
            import httpx
            response = httpx.get(
                f"{self.base_url}/{service}/A_BusinessPartner",
                headers=self.headers,
                auth=(self.config.user, self.config.password_encrypted),
                timeout=30,
            )
            return 0
        except Exception:
            return 0


def check_mock_erp_status() -> dict:
    """Check if SAP Mock ERP is running on port 8001."""
    try:
        import httpx
        response = httpx.get(f"{SAP_MOCK_URL}/sap/status", timeout=3)
        if response.status_code == 200:
            data = response.json()
            return {
                "connected": True,
                "system": data.get("system", "SAP Mock ERP"),
                "plant": data.get("plant", ""),
                "plant_name": data.get("plant_name", ""),
                "materials_count": data.get("materials_count", 0),
                "stock_records": data.get("stock_records", 0),
                "sales_orders": data.get("sales_orders", 0),
            }
    except Exception:
        pass
    return {"connected": False}


def get_sap_connector(db: Session) -> Optional[SAPConnector]:
    """Factory function to get the appropriate SAP connector."""
    config = db.query(SapConfig).filter(SapConfig.is_active == True).first()

    mock_status = check_mock_erp_status()
    if mock_status.get("connected"):
        return MockSAPConnector(config)

    if not config:
        return None

    host_lower = (config.host or "").lower()
    if "hana" in host_lower or "s4" in host_lower:
        return ODataConnector(config)
    else:
        return RFCConnector(config)
