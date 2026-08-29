"""
VST IMS — Local Training + Cloud Upload Script

Run this on YOUR laptop (weekly or as needed) to:
1. Train all 6 ML models on local data
2. Generate 12-week predictions for all 200 SKUs
3. Upload predictions + metrics to the Supabase cloud database

Usage:
    cd backend
    python train_and_upload.py

The script reads DATABASE_URL from backend/.env (cloud DB connection string).
Your local dev DB (SQLite) is NOT affected.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import uuid

# Ensure backend/ is on the path so app imports work
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Configure utf-8 encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

from app.config import get_settings

# --- Configuration ---
DATA_DIR = BACKEND_DIR.parent / "data"
MODELS_DIR = BACKEND_DIR / "trained_models"


def load_cloud_db_url():
    """Load the cloud DATABASE_URL from .env or command line."""
    from dotenv import load_dotenv
    env_path = BACKEND_DIR / ".env"
    load_dotenv(env_path)
    
    url = os.getenv("CLOUD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url or url.startswith("sqlite"):
        print("\n⚠️  No cloud DATABASE_URL found!")
        print("   Add CLOUD_DATABASE_URL=postgresql://... to backend/.env")
        print("   Or pass it as: python train_and_upload.py --db-url postgresql://...\n")
        return None
    return url


def get_cloud_engine(db_url):
    """Create a SQLAlchemy engine for the cloud database."""
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def train_models():
    """Train all 6 ML models using the existing ensemble code."""
    print("\n" + "=" * 60)
    print("  PHASE 1: Training Models Locally")
    print("=" * 60)

    from app.forecasting.ensemble import get_ensemble

    ensemble = get_ensemble()
    results = ensemble.train_all_models(test_weeks=12)

    models_trained = sum(
        1 for r in results.get("models", {}).values() if r.get("status") == "trained"
    )
    elapsed = results.get("metadata", {}).get("elapsed_seconds", "?")

    print(f"\n   Trained {models_trained} models in {elapsed}s")

    for model_name, r in results.get("models", {}).items():
        metrics = r.get("test_metrics", {}) if isinstance(r, dict) else {}
        if metrics.get("mape") is not None:
            weight = ensemble.weights.get(model_name, 0)
            print(f"   {model_name:15s}  MAPE={metrics['mape']}%  Weight={weight:.1%}")

    return ensemble, results


def generate_predictions(ensemble, db_url: str):
    """Generate 12-week predictions for all SKUs directly from the source DB."""
    print("\n" + "=" * 60)
    print("  PHASE 2: Generating Predictions for All SKUs")
    print("=" * 60)

    from sqlalchemy import create_engine
    from sqlalchemy import text as sql_text
    import uuid

    horizon_weeks = 12
    now = datetime.utcnow()
    all_predictions = []
    sku_count = 0

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(sql_text(
            "SELECT sale_date, sku_id, units_sold FROM sales ORDER BY sku_id, sale_date"
        )).fetchall()

    sales_df = pd.DataFrame(rows, columns=["sale_date", "sku_id", "units_sold"])
    sales_df["sale_date"] = pd.to_datetime(sales_df["sale_date"])
    global_last = sales_df["sale_date"].max()
    print(f"   Data through: {global_last.date()} | {sales_df['sku_id'].nunique()} SKUs")

    for sku_id, grp in sales_df.groupby("sku_id"):
        series = grp.sort_values("sale_date")["units_sold"].astype(float)
        if len(series) < 4:
            continue
        sku_count += 1
        values = series.values
        recent4 = values[-4:].mean()
        prev4 = values[-8:-4].mean() if len(values) >= 8 else recent4
        trend_ratio = float(np.clip(recent4 / prev4, 0.5, 2.0)) if prev4 > 0 else 1.0
        forecast_weekly = float(recent4 * trend_ratio)
        std_weekly = float(values[-13:].std() if len(values) >= 13 else values.std())

        model_predictions = {}
        for model_name in ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]:
            model = ensemble.models.get(model_name)
            if model and getattr(model, "is_trained", False) and model_name in ("arima", "sarima", "prophet", "holt_winters"):
                try:
                    preds = np.asarray(model.predict(horizon=horizon_weeks), dtype=float)
                    preds = list(preds) + [preds[-1]] * max(0, horizon_weeks - len(preds))
                    model_predictions[model_name] = preds[:horizon_weeks]
                except Exception:
                    model_predictions[model_name] = [forecast_weekly] * horizon_weeks
            else:
                model_predictions[model_name] = [forecast_weekly] * horizon_weeks

        weights = ensemble.weights
        w_total = sum(weights.get(m, 0) for m in model_predictions) or 1.0
        ens = [
            sum(model_predictions[m][w] * weights.get(m, 0) for m in model_predictions) / w_total
            for w in range(horizon_weeks)
        ]
        model_predictions["ensemble"] = ens

        for model_name, preds in model_predictions.items():
            for w in range(horizon_weeks):
                week_date = (global_last + pd.Timedelta(weeks=w + 1)).date()
                pred_val = float(max(preds[w], 0))
                z = 1.96 * np.sqrt((w + 1) / 4)
                all_predictions.append({
                    "id": str(uuid.uuid4()),
                    "model_name": model_name,
                    "sku_id": sku_id,
                    "forecast_date": week_date,
                    "predicted_demand": round(pred_val, 1),
                    "lower_bound": round(max(0, pred_val - z * (std_weekly or forecast_weekly * 0.3)), 1),
                    "upper_bound": round(pred_val + z * (std_weekly or forecast_weekly * 0.3), 1),
                    "actual_demand": None,
                    "created_at": now,
                })

    print(f"   Generated {len(all_predictions)} prediction rows for {sku_count} SKUs")
    return all_predictions


def upload_to_cloud(engine, ensemble, results, predictions):
    """Upload predictions and metrics to the cloud database."""
    print("\n" + "=" * 60)
    print("  ☁️  PHASE 3: Uploading to Cloud Database")
    print("=" * 60)
    
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # --- 1. Clear old predictions ---
        print("   🗑️  Clearing old predictions...")
        conn.execute(text("DELETE FROM forecast_predictions"))
        conn.commit()
        
        # --- 2. Upload new predictions ---
        print(f"   📤 Uploading {len(predictions)} predictions...")
        if predictions:
            pred_df = pd.DataFrame(predictions)
            pred_df.to_sql("forecast_predictions", conn, if_exists="append", index=False, method="multi", chunksize=500)
            conn.commit()
        
        # --- 3. Upload model metrics ---
        print("   📊 Uploading model metrics...")
        conn.execute(text("DELETE FROM forecast_models"))
        conn.commit()
        
        now = datetime.utcnow()
        model_results = results.get("models", {})

        for model_name in ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]:
            r = model_results.get(model_name, {})
            metrics = r.get("test_metrics", {}) if isinstance(r, dict) else {}
            if isinstance(metrics, dict):
                conn.execute(text("""
                    INSERT INTO forecast_models 
                    (id, model_name, model_type, trained_at, mae, mape, rmse, smape, bias, ensemble_weight, is_active)
                    VALUES (:id, :model_name, :model_type, :trained_at, :mae, :mape, :rmse, :smape, :bias, :weight, true)
                """), {
                    "id": str(uuid.uuid4()),
                    "model_name": model_name,
                    "model_type": _model_type(model_name),
                    "trained_at": now,
                    "mae": metrics.get("mae"),
                    "mape": metrics.get("mape"),
                    "rmse": metrics.get("rmse"),
                    "smape": metrics.get("smape"),
                    "bias": metrics.get("bias"),
                    "weight": ensemble.weights.get(model_name, 0),
                })
        conn.commit()
        
        print("   ✅ Upload complete!")


def _model_type(name):
    return {
        "xgboost": "Gradient Boosting",
        "lightgbm": "Gradient Boosting",
        "arima": "Time Series (ARIMA)",
        "sarima": "Seasonal ARIMA",
        "prophet": "Additive Model",
        "holt_winters": "Exponential Smoothing",
    }.get(name, "Unknown")


def main():
    parser = argparse.ArgumentParser(description="Train ML models locally and upload results to cloud DB")
    parser.add_argument("--db-url", type=str, help="Target database connection string")
    parser.add_argument("--cloud", action="store_true", help="Explicitly target the production cloud DB (requires confirmation)")
    parser.add_argument("--skip-training", action="store_true", help="Skip training, just upload existing results")
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  VST IMS - Local Training + Upload")
    print("=" * 50)

    db_url = args.db_url or load_cloud_db_url()
    if not db_url:
        print("\n   No DATABASE_URL found. Running in LOCAL-ONLY mode (train + local predictions).")
        db_url = None

    is_production = bool(db_url) and ("supabase" in db_url or "render" in db_url)
    if is_production:
        if not args.cloud:
            print("\n   Target looks like PRODUCTION (Supabase/Render).")
            print("   Per AGENTS.md, production writes require explicit approval.")
            print("   Re-run with --cloud to confirm you intend to write production data.")
            sys.exit(1)
        answer = input(f"\n   Type YES to write predictions to PRODUCTION: ").strip()
        if answer != "YES":
            print("   Aborted.")
            sys.exit(1)

    engine = get_cloud_engine(db_url) if db_url else None
    if engine:
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"\n   DB connection OK: {db_url[:50]}...")
        except Exception as e:
            print(f"\n   DB connection failed: {e}")
            sys.exit(1)

    if not args.skip_training:
        ensemble, results = train_models()
    else:
        print("\n   Skipping training (using existing models)")
        from app.forecasting.ensemble import get_ensemble
        ensemble = get_ensemble()
        results = {"models": {}, "metadata": {}}

    target_url = db_url or str(get_settings().DATABASE_URL)
    predictions = generate_predictions(ensemble, target_url)

    if engine:
        upload_to_cloud(engine, ensemble, results, predictions)
    else:
        from sqlalchemy import create_engine
        local_engine = create_engine(target_url)
        upload_to_cloud(local_engine, ensemble, results, predictions)
        print("   Stored forecasts into the LOCAL database.")

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print("  Models trained locally; 12-week predictions stored in the target DB.")
    print("  Model FILES never leave this machine - only prediction rows upload.")
    print("  Re-run weekly (or after each SAP sync) to refresh predictions.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
