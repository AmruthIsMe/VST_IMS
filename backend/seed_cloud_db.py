"""
VST IMS — One-Time Cloud Database Seeder

Seeds the Supabase PostgreSQL database with initial data from CSV files.
Run this ONCE after creating the Supabase database.

Usage:
    cd backend
    python seed_cloud_db.py

Reads CLOUD_DATABASE_URL from backend/.env
"""

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime

# Configure utf-8 encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd
import numpy as np


DATA_DIR = BACKEND_DIR.parent / "data"


def load_db_url():
    """Load the cloud DATABASE_URL."""
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
    
    url = os.getenv("CLOUD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url or url.startswith("sqlite"):
        print("\n⚠️  No cloud DATABASE_URL found!")
        print("   Add CLOUD_DATABASE_URL=postgresql://... to backend/.env")
        sys.exit(1)
    return url


def create_tables(engine):
    """Create all tables from SQLAlchemy models."""
    print("   📋 Creating tables...")
    
    # Import all models to register them with Base
    from app.database import Base
    from app.models import (
        Product, Supplier, User, Order, OrderItem, Sale,
        ExternalFactor, Forecast, ForecastModel, ForecastPrediction,
        SapSyncLog, SapConfig, GenieConversation, GenieMessage,
    )
    
    Base.metadata.create_all(bind=engine)
    print("   ✅ All 14 tables created")


def seed_products(conn):
    """Seed products from dim_products.csv."""
    csv_path = DATA_DIR / "dim_products.csv"
    if not csv_path.exists():
        print("   ⚠️  dim_products.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path)
    print(f"   📦 Loading {len(df)} products...")
    
    now = datetime.utcnow()
    records = []
    for _, row in df.iterrows():
        records.append({
            "id": str(uuid.uuid4()),
            "sku_id": row["SKU_ID"],
            "category": row["Category"],
            "sub_category": row.get("Sub_Category", ""),
            "machine_compatibility": row.get("Machine_Compatibility", ""),
            "shelf_life_days": int(row["Shelf_Life_Days"]) if pd.notna(row.get("Shelf_Life_Days")) else None,
            "unit_volume_m3": float(row["Unit_Volume_m3"]) if pd.notna(row.get("Unit_Volume_m3")) else None,
            "criticality_score": float(row["Criticality_Score"]) if pd.notna(row.get("Criticality_Score")) else None,
            "created_at": now,
            "updated_at": now,
        })
    
    pd.DataFrame(records).to_sql("products", conn, if_exists="append", index=False, method="multi")
    print(f"   ✅ {len(records)} products seeded")


def seed_suppliers(conn):
    """Seed suppliers from dim_suppliers.csv."""
    csv_path = DATA_DIR / "dim_suppliers.csv"
    if not csv_path.exists():
        print("   ⚠️  dim_suppliers.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path)
    print(f"   🏭 Loading {len(df)} suppliers...")
    
    now = datetime.utcnow()
    records = []
    for _, row in df.iterrows():
        records.append({
            "id": str(uuid.uuid4()),
            "supplier_id": row["Supplier_ID"],
            "supplier_name": row.get("Supplier_Name", f"Supplier {row['Supplier_ID']}"),
            "origin_country": row.get("Origin_Country", ""),
            "primary_category": row.get("Primary_Category", ""),
            "base_lead_time_days": int(row.get("Base_Lead_Time_Days", 30)),
            "lead_time_volatility": float(row.get("Lead_Time_Volatility", 0.1)),
            "moq": int(row.get("Minimum_Order_Quantity", 10)),
            "unit_cost_inr": float(row.get("Unit_Cost_INR", 1000)),
            "created_at": now,
            "updated_at": now,
        })
    
    pd.DataFrame(records).to_sql("suppliers", conn, if_exists="append", index=False, method="multi")
    print(f"   ✅ {len(records)} suppliers seeded")


def seed_users(conn):
    """Seed users from dim_users.csv."""
    csv_path = DATA_DIR / "dim_users.csv"
    if not csv_path.exists():
        print("   ⚠️  dim_users.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path)
    print(f"   👤 Loading {len(df)} users...")
    
    import hashlib
    def get_hash(pw: str) -> str:
        try:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt", "pbkdf2_sha256"], deprecated="auto")
            return pwd_context.hash(pw)
        except Exception:
            return "$pbkdf2-sha256$" + hashlib.sha256(pw.encode()).hexdigest()
    
    now = datetime.utcnow()
    records = []
    for _, row in df.iterrows():
        pw = str(row.get("Password", "vst2026"))
        records.append({
            "id": str(uuid.uuid4()),
            "user_id": row.get("User_ID", f"U{len(records)+1:03d}"),
            "name": row.get("Name", "User"),
            "email": row.get("Email", f"user{len(records)+1}@vst.com"),
            "password_hash": get_hash(pw),
            "role": row.get("Role", "Viewer"),
            "status": "Active",
            "created_at": now,
            "updated_at": now,
        })
    
    pd.DataFrame(records).to_sql("users", conn, if_exists="append", index=False, method="multi")
    print(f"   ✅ {len(records)} users seeded")



def seed_sales(conn):
    """Seed sales from fact_sales.csv."""
    csv_path = DATA_DIR / "fact_sales.csv"
    if not csv_path.exists():
        print("   ⚠️  fact_sales.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path, parse_dates=["Date"])
    print(f"   📈 Loading {len(df)} sales records (this may take a moment)...")
    
    # We need product IDs — query from the products table
    from sqlalchemy import text
    prod_rows = conn.execute(text("SELECT id, sku_id FROM products")).fetchall()
    sku_to_id = {row[1]: row[0] for row in prod_rows}
    
    records = []
    for _, row in df.iterrows():
        sku_id = row.get("SKU_ID", "")
        product_id = sku_to_id.get(sku_id)
        if not product_id:
            continue
        
        records.append({
            "id": str(uuid.uuid4()),
            "sale_date": row["Date"].date() if hasattr(row["Date"], "date") else row["Date"],
            "product_id": product_id,
            "sku_id": sku_id,
            "units_sold": int(row.get("Units_Sold", 0)),
            "fulfillment_region": row.get("Fulfillment_Region", "Unknown"),
            "stockout_flag": bool(row.get("Stockout_Flag", False)),
        })
    
    # Upload in chunks to avoid memory issues
    chunk_size = 5000
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        pd.DataFrame(chunk).to_sql("sales", conn, if_exists="append", index=False, method="multi")
        print(f"   📊 Uploaded {min(i + chunk_size, len(records))}/{len(records)} sales records...")
    
    conn.commit()
    print(f"   ✅ {len(records)} sales records seeded")


def seed_external_factors(conn):
    """Seed external factors from fact_external.csv."""
    csv_path = DATA_DIR / "fact_external.csv"
    if not csv_path.exists():
        print("   ⚠️  fact_external.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path, parse_dates=["Date"])
    print(f"   🌍 Loading {len(df)} external factor records...")
    
    records = []
    for _, row in df.iterrows():
        records.append({
            "id": str(uuid.uuid4()),
            "factor_date": row["Date"].date() if hasattr(row["Date"], "date") else row["Date"],
            "monsoon_index": float(row.get("Monsoon_Index", 0)),
            "crop_sowing_season": row.get("Crop_Sowing_Season", ""),
            "macro_economic_index": float(row.get("Macro_Economic_Index", 0)),
        })
    
    pd.DataFrame(records).to_sql("external_factors", conn, if_exists="append", index=False, method="multi")
    print(f"   ✅ {len(records)} external factors seeded")


def seed_forecasts(conn):
    """Seed pre-generated forecasts from demand_forecast.csv."""
    csv_path = DATA_DIR / "demand_forecast.csv"
    if not csv_path.exists():
        print("   ⚠️  demand_forecast.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path, parse_dates=["Date"])
    print(f"   🔮 Loading {len(df)} forecast records...")
    
    # Get product IDs
    from sqlalchemy import text
    prod_rows = conn.execute(text("SELECT id, sku_id FROM products")).fetchall()
    sku_to_id = {row[1]: row[0] for row in prod_rows}
    
    now = datetime.utcnow()
    records = []
    for _, row in df.iterrows():
        sku_id = row.get("SKU_ID", "")
        product_id = sku_to_id.get(sku_id)
        if not product_id:
            continue
        
        records.append({
            "id": str(uuid.uuid4()),
            "product_id": product_id,
            "sku_id": sku_id,
            "forecast_date": row["Date"].date() if hasattr(row["Date"], "date") else row["Date"],
            "predicted_demand": float(row.get("Predicted_Demand", row.get("predicted_demand", 0))),
            "actual_demand": float(row.get("Actual_Demand", row.get("actual_demand", 0))) if pd.notna(row.get("Actual_Demand", row.get("actual_demand"))) else None,
            "model_version": "v1-seed",
            "created_at": now,
        })
    
    chunk_size = 5000
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        pd.DataFrame(chunk).to_sql("forecasts", conn, if_exists="append", index=False, method="multi")
        print(f"   📊 Uploaded {min(i + chunk_size, len(records))}/{len(records)} forecast records...")
    
    conn.commit()
    print(f"   ✅ {len(records)} forecast records seeded")


def main():
    print("\n" + "🌱" * 20)
    print("  VST IMS — Cloud Database Seeder")
    print("🌱" * 20)
    
    db_url = load_db_url()
    print(f"\n   🔗 Cloud DB: {db_url[:50]}...")
    
    from sqlalchemy import create_engine, text
    engine = create_engine(db_url, pool_pre_ping=True)
    
    # Test connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("   ✅ Connected to cloud database!")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        sys.exit(1)
    
    # Create tables
    create_tables(engine)
    
    # Clean existing data before seeding to ensure consistent state
    with engine.connect() as conn:
        print("   🗑️  Resetting tables for clean seed...")
        for table in ["forecast_predictions", "forecast_models", "forecasts", "genie_messages",
                     "genie_conversations", "sap_sync_log", "sap_config", "order_items",
                     "orders", "sales", "external_factors", "suppliers", "users", "products"]:
            try:
                conn.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass
        conn.commit()

    
    # Seed each table
    with engine.connect() as conn:
        seed_products(conn)
        conn.commit()
        seed_suppliers(conn)
        conn.commit()
        seed_users(conn)
        conn.commit()
        seed_sales(conn)
        conn.commit()
        seed_external_factors(conn)
        conn.commit()
        seed_forecasts(conn)
        conn.commit()
    
    print("\n" + "=" * 60)
    print("  🎉  DATABASE SEEDED SUCCESSFULLY!")
    print("=" * 60)
    print(f"  Tables populated:")
    
    with engine.connect() as conn:
        for table in ["products", "suppliers", "users", "sales", "external_factors", "forecasts"]:
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]
                print(f"    {table:25s} {count:>8,} rows")
            except Exception:
                print(f"    {table:25s} (error)")
    
    print("\n  Next steps:")
    print("  1. Deploy backend to Render")
    print("  2. Run train_and_upload.py to generate ML predictions")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
