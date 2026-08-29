"""
SAP Mock ERP Server (Standalone)
Simulates SAP ECC/S-4HANA on port 8001.

Serves the REAL VST product catalog (data/dim_products.csv) and generates
synthetic weekly sales history that statistically mirrors the historical
demand in data/fact_sales.csv (per-SKU mean/std, Indian agri seasonality).

Sales are generated on WEEKLY Monday buckets to match the IMS database
cadence, starting 2022-01-03 and auto-extending to the current week on
every fetch — so each SAP Sync pulls genuinely NEW weeks of data.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import random
import os
import uuid
import logging

logger = logging.getLogger("sap_mock_erp")

app = FastAPI(title="SAP Mock ERP", version="2.0.0")

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
DEMAND_PROFILE = {}
STOCK = {}
SALES_ORDERS = []
STOCK_MOVEMENTS = []
CYCLE_LOG = []
LAST_GENERATED_WEEK = None   # last fully-closed week generated
LIVE_WEEK_LAST_DAY = None    # last day of the ongoing week emitted


def _load_catalog():
    """Load the real VST catalog from dim_products.csv."""
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


def _load_demand_profiles():
    """Per-SKU weekly demand statistics from fact_sales.csv."""
    global DEMAND_PROFILE
    profiles = {}
    csv_path = os.path.join(DATA_DIR, "fact_sales.csv")
    if os.path.exists(csv_path):
        import csv
        import math
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


def _generate_week(week_monday: date):
    so_counter = len(SALES_ORDERS)
    for mat in MATERIALS:
        qty = _weekly_quantity(mat, week_monday)
        if qty <= 0:
            continue
        SALES_ORDERS.append({
            "VBELN": f"SO{900000 + so_counter}",
            "MATNR": mat["MATNR"],
            "MAKTX": mat.get("MAKTX", ""),
            "KWMENG": qty,
            "MEINS": mat.get("MEINS", "EA"),
            "KUNNR": random.choice(CUSTOMERS),
            "REGIO": random.choice(REGIONS),
            "ERDAT": week_monday.isoformat(),
            "ERZET": "08:00:00",
            "NETWR": round(qty * random.uniform(500, 2500), 2),
            "WAERK": "INR",
            "NETWORTH": mat.get("category", ""),
            "status": "dispatched",
            "created_at": datetime.now().isoformat(),
        })
        so_counter += 1


def _generate_day(d: date):
    """Emit one day's worth of the ongoing week (≈1/7 of weekly demand each)."""
    so_counter = len(SALES_ORDERS)
    for mat in MATERIALS:
        weekly_full = _weekly_quantity(mat, d)
        qty = max(0, int(round((weekly_full / 7.0) * random.uniform(0.5, 1.5))))
        if qty <= 0:
            continue
        SALES_ORDERS.append({
            "VBELN": f"SO{900000 + so_counter}",
            "MATNR": mat["MATNR"],
            "MAKTX": mat.get("MAKTX", ""),
            "KWMENG": qty,
            "MEINS": mat.get("MEINS", "EA"),
            "KUNNR": random.choice(CUSTOMERS),
            "REGIO": random.choice(REGIONS),
            "ERDAT": d.isoformat(),
            "ERZET": "08:00:00",
            "NETWR": round(qty * random.uniform(500, 2500), 2),
            "WAERK": "INR",
            "NETWORTH": mat.get("category", ""),
            "status": "dispatched",
            "created_at": datetime.now().isoformat(),
        })
        so_counter += 1


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


def top_up_sales_history():
    """
    Extend sales orders up to TODAY (idempotent, incremental).

    - Past weeks are emitted whole (ERDAT = week Monday).
    - The ONGOING week is emitted day-by-day: each fetch adds one day of
      orders per material, so syncing daily always brings genuinely new
      actuals instead of waiting for next Monday.
    """
    global LAST_GENERATED_WEEK, LIVE_WEEK_LAST_DAY
    today = date.today()
    current_week = _monday_of(today)
    if LAST_GENERATED_WEEK is None:
        LAST_GENERATED_WEEK = HISTORY_START - timedelta(days=7)
        LIVE_WEEK_LAST_DAY = current_week - timedelta(days=1)
    weeks_added = 0
    while LAST_GENERATED_WEEK < current_week:
        LAST_GENERATED_WEEK += timedelta(days=7)
        if LAST_GENERATED_WEEK < current_week:
            _generate_week(LAST_GENERATED_WEEK)
            weeks_added += 1
    days_added = 0
    while LIVE_WEEK_LAST_DAY < today:
        LIVE_WEEK_LAST_DAY += timedelta(days=1)
        _generate_day(LIVE_WEEK_LAST_DAY)
        days_added += 1
    if weeks_added or days_added:
        logger.info(
            f"SAP mock: generated {weeks_added} closed week(s) + {days_added} live-week day(s), "
            f"total orders={len(SALES_ORDERS)}"
        )


_load_catalog()
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
        "version": "7.50",
        "timestamp": datetime.now().isoformat(),
        "materials_count": len(MATERIALS),
        "stock_records": len(STOCK),
        "sales_orders": len(SALES_ORDERS),
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
def get_sales():
    top_up_sales_history()
    return {"d": {"results": SALES_ORDERS, "__count": len(SALES_ORDERS)}}


@app.get("/sap/opu/odata/sap/API_MATERIAL_SRV/Materials")
def get_materials():
    return {"d": {"results": MATERIALS, "__count": len(MATERIALS)}}


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
    order = {
        "VBELN": f"SO{random.randint(100000, 999999)}",
        "MATNR": req.material,
        "KWMENG": req.quantity,
        "MEINS": stk["MEINS"],
        "KUNNR": req.customer,
        "REGIO": req.region,
        "ERDAT": _monday_of(date.today()).isoformat(),
        "ERZET": datetime.now().strftime("%H:%M:%S"),
        "NETWR": round(random.uniform(500, 50000), 2),
        "WAERK": "INR",
        "status": "dispatched",
        "created_at": datetime.now().isoformat(),
    }
    SALES_ORDERS.append(order)
    return {"status": "success", "message": f"Sales order {order['VBELN']} created", "order": order}


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
