"""
Schema Extractor for Genie's SQL Agent.

Builds a plain-text schema description from the live SQLAlchemy ORM models so
the LLM has authoritative table/column names.  We avoid dumping raw DDL (which
would have UUID PK column noise) and instead emit a compact, human-readable
contract:

    TABLE products (
      sku_id              TEXT        -- unique SKU code e.g. SP-FIL-0001
      category            TEXT        -- Spare Parts | Lubricants | Electric Pumps | Engines | Precision Components
      ...
    )

A secondary `BUSINESS_NOTES` block adds the implicit domain rules the schema
alone cannot express (date semantics, derived metrics the user often asks about).
"""

import logging
from typing import Optional

from app.models import (
    Product, Supplier, Sale, Order, OrderItem, ExternalFactor,
    Forecast, ForecastModel, ForecastPrediction, User, SapSyncLog, SapConfig,
    Inventory,
)
from app.database import engine

logger = logging.getLogger(__name__)


#tables Genie is allowed to read.  This is a deliberate allow-list: even if the
#DB contains more tables (sap_sync_log, users, etc.), the SQL agent should only
#be permitted to touch inventory-relevant ones.
ALLOWED_TABLES = [
    "products", "suppliers", "sales", "external_factors",
    "forecasts", "forecast_models", "forecast_predictions",
    "orders", "order_items", "inventory",
]

# ── Domain notes added to the schema prompt ────────────────────────────
BUSINESS_NOTES = """
BUSINESS RULES & DERIVED METRICS (apply when writing SQL):
- `products.sku_id` follows the pattern `XX-YYY-####` where XX encodes category:
  SP=Spare Parts, LU=Lubricants, EP=Electric Pumps, EN=Engines, PC=Precision Components.
- `products.criticality_score` is on a 1-5 scale; >=4 is "critical".
- `sales.sale_date` is weekly (every Monday).  Use `strftime('%Y-W%W', sale_date)` for week-bucketing.
- `sales.units_sold` is the weekly demand.  "Recent N-week average" = AVG over the last N sale_dates.
- "Burn rate" = average `units_sold` over the most recent 13 weeks.
- We have a LIVE `inventory` table (synced from SAP): quantity_on_hand / quantity_reserved / quantity_available per sku_id.
  For "current stock" questions, use inventory.quantity_available. If no inventory row exists for a SKU,
  estimate stock = burn_rate * 8 weeks coverage.
- "Coverage weeks" = available_stock / weekly_demand.
- `suppliers.origin_country` ∈ {Japan, China, Germany, India, Domestic}.
- `suppliers.base_lead_time_days` is the normal lead time; assume replenishment lead time equals this.
- `external_factors.factor_date` aligns with `sales.sale_date`; carries `monsoon_index`, `crop_sowing_season`, `macro_economic_index`.
- `forecasts.predicted_demand` is per-SKU per-date; `forecast_predictions` is per-model breakdown with `lower_bound`/`upper_bound` CIs.
- For "current month" use `strftime('%Y-%m', sale_date) = strftime('%Y-%m', CURRENT_DATE)`.
- Today's date is dynamically substituted by the agent as CURRENT_DATE.
"""


def _column_line(col) -> str:
    """Format one column as `col_name  TYPE  -- comment`."""
    line = f"  {col.name:<22}"
    # Type
    try:
        t = str(col.type).upper()
    except Exception:
        t = "TEXT"
    line += f"{t:<14}"
    # Constraints
    flags = []
    if not col.nullable:
        flags.append("NOT NULL")
    if col.primary_key:
        flags.append("PK")
    if col.unique:
        flags.append("UNIQUE")
    if flags:
        line += " ".join(flags)
    return line


def _emit_table(model_class) -> str:
    """Emit one `TABLE ... (...)` block for an ORM model."""
    tbl_name = model_class.__tablename__
    lines = [f"TABLE {tbl_name} ("]
    for col in model_class.__table__.columns:
        lines.append(_column_line(col))
        # Add a comment if the column is referenced in BUSINESS_NOTES
        if col.name in FREQUENTLY_COMMENTED.get(tbl_name, {}):
            lines[-1] += f"  -- {FREQUENTLY_COMMENTED[tbl_name][col.name]}"
    lines.append(");")
    return "\n".join(lines)


