"""
SAP Mock ERP Server (Standalone)
Simulates SAP ECC/S-4HANA on port 8001.

Serves the REAL VST product catalog (data/dim_products.csv) and generates
synthetic weekly sales history that statistically mirrors the historical
demand in data/fact_sales.csv (per-SKU mean/std, Indian agri seasonality).

Enhancements:
  - Multi-item batch orders (1-3 SKUs per sales order, 1-5 per purchase order)
  - Purchase orders (incoming stock from suppliers)
  - Stock adjusts per order (sales decrease, PO receipts increase)
  - last_sync_date parameter for incremental generation
  - Stock movements ledger (IN/OUT)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from typing import Optional
import random
import os
import uuid
import logging
import math

logger = logging.getLogger("sap_mock_erp")

app = FastAPI(title="SAP Mock ERP", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PLANT_ID = "1000"
PLANT_NAME = "VST Main Warehouse - Bidar"
HISTORY_START = date(2022, 1, 3)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

LEGACY_MATERIALS = [
    {"MATNR": "SP-001", "MAKTX": "Tractor Bearing 6205", "MTART": "HALB", "MATKL": "Bearings", "MEINS": "EA", "LBST": 15, "category": "Spare Parts", "sub_category": "Bearings"},
    {"MATNR": "EP-001", "MAKTX": "Monoblock Pump 1HP", "MTART": "FERT", "MEINS": "EA", "LBST": 8, "category": "Electric Pumps", "sub_category": "Monoblock Pump"},
    {"MATNR": "EN-001", "MAKTX": "3-Cyl Diesel Engine", "MTART": "FERT", "MEINS": "EA", "LBST": 30, "category": "Engines", "sub_category": "3-Cylinder"},
]

CATEGORY_DEMAND_FALLBACK = {
    "Engines": (5, 15),
    "Electric Pumps": (20, 60),
    "Lubricants": (100, 500),
    "Spare Parts": (30, 150),
    "Precision Components": (10, 40),
}

REGIONS = ["Karnataka", "Maharashtra", "Andhra Pradesh", "Telangana", "Tamil Nadu"]
CUSTOMERS = [
    "Rajesh Farm Equipment", "Karnataka Agri Stores", "Deccan Tractors",
    "VST Dealer Hub", "South India Farming Co", "Bharat Agri Solutions",
    "Madhav Traders", "Sri Ganesh Industries", "National Equipment", "Global Supplies",
]

MATERIALS = []
SUPPLIERS = []
DEMAND_PROFILE = {}
STOCK = {}
SALES_ORDERS = []
PURCHASE_ORDERS = []
STOCK_MOVEMENTS = []
CYCLE_LOG = []
LAST_GENERATED_WEEK = None
LIVE_WEEK_LAST_DAY = None
LAST_PO_GENERATED_DAY = None


def _load_catalog():
    global MATERIALS
    csv_path = os.path.join(DATA_DIR, "dim_products.csv")
    materials = []
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sku = (row.get("SKU_ID") or "").strip()
                if not sku:
                    continue
                materials.append({
                    "MATNR": sku,
                    "MAKTX": row.get("Product_Name") or sku,
                    "MTART": "FERT" if sku.startswith("EN") else "HALB",
                    "MATKL": row.get("Category", ""),
                    "MEINS": "EA",
                    "LBST": 10,
                    "category": row.get("Category", "Unknown"),
                    "sub_category": row.get("Sub_Category", ""),
                })
    if not materials:
        logger.warning("dim_products.csv not found or empty; using legacy material list")
        materials = list(LEGACY_MATERIALS)
    MATERIALS = materials
    return materials


def _load_suppliers():
    global SUPPLIERS
    csv_path = os.path.join(DATA_DIR, "dim_suppliers.csv")
    suppliers = []
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sid = (row.get("Supplier_ID") or "").strip()
                if not sid:
                    continue
                suppliers.append({
                    "LIFNR": sid,
                    "NAME1": f"{row.get('Origin_Country', 'Unknown')} Supply Co ({sid})",
                    "LAND1": row.get("Origin_Country", "Unknown"),
                    "primary_category": row.get("Primary_Category", ""),
                    "lead_time_days": int(row.get("Base_Lead_Time_Days", 30)),
                    "moq": int(row.get("Minimum_Order_Quantity", 10)),
                })
    SUPPLIERS = suppliers if suppliers else [
        {"LIFNR": "SUP-001", "NAME1": "Default Supplier", "LAND1": "India",
         "primary_category": "", "lead_time_days": 14, "moq": 10},
    ]
    return SUPPLIERS


def _load_demand_profiles():
    global DEMAND_PROFILE
    profiles = {}
    csv_path = os.path.join(DATA_DIR, "fact_sales.csv")
    if os.path.exists(csv_path):
        import csv
        sums, counts, sq_sums = {}, {}, {}
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sku = (row.get("SKU_ID") or "").strip()
                try:
                    units = float(row.get("Units_Sold", 0))
                except ValueError:
                    continue
                sums[sku] = sums.get(sku, 0.0) + units
                counts[sku] = counts.get(sku, 0) + 1
                sq_sums[sku] = sq_sums.get(sku, 0.0) + units * units
        for sku, n in counts.items():
            mean = sums[sku] / n
            var = max(sq_sums[sku] / n - mean * mean, 0.0)
            profiles[sku] = {"mean": mean, "std": math.sqrt(var)}
    DEMAND_PROFILE = profiles
    return profiles


def _seasonal_factor(d: date) -> float:
    month = d.month
    if month in (10, 11, 12):
        return random.uniform(1.2, 1.8)
    if month in (3, 4, 5):
        return random.uniform(1.1, 1.3)
    if month in (6, 7, 8, 9):
        return random.uniform(1.2, 1.5)
    return random.uniform(0.9, 1.1)


def _weekly_quantity(mat: dict, d: date) -> int:
    sku = mat["MATNR"]
    prof = DEMAND_PROFILE.get(sku)
    if prof and prof["mean"] > 0:
        base = prof["mean"]
        std = min(prof["std"], base * 0.6)
        qty = random.gauss(base * _seasonal_factor(d), std)
    else:
        lo, hi = CATEGORY_DEMAND_FALLBACK.get(mat.get("category", ""), (10, 50))
        qty = random.uniform(lo, hi) * _seasonal_factor(d)
    return max(0, int(round(qty)))


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _daily_quantity(mat: dict, d: date) -> int:
    weekly = _weekly_quantity(mat, d)
    return max(0, int(round((weekly / 7.0) * random.uniform(0.5, 1.5))))


def _pick_batch_size(max_items: int = 3) -> int:
    r = random.random()
    if r < 0.45:
        return 1
    elif r < 0.80:
        return 2
    return min(3, max_items)


def _pick_items_for_order(max_items: int = 3) -> list[dict]:
    batch_size = _pick_batch_size(max_items)
    chosen = random.sample(MATERIALS, min(batch_size, len(MATERIALS)))
    items = []
    for mat in chosen:
        qty = _daily_quantity(mat, date.today()) if date.today() else _weekly_quantity(mat, date.today())
        if qty <= 0:
            qty = random.randint(1, 10)
        items.append({
            "MATNR": mat["MATNR"],
            "MAKTX": mat.get("MAKTX", ""),
            "KWMENG": qty,
            "MEINS": mat.get("MEINS", "EA"),
            "NETWR": round(qty * random.uniform(500, 2500), 2),
            "category": mat.get("category", ""),
        })
    return items


def _record_stock_movement(matnr: str, quantity: int, direction: str,
                           movement_type: str, order_id: str, order_date: str):
    if matnr not in STOCK:
        return
    stk = STOCK[matnr]
    if direction == "OUT":
        stk["LBLAB"] = max(0, stk["LBLAB"] - quantity)
    else:
        stk["LBLAB"] += quantity
    stk["Last_Updated"] = datetime.now().isoformat()
    STOCK_MOVEMENTS.append({
        "id": str(uuid.uuid4())[:8],
        "MATNR": matnr,
        "quantity": quantity,
        "direction": direction,
        "movement_type": movement_type,
        "order_id": order_id,
        "order_date": order_date,
        "stock_after": stk["LBLAB"],
        "timestamp": datetime.now().isoformat(),
    })


def _generate_sales_order_batch(d: date):
    """Generate 1-3 multi-item sales orders per day."""
    num_orders = random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
    so_counter = len(SALES_ORDERS)
    for _ in range(num_orders):
        items = _pick_items_for_order(max_items=3)
        if not items:
            continue
        total = sum(it["NETWR"] for it in items)
        vbeln = f"SO{900000 + so_counter}"
        order = {
            "VBELN": vbeln,
            "ERDAT": d.isoformat(),
            "ERZET": f"{random.randint(8,17):02d}:{random.randint(0,59):02d}:00",
            "KUNNR": random.choice(CUSTOMERS),
            "REGIO": random.choice(REGIONS),
            "NETWR": round(total, 2),
            "WAERK": "INR",
            "status": "dispatched",
            "created_at": datetime.now().isoformat(),
            "items": items,
        }
        SALES_ORDERS.append(order)
        so_counter += 1
        for it in items:
            _record_stock_movement(it["MATNR"], it["KWMENG"], "OUT", "goods_issue", vbeln, d.isoformat())


def _generate_purchase_order_batch(d: date):
    """Generate 1-2 purchase orders per day (incoming stock)."""
    num_pos = random.choices([1, 2], weights=[0.7, 0.3])[0]
    po_counter = len(PURCHASE_ORDERS)
    for _ in range(num_pos):
        supplier = random.choice(SUPPLIERS)
        batch_size = random.randint(1, min(5, len(MATERIALS)))
        chosen = random.sample(MATERIALS, batch_size)
        items = []
        for mat in chosen:
            prof = DEMAND_PROFILE.get(mat["MATNR"])
            if prof and prof["mean"] > 0:
                qty = max(int(prof["moq"] if "moq" in supplier else prof["mean"] * 0.5),
                          random.randint(10, 100))
            else:
                lo, hi = CATEGORY_DEMAND_FALLBACK.get(mat.get("category", ""), (10, 50))
                qty = random.randint(int(lo * 0.5), int(hi * 2))
            items.append({
                "MATNR": mat["MATNR"],
                "MAKTX": mat.get("MAKTX", ""),
                "KWMENG": qty,
                "MEINS": mat.get("MEINS", "EA"),
                "NETWR": round(qty * random.uniform(400, 2000), 2),
                "category": mat.get("category", ""),
            })
        total = sum(it["NETWR"] for it in items)
        ebeln = f"PO{700000 + po_counter}"
        status = "delivered" if d < date.today() else "in_transit"
        order = {
            "EBELN": ebeln,
            "LIFNR": supplier["LIFNR"],
            "LNAME": supplier["NAME1"],
            "BEDAT": d.isoformat(),
            "NETWR": round(total, 2),
            "WAERK": "INR",
            "status": status,
            "created_at": datetime.now().isoformat(),
            "items": items,
        }
        PURCHASE_ORDERS.append(order)
        po_counter += 1
        if status == "delivered":
            for it in items:
                _record_stock_movement(it["MATNR"], it["KWMENG"], "IN",
                                       "goods_receipt", ebeln, d.isoformat())


def _init_stock():
    for mat in MATERIALS:
        STOCK[mat["MATNR"]] = {
            "MATNR": mat["MATNR"],
            "WERKS": PLANT_ID,
            "LGORT": "0001",
            "LBLAB": random.randint(500, 3000),
            "LFSME": 0,
            "INSME": 0,
            "MEINS": mat.get("MEINS", "EA"),
            "Last_Updated": datetime.now().isoformat(),
        }


def _top_up_from(start_date: date, end_date: date):
    """Generate sales + purchase orders day-by-day from start_date to end_date."""
    global LAST_GENERATED_WEEK, LIVE_WEEK_LAST_DAY, LAST_PO_GENERATED_DAY
    today = date.today()
    current_week = _monday_of(today)

    d = start_date
    while d <= end_date:
        if d < current_week and (LAST_GENERATED_WEEK is None or d > LAST_GENERATED_WEEK):
            _generate_sales_order_batch(d)
            _generate_purchase_order_batch(d)
            LAST_GENERATED_WEEK = d
        elif d >= current_week:
            if LIVE_WEEK_LAST_DAY is None or d > LIVE_WEEK_LAST_DAY:
                _generate_sales_order_batch(d)
                _generate_purchase_order_batch(d)
                LIVE_WEEK_LAST_DAY = d
        d += timedelta(days=1)


def top_up_sales_history(last_sync_date: Optional[str] = None):
    """
    Extend orders up to TODAY. When last_sync_date is provided, only generate
    from that date forward (incremental). Without it, full history from HISTORY_START.
    """
    global LAST_GENERATED_WEEK, LIVE_WEEK_LAST_DAY, LAST_PO_GENERATED_DAY
    today = date.today()
    current_week = _monday_of(today)

    if last_sync_date:
        try:
            start = datetime.strptime(last_sync_date[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            start = HISTORY_START
    else:
        if LAST_GENERATED_WEEK is not None:
            return
        start = HISTORY_START

    _top_up_from(start, today)

    if LAST_GENERATED_WEEK is None:
        LAST_GENERATED_WEEK = current_week - timedelta(days=7)
    if LIVE_WEEK_LAST_DAY is None:
        LIVE_WEEK_LAST_DAY = current_week - timedelta(days=1)


_load_catalog()
_load_suppliers()
_load_demand_profiles()
random.seed(99)
_init_stock()
top_up_sales_history()


class StockAdjustRequest(BaseModel):
    material: str
    quantity: int
    movement_type: str = "301"
    description: str = ""


class SalesCreateRequest(BaseModel):
    material: str
    quantity: int
    customer: str = "Walk-in Customer"
    region: str = "Karnataka"


class CycleSimulateRequest(BaseModel):
    num_sales: int = 5
    stock_adjustments: int = 3


@app.get("/sap/status")
def sap_status():
    return {
        "status": "RUNNING",
        "system": "SAP ECC Mock (VST IMS)",
        "plant": PLANT_ID,
        "plant_name": PLANT_NAME,
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat(),
        "materials_count": len(MATERIALS),
        "suppliers_count": len(SUPPLIERS),
        "stock_records": len(STOCK),
        "sales_orders": len(SALES_ORDERS),
        "purchase_orders": len(PURCHASE_ORDERS),
        "stock_movements": len(STOCK_MOVEMENTS),
        "history_start": HISTORY_START.isoformat(),
        "last_generated_week": LAST_GENERATED_WEEK.isoformat() if LAST_GENERATED_WEEK else None,
        "live_week_last_day": LIVE_WEEK_LAST_DAY.isoformat() if LIVE_WEEK_LAST_DAY else None,
    }


@app.get("/sap/opu/odata/sap/API_STOCK_SRV/Stocks")
def get_stocks():
    results = []
    for matnr, stk in STOCK.items():
        results.append({
            "MATNR": stk["MATNR"],
            "MAKTX": next((m["MAKTX"] for m in MATERIALS if m["MATNR"] == matnr), ""),
            "WERKS": stk["WERKS"],
            "LGORT": stk["LGORT"],
            "LBLAB": stk["LBLAB"],
            "LFSME": stk["LFSME"],
            "INSME": stk["INSME"],
            "MEINS": stk["MEINS"],
            "Last_Updated": stk["Last_Updated"],
        })
    return {"d": {"results": results, "__count": len(results)}}


@app.get("/sap/opu/odata/sap/API_SALES_SRV/Sales")
def get_sales(last_sync_date: Optional[str] = Query(None)):
    top_up_sales_history(last_sync_date=last_sync_date)
    if last_sync_date:
        try:
            cutoff = datetime.strptime(last_sync_date[:10], "%Y-%m-%d").date()
            filtered = [o for o in SALES_ORDERS if datetime.strptime(o["ERDAT"], "%Y-%m-%d").date() >= cutoff]
            return {"d": {"results": filtered, "__count": len(filtered)}}
        except (ValueError, TypeError):
            pass
    return {"d": {"results": SALES_ORDERS, "__count": len(SALES_ORDERS)}}


@app.get("/sap/opu/odata/sap/API_PO_SRV/PurchaseOrders")
def get_purchase_orders(last_sync_date: Optional[str] = Query(None)):
    top_up_sales_history(last_sync_date=last_sync_date)
    if last_sync_date:
        try:
            cutoff = datetime.strptime(last_sync_date[:10], "%Y-%m-%d").date()
            filtered = [o for o in PURCHASE_ORDERS
                        if datetime.strptime(o["BEDAT"], "%Y-%m-%d").date() >= cutoff]
            return {"d": {"results": filtered, "__count": len(filtered)}}
        except (ValueError, TypeError):
            pass
    return {"d": {"results": PURCHASE_ORDERS, "__count": len(PURCHASE_ORDERS)}}


@app.get("/sap/opu/odata/sap/API_MATERIAL_SRV/Materials")
def get_materials():
    return {"d": {"results": MATERIALS, "__count": len(MATERIALS)}}


@app.get("/sap/api/stock-movements")
def get_all_stock_movements(
    last_sync_date: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    top_up_sales_history(last_sync_date=last_sync_date)
    movements = STOCK_MOVEMENTS
    if last_sync_date:
        try:
            cutoff = datetime.strptime(last_sync_date[:10], "%Y-%m-%d").date()
            movements = [m for m in movements
                         if datetime.strptime(m["order_date"], "%Y-%m-%d").date() >= cutoff]
        except (ValueError, TypeError):
            pass
    return {"movements": movements[-limit:], "total": len(movements)}


@app.post("/sap/api/stocks/adjust")
def adjust_stock(req: StockAdjustRequest):
    if req.material not in STOCK:
        raise HTTPException(status_code=404, detail=f"Material {req.material} not found")
    stk = STOCK[req.material]
    if req.movement_type == "201":
        if stk["LBLAB"] < req.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock. Available: {stk['LBLAB']}")
        stk["LBLAB"] -= req.quantity
        direction = "DECREASE"
    elif req.movement_type == "101":
        stk["LBLAB"] += req.quantity
        direction = "INCREASE"
    else:
        stk["LBLAB"] += req.quantity
        direction = "ADJUSTED"
    stk["Last_Updated"] = datetime.now().isoformat()
    movement = {
        "id": str(uuid.uuid4())[:8],
        "MATNR": req.material,
        "movement_type": req.movement_type,
        "quantity": req.quantity,
        "direction": direction,
        "description": req.description,
        "new_stock": stk["LBLAB"],
        "timestamp": datetime.now().isoformat(),
    }
    STOCK_MOVEMENTS.append(movement)
    return {"status": "success", "message": f"Stock {direction.lower()} for {req.material}", "movement": movement}


@app.post("/sap/api/sales/create")
def create_sales_order(req: SalesCreateRequest):
    if req.material not in STOCK:
        raise HTTPException(status_code=404, detail=f"Material {req.material} not found")
    stk = STOCK[req.material]
    if stk["LBLAB"] < req.quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient stock for dispatch. Available: {stk['LBLAB']}")
    stk["LBLAB"] -= req.quantity
    stk["Last_Updated"] = datetime.now().isoformat()
    vbeln = f"SO{random.randint(100000, 999999)}"
    order = {
        "VBELN": vbeln,
        "ERDAT": _monday_of(date.today()).isoformat(),
        "ERZET": datetime.now().strftime("%H:%M:%S"),
        "KUNNR": req.customer,
        "REGIO": req.region,
        "NETWR": round(random.uniform(500, 50000), 2),
        "WAERK": "INR",
        "status": "dispatched",
        "created_at": datetime.now().isoformat(),
        "items": [{
            "MATNR": req.material,
            "KWMENG": req.quantity,
            "MEINS": stk["MEINS"],
            "NETWR": round(req.quantity * random.uniform(500, 2500), 2),
        }],
    }
    SALES_ORDERS.append(order)
    _record_stock_movement(req.material, req.quantity, "OUT", "goods_issue", vbeln, order["ERDAT"])
    return {"status": "success", "message": f"Sales order {vbeln} created", "order": order}


@app.post("/sap/api/simulate-cycle")
def simulate_cycle(req: CycleSimulateRequest):
    results = {"sales_created": [], "stock_adjusted": [], "errors": []}
    for _ in range(req.num_sales):
        mat = random.choice(MATERIALS)
        try:
            order = create_sales_order(SalesCreateRequest(
                material=mat["MATNR"], quantity=random.randint(1, 10),
                customer=random.choice(CUSTOMERS), region=random.choice(REGIONS),
            ))
            results["sales_created"].append(order["order"]["VBELN"])
        except HTTPException as e:
            results["errors"].append(f"{mat['MATNR']}: {e.detail}")
    for _ in range(req.stock_adjustments):
        mat = random.choice(MATERIALS)
        try:
            adj = adjust_stock(StockAdjustRequest(
                material=mat["MATNR"], quantity=random.randint(5, 30),
                movement_type="101", description="Simulated goods receipt",
            ))
            results["stock_adjusted"].append(adj["movement"]["id"])
        except HTTPException as e:
            results["errors"].append(f"{mat['MATNR']}: {e.detail}")
    cycle_log = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "sales_created": len(results["sales_created"]),
        "stock_adjusted": len(results["stock_adjusted"]),
        "errors": len(results["errors"]),
    }
    CYCLE_LOG.append(cycle_log)
    return {"status": "success", "message": "Cycle complete", "cycle": cycle_log}


@app.get("/sap/api/cycle-log")
def get_cycle_log():
    return {"log": CYCLE_LOG[-20:]}


@app.get("/sap/api/movements")
def get_movements():
    return {"movements": STOCK_MOVEMENTS[-50:]}


@app.get("/sap/api/materials")
def get_materials_list():
    return {"materials": MATERIALS}


@app.get("/sap/api/materials/{matnr}")
def get_material_detail(matnr: str):
    mat = next((m for m in MATERIALS if m["MATNR"] == matnr), None)
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"material": mat, "stock": STOCK.get(matnr, {})}


@app.get("/", response_class=HTMLResponse)
def web_ui():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>SAP Mock ERP</h1><p>Template not found.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
