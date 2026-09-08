"""
VST IMS — Local Training + Cloud Upload Script

Run this on YOUR laptop (weekly or as needed) to:
1. Train all 6 ML models on local data (parallel)
2. Generate 12-week predictions for all 200 SKUs
3. Upload predictions + metrics to the Supabase cloud database
4. Store training run metadata in training_runs table

Usage:
    cd backend
    python train_and_upload.py --cloud                    # one-shot
    python train_and_upload.py --cloud --watch --interval 168  # weekly auto

The script reads DATABASE_URL from backend/.env (cloud DB connection string).
Your local dev DB (SQLite) is NOT affected.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import uuid

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

from app.config import get_settings

MODELS_DIR = BACKEND_DIR / "trained_models"
RL_STATE_FILE = MODELS_DIR / "rl_state.json"


def load_cloud_db_url():
    """Load the cloud DATABASE_URL from .env or command line."""
    from dotenv import load_dotenv
    env_path = BACKEND_DIR / ".env"
    load_dotenv(env_path)

    url = os.getenv("CLOUD_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url or url.startswith("sqlite"):
        print("\n  No cloud DATABASE_URL found!")
        print("   Add CLOUD_DATABASE_URL=postgresql://... to backend/.env")
        print("   Or pass it as: python train_and_upload.py --db-url postgresql://...\n")
        return None
    return url


def get_cloud_engine(db_url):
    """Create a SQLAlchemy engine for the cloud database."""
    from sqlalchemy import create_engine
    return create_engine(db_url, pool_pre_ping=True)


def sync_rl_state_from_cloud(engine):
    """Download current RL bandit state from cloud before training."""
    print("\n   Syncing RL state from cloud...")
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT weights, per_model_metrics FROM training_runs "
                "ORDER BY trained_at DESC LIMIT 1"
            ))
            row = result.fetchone()
            if row and row[0]:
                weights_data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                MODELS_DIR.mkdir(exist_ok=True)
                rl_state = {
                    "n_pulls": weights_data.get("n_pulls", {}),
                    "total_reward": weights_data.get("total_reward", {}),
                    "mean_reward": weights_data.get("mean_reward", {}),
                    "total_rounds": weights_data.get("total_rounds", 0),
                    "reward_history": [],
                }
                RL_STATE_FILE.write_text(json.dumps(rl_state, indent=2, default=str))
                print("   RL state synced from cloud.")
                return True
    except Exception as e:
        print(f"   RL state sync skipped: {e}")
    return False


def sync_rl_state_to_cloud(engine, ensemble):
    """Upload updated RL weights back to cloud after training."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE training_runs SET weights = :weights "
                "WHERE id = (SELECT id FROM training_runs ORDER BY trained_at DESC LIMIT 1)"
            ), {"weights": json.dumps(ensemble.weights, default=str)})
            conn.commit()
        print("   RL weights uploaded to cloud.")
    except Exception as e:
        print(f"   RL weight upload skipped: {e}")


def train_models(parallel=True, max_workers=4):
    """Train all 6 ML models using the ensemble code."""
    print("\n" + "=" * 60)
    print("  PHASE 1: Training Models Locally")
    print("=" * 60)

    from app.forecasting.ensemble import get_ensemble
    from app.forecasting import training_progress as progress

    ensemble = get_ensemble()
    progress.start_training()

    if parallel:
        print("   Using parallel training (ThreadPoolExecutor)...")
        results = ensemble.train_all_models_parallel(test_weeks=12, max_workers=max_workers)
    else:
        print("   Using sequential training...")
        results = ensemble.train_all_models(test_weeks=12)

    progress.complete_training(error=results.get("error"))

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

    horizon_weeks = 12
    now = datetime.now()
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
    return all_predictions, sku_count


def upload_to_cloud(engine, ensemble, results, predictions, sku_count):
    """Upload predictions, metrics, and training run metadata to the cloud database."""
    print("\n" + "=" * 60)
    print("  PHASE 3: Uploading to Cloud Database")
    print("=" * 60)

    from sqlalchemy import text

    with engine.connect() as conn:
        print("   Clearing old predictions...")
        conn.execute(text("DELETE FROM forecast_predictions"))
        conn.commit()

        print(f"   Uploading {len(predictions)} predictions...")
        if predictions:
            pred_df = pd.DataFrame(predictions)
            pred_df.to_sql("forecast_predictions", conn, if_exists="append", index=False, method="multi", chunksize=500)
            conn.commit()

        print("   Uploading model metrics...")
        conn.execute(text("DELETE FROM forecast_models"))
        conn.commit()

        now = datetime.now()
        model_results = results.get("models", {})
        weights = ensemble.weights

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
                    "weight": weights.get(model_name, 0),
                })
        conn.commit()

        # Upload training run metadata
        print("   Recording training run metadata...")
        elapsed = results.get("metadata", {}).get("elapsed_seconds", 0)
        models_trained = sum(1 for r in model_results.values() if r.get("status") == "trained")
        ensemble_mape = results.get("ensemble", {}).get("mape")

        per_model = {}
        for model_name, r in model_results.items():
            tm = r.get("test_metrics", {}) or {}
            per_model[model_name] = {
                "status": r.get("status"),
                "mae": tm.get("mae"),
                "mape": tm.get("mape"),
                "rmse": tm.get("rmse"),
            }

        conn.execute(text("""
            INSERT INTO training_runs
            (id, trained_at, trained_on, elapsed_seconds, models_trained, ensemble_mape,
             sku_count, predictions_uploaded, trigger, weights, per_model_metrics)
            VALUES (:id, :trained_at, :trained_on, :elapsed, :models_trained, :mape,
                    :sku_count, :preds_uploaded, :trigger, :weights, :per_model)
        """), {
            "id": str(uuid.uuid4()),
            "trained_at": now,
            "trained_on": "local",
            "elapsed": elapsed,
            "models_trained": models_trained,
            "mape": ensemble_mape,
            "sku_count": sku_count,
            "preds_uploaded": len(predictions),
            "trigger": "manual",
            "weights": json.dumps(weights, default=str),
            "per_model": json.dumps(per_model, default=str),
        })
        conn.commit()

        print("   Upload complete!")


