"""
restore_cloud_data.py — Extend sales/forecasts/external data to today.

When run with --cloud, connects to Supabase PostgreSQL and generates
realistic sales data from the last seeded date up to today's date,
using the same demand profiles and seasonality as the mock ERP.

Usage:
    python restore_cloud_data.py --cloud
    python restore_cloud_data.py            # local SQLite
"""

import sys
import os
import csv
import math
import random
import uuid
from datetime import date, datetime, timedelta

random.seed(42)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _load_demand_profiles():
    """Build per-SKU demand profiles (mean, std) from fact_sales.csv."""
    profiles = {}
    csv_path = os.path.join(DATA_DIR, "fact_sales.csv")
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
    return profiles


def _seasonal_factor(d: date) -> float:
    """Indian agri seasonality — matches mock ERP."""
    month = d.month
    if month in (10, 11, 12):
        return random.uniform(1.2, 1.8)
    if month in (3, 4, 5):
        return random.uniform(1.1, 1.3)
    if month in (6, 7, 8, 9):
        return random.uniform(1.2, 1.5)
    return random.uniform(0.9, 1.1)


def _load_external_factors():
    """Load existing external factor patterns from CSV."""
    factors = []
    csv_path = os.path.join(DATA_DIR, "fact_external.csv")
    if not os.path.exists(csv_path):
        return factors
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                factors.append({
                    "date": row["Date"],
                    "monsoon_index": float(row.get("Monsoon_Index", 0)),
                    "crop_season": row.get("Crop_Sowing_Season", ""),
                    "macro_index": float(row.get("Macro_Economic_Index", 1.0)),
                })
            except (ValueError, KeyError):
                continue
    return factors


