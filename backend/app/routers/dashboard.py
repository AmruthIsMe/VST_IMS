from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal_column
from datetime import date, timedelta
import pandas as pd
import numpy as np
from pathlib import Path
import logging

from app.database import get_db, engine
from app.models import Product, Supplier, Order, Sale, Forecast, Inventory
from app.schemas import DashboardKPI, ChartData
from app.forecasting.data_pipeline import SKU_CATEGORY_PREFIX
from app.forecasting.constants import get_risk_level
from app.config import get_settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(get_settings().DATA_DIR)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/kpis", response_model=DashboardKPI)
def get_kpis(db: Session = Depends(get_db)):
    total_skus = db.query(func.count(Product.id)).scalar() or 0
    total_suppliers = db.query(func.count(Supplier.id)).scalar() or 0
    active_orders = db.query(func.count(Order.id)).filter(
        Order.order_status.in_(["Pending", "Processing", "Shipped"])
    ).scalar() or 0

    total_sales = db.query(func.sum(Sale.units_sold)).scalar() or 0

    # Inventory metrics from inventory table
    total_units = db.query(func.sum(Inventory.quantity_on_hand)).scalar() or 0

    from sqlalchemy import text
    val_query = text("""
        SELECT COALESCE(
            SUM(
                i.quantity_on_hand * COALESCE(
                    i.unit_cost_inr,
                    (SELECT AVG(s.unit_cost_inr) FROM suppliers s WHERE s.primary_category = p.category),
                    CASE p.category
                        WHEN 'Engines' THEN 85000.0
                        WHEN 'Precision Components' THEN 35000.0
                        WHEN 'Electric Pumps' THEN 14500.0
                        WHEN 'Lubricants' THEN 850.0
                        ELSE 1250.0
                    END
                )
            ),
            0.0
        )
        FROM inventory i
        LEFT JOIN products p ON i.sku_id = p.sku_id
    """)
    try:
        total_inventory_value = db.execute(val_query).scalar() or 0.0
    except Exception:
        db.rollback()
        total_inventory_value = float(total_units * 2086.0)

    # Low stock: SKUs with quantity_on_hand below 20% of their category threshold
    low_stock = 0
    try:
        low_stock_query = text("""
            SELECT COUNT(*) FROM inventory i
            WHERE i.quantity_on_hand < (
                SELECT AVG(i2.quantity_on_hand) * 0.2 FROM inventory i2
            )
        """)
        low_stock = db.execute(low_stock_query).scalar() or 0
    except Exception:
        db.rollback()

    # Fill rate: % of SKUs with stock > 0
    skus_with_stock = 0
    try:
        skus_with_stock = db.query(func.count(Inventory.id)).filter(
            Inventory.quantity_on_hand > 0
        ).scalar() or 0
    except Exception:
        db.rollback()
    fill_rate = round((skus_with_stock / total_skus * 100), 1) if total_skus > 0 else 0.0

    return DashboardKPI(
        total_skus=total_skus,
        total_suppliers=total_suppliers,
        active_orders=active_orders,
        total_sales=float(total_sales),
        low_stock_count=low_stock,
        fill_rate=fill_rate,
        total_inventory_value=float(total_inventory_value),
        total_units_in_stock=int(total_units),
    )


@router.get("/charts/category-distribution")
def category_distribution(db: Session = Depends(get_db)):
    """Category distribution based on product catalog."""
    rows = (
        db.query(Product.category, func.count(Product.id))
        .group_by(Product.category)
        .order_by(Product.category)
        .all()
    )
    return {
        "labels": [r[0] for r in rows],
        "values": [float(r[1]) for r in rows],
    }


@router.get("/charts/sales-by-region")
def sales_by_region(db: Session = Depends(get_db)):
    rows = (
        db.query(Sale.fulfillment_region, func.sum(Sale.units_sold))
        .group_by(Sale.fulfillment_region)
        .all()
    )
    return {
        "labels": [r[0] or "Unknown" for r in rows],
        "values": [float(r[1]) for r in rows],
    }