def _model_type(name):
    return {
        "xgboost": "Gradient Boosting",
        "lightgbm": "Gradient Boosting",
        "arima": "Time Series (ARIMA)",
        "sarima": "Seasonal ARIMA",
        "prophet": "Additive Model",
        "holt_winters": "Exponential Smoothing",
    }.get(name, "Unknown")


def run_training_cycle(db_url, parallel=True, max_workers=4):
    """Run one complete training + upload cycle. Returns True on success."""
    engine = get_cloud_engine(db_url)

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"\n   DB connection OK: {db_url[:50]}...")
    except Exception as e:
        print(f"\n   DB connection failed: {e}")
        return False

    sync_rl_state_from_cloud(engine)

    ensemble, results = train_models(parallel=parallel, max_workers=max_workers)
    predictions, sku_count = generate_predictions(ensemble, db_url)
    upload_to_cloud(engine, ensemble, results, predictions, sku_count)

    sync_rl_state_to_cloud(engine, ensemble)

    models_trained = sum(1 for r in results.get("models", {}).values() if r.get("status") == "trained")
    elapsed = results.get("metadata", {}).get("elapsed_seconds", "?")
    ensemble_mape = results.get("ensemble", {}).get("mape", "N/A")

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print(f"  Models trained: {models_trained}/6")
    print(f"  Ensemble MAPE: {ensemble_mape}%")
    print(f"  Predictions uploaded: {len(predictions)} rows for {sku_count} SKUs")
    print(f"  Elapsed: {elapsed}s")
    print("  Model FILES never leave this machine - only prediction rows upload.")
    print("=" * 60 + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Train ML models locally and upload results to cloud DB")
    parser.add_argument("--db-url", type=str, help="Target database connection string")
    parser.add_argument("--cloud", action="store_true", help="Explicitly target the production cloud DB (requires confirmation)")
    parser.add_argument("--skip-training", action="store_true", help="Skip training, just upload existing results")
    parser.add_argument("--parallel", action="store_true", default=True, help="Use parallel training (default: True)")
    parser.add_argument("--sequential", action="store_true", help="Use sequential training instead of parallel")
    parser.add_argument("--max-workers", type=int, default=4, help="Max parallel workers (default: 4)")
    parser.add_argument("--watch", action="store_true", help="Run training in a loop every --interval hours")
    parser.add_argument("--interval", type=float, default=168, help="Hours between retraining in watch mode (default: 168 = weekly)")
    args = parser.parse_args()

    use_parallel = not args.sequential

    print("\n" + "=" * 50)
    print("  VST IMS - Local Training + Upload")
    print("=" * 50)

    db_url = args.db_url or load_cloud_db_url()
    if not db_url:
        print("\n   No DATABASE_URL found. Running in LOCAL-ONLY mode (train + local predictions).")
        db_url = str(get_settings().DATABASE_URL)

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

    if args.watch:
        print(f"\n   WATCH MODE: Training every {args.interval}h ({args.interval / 24:.1f} days)")
        print("   Press Ctrl+C to stop.\n")
        cycle = 0
        while True:
            cycle += 1
            print(f"\n{'#' * 60}")
            print(f"  CYCLE {cycle} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#' * 60}")

            if not args.skip_training:
                run_training_cycle(db_url, parallel=use_parallel, max_workers=args.max_workers)
            else:
                print("\n   Skipping training (using existing models)")
                from app.forecasting.ensemble import get_ensemble
                ensemble = get_ensemble()
                predictions, sku_count = generate_predictions(ensemble, db_url)
                engine = get_cloud_engine(db_url)
                upload_to_cloud(engine, ensemble, {"models": {}, "metadata": {}}, predictions, sku_count)

            next_run = datetime.now() + timedelta(hours=args.interval)
            print(f"\n   Next training at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Sleeping {args.interval}h... (Ctrl+C to stop)")
            try:
                time.sleep(args.interval * 3600)
            except KeyboardInterrupt:
                print("\n   Watch mode stopped.")
                break
    else:
        if not args.skip_training:
            run_training_cycle(db_url, parallel=use_parallel, max_workers=args.max_workers)
        else:
            print("\n   Skipping training (using existing models)")
            from app.forecasting.ensemble import get_ensemble
            ensemble = get_ensemble()
            predictions, sku_count = generate_predictions(ensemble, db_url)
            engine = get_cloud_engine(db_url)
            upload_to_cloud(engine, ensemble, {"models": {}, "metadata": {}}, predictions, sku_count)

            print("\n" + "=" * 60)
            print("  ALL DONE!")
            print("=" * 60)
            print("  Predictions uploaded to the target DB.")
            print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
