from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal_column
from datetime import date, timedelta
from app.database import get_db, engine
from app.models import Product, Supplier, Order, Sale, Forecast
from app.schemas import DashboardKPI, ChartData

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


@router.get("/charts/demand-trend")
def demand_trend(db: Session = Depends(get_db)):
    is_sqlite = "sqlite" in str(engine.url)
    six_months_ago = date(2025, 1, 1)

    if is_sqlite:
        month_expr = func.strftime("%Y-%m", Sale.sale_date)
    else:
        month_expr = func.date_trunc("month", Sale.sale_date)

    rows = (
        db.query(
            month_expr.label("month"),
            func.sum(Sale.units_sold).label("total"),
        )
        .filter(Sale.sale_date >= six_months_ago)
        .group_by("month")
        .order_by("month")
        .all()
    )
    return {
        "labels": [str(r.month)[:7] for r in rows],
        "values": [float(r.total) for r in rows],
    }


@router.get("/charts/category-distribution")
def category_distribution(db: Session = Depends(get_db)):
    rows = (
        db.query(Product.category, func.count(Product.id))
        .group_by(Product.category)
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
