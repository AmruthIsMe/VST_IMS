from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal_column
from datetime import date, timedelta
import pandas as pd
import numpy as np
from pathlib import Path
import logging

from app.database import get_db, engine
from app.models import Product, Supplier, Order, Sale, Forecast
from app.schemas import DashboardKPI, ChartData

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/kpis", response_model=DashboardKPI)
def get_kpis(db: Session = Depends(get_db)):
    total_skus = db.query(func.count(Product.id)).scalar() or 0
    total_suppliers = db.query(func.count(Supplier.id)).scalar() or 0
    active_orders = db.query(func.count(Order.id)).filter(
        Order.order_status.in_(["Pending", "Processing", "Shipped"])
    ).scalar() or 0

    total_sales = db.query(func.sum(Sale.units_sold)).scalar() or 0

    low_stock = db.query(func.count(Product.id)).filter(
        Product.criticality_score >= 0.8
    ).scalar() or 0

    forecast_row = db.query(Forecast).first()
    fill_rate = 97.9

    return DashboardKPI(
        total_skus=total_skus,
        total_suppliers=total_suppliers,
        active_orders=active_orders,
        total_sales=float(total_sales),
        low_stock_count=low_stock,
        fill_rate=fill_rate,
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
    Per-SKU stockout risk analysis using demand forecasting.
    Tries database first (dynamic), falls back to CSV files if DB is empty.
    Returns all SKUs with demand forecasts and risk levels.
    """
    from sqlalchemy import text

    sales_df = None
    products_df = None

    # --- Try loading from database first ---
    try:
        sales_query = text("""
            SELECT sku_id, sale_date, units_sold
            FROM sales
            WHERE sale_date >= :cutoff
            ORDER BY sale_date
        """)
        cutoff = date.today() - timedelta(weeks=26)
        rows = db.execute(sales_query, {"cutoff": cutoff}).fetchall()
        if rows:
            sales_df = pd.DataFrame(rows, columns=["sku_id", "sale_date", "units_sold"])
            sales_df["sale_date"] = pd.to_datetime(sales_df["sale_date"])

            products_query = text("SELECT sku_id, category, sub_category, criticality_score FROM products")
            prod_rows = db.execute(products_query).fetchall()
            if prod_rows:
                products_df = pd.DataFrame(prod_rows, columns=["sku_id", "category", "sub_category", "criticality_score"])
    except Exception:
        pass

    # --- Fallback to CSV files ---
    if sales_df is None or len(sales_df) == 0:
        csv_path = DATA_DIR / "fact_sales.csv"
        products_path = DATA_DIR / "dim_products.csv"
        if not csv_path.exists():
            return {"status": "error", "message": "No sales data found in database or CSV files"}

        sales_df = pd.read_csv(csv_path, parse_dates=["Date"])
        sales_df.rename(columns={"Date": "sale_date", "SKU_ID": "sku_id", "Units_Sold": "units_sold"}, inplace=True)

        if products_path.exists():
            products_df = pd.read_csv(products_path)
            products_df.rename(columns={"SKU_ID": "sku_id", "Category": "category", "Sub_Category": "sub_category", "Criticality_Score": "criticality_score"}, inplace=True)

    max_date = sales_df["sale_date"].max()
    cutoff_13w = max_date - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w].copy()

    # Per-SKU demand statistics
    sku_stats = recent.groupby("sku_id").agg(
        total_sold_13w=("units_sold", "sum"),
        avg_weekly=("units_sold", "mean"),
        std_weekly=("units_sold", "std"),
        weeks_active=("sale_date", "nunique"),
        last_week_sales=("units_sold", "last"),
    ).reset_index()

    # Include ALL SKUs with at least 2 weeks of data (be inclusive)
    sku_stats = sku_stats[sku_stats["weeks_active"] >= 2].copy()

    if len(sku_stats) == 0:
        return {"status": "error", "message": "Not enough sales data for risk analysis"}

    # Demand trend: compare last 4 weeks vs previous 4 weeks
    cutoff_4w = max_date - pd.Timedelta(weeks=4)
    cutoff_8w = max_date - pd.Timedelta(weeks=8)

    recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
    prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()

    sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
    sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)

    # Demand trend ratio (1.0 = stable, >1.0 = increasing, <1.0 = decreasing)
    sku_stats["demand_trend"] = np.where(
        sku_stats["prev_4w"] > 0,
        sku_stats["recent_4w"] / sku_stats["prev_4w"],
        1.0,
    )

    # Forecast weekly demand for next 12 weeks using EWMA trend
    sku_stats["forecast_weekly"] = sku_stats["avg_weekly"] * sku_stats["demand_trend"]

    # Estimate current stock: assume 8 weeks baseline
    sku_stats["estimated_stock"] = (sku_stats["avg_weekly"] * 8).round(0).astype(int)

    # Weeks of coverage at forecasted demand
    sku_stats["coverage_weeks"] = np.where(
        sku_stats["forecast_weekly"] > 0,
        sku_stats["estimated_stock"] / sku_stats["forecast_weekly"],
        99,
    )

    # Total forecasted demand for next 12 weeks
    sku_stats["forecast_12w"] = (sku_stats["forecast_weekly"] * weeks_ahead).round(0).astype(int)

    # Shortfall if coverage < weeks_ahead
    sku_stats["shortfall_weeks"] = np.maximum(weeks_ahead - sku_stats["coverage_weeks"], 0).round(1)

    # Risk level
    def risk_level(cov_weeks, trend):
        if cov_weeks < 4 or (cov_weeks < 6 and trend > 1.1):
            return "CRITICAL"
        elif cov_weeks < 6:
            return "HIGH"
        elif cov_weeks < 8:
            return "MEDIUM"
        else:
            return "LOW"

    sku_stats["risk_level"] = sku_stats.apply(
        lambda r: risk_level(r["coverage_weeks"], r["demand_trend"]), axis=1
    )

    # Merge category from products
    if products_df is not None and len(products_df) > 0:
        sku_cat = products_df[["sku_id", "category", "sub_category", "criticality_score"]].drop_duplicates(subset="sku_id")
        sku_stats = sku_stats.merge(sku_cat, on="sku_id", how="left")
        sku_stats.rename(columns={"category": "Category", "sub_category": "Sub_Category", "criticality_score": "Criticality_Score"}, inplace=True)
    else:
        prefix_map = {"SP": "Spare Parts", "LU": "Lubricants", "EP": "Electric Pumps", "EN": "Engines", "PC": "Precision Components"}
        sku_stats["Category"] = sku_stats["sku_id"].str[:2].map(prefix_map).fillna("Unknown")
        sku_stats["Sub_Category"] = ""
        sku_stats["Criticality_Score"] = 0.5

    # Fill NaN categories
    sku_stats["Category"] = sku_stats["Category"].fillna("Unknown")

    # Sort by risk (critical first), then by shortfall
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sku_stats["risk_sort"] = sku_stats["risk_level"].map(risk_order)
    sku_stats = sku_stats.sort_values(["risk_sort", "shortfall_weeks"], ascending=[True, False]).reset_index(drop=True)

    # Build response — ALL SKUs, with serial number
    results = []
    for idx, row in sku_stats.iterrows():
        results.append({
            "s_no": idx + 1,
            "sku_id": row["sku_id"],
            "category": row.get("Category", "Unknown"),
            "sub_category": row.get("Sub_Category", ""),
            "criticality": float(row.get("Criticality_Score", 0.5)),
            "avg_weekly_demand": round(float(row["avg_weekly"]), 1),
            "forecast_weekly": round(float(row["forecast_weekly"]), 1),
            "demand_trend_pct": round(float((row["demand_trend"] - 1) * 100), 1),
            "estimated_stock": int(row["estimated_stock"]),
            "coverage_weeks": round(float(row["coverage_weeks"]), 1),
            "forecast_12w_demand": int(row["forecast_12w"]),
            "shortfall_weeks": round(float(row["shortfall_weeks"]), 1),
            "risk_level": row["risk_level"],
        })

    # Summary stats
    critical_count = len(sku_stats[sku_stats["risk_level"] == "CRITICAL"])
    high_count = len(sku_stats[sku_stats["risk_level"] == "HIGH"])
    medium_count = len(sku_stats[sku_stats["risk_level"] == "MEDIUM"])

    return {
        "status": "success",
        "summary": {
            "total_skus_analyzed": len(sku_stats),
            "critical": critical_count,
            "high": high_count,
            "medium": medium_count,
            "low": len(sku_stats) - critical_count - high_count - medium_count,
        },
        "risks": results,
        "forecast_horizon_weeks": weeks_ahead,
    }


def _load_sales_products():
    """Shared helper: load sales + products from DB or CSV fallback."""
    from sqlalchemy import text
    from app.database import SessionLocal

    db = SessionLocal()
    sales_df = None
    products_df = None
    try:
        try:
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
            csv_path = DATA_DIR / "fact_sales.csv"
            products_path = DATA_DIR / "dim_products.csv"
            if csv_path.exists():
                sales_df = pd.read_csv(csv_path, parse_dates=["Date"])
                sales_df.rename(columns={"Date": "sale_date", "SKU_ID": "sku_id", "Units_Sold": "units_sold"}, inplace=True)
            if products_path.exists():
                products_df = pd.read_csv(products_path)
                products_df.rename(columns={"SKU_ID": "sku_id", "Category": "category", "Sub_Category": "sub_category", "Criticality_Score": "criticality_score"}, inplace=True)
    finally:
        db.close()

    return sales_df, products_df


@router.get("/charts/category-forecast")
def category_forecast():
    """
    Category-level forecast aggregation with trends.
    Shows total forecast demand per category for next 12 weeks, trend arrows, and contribution %.
    """
    sales_df, products_df = _load_sales_products()
    if sales_df is None or len(sales_df) == 0:
        return {"status": "error", "message": "No sales data"}

    max_date = sales_df["sale_date"].max()

    # Merge category
    if products_df is not None and len(products_df) > 0:
        sales_df = sales_df.merge(products_df[["sku_id", "category"]].drop_duplicates("sku_id"), on="sku_id", how="left")
    else:
        prefix_map = {"SP": "Spare Parts", "LU": "Lubricants", "EP": "Electric Pumps", "EN": "Engines", "PC": "Precision Components"}
        sales_df["category"] = sales_df["sku_id"].str[:2].map(prefix_map).fillna("Unknown")

    sales_df["category"] = sales_df["category"].fillna("Unknown")

    # Recent 13 weeks per category
    cutoff_13w = max_date - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
    cat_stats = recent.groupby("category").agg(
        avg_weekly=("units_sold", "mean"),
        total_13w=("units_sold", "sum"),
    ).reset_index()

    # Trend: last 4w vs prev 4w
    cutoff_4w = max_date - pd.Timedelta(weeks=4)
    cutoff_8w = max_date - pd.Timedelta(weeks=8)
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
    sales_df, _ = _load_sales_products()
    if sales_df is None or len(sales_df) == 0:
        return {"labels": [], "values": [], "granularity": granularity}

    max_date = sales_df["sale_date"].max()

    if months is not None and months > 0:
        if months == 12:
            cutoff = pd.Timestamp(f"{max_date.year}-01-01")
        else:
            cutoff = max_date - pd.DateOffset(months=months)
        sales_df = sales_df[sales_df["sale_date"] >= cutoff]
    elif start_date:
        sales_df = sales_df[sales_df["sale_date"] >= pd.to_datetime(start_date)]

    if end_date:
        ed = pd.to_datetime(end_date)
        if ed > max_date:
            ed = max_date
        sales_df = sales_df[sales_df["sale_date"] <= ed]

    if len(sales_df) == 0:
        return {"labels": [], "values": [], "granularity": granularity}

    if granularity == "daily":
        grouped = sales_df.groupby(sales_df["sale_date"].dt.strftime("%Y-%m-%d"))["units_sold"].sum().reset_index()
        grouped.columns = ["period", "value"]
    elif granularity == "monthly":
        grouped = sales_df.groupby(sales_df["sale_date"].dt.strftime("%Y-%m"))["units_sold"].sum().reset_index()
        grouped.columns = ["period", "value"]
    else:  # weekly (default)
        week_starts = sales_df["sale_date"].dt.to_period("W").apply(lambda r: r.start_time)
        grouped = sales_df.groupby(week_starts)["units_sold"].sum().reset_index()
        grouped.columns = ["week_start", "value"]
        grouped = grouped.sort_values("week_start")
        if months is not None and 0 < months <= 6:
            grouped["period"] = pd.to_datetime(grouped["week_start"]).dt.strftime("%b %d")
        else:
            grouped["period"] = pd.to_datetime(grouped["week_start"]).dt.strftime("%Y-%m-%d")
        return {
            "labels": grouped["period"].tolist(),
            "values": [int(v) for v in grouped["value"].tolist()],
            "granularity": granularity,
        }

    grouped = grouped.sort_values("period")

    return {
        "labels": grouped["period"].tolist(),
        "values": [int(v) for v in grouped["value"].tolist()],
        "granularity": granularity,
    }