# Optional helpful inline comments for the most-used columns.
FREQUENTLY_COMMENTED = {
    "products": {
        "sku_id": "unique SKU code, e.g. SP-FIL-0001",
        "category": "Spare Parts | Lubricants | Electric Pumps | Engines | Precision Components",
        "sub_category": "e.g. Filters, Engine Oil, Diesel Engines",
        "machine_compatibility": "comma-separated list of machines",
        "shelf_life_days": "0 means no shelf-life tracking",
        "criticality_score": "1..5 (>=4 = critical)",
    },
    "suppliers": {
        "supplier_id": "e.g. SUP-JP-001",
        "supplier_name": "human-readable name",
        "origin_country": "Japan | China | Germany | India | Domestic",
        "primary_category": "category this supplier primarily serves",
        "base_lead_time_days": "normal replenishment lead time in days",
        "lead_time_volatility": "0..1 std-dev of lead time",
        "moq": "minimum order quantity",
        "unit_cost_inr": "unit cost in INR",
    },
    "sales": {
        "sale_date": "weekly (every Monday)",
        "sku_id": "FK to products.sku_id",
        "units_sold": "weekly demand",
        "fulfillment_region": "South India | North India | West India | East India | Export",
        "stockout_flag": "1 if a stockout was recorded that week",
    },
    "external_factors": {
        "factor_date": "weekly, aligns with sales.sale_date",
        "monsoon_index": "0..1 (higher = stronger monsoon)",
        "crop_sowing_season": "Kharif | Rabi | Summer | None",
        "macro_economic_index": "multiplier around 1.0",
    },
    "forecasts": {
        "sku_id": "FK to products.sku_id",
        "forecast_date": "future weekly date",
        "predicted_demand": "ensemble-averaged forecast units",
        "actual_demand": "filled once actuals arrive (nullable)",
        "model_version": "e.g. ensemble-v1",
    },
    "forecast_models": {
        "model_name": "xgboost | lightgbm | arima | sarima | prophet | holt_winters",
        "model_type": "Gradient Boosting | Time Series (ARIMA) | etc.",
        "sku_id": "nullable (null = trained across all SKUs)",
        "category": "nullable (null = trained across all categories)",
        "mape": "Mean Absolute Percentage Error (%) - lower is better",
        "ensemble_weight": "0..1 share in the ensemble; 0 means inactive",
        "is_active": "1 = usable",
    },
    "forecast_predictions": {
        "model_name": "single model that produced this row",
        "sku_id": "FK to products.sku_id",
        "forecast_date": "future weekly date",
        "predicted_demand": "this model's prediction",
        "lower_bound": "lower bound for the prediction",
        "upper_bound": "upper bound for the prediction",
        "actual_demand": "nullable until actuals arrive",
    },
    "orders": {
        "order_id": "e.g. ORD-2024-001",
        "order_date": "purchase order date",
        "customer_name": "buyer name",
        "total_amount_inr": "PO total in INR",
        "payment_status": "Pending | Paid | Overdue",
        "order_status": "Created | Confirmed | Shipped | Delivered | Cancelled",
    },
    "order_items": {
        "order_id": "FK to orders.id",
        "product_id": "FK to products.id",
        "quantity": "units ordered",
        "unit_price_inr": "per-unit price in INR",
        "total_price_inr": "quantity * unit_price_inr",
    },
    "inventory": {
        "sku_id": "FK to products.sku_id (unique)",
        "quantity_on_hand": "physical stock synced from SAP",
        "quantity_reserved": "stock allocated to orders",
        "quantity_available": "on_hand minus reserved — use for availability answers",
        "last_sap_sync_at": "when SAP last pushed this stock level",
    },
}


def get_schema_text() -> str:
    """
    Build the live schema text used in the SQL agent's system prompt.

    Returns:
      String with one `TABLE ...` block per allowed table
      followed by the BUSINESS_NOTES footer.
    """
    parts = []
    for name in ALLOWED_TABLES:
        model = _MODEL_MAP.get(name)
        if model is None:
            logger.warning("No model mapping for allowed table %s", name)
            continue
        parts.append(_emit_table(model))
    parts.append(BUSINESS_NOTES.strip())
    return "\n\n".join(parts)


_MODEL_MAP = {
    "products": Product,
    "suppliers": Supplier,
    "sales": Sale,
    "external_factors": ExternalFactor,
    "forecasts": Forecast,
    "forecast_models": ForecastModel,
    "forecast_predictions": ForecastPrediction,
    "orders": Order,
    "order_items": OrderItem,
    "inventory": Inventory,
}


_schema_cache: Optional[str] = None


def get_schema_text_cached() -> str:
    """Cached version - safe because the schema is essentially immutable at runtime."""
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = get_schema_text()
    return _schema_cache