@router.get("/stockout-risk")
def stockout_risk(weeks_ahead: int = 12, db: Session = Depends(get_db)):
    """
    Per-SKU stockout risk analysis.
    Uses real inventory data + ML model predictions from forecast_predictions table.
    Falls back to sales-based estimates only if no ML predictions exist.
    """
    from sqlalchemy import text
    from app.models import Inventory

    # --- 1. Get real stock from inventory table ---
    inv_rows = db.query(Inventory.sku_id, Inventory.quantity_on_hand).all()
    stock_map = {row.sku_id: row.quantity_on_hand for row in inv_rows}

    # --- 2. Get ML model predictions from forecast_predictions ---
    pred_query = text("""
        SELECT sku_id, predicted_demand, forecast_date
        FROM forecast_predictions
        ORDER BY sku_id, forecast_date
    """)
    pred_rows = db.execute(pred_query).fetchall()

    ml_forecast = {}  # {sku_id: avg_weekly_forecast}
    if pred_rows:
        pred_df = pd.DataFrame(pred_rows, columns=["sku_id", "predicted_demand", "forecast_date"])
        pred_df["forecast_date"] = pd.to_datetime(pred_df["forecast_date"])
        # Average predicted demand per SKU across all forecast dates
        sku_preds = pred_df.groupby("sku_id")["predicted_demand"].agg(["mean", "count"]).reset_index()
        # Only use SKUs with at least 3 prediction points for reliability
        reliable = sku_preds[sku_preds["count"] >= 3]
        for _, row in reliable.iterrows():
            ml_forecast[row["sku_id"]] = round(float(row["mean"]), 1)

    # --- 3. Get sales data for SKUs without ML predictions ---
    sales_query = text("""
        SELECT sku_id, sale_date, units_sold
        FROM sales
        ORDER BY sale_date
    """)
    sales_rows = db.execute(sales_query).fetchall()

    if not sales_rows:
        return {"status": "error", "message": "No sales data found"}

    sales_df = pd.DataFrame(sales_rows, columns=["sku_id", "sale_date", "units_sold"])
    sales_df["sale_date"] = pd.to_datetime(sales_df["sale_date"])

    # Get product categories
    products_query = text("SELECT sku_id, category, sub_category FROM products")
    prod_rows = db.execute(products_query).fetchall()
    products_df = pd.DataFrame(prod_rows, columns=["sku_id", "category", "sub_category"]) if prod_rows else pd.DataFrame(columns=["sku_id", "category", "sub_category"])

    # --- 4. Compute demand stats for all SKUs ---
    today_ts = pd.Timestamp(date.today())
    cutoff_13w = today_ts - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w].copy()

    sku_stats = recent.groupby("sku_id").agg(
        avg_weekly=("units_sold", "mean"),
        weeks_active=("sale_date", "nunique"),
    ).reset_index()
    sku_stats = sku_stats[sku_stats["weeks_active"] >= 2].copy()

    # Demand trend: last 4w vs prev 4w
    cutoff_4w = today_ts - pd.Timedelta(weeks=4)
    cutoff_8w = today_ts - pd.Timedelta(weeks=8)
    recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
    prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()
    sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
    sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)
    sku_stats["demand_trend"] = np.where(
        sku_stats["prev_4w"] > 0,
        sku_stats["recent_4w"] / sku_stats["prev_4w"],
        1.0,
    )

    # --- 5. Build results: ML forecast where available, sales-based fallback ---
    results = []
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    risk_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for _, row in sku_stats.iterrows():
        sku = row["sku_id"]
        avg_wk = float(row["avg_weekly"])
        trend = float(row["demand_trend"])

        # Forecast: prefer ML, fallback to trend-adjusted sales average
        if sku in ml_forecast:
            forecast_weekly = ml_forecast[sku]
        else:
            forecast_weekly = round(avg_wk * trend, 1)

        # Real stock from inventory table
        quantity_on_hand = stock_map.get(sku, 0)

        # Coverage: how many weeks the current stock lasts at forecasted demand
        coverage_weeks = round(quantity_on_hand / forecast_weekly, 1) if forecast_weekly > 0 else None

        # 12-week demand forecast
        forecast_12w = int(forecast_weekly * weeks_ahead)

        # Shortfall
        shortfall = round(max(weeks_ahead - coverage_weeks, 0), 1) if coverage_weeks is not None else 0

        # Risk level
        risk = get_risk_level(coverage_weeks, trend, 0)

        risk_counts[risk] += 1

        # Get category
        cat_match = products_df[products_df["sku_id"] == sku]
        category = cat_match.iloc[0]["category"] if len(cat_match) > 0 else "Unknown"
        sub_category = cat_match.iloc[0]["sub_category"] if len(cat_match) > 0 else ""

        results.append({
            "sku_id": sku,
            "category": category,
            "sub_category": sub_category,
            "avg_weekly_demand": round(avg_wk, 1),
            "forecast_weekly": forecast_weekly,
            "demand_trend_pct": round((trend - 1) * 100, 1),
            "estimated_stock": quantity_on_hand,
            "coverage_weeks": coverage_weeks,
            "forecast_12w_demand": forecast_12w,
            "shortfall_weeks": shortfall,
            "risk_level": risk,
            "forecast_source": "ml_model" if sku in ml_forecast else "sales_trend",
        })

    # Sort by risk, then by shortfall
    results.sort(key=lambda r: (risk_order.get(r["risk_level"], 9), -r["shortfall_weeks"]))

    # Add serial numbers
    for i, r in enumerate(results):
        r["s_no"] = i + 1

    return {
        "status": "success",
        "summary": {
            "total_skus_analyzed": len(results),
            "critical": risk_counts["CRITICAL"],
            "high": risk_counts["HIGH"],
            "medium": risk_counts["MEDIUM"],
            "low": risk_counts["LOW"],
        },
        "risks": results,
        "forecast_horizon_weeks": weeks_ahead,
    }


