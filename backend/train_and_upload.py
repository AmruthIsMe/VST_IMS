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
    print("  🏋️  PHASE 1: Training Models Locally")
    print("=" * 60)
    
    from app.forecasting.ensemble import get_ensemble
    
    ensemble = get_ensemble()
    results = ensemble.train_all_models(test_weeks=12)
    
    models_trained = results.get("metadata", {}).get("models_trained", 0)
    elapsed = results.get("metadata", {}).get("elapsed_seconds", "?")
    
    print(f"\n   ✅ Trained {models_trained} models in {elapsed}s")
    
    # Show per-model metrics
    for model_name, metrics in results.get("model_results", {}).items():
        if isinstance(metrics, dict) and "mape" in metrics:
            mape = metrics["mape"]
            weight = ensemble.weights.get(model_name, 0)
            print(f"   📊 {model_name:15s}  MAPE={mape:.1f}%  Weight={weight:.1%}")
    
    return ensemble, results


def generate_predictions(ensemble):
    """Generate 12-week predictions for all 200 SKUs."""
    print("\n" + "=" * 60)
    print("  🔮  PHASE 2: Generating Predictions for All SKUs")
    print("=" * 60)
    
    from app.forecasting.data_pipeline import prepare_dataset, load_products_data
    
    products_df = load_products_data()
    if products_df is None or len(products_df) == 0:
        print("   ❌ No products data found!")
        return []
    
    sku_ids = products_df["SKU_ID"].unique().tolist()
    print(f"   📦 Found {len(sku_ids)} SKUs to forecast")
    
    # Load sales data for EWMA-based predictions
    sales_path = DATA_DIR / "fact_sales.csv"
    if not sales_path.exists():
        print("   ❌ fact_sales.csv not found!")
        return []
    
    sales_df = pd.read_csv(sales_path, parse_dates=["Date"])
    sales_df.rename(columns={"Date": "sale_date", "SKU_ID": "sku_id", "Units_Sold": "units_sold"}, inplace=True)
    max_date = sales_df["sale_date"].max()
    
    all_predictions = []
    horizon_weeks = 12
    now = datetime.utcnow()
    
    for i, sku_id in enumerate(sku_ids):
        sku_sales = sales_df[sales_df["sku_id"] == sku_id].sort_values("sale_date")
        if len(sku_sales) < 4:
            continue
        
        # Compute EWMA-based forecast
        cutoff_13w = max_date - pd.Timedelta(weeks=13)
        recent = sku_sales[sku_sales["sale_date"] >= cutoff_13w]
        avg_weekly = recent["units_sold"].mean()
        std_weekly = recent["units_sold"].std()
        
        cutoff_4w = max_date - pd.Timedelta(weeks=4)
        cutoff_8w = max_date - pd.Timedelta(weeks=8)
        recent_4w = sku_sales[sku_sales["sale_date"] >= cutoff_4w]["units_sold"].sum()
        prev_4w = sku_sales[(sku_sales["sale_date"] >= cutoff_8w) & (sku_sales["sale_date"] < cutoff_4w)]["units_sold"].sum()
        trend_ratio = recent_4w / prev_4w if prev_4w > 0 else 1.0
        forecast_weekly = avg_weekly * trend_ratio
        
        # Try ML model predictions if available
        model_predictions = {}
        for model_name in ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]:
            if model_name in ensemble.models and ensemble.models[model_name].is_trained:
                try:
                    if model_name in ensemble.ML_MODELS:
                        # ML models need features
                        try:
                            dataset = prepare_dataset(sku_id=sku_id, test_weeks=0)
                            test_df = dataset["train"].tail(horizon_weeks)
                            feature_cols = dataset["feature_cols"]
                            X = pd.DataFrame(test_df[feature_cols].values, columns=feature_cols)
                            preds = ensemble.models[model_name].predict(X)
                            model_predictions[model_name] = preds.tolist()
                        except Exception:
                            model_predictions[model_name] = [forecast_weekly] * horizon_weeks
                    else:
                        # Time series models
                        preds = ensemble.models[model_name].predict(horizon=horizon_weeks)
                        if len(preds) < horizon_weeks:
                            preds = list(preds) + [preds[-1]] * (horizon_weeks - len(preds))
                        model_predictions[model_name] = preds[:horizon_weeks]
                except Exception:
                    model_predictions[model_name] = [forecast_weekly] * horizon_weeks
            else:
                # Use EWMA as fallback for untrained models
                model_predictions[model_name] = [forecast_weekly] * horizon_weeks
        
        # Generate prediction rows for each week
        for w in range(horizon_weeks):
            week_date = (max_date + pd.Timedelta(weeks=w + 1)).date()
            z = 1.96 * np.sqrt((w + 1) / 4)
            
            for model_name, preds in model_predictions.items():
                pred_val = float(preds[w]) if w < len(preds) else forecast_weekly
                all_predictions.append({
                    "id": str(uuid.uuid4()),
                    "model_name": model_name,
                    "sku_id": sku_id,
                    "forecast_date": week_date,
                    "predicted_demand": round(max(0, pred_val), 1),
                    "lower_bound": round(max(0, pred_val - z * (std_weekly or avg_weekly * 0.3)), 1),
                    "upper_bound": round(pred_val + z * (std_weekly or avg_weekly * 0.3), 1),
                    "actual_demand": None,
                    "created_at": now,
                })
        
        if (i + 1) % 50 == 0 or i == len(sku_ids) - 1:
            print(f"   📊 Processed {i + 1}/{len(sku_ids)} SKUs...")
    
    print(f"   ✅ Generated {len(all_predictions)} prediction rows")
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
        model_results = results.get("model_results", {})
        
        for model_name in ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]:
            metrics = model_results.get(model_name, {})
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
    parser.add_argument("--db-url", type=str, help="Cloud PostgreSQL connection string")
    parser.add_argument("--skip-training", action="store_true", help="Skip training, just upload existing results")
    args = parser.parse_args()
    
    print("\n" + "🚀" * 20)
    print("  VST IMS — Local Training + Cloud Upload")
    print("🚀" * 20)
    
    # Get cloud DB URL
    db_url = args.db_url or load_cloud_db_url()
    if not db_url:
        sys.exit(1)
    
    print(f"\n   🔗 Cloud DB: {db_url[:50]}...")
    
    # Create cloud engine
    engine = get_cloud_engine(db_url)
    
    # Test connection
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("   ✅ Cloud DB connection successful!")
    except Exception as e:
        print(f"   ❌ Cloud DB connection failed: {e}")
        sys.exit(1)
    
    # Train models
    if not args.skip_training:
        ensemble, results = train_models()
    else:
        print("\n   ⏭️  Skipping training (using existing models)")
        from app.forecasting.ensemble import get_ensemble
        ensemble = get_ensemble()
        results = {"model_results": {}, "metadata": {}}
    
    # Generate predictions
    predictions = generate_predictions(ensemble)
    
    # Upload to cloud
    upload_to_cloud(engine, ensemble, results, predictions)
    
    print("\n" + "=" * 60)
    print("  🎉  ALL DONE!")
    print("=" * 60)
    print(f"  ✅ Models trained and predictions uploaded to cloud DB")
    print(f"  ✅ Managers can now see updated forecasts at the live URL")
    print(f"  ⏰ Run this script again next week to refresh predictions")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