def _load_forecast_profiles():
    """Load forecast data patterns from demand_forecast.csv."""
    profiles = {}
    csv_path = os.path.join(DATA_DIR, "demand_forecast.csv")
    if not os.path.exists(csv_path):
        return profiles
    sums, counts = {}, {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sku = (row.get("SKU_ID") or "").strip()
            try:
                predicted = float(row.get("predicted_demand", 0))
            except ValueError:
                continue
            sums[sku] = sums.get(sku, 0.0) + predicted
            counts[sku] = counts.get(sku, 0) + 1
    for sku, n in counts.items():
        profiles[sku] = sums[sku] / n
    return profiles


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def load_db_url(cloud_mode=False):
    if cloud_mode:
        url = os.environ.get("CLOUD_DATABASE_URL", "")
        if not url:
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("CLOUD_DATABASE_URL="):
                            url = line.split("=", 1)[1].strip()
                            break
        if not url:
            print("ERROR: Set CLOUD_DATABASE_URL or add it to .env")
            sys.exit(1)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    return f"sqlite:///{os.path.join(os.path.dirname(__file__), 'vst_ims.db')}"


def main():
    cloud_mode = "--cloud" in sys.argv
    print("\n" + "=" * 60)
    print("  VST IMS — Cloud Data Restoration")
    print("=" * 60)

    db_url = load_db_url(cloud_mode=cloud_mode)
    print(f"  DB: {db_url[:60]}...")

    from sqlalchemy import create_engine, text

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("  Connected!")

    profiles = _load_demand_profiles()
    print(f"  Loaded {len(profiles)} SKU demand profiles from CSV")

    with engine.connect() as conn:
        max_date_row = conn.execute(text("SELECT MAX(sale_date) FROM sales")).fetchone()
        max_date = max_date_row[0] if max_date_row and max_date_row[0] else None
        if isinstance(max_date, str):
            max_date = date.fromisoformat(max_date[:10])
        elif isinstance(max_date, datetime):
            max_date = max_date.date()

        pid_by_sku = {r[0]: r[1] for r in conn.execute(text("SELECT sku_id, id FROM products")).fetchall()}

        sku_count = conn.execute(text("SELECT COUNT(DISTINCT sku_id) FROM sales")).scalar() or 0
        total_sales = conn.execute(text("SELECT COUNT(*) FROM sales")).scalar() or 0

    print(f"  Current sales: {total_sales} rows, {sku_count} SKUs")
    print(f"  Last sales date: {max_date}")

    today = date.today()
    if max_date and max_date >= today:
        print("  Sales data is already up to date. Nothing to do.")
        return

    start_date = (max_date + timedelta(days=1)) if max_date else date(2026, 1, 1)
    start_monday = _week_monday(start_date)
    end_monday = _week_monday(today)

    print(f"\n  Generating sales data: {start_monday} -> {end_monday}")
    print(f"  That's {((end_monday - start_monday).days // 7) + 1} weeks")

    now = datetime.now()
    inserted = 0
    batch = []

    with engine.connect() as conn:
        week = start_monday
        while week <= end_monday:
            for sku, prof in profiles.items():
                pid = pid_by_sku.get(sku)
                if not pid:
                    continue
                qty = max(0, int(round(random.gauss(prof["mean"] * _seasonal_factor(week), prof["std"]))))
                if qty > 0:
                    region = random.choice(["South India", "North India", "West India", "East India", "Export"])
                    batch.append({
                        "id": str(uuid.uuid4()),
                        "sale_date": week,
                        "product_id": pid,
                        "sku_id": sku,
                        "units_sold": qty,
                        "fulfillment_region": region,
                        "stockout_flag": random.random() < 0.02,
                        "created_at": now,
                    })
            if len(batch) >= 500:
                _insert_sales_batch(conn, batch)
                inserted += len(batch)
                batch = []
                conn.commit()
                print(f"    ... inserted {inserted} rows ({week})")
            week += timedelta(days=7)

        if batch:
            _insert_sales_batch(conn, batch)
            inserted += len(batch)

        conn.commit()

    print(f"\n  Inserted {inserted} new sales rows")

    _generate_forecasts(engine, profiles, start_monday, end_monday)
    _generate_external_factors(engine, start_monday, end_monday)

    with engine.connect() as conn:
        final_count = conn.execute(text("SELECT COUNT(*) FROM sales")).scalar() or 0
        final_max = conn.execute(text("SELECT MAX(sale_date) FROM sales")).scalar()

    print(f"\n  Final sales: {final_count} rows, latest date: {final_max}")
    print("\n" + "=" * 60)
    print("  Data restoration complete!")
    print("=" * 60)


def _insert_sales_batch(conn, batch):
    from sqlalchemy import text
    if not batch:
        return
    CHUNK = 100
    for i in range(0, len(batch), CHUNK):
        chunk = batch[i:i+CHUNK]
        values_parts = []
        params = {}
        for j, row in enumerate(chunk):
            prefix = f"r{j}"
            values_parts.append(
                f"(:{prefix}_id, :{prefix}_sd, :{prefix}_pid, :{prefix}_sku, :{prefix}_qty, "
                f":{prefix}_reg, :{prefix}_so)"
            )
            params[f"{prefix}_id"] = row["id"]
            params[f"{prefix}_sd"] = row["sale_date"]
            params[f"{prefix}_pid"] = row["product_id"]
            params[f"{prefix}_sku"] = row["sku_id"]
            params[f"{prefix}_qty"] = row["units_sold"]
            params[f"{prefix}_reg"] = row["fulfillment_region"]
            params[f"{prefix}_so"] = row["stockout_flag"]
        sql = f"""
            INSERT INTO sales (id, sale_date, product_id, sku_id, units_sold,
                               fulfillment_region, stockout_flag)
            VALUES {', '.join(values_parts)}
        """
        conn.execute(text(sql), params)


def _generate_forecasts(engine, sales_profiles, start_monday, end_monday):
    """Generate forecast rows to match the extended sales data."""
    from sqlalchemy import text
    print("\n  Generating forecast data...")
    forecast_profiles = _load_forecast_profiles()
    if not forecast_profiles:
        print("  No forecast profiles found in CSV, skipping")
        return

    now = datetime.now()
    inserted = 0
    batch = []

    with engine.connect() as conn:
        pid_by_sku = {r[0]: r[1] for r in conn.execute(text("SELECT sku_id, id FROM products")).fetchall()}
        cat_by_sku = {}
        for r in conn.execute(text("SELECT sku_id, category FROM products")).fetchall():
            cat_by_sku[r[0]] = r[1]

        week = start_monday
        while week <= end_monday:
            for sku in forecast_profiles:
                pid = pid_by_sku.get(sku)
                if not pid:
                    continue
                base = sales_profiles.get(sku, {}).get("mean", 20)
                predicted = max(0, round(base * _seasonal_factor(week) * random.uniform(0.85, 1.15), 1))
                actual = max(0, round(predicted * random.uniform(0.7, 1.3), 1))
                if predicted > 0:
                    batch.append({
                        "id": str(uuid.uuid4()),
                        "product_id": pid,
                        "sku_id": sku,
                        "forecast_date": week,
                        "predicted_demand": predicted,
                        "actual_demand": actual,
                        "model_version": "ensemble_v1",
                        "created_at": now,
                    })
            if len(batch) >= 500:
                for row in batch:
                    conn.execute(text("""
                        INSERT INTO forecasts (id, product_id, sku_id, forecast_date,
                                               predicted_demand, actual_demand, model_version)
                        VALUES (:id, :product_id, :sku_id, :forecast_date,
                                :predicted_demand, :actual_demand, :model_version)
                    """), {k: v for k, v in row.items() if k != "created_at"})
                inserted += len(batch)
                batch = []
                conn.commit()
            week += timedelta(days=7)

        if batch:
            for row in batch:
                conn.execute(text("""
                    INSERT INTO forecasts (id, product_id, sku_id, forecast_date,
                                           predicted_demand, actual_demand, model_version)
                    VALUES (:id, :product_id, :sku_id, :forecast_date,
                            :predicted_demand, :actual_demand, :model_version)
                """), {k: v for k, v in row.items() if k != "created_at"})
            inserted += len(batch)
        conn.commit()

    print(f"  Inserted {inserted} forecast rows")


def _generate_external_factors(engine, start_monday, end_monday):
    """Generate external factors for the extended date range."""
    from sqlalchemy import text
    print("\n  Generating external factors...")
    existing_factors = _load_external_factors()

    if existing_factors:
        last = existing_factors[-1]
        last_date = date.fromisoformat(last["date"])
    else:
        last_date = date(2025, 12, 29)

    now = datetime.now()
    inserted = 0
    week = start_monday

    with engine.connect() as conn:
        while week <= end_monday:
            month = week.month
            if month in (6, 7, 8, 9):
                monsoon = random.uniform(0.6, 1.0)
                crop = "Kharif"
            elif month in (10, 11, 12):
                monsoon = random.uniform(0.1, 0.4)
                crop = "Rabi"
            elif month in (1, 2, 3):
                monsoon = random.uniform(0.0, 0.15)
                crop = "Rabi"
            else:
                monsoon = random.uniform(0.05, 0.25)
                crop = "Zaid"

            macro = 1.0 + (week - date(2026, 1, 1)).days * 0.0003

            conn.execute(text("""
                INSERT INTO external_factors (id, factor_date, monsoon_index,
                                              crop_sowing_season, macro_economic_index)
                VALUES (:id, :date, :monsoon, :crop, :macro)
                ON CONFLICT (factor_date) DO NOTHING
            """), {
                "id": str(uuid.uuid4()),
                "date": week,
                "monsoon": round(monsoon, 4),
                "crop": crop,
                "macro": round(macro, 4),
            })
            inserted += 1
            week += timedelta(days=7)
        conn.commit()

    print(f"  Inserted {inserted} external factor rows")


if __name__ == "__main__":
    main()