def _load_sales_products(since_date=None):
    """Shared helper: load sales + products from DB or CSV fallback."""
    from sqlalchemy import text
    from app.database import SessionLocal

    db = SessionLocal()
    sales_df = None
    products_df = None
    try:
        try:
            if since_date:
                sales_query = text("""
                    SELECT sku_id, sale_date, units_sold FROM sales WHERE sale_date >= :sd ORDER BY sale_date
                """)
                rows = db.execute(sales_query, {"sd": since_date}).fetchall()
            else:
                sales_query = text("""
                    SELECT sku_id, sale_date, units_sold FROM sales ORDER BY sale_date
                """)
                rows = db.execute(sales_query).fetchall()
            if rows:
                sales_df = pd.DataFrame(rows, columns=["sku_id", "sale_date", "units_sold"])
                sales_df["sale_date"] = pd.to_datetime(sales_df["sale_date"])
                prod_query = text("SELECT sku_id, category, sub_category, criticality_score FROM products")
                prod_rows = db.execute(prod_query).fetchall()
                if prod_rows:
                    products_df = pd.DataFrame(prod_rows, columns=["sku_id", "category", "sub_category", "criticality_score"])
        except Exception:
            pass

        if sales_df is None or len(sales_df) == 0:
            logger.warning("No sales data found in database")
    finally:
        db.close()

    return sales_df, products_df


@router.get("/charts/category-forecast")
def category_forecast():
    """
    Category-level forecast aggregation with trends.
    Shows total forecast demand per category for next 12 weeks, trend arrows, and contribution %.
    """
    cutoff_14w = date.today() - timedelta(weeks=14)
    sales_df, products_df = _load_sales_products(since_date=cutoff_14w)
    if sales_df is None or len(sales_df) == 0:
        return {"status": "error", "message": "No sales data"}

    today_ts = pd.Timestamp(date.today())

    # Merge category
    if products_df is not None and len(products_df) > 0:
        sales_df = sales_df.merge(products_df[["sku_id", "category"]].drop_duplicates("sku_id"), on="sku_id", how="left")
    else:
        sales_df["category"] = sales_df["sku_id"].str[:2].map(SKU_CATEGORY_PREFIX).fillna("Unknown")

    sales_df["category"] = sales_df["category"].fillna("Unknown")

    # Recent 13 weeks per category
    cutoff_13w = today_ts - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
    cat_stats = recent.groupby("category").agg(
        total_13w=("units_sold", "sum"),
    ).reset_index()
    weekly_totals = recent.groupby(["category", "sale_date"])["units_sold"].sum().reset_index()
    avg_weekly_map = weekly_totals.groupby("category")["units_sold"].mean()
    cat_stats["avg_weekly"] = cat_stats["category"].map(avg_weekly_map).fillna(0)

    # Trend: last 4w vs prev 4w
    cutoff_4w = today_ts - pd.Timedelta(weeks=4)
    cutoff_8w = today_ts - pd.Timedelta(weeks=8)
    recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("category")["units_sold"].sum()
    prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("category")["units_sold"].sum()
    cat_stats["recent_4w"] = cat_stats["category"].map(recent_4w).fillna(0)
    cat_stats["prev_4w"] = cat_stats["category"].map(prev_4w).fillna(0)
    cat_stats["trend_pct"] = np.where(cat_stats["prev_4w"] > 0, ((cat_stats["recent_4w"] - cat_stats["prev_4w"]) / cat_stats["prev_4w"] * 100).round(1), 0)

    # Forecast next 12 weeks per category
    cat_stats["forecast_12w"] = (cat_stats["avg_weekly"] * 12).round(0).astype(int)
    total_forecast = cat_stats["forecast_12w"].sum()
    cat_stats["contribution_pct"] = np.where(total_forecast > 0, (cat_stats["forecast_12w"] / total_forecast * 100).round(1), 0)

    # SKU count per category
    sku_counts = recent.groupby("category")["sku_id"].nunique().reset_index()
    sku_counts.columns = ["category", "sku_count"]
    cat_stats = cat_stats.merge(sku_counts, on="category", how="left")

    results = []
    for _, row in cat_stats.sort_values("forecast_12w", ascending=False).iterrows():
        results.append({
            "category": row["category"],
            "sku_count": int(row.get("sku_count", 0)),
            "avg_weekly_demand": round(float(row["avg_weekly"]), 1),
            "forecast_12w": int(row["forecast_12w"]),
            "contribution_pct": float(row["contribution_pct"]),
            "trend_pct": float(row["trend_pct"]),
            "trend_direction": "up" if row["trend_pct"] > 2 else ("down" if row["trend_pct"] < -2 else "stable"),
        })

    return {"status": "success", "categories": results, "total_forecast_12w": int(total_forecast)}


