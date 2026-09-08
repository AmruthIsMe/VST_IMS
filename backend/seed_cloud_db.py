"""
VST IMS — Database Seeder

Seeds the database with initial data from CSV files.
Supports both local SQLite and cloud PostgreSQL.

Usage:
    cd backend
    python seed_cloud_db.py              # seeds local SQLite (default)
    python seed_cloud_db.py --cloud      # seeds cloud Supabase PostgreSQL
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


def load_db_url(cloud_mode=False):
    """Load the database URL. Cloud mode uses CLOUD_DATABASE_URL, local uses SQLite."""
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")

    if cloud_mode:
        url = os.getenv("CLOUD_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not url or url.startswith("sqlite"):
            print("\n⚠️  No cloud DATABASE_URL found!")
            print("   Add CLOUD_DATABASE_URL=postgresql://... to backend/.env")
            sys.exit(1)
        return url

    # Local mode: use SQLite
    url = os.getenv("DATABASE_URL")
    if url and not url.startswith("sqlite"):
        print(f"\n   Using DATABASE_URL from env: {url[:50]}...")
        return url

    sqlite_path = BACKEND_DIR / "vst_ims.db"
    return f"sqlite:///{str(sqlite_path).replace(chr(92), '/')}"


def create_tables(engine):
    """Create all tables from SQLAlchemy models."""
    print("   📋 Creating tables...")
    
    # Import all models to register them with Base
    from app.database import Base
    from app.models import (
        Product, Supplier, User, Order, OrderItem, Sale,
        ExternalFactor, Forecast, ForecastModel, ForecastPrediction,
        SapSyncLog, SapConfig, GenieConversation, GenieMessage, Inventory,
    )
    
    Base.metadata.create_all(bind=engine)
    print("   ✅ All 15 tables created")


def seed_products(conn):
    """Seed products from dim_products.csv."""
    csv_path = DATA_DIR / "dim_products.csv"
    if not csv_path.exists():
        print("   ⚠️  dim_products.csv not found, skipping")
        return
    
    df = pd.read_csv(csv_path)
    print(f"   📦 Loading {len(df)} products...")
    
    now = datetime.now()
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
    
    now = datetime.now()
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
    
    def get_hash(pw: str) -> str:
        return pw
    
    now = datetime.now()
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

    # Also add standard demo accounts for UI login
    demo_defaults = [
        {"user_id": "admin", "name": "Amruth", "email": "admin@vst.com", "role": "Admin"},
        {"user_id": "manager", "name": "Priya Sharma", "email": "manager@vst.com", "role": "Manager"},
        {"user_id": "cashier", "name": "Rahul Desai", "email": "cashier@vst.com", "role": "Cashier"},
    ]
    for demo in demo_defaults:
        if not any(r["user_id"] == demo["user_id"] or r["email"] == demo["email"] for r in records):
            records.append({
                "id": str(uuid.uuid4()),
                "user_id": demo["user_id"],
                "name": demo["name"],
                "email": demo["email"],
                "password_hash": get_hash("vst2026"),
                "role": demo["role"],
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
    
    now = datetime.now()
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


def seed_inventory(conn):
    """
    Seed inventory with realistic stock levels per category.
    Stock ranges are based on typical warehouse operations:
      - Spare Parts (SP): high volume, 200–2000 units
      - Lubricants (LU): bulk items, 150–1500 units
      - Electric Pumps (EP): medium, 20–150 units
      - Engines (EN): low volume, high value, 5–40 units
      - Precision Components (PC): low volume, 10–80 units
    """
    import random
    random.seed(42)

    from sqlalchemy import text
    prod_rows = conn.execute(text("SELECT sku_id, category FROM products")).fetchall()

    category_ranges = {
        "Spare Parts":        (200, 2000),
        "Lubricants":         (150, 1500),
        "Electric Pumps":     (20, 150),
        "Engines":            (5, 40),
        "Precision Components": (10, 80),
    }

    category_costs = {
        "Spare Parts":        (500.0, 3500.0),
        "Lubricants":         (400.0, 1800.0),
        "Electric Pumps":     (8000.0, 25000.0),
        "Engines":            (45000.0, 180000.0),
        "Precision Components": (15000.0, 65000.0),
    }

    now = datetime.now()
    records = []
    for sku_id, category in prod_rows:
        lo, hi = category_ranges.get(category, (50, 500))
        on_hand = random.randint(lo, hi)
        reserved = random.randint(0, int(on_hand * 0.3))
        available = on_hand - reserved
        
        cost_lo, cost_hi = category_costs.get(category, (800.0, 5000.0))
        unit_cost = round(random.uniform(cost_lo, cost_hi), 2)

        records.append({
            "id": str(uuid.uuid4()),
            "sku_id": sku_id,
            "quantity_on_hand": on_hand,
            "quantity_reserved": reserved,
            "quantity_available": available,
            "unit_cost_inr": unit_cost,
            "created_at": now,
            "updated_at": now,
        })

    pd.DataFrame(records).to_sql("inventory", conn, if_exists="append", index=False, method="multi")
    print(f"   ✅ {len(records)} inventory records seeded")


def main():
    cloud_mode = "--cloud" in sys.argv

    mode_label = "Cloud PostgreSQL" if cloud_mode else "Local SQLite"
    print("\n" + "🌱" * 20)
    print(f"  VST IMS — Database Seeder ({mode_label})")
    print("🌱" * 20)

    if cloud_mode:
        print("\n  ⚠️  WARNING: This will DELETE ALL production data in the cloud database!")
        print("  ⚠️  Sales, orders, SAP sync logs, and all other data will be permanently lost.")
        print("  ⚠️  This should ONLY be run on a fresh database or during initial setup.")
        confirm = input("\n  Type 'YES-DELETE-PRODUCTION-DATA' to confirm: ").strip()
        if confirm != "YES-DELETE-PRODUCTION-DATA":
            print("  ❌ Aborted. No changes made.")
            sys.exit(0)

    db_url = load_db_url(cloud_mode=cloud_mode)
    print(f"\n   🔗 DB: {db_url[:60]}...")

    from sqlalchemy import create_engine, text
    engine = create_engine(db_url, pool_pre_ping=True)

    # Test connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("   ✅ Connected to database!")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        sys.exit(1)

    # Create tables
    create_tables(engine)

    # Clean existing data before seeding to ensure consistent state
    with engine.connect() as conn:
        print("   🗑️  Resetting tables for clean seed...")
        for table in ["inventory", "forecast_predictions", "forecast_models", "forecasts", "genie_messages",
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
        seed_inventory(conn)
        conn.commit()

    print("\n" + "=" * 60)
    print("  🎉  DATABASE SEEDED SUCCESSFULLY!")
    print("=" * 60)
    print(f"  Tables populated:")

    with engine.connect() as conn:
        for table in ["products", "suppliers", "users", "sales", "external_factors", "forecasts", "inventory"]:
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]
                print(f"    {table:25s} {count:>8,} rows")
            except Exception:
                print(f"    {table:25s} (error)")

    print("\n  Next steps:")
    if cloud_mode:
        print("  1. Deploy backend to Render")
        print("  2. Run train_and_upload.py to generate ML predictions")
    else:
        print("  1. Restart the backend: uvicorn app.main:app --reload")
        print("  2. Visit http://localhost:8000/docs to explore the API")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
