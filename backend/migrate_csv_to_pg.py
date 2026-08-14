"""
One-time migration script: CSV files -> PostgreSQL
Run after setting up the database and models.
Usage: python migrate_csv_to_pg.py
"""
import sys
import os
import uuid
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.models import Product, Supplier, User, Order, Sale, ExternalFactor, Forecast


def generate_uuid():
    return uuid.uuid4()


def safe_int(val, default=0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_str(val, default=""):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return str(val)


def migrate_products(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for _, row in df.iterrows():
        product = Product(
            id=generate_uuid(),
            sku_id=safe_str(row.get("SKU_ID"), f"SKU-{count}"),
            category=safe_str(row.get("Category")),
            sub_category=safe_str(row.get("Sub_Category")),
            machine_compatibility=safe_str(row.get("Machine_Compatibility")),
            shelf_life_days=safe_int(row.get("Shelf_Life_Days")),
            unit_volume_m3=safe_float(row.get("Unit_Volume_m3")),
            criticality_score=safe_float(row.get("Criticality_Score")),
        )
        db.add(product)
        count += 1
    db.commit()
    print(f"  Migrated {count} products")
    return count


def migrate_suppliers(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for _, row in df.iterrows():
        supplier = Supplier(
            id=generate_uuid(),
            supplier_id=safe_str(row.get("Supplier_ID"), f"SUP-{count}"),
            supplier_name=safe_str(row.get("Supplier_Name"), f"Supplier {count}"),
            origin_country=safe_str(row.get("Origin_Country")),
            primary_category=safe_str(row.get("Primary_Category")),
            base_lead_time_days=safe_int(row.get("Base_Lead_Time_Days")),
            lead_time_volatility=safe_float(row.get("Lead_Time_Volatility")),
            moq=safe_int(row.get("MOQ")),
            unit_cost_inr=safe_float(row.get("Unit_Cost_INR")),
        )
        db.add(supplier)
        count += 1
    db.commit()
    print(f"  Migrated {count} suppliers")
    return count


def migrate_users(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    count = 0
    for _, row in df.iterrows():
        user = User(
            id=generate_uuid(),
            user_id=safe_str(row.get("User_ID"), f"USR-{count}"),
            name=safe_str(row.get("Name")),
            email=safe_str(row.get("Email"), f"user{count}@vst.com"),
            password_hash=pwd_context.hash("default123"),
            role=safe_str(row.get("Role"), "Viewer"),
            status=safe_str(row.get("Status"), "Active"),
        )
        db.add(user)
        count += 1
    db.commit()
    print(f"  Migrated {count} users (default password: default123)")
    return count


def migrate_sales(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)

    products = {p.sku_id: p.id for p in db.query(Product).all()}
    count = 0
    for _, row in df.iterrows():
        sku = row.get("SKU_ID", "")
        product_id = products.get(sku)
        if not product_id:
            continue
        sale = Sale(
            id=generate_uuid(),
            sale_date=pd.to_datetime(row.get("Date")).date(),
            product_id=product_id,
            sku_id=sku,
            units_sold=safe_int(row.get("Units_Sold")),
            fulfillment_region=safe_str(row.get("Fulfillment_Region")),
            stockout_flag=bool(row.get("Stockout_Flag", False)),
        )
        db.add(sale)
        count += 1
        if count % 5000 == 0:
            db.commit()
            print(f"    ... {count} sales migrated")
    db.commit()
    print(f"  Migrated {count} sales records")
    return count


def migrate_orders(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for _, row in df.iterrows():
        order = Order(
            id=generate_uuid(),
            order_id=safe_str(row.get("Order_ID"), f"ORD-{count}"),
            order_date=pd.to_datetime(row.get("Date")).date(),
            customer_name=safe_str(row.get("Customer_Name")),
            total_amount_inr=safe_float(row.get("Total_Amount_INR")),
            payment_status=safe_str(row.get("Payment_Status"), "Pending"),
            order_status=safe_str(row.get("Order_Status"), "Pending"),
        )
        db.add(order)
        count += 1
    db.commit()
    print(f"  Migrated {count} orders")
    return count


def migrate_external_factors(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for _, row in df.iterrows():
        ef = ExternalFactor(
            id=generate_uuid(),
            factor_date=pd.to_datetime(row.get("Date")).date(),
            monsoon_index=safe_float(row.get("Monsoon_Index")),
            crop_sowing_season=safe_str(row.get("Crop_Sowing_Season")),
            macro_economic_index=safe_float(row.get("Macro_Economic_Index")),
        )
        db.add(ef)
        count += 1
    db.commit()
    print(f"  Migrated {count} external factors")
    return count


def migrate_forecasts(db, csv_path):
    if not os.path.exists(csv_path):
        print(f"  Skipping {csv_path} (not found)")
        return 0
    df = pd.read_csv(csv_path)

    products = {p.sku_id: p.id for p in db.query(Product).all()}
    count = 0
    for _, row in df.iterrows():
        sku = row.get("SKU_ID", "")
        product_id = products.get(sku)
        if not product_id:
            continue
        forecast = Forecast(
            id=generate_uuid(),
            product_id=product_id,
            sku_id=sku,
            forecast_date=pd.to_datetime(row.get("Date")).date(),
            predicted_demand=safe_float(row.get("Predicted_Demand")),
            actual_demand=safe_float(row.get("Actual_Demand")) if pd.notna(row.get("Actual_Demand")) else None,
            model_version="xgb_v1",
        )
        db.add(forecast)
        count += 1
        if count % 2000 == 0:
            db.commit()
    db.commit()
    print(f"  Migrated {count} forecasts")
    return count


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("\nMigrating CSV data to PostgreSQL...")
        print("-" * 40)

        migrate_products(db, os.path.join(data_dir, "dim_products.csv"))
        migrate_suppliers(db, os.path.join(data_dir, "dim_suppliers.csv"))
        migrate_users(db, os.path.join(data_dir, "dim_users.csv"))
        migrate_orders(db, os.path.join(data_dir, "fact_orders.csv"))
        migrate_sales(db, os.path.join(data_dir, "fact_sales.csv"))
        migrate_external_factors(db, os.path.join(data_dir, "fact_external.csv"))
        migrate_forecasts(db, os.path.join(data_dir, "demand_forecast.csv"))

        print("-" * 40)
        print("Migration complete!")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