@router.get("/charts/demand-trend")
def demand_trend(months: int = None, start_date: str = None, end_date: str = None, granularity: str = "weekly", db: Session = Depends(get_db)):
    """
    Dynamic demand trend with date range filtering.
    months: number of months of data to show (0 = all). Calculated from data's max date.
    granularity: 'daily', 'weekly', 'monthly'
    """
    try:
        query = db.query(Sale.sale_date, func.sum(Sale.units_sold)).group_by(Sale.sale_date).order_by(Sale.sale_date)
        if start_date:
            query = query.filter(Sale.sale_date >= pd.to_datetime(start_date).date())
        if end_date:
            query = query.filter(Sale.sale_date <= pd.to_datetime(end_date).date())
        rows = query.all()
    except Exception as e:
        logger.error(f"Error querying sales for demand-trend: {e}")
        db.rollback()
        rows = []

    if not rows:
        return {"labels": [], "values": [], "granularity": granularity}

    # If months filter is active, filter by max_date - offset
    if months is not None and months > 0:
        max_date = rows[-1][0]
        if hasattr(max_date, "date"):
            max_date = max_date.date()
        if months == 12:
            cutoff = date(max_date.year, 1, 1)
        else:
            cutoff = (pd.Timestamp(max_date) - pd.DateOffset(months=months)).date()
        rows = [r for r in rows if (r[0].date() if hasattr(r[0], "date") else r[0]) >= cutoff]

    if not rows:
        return {"labels": [], "values": [], "granularity": granularity}

    if granularity == "daily":
        labels = [r[0].strftime("%Y-%m-%d") if hasattr(r[0], "strftime") else str(r[0]) for r in rows]
        values = [int(r[1] or 0) for r in rows]
    elif granularity == "monthly":
        monthly_map = {}
        for d, u in rows:
            m = d.strftime("%Y-%m") if hasattr(d, "strftime") else str(d)[:7]
            monthly_map[m] = monthly_map.get(m, 0) + int(u or 0)
        sorted_m = sorted(monthly_map.items())
        labels = [k for k, _ in sorted_m]
        values = [v for _, v in sorted_m]
    else:  # weekly (default)
        from datetime import date as _date
        today = _date.today()
        current_week_monday = today - timedelta(days=today.weekday())
        weekly_map = {}
        for d, u in rows:
            dt = d.date() if hasattr(d, "date") else d
            w = dt - timedelta(days=dt.weekday())
            weekly_map[w] = weekly_map.get(w, 0) + int(u or 0)
        sorted_w = sorted(weekly_map.items())
        # Exclude the current week only on Monday (start of week, no data yet).
        # On other days the backfill/sync has already populated it.
        if today.weekday() == 0:  # Monday
            sorted_w = [(k, v) for k, v in sorted_w if k < current_week_monday]
        # Exclude partial weeks (value < 75% of median) to avoid dips from incomplete data
        if sorted_w:
            import statistics
            all_vals = [v for _, v in sorted_w]
            median_v = statistics.median(all_vals) if all_vals else 0
            if median_v > 0:
                sorted_w = [(k, v) for k, v in sorted_w if v >= median_v * 0.75]
        if months is not None and 0 < months <= 6:
            labels = [k.strftime("%b %d") for k, _ in sorted_w]
        else:
            labels = [k.strftime("%Y-%m-%d") for k, _ in sorted_w]
        values = [v for _, v in sorted_w]

    return {
        "labels": labels,
        "values": values,
        "granularity": granularity,
    }
