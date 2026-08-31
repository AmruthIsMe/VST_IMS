"""
Forecast API Router for VST IMS.
Endpoints for training, predicting, comparing, and managing forecasting models.

Supports two modes:
- LOCAL:  Full ML — trains models, runs inference, loads .joblib files
- CLOUD:  Pre-computed — serves predictions from DB, no ML libs needed
"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, timedelta, datetime
import pandas as pd
import numpy as np
import io
import logging

from pathlib import Path

from app.database import get_db
from app.config import get_settings
from app.forecasting.data_pipeline import load_products_data, SKU_CATEGORY_PREFIX
from app.forecasting.constants import get_stockout_severity, get_risk_level
from app.models import Inventory, Product
from app.routers.auth import get_current_user

# --- Conditional ML imports (not available in cloud deployment) ---
try:
    from app.forecasting.ensemble import get_ensemble
    from app.forecasting.rl_feedback import get_feedback_loop
    from app.forecasting.data_pipeline import prepare_dataset
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/forecast", tags=["forecast"])
DEPLOYMENT_MODE = get_settings().DEPLOYMENT_MODE
DATA_DIR = Path(get_settings().DATA_DIR)


@router.get("/training-status")
async def get_training_status():
    """Real-time per-model training progress. Poll every 2s during retrain."""
    from app.forecasting import training_progress
    return training_progress.get_status()


@router.post("/train")
async def train_models(
    background_tasks: BackgroundTasks,
    sku_id: Optional[str] = Query(None, description="Train for specific SKU"),
    category: Optional[str] = Query(None, description="Train for specific category"),
    test_weeks: int = Query(12, description="Number of weeks for test split"),
    current_user: dict = Depends(get_current_user),
):
    """Train all forecasting models and compute ensemble weights."""
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return {
            "status": "cloud_mode",
            "message": "Training is disabled on the cloud server. Run 'python train_and_upload.py' on your local machine to train models and upload predictions.",
        }
    ensemble = get_ensemble()
    try:
        results = ensemble.train_all_models(
            sku_id=sku_id,
            category=category,
            test_weeks=test_weeks,
        )
        # Check if training actually failed
        if "error" in results and results.get("metadata", {}).get("models_trained", 0) == 0:
            return {
                "status": "error",
                "message": results["error"],
                "results": results,
            }
        return {
            "status": "success",
            "message": f"Trained {results.get('metadata', {}).get('sku_count', 0)} SKU(s)",
            "results": results,
        }
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/predict")
async def get_predictions(
    sku_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    horizon_weeks: int = Query(12, ge=1, le=52),
    model: Optional[str] = Query(None, description="Specific model name or 'ensemble'"),
    db: Session = Depends(get_db),
):
    """Get demand predictions from ensemble or specific model."""
    try:
        if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
            return _predict_from_db(db, sku_id=sku_id, category=category, horizon_weeks=horizon_weeks)

        ensemble = get_ensemble()

        if not ensemble.is_trained:
            return {"status": "not_trained", "message": "Models not trained yet. Call POST /api/forecast/train first."}

        dataset = prepare_dataset(sku_id=sku_id, category=category, test_weeks=0)
        test_df = dataset["test"] if len(dataset["test"]) > 0 else dataset["train"].tail(horizon_weeks)
        feature_cols = dataset["feature_cols"]

        import pandas as pd
        X = pd.DataFrame(test_df[feature_cols].values[-horizon_weeks:], columns=feature_cols)

        result = ensemble.predict(
            X=X,
            horizon=horizon_weeks,
            model_name=model if model != "ensemble" else None,
        )

        dates = test_df["Date"].values[-horizon_weeks:]
        result["dates"] = [str(d)[:10] for d in dates] if len(dates) > 0 else []

        if "target" in test_df.columns:
            actuals = test_df["target"].values[-horizon_weeks:]
            result["actuals"] = actuals.tolist()

        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Prediction failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Prediction failed: {str(e)}"}


@router.get("/compare")
async def compare_models(
    sku_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Compare all model predictions side-by-side on test data."""
    try:
        if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
            return _compare_from_db(db, sku_id=sku_id)

        ensemble = get_ensemble()

        if not ensemble.is_trained:
            return {"status": "not_trained", "message": "Models not trained yet."}

        dataset = prepare_dataset(sku_id=sku_id, category=category)
        test_df = dataset["test"]
        feature_cols = dataset["feature_cols"]

        import pandas as pd
        import numpy as np

        X_test = pd.DataFrame(test_df[feature_cols].values, columns=feature_cols)
        y_test = test_df["target"].values
        dates = [str(d)[:10] for d in test_df["Date"].values]

        all_preds = {}
        for model_name, model in ensemble.models.items():
            try:
                if model_name in ensemble.ML_MODELS:
                    preds = model.predict(X_test)
                    all_preds[model_name] = preds
                else:
                    preds = model.predict(horizon=len(y_test))
                    if len(preds) >= len(y_test):
                        all_preds[model_name] = preds[:len(y_test)]
                    else:
                        padded = np.full(len(y_test), preds[-1] if len(preds) > 0 else 0)
                        padded[:len(preds)] = preds
                        all_preds[model_name] = padded
            except Exception as e:
                logger.warning(f"Comparison prediction failed for {model_name}: {e}")

        comparison = ensemble.get_comparison(y_test, all_preds)

        chart_data = {
            "dates": dates,
            "actual": y_test.tolist(),
            "predictions": {name: preds.tolist() for name, preds in all_preds.items()},
        }

        return {
            "status": "success",
            "comparison": comparison,
            "chart_data": chart_data,
            "weights": ensemble.weights,
        }
    except Exception as e:
        logger.error(f"Comparison failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Comparison failed: {str(e)}"}


@router.get("/metrics")
async def get_metrics(
    sku_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    group_by: Optional[str] = Query(None, description="Group metrics by: category, sku"),
    db: Session = Depends(get_db),
):
    """Get detailed error metrics for all models."""
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return _metrics_from_db(db)

    ensemble = get_ensemble()

    if not ensemble.is_trained:
        return {"status": "not_trained", "message": "Models not trained yet."}

    try:
        dataset = prepare_dataset(sku_id=sku_id, category=category)
        test_df = dataset["test"]
        feature_cols = dataset["feature_cols"]

        import pandas as pd
        from app.forecasting.metrics import compute_all_metrics, compute_metrics_by_group

        X_test = pd.DataFrame(test_df[feature_cols].values, columns=feature_cols)
        y_test = test_df["target"].values

        model_metrics = {}
        for model_name, model in ensemble.models.items():
            try:
                if model_name in ensemble.ML_MODELS:
                    preds = model.predict(X_test)
                    metrics = compute_all_metrics(y_test, preds)
                    model_metrics[model_name] = metrics

                    # Feature importance for tree models
                    if hasattr(model, "get_feature_importance"):
                        model_metrics[model_name]["feature_importance"] = model.get_feature_importance()

                    # Grouped metrics
                    if group_by and group_by in test_df.columns:
                        test_df_copy = test_df.copy()
                        test_df_copy["predicted"] = preds
                        model_metrics[model_name]["by_group"] = compute_metrics_by_group(
                            test_df_copy, "target", "predicted", group_by
                        )
            except Exception as e:
                model_metrics[model_name] = {"error": str(e)}

        return {
            "status": "success",
            "metrics": model_metrics,
            "weights": ensemble.weights,
            "test_size": len(y_test),
        }
    except Exception as e:
        logger.error(f"Metrics failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/ensemble-weights")
async def get_ensemble_weights(db: Session = Depends(get_db)):
    """Get current ensemble weights and their evolution history."""
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return _weights_from_db(db)

    ensemble = get_ensemble()
    feedback = get_feedback_loop()

    return {
        "current_weights": ensemble.weights,
        "weight_history": ensemble.get_weight_history(),
        "rl_diagnostics": feedback.optimizer.get_diagnostics(),
        "retrain_suggestions": feedback.get_retrain_suggestions(),
    }


@router.post("/retrain")
async def retrain_models(
    sku_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Trigger re-training with RL feedback loop.
    Updates model weights based on accumulated error signals.
    """
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return {
            "status": "cloud_mode",
            "message": "Retraining is disabled on the cloud server. Run 'python train_and_upload.py' on your local machine.",
        }
    ensemble = get_ensemble()
    feedback = get_feedback_loop()

    # Get RL-updated weights before retraining
    rl_weights = feedback.get_updated_weights()
    retrain_list = feedback.get_retrain_suggestions()

    # Retrain all models
    results = ensemble.train_all_models(
        sku_id=sku_id,
        category=category,
    )

    # Apply RL weight adjustments
    if rl_weights:
        # Blend ensemble weights with RL weights (70% ensemble, 30% RL)
        for model_name in ensemble.weights:
            if model_name in rl_weights:
                ensemble.weights[model_name] = round(
                    0.7 * ensemble.weights[model_name] + 0.3 * rl_weights[model_name], 4
                )

    # Normalize
    total = sum(ensemble.weights.values())
    if total > 0:
        ensemble.weights = {m: round(w / total, 4) for m, w in ensemble.weights.items()}

    ensemble._save_history()

    return {
        "status": "success",
        "message": "Models retrained with RL feedback",
        "results": results,
        "rl_weights_applied": rl_weights,
        "models_retrained": retrain_list,
    }


@router.get("/models")
async def list_models(db: Session = Depends(get_db)):
    """List all available forecasting models with their status."""
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return _models_from_db(db)

    ensemble = get_ensemble()

    models_info = []
    all_model_names = ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]

    for name in all_model_names:
        info = {
            "name": name,
            "type": _get_model_type(name),
            "is_trained": name in ensemble.models and ensemble.models[name].is_trained,
            "weight": ensemble.weights.get(name, 0),
            "description": _get_model_description(name),
        }
        if name in ensemble.models:
            model = ensemble.models[name]
            info["train_date"] = model.train_date
            info["params"] = model.get_params()
        models_info.append(info)

    return {"models": models_info}


@router.get("/training-history")
async def get_training_history(
    limit: int = Query(30, ge=1, le=100, description="Max runs to return (newest first)"),
):
    """
    Performance drill-down: every training run with per-model metrics and
    deltas vs the previous run, so you can see how each of the 6 models
    changes/learns as new data arrives.
    """
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return {
            "status": "cloud_mode",
            "message": "Training history is available in local mode only.",
        }

    history = get_ensemble().get_training_history()
    if not history:
        return {"status": "success", "runs": [], "total_runs": 0}

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    enriched = []
    for i, run in enumerate(history):
        prev = history[i - 1] if i > 0 else None

        cur_mape = _num(run.get("ensemble_mape"))
        prev_mape = _num(prev.get("ensemble_mape")) if prev else None

        per_model = {}
        for name, cur in (run.get("per_model") or {}).items():
            prev_pm = (prev or {}).get("per_model", {}).get(name, {}) if prev else {}
            cur_w = (run.get("weights") or {}).get(name)
            prev_w = ((prev or {}).get("weights") or {}).get(name)
            entry = {
                "status": cur.get("status"),
                "mape": _num(cur.get("mape")),
                "mae": _num(cur.get("mae")),
                "rmse": _num(cur.get("rmse")),
                "smape": _num(cur.get("smape")),
                "bias": _num(cur.get("bias")),
                "weight": _num(cur_w),
                "mape_delta": None,
                "weight_delta": None,
                "improved": None,
            }
            pm_prev = _num(prev_pm.get("mape"))
            if entry["mape"] is not None and pm_prev is not None:
                entry["mape_delta"] = round(pm_prev - entry["mape"], 2)  # + = error reduced
                entry["improved"] = entry["mape_delta"] > 0
            w_prev = _num(prev_w)
            if entry["weight"] is not None and w_prev is not None:
                entry["weight_delta"] = round(entry["weight"] - w_prev, 4)
            per_model[name] = entry
        # Fallback for legacy runs without per_model snapshots
        if not per_model:
            for name, w in (run.get("weights") or {}).items():
                per_model[name] = {"status": "trained", "weight": _num(w)}

        ensemble_delta = None
        if cur_mape is not None and prev_mape is not None:
            ensemble_delta = round(prev_mape - cur_mape, 2)

        enriched.append({
            "index": i,
            "date": run.get("date"),
            "models_trained": run.get("models_trained", 0),
            "elapsed_seconds": run.get("elapsed_seconds"),
            "ensemble_mape": cur_mape,
            "ensemble_mape_delta": ensemble_delta,
            "error": run.get("error"),
            "dataset": run.get("dataset"),
            "weights": run.get("weights") or {},
            "per_model": per_model,
        })

    return {
        "status": "success",
        "runs": enriched[-limit:][::-1],  # newest first
        "total_runs": len(enriched),
    }


@router.get("/summary")
async def get_forecast_summary(db: Session = Depends(get_db)):
    """AI-generated summary of forecasting performance."""
    try:
        if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
            return _summary_from_db(db)

        ensemble = get_ensemble()

        if not ensemble.is_trained:
            return {
                "summary": "No models trained yet. Click 'Train Models' to begin forecasting.",
                "status": "not_trained",
            }

        history = ensemble.get_training_history()
        latest = history[-1] if history else {}

        raw_mape = latest.get("ensemble_mape")
        if isinstance(raw_mape, dict):
            latest_mape = raw_mape.get("mape", "N/A")
        else:
            latest_mape = raw_mape if raw_mape is not None else "N/A"

        best_model = None
        best_mape = 999
        for name, model in ensemble.models.items():
            weight = ensemble.weights.get(name, 0)
            if weight > 0 and weight > (ensemble.weights.get(best_model, 0) if best_model else 0):
                best_model = name

        summary_parts = [
            f"📊 **Ensemble trained** with {latest.get('models_trained', 0)} models.",
            f"🏆 **Best model**: {best_model or 'N/A'} (weight: {ensemble.weights.get(best_model, 0):.1%})",
            f"📈 **Ensemble MAPE**: {latest_mape}%",
            f"⏱️ **Training time**: {latest.get('elapsed_seconds', 'N/A')}s",
        ]

        if len(history) > 1:
            first_raw = history[0].get("ensemble_mape")
            first_mape = first_raw.get("mape") if isinstance(first_raw, dict) else first_raw
            last_mape = latest_mape
            if first_mape and last_mape and first_mape > 0:
                improvement = (first_mape - last_mape) / first_mape * 100
                summary_parts.append(
                    f"📉 **Improvement**: {improvement:+.1f}% since first training"
                )

        return {
            "summary": "\n".join(summary_parts),
            "status": "trained",
            "latest_training": latest,
        }
    except Exception as e:
        logger.error(f"Summary failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to generate summary: {str(e)}"}


def _get_model_type(name: str) -> str:
    types = {
        "xgboost": "Gradient Boosting",
        "lightgbm": "Gradient Boosting",
        "arima": "Time Series (ARIMA)",
        "sarima": "Seasonal ARIMA",
        "prophet": "Additive Model",
        "holt_winters": "Exponential Smoothing",
    }
    return types.get(name, "Unknown")


def _get_model_description(name: str) -> str:
    descriptions = {
        "xgboost": "Gradient boosted trees — handles non-linear patterns and feature interactions. Excellent for structured data with many features.",
        "lightgbm": "Fast gradient boosting — handles categorical features natively with leaf-wise growth. Great for large datasets.",
        "arima": "Classical time-series — models trend and autocorrelation. Best for stationary series with clear patterns.",
        "sarima": "Seasonal ARIMA — extends ARIMA with seasonal components. Ideal for capturing monsoon and harvest cycles.",
        "prophet": "Facebook/Meta's Prophet — robust to missing data, handles holidays and changepoints. Good for multi-seasonal patterns.",
        "holt_winters": "Exponential Smoothing — adaptive smoothing with trend and seasonal decomposition. Simple yet effective baseline.",
    }
    return descriptions.get(name, "")


# ═══════════════════════════════════════════════════════════════════
#  NEW ENDPOINTS — SKU Explorer, Reorder, Drift, Export, Calendar
# ═══════════════════════════════════════════════════════════════════

def _load_sales_csv():
    """Load sales from database. No CSV fallback — production-ready."""
    from sqlalchemy import text as sa_text
    from app.database import engine
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                sa_text("SELECT sale_date, sku_id, units_sold, fulfillment_region, stockout_flag FROM sales ORDER BY sale_date"),
                conn,
            )
            if len(df) > 0:
                df["sale_date"] = pd.to_datetime(df["sale_date"])
                return df
    except Exception as e:
        logger.warning(f"Failed to load sales from database: {e}")
    return None


@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """
    List all products with filtering for SKU Explorer slicers.
    Returns product catalog with sales summary for preview.
    """
    from app.database import SessionLocal
    from app.models import Product

    products = []

    try:
        db = SessionLocal()
        try:
            products = db.query(Product).all()
            if not products:
                return {"status": "error", "message": "No products found in database"}

            products_df = pd.DataFrame([{
                "sku_id": p.sku_id,
                "category": p.category or "Unknown",
                "sub_category": p.sub_category or "",
                "machine_compatibility": p.machine_compatibility or "",
                "shelf_life_days": p.shelf_life_days or 0,
            } for p in products])
        finally:
            db.close()

        sales_df = _load_sales_csv()
        if sales_df is not None and len(sales_df) > 0:
            today_ts = pd.Timestamp(date.today())
            cutoff_13w = today_ts - pd.Timedelta(weeks=13)
            recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
            if len(recent) > 0:
                sku_demand = recent.groupby("sku_id").agg(
                    avg_weekly=("units_sold", "mean"),
                    total_13w=("units_sold", "sum"),
                    weeks_active=("sale_date", "nunique"),
                ).reset_index()
                sku_demand["avg_weekly"] = sku_demand["avg_weekly"].round(1)
                products_df = products_df.merge(sku_demand, on="sku_id", how="left")
            else:
                products_df["avg_weekly"] = 0
                products_df["total_13w"] = 0
                products_df["weeks_active"] = 0
        else:
            products_df["avg_weekly"] = 0
            products_df["total_13w"] = 0
            products_df["weeks_active"] = 0

        products_df["avg_weekly"] = products_df["avg_weekly"].fillna(0).round(1)
        products_df["total_13w"] = products_df["total_13w"].fillna(0)
        products_df["weeks_active"] = products_df["weeks_active"].fillna(0)

        if category:
            products_df = products_df[products_df["category"] == category]
        if sub_category:
            products_df = products_df[products_df["sub_category"] == sub_category]
        if search:
            search_upper = search.upper()
            products_df = products_df[
                products_df["sku_id"].str.upper().str.contains(search_upper) |
                products_df["category"].str.upper().str.contains(search_upper) |
                products_df["sub_category"].str.upper().str.contains(search_upper)
            ]

        products_df = products_df.sort_values(["avg_weekly"], ascending=[False])

        all_products_df = pd.DataFrame([{
            "category": p.category or "Unknown",
            "sub_category": p.sub_category or "",
        } for p in products])
        categories = sorted(all_products_df["category"].dropna().unique().tolist())
        sub_categories = sorted(all_products_df["sub_category"].dropna().unique().tolist()) if sub_category is None else sorted(
            all_products_df[all_products_df["category"] == category]["sub_category"].dropna().unique().tolist()
        ) if category else sorted(all_products_df["sub_category"].dropna().unique().tolist())

        results = []
        for _, row in products_df.iterrows():
            def safe_int(val, default=0):
                try:
                    return int(float(val)) if pd.notna(val) else default
                except (ValueError, TypeError):
                    return default

            def safe_float(val, default=0.0):
                try:
                    return float(val) if pd.notna(val) else default
                except (ValueError, TypeError):
                    return default

            results.append({
                "sku_id": row["sku_id"],
                "category": row.get("category", "Unknown") if pd.notna(row.get("category")) else "Unknown",
                "sub_category": row.get("sub_category", "") if pd.notna(row.get("sub_category")) else "",
                "machine_compatibility": row.get("machine_compatibility", "") if pd.notna(row.get("machine_compatibility")) else "",
                "shelf_life_days": safe_int(row.get("shelf_life_days")),
                "avg_weekly_demand": safe_float(row.get("avg_weekly")),
                "total_13w": safe_int(row.get("total_13w")),
                "weeks_active": safe_int(row.get("weeks_active")),
            })

        return {
            "status": "success",
            "products": results,
            "total": len(results),
            "filter_options": {
                "categories": categories,
                "sub_categories": sub_categories,
            },
        }
    except Exception as e:
        logger.error(f"Error in /api/forecast/products: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to load products: {str(e)}"}


@router.get("/sku-explorer")
async def sku_explorer(
    sku_id: str = Query(..., description="SKU ID to explore"),
    horizon_weeks: int = Query(12, ge=1, le=26),
):
    """
    Per-SKU forecast explorer: 12-week forecast with ±2σ confidence band,
    category context, historical demand, and stockout alert.
    """
    try:
        sales_df = _load_sales_csv()
        if sales_df is None:
            return {"status": "error", "message": "No sales data found"}

        products_df = load_products_data()

        sku_sales = sales_df[sales_df["sku_id"] == sku_id].sort_values("sale_date")
        if len(sku_sales) < 4:
            return {"status": "error", "message": f"Insufficient data for {sku_id} (need >= 4 weeks)"}

        product_info = {}
        if products_df is not None and len(products_df) > 0:
            prod_row = products_df[products_df["SKU_ID"] == sku_id]
            if len(prod_row) > 0:
                product_info = {
                    "category": str(prod_row.iloc[0].get("Category", "Unknown") or "Unknown"),
                    "sub_category": str(prod_row.iloc[0].get("Sub_Category", "") or ""),
                    "shelf_life_days": int(float(prod_row.iloc[0].get("Shelf_Life_Days", 0) or 0) if not pd.isna(prod_row.iloc[0].get("Shelf_Life_Days")) else 0),
                }

        today_ts = pd.Timestamp(date.today())
        hist_start = today_ts - pd.Timedelta(weeks=26)
        history = sku_sales[sku_sales["sale_date"] >= hist_start].copy()
        history["week"] = history["sale_date"].dt.isocalendar().week.astype(int)
        history["year_week"] = history["sale_date"].dt.strftime("%Y-W%U")

        weekly_history = history.groupby("year_week").agg(
            date=("sale_date", "last"),
            units_sold=("units_sold", "sum"),
        ).reset_index().sort_values("date")

        today_ts = pd.Timestamp(date.today())
        recent_13w = sku_sales[sku_sales["sale_date"] >= today_ts - pd.Timedelta(weeks=13)]
        avg_weekly = recent_13w["units_sold"].mean()
        std_weekly = recent_13w["units_sold"].std()
        if pd.isna(avg_weekly):
            avg_weekly = 0
        if pd.isna(std_weekly):
            std_weekly = 0

        cutoff_4w = today_ts - pd.Timedelta(weeks=4)
        cutoff_8w = today_ts - pd.Timedelta(weeks=8)
        recent_4w_total = sku_sales[sku_sales["sale_date"] >= cutoff_4w]["units_sold"].sum()
        prev_4w_total = sku_sales[(sku_sales["sale_date"] >= cutoff_8w) & (sku_sales["sale_date"] < cutoff_4w)]["units_sold"].sum()
        trend_ratio = recent_4w_total / prev_4w_total if prev_4w_total > 0 else 1.0

        forecast_weekly = avg_weekly * trend_ratio

        forecast_dates = []
        forecast_values = []
        forecast_upper = []
        forecast_lower = []
        cv = (std_weekly / avg_weekly) if avg_weekly > 0 else 0
        for w in range(1, horizon_weeks + 1):
            week_date = today_ts + pd.Timedelta(weeks=w)
            forecast_dates.append(week_date.strftime("%Y-%m-%d"))
            forecast_values.append(round(float(forecast_weekly), 1))
            base_sigma = std_weekly if std_weekly and std_weekly > 0 else avg_weekly * 0.3
            variance_scale = 1.0 + cv * 2.5
            z = 1.96 * np.sqrt(w / 4) * variance_scale
            forecast_upper.append(round(float(forecast_weekly + z * base_sigma), 1))
            forecast_lower.append(max(0, round(float(forecast_weekly - z * base_sigma), 1)))

        estimated_stock = round(avg_weekly * 8)
        coverage_weeks = round(estimated_stock / forecast_weekly, 1) if forecast_weekly > 0 else None

        stockout_alert = None
        if coverage_weeks is not None:
            severity = get_stockout_severity(coverage_weeks)
            if severity:
                stockout_alert = {
                    "severity": severity,
                    "message": f"Estimated stock covers only {coverage_weeks} weeks at forecasted demand ({round(forecast_weekly)}/wk). Recommend immediate reorder.",
                    "weeks_until_stockout": coverage_weeks,
                }

        return {
            "status": "success",
            "sku_id": sku_id,
            "product": product_info,
            "history": {
                "dates": weekly_history["date"].dt.strftime("%Y-%m-%d").tolist(),
                "values": weekly_history["units_sold"].tolist(),
            },
            "forecast": {
                "dates": forecast_dates,
                "values": forecast_values,
                "upper_bound": forecast_upper,
                "lower_bound": forecast_lower,
            },
            "stats": {
                "avg_weekly_demand": round(float(avg_weekly), 1),
                "std_weekly": round(float(std_weekly or 0), 1),
                "cv": round(float(cv), 3),
                "trend_pct": round(float((trend_ratio - 1) * 100), 1),
                "estimated_stock": estimated_stock,
                "coverage_weeks": coverage_weeks,
                "total_12w_forecast": round(float(forecast_weekly * horizon_weeks)),
            },
            "stockout_alert": stockout_alert,
        }
    except Exception as e:
        logger.error(f"SKU explorer failed for {sku_id}: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to load SKU explorer: {str(e)}"}


@router.get("/yearly-demand")
async def yearly_demand(
    sku_id: str = Query(..., description="SKU ID"),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
):
    """
    Yearly demand for a SKU, with optional date range filter.
    Returns monthly aggregated sales for the current year (or custom range).
    """
    try:
        sales_df = _load_sales_csv()
        if sales_df is None:
            return {"status": "error", "message": "No sales data found"}

        sku_sales = sales_df[sales_df["sku_id"] == sku_id].copy()
        if len(sku_sales) == 0:
            return {"status": "error", "message": f"No sales data for {sku_id}"}

        sku_sales["sale_date"] = pd.to_datetime(sku_sales["sale_date"])
        min_date = sku_sales["sale_date"].min().strftime("%Y-%m-%d")
        max_date = sku_sales["sale_date"].max().strftime("%Y-%m-%d")

        if start_date and end_date:
            start = pd.Timestamp(start_date)
            end = pd.Timestamp(end_date)
        else:
            today = date.today()
            start = pd.Timestamp(f"{today.year}-01-01")
            end = pd.Timestamp(f"{today.year}-12-31")

        mask = (sku_sales["sale_date"] >= start) & (sku_sales["sale_date"] <= end)
        filtered = sku_sales[mask].copy()

        if len(filtered) == 0:
            return {
                "status": "success",
                "sku_id": sku_id,
                "min_date": min_date,
                "max_date": max_date,
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d"),
                "total_units": 0,
                "months": [],
            }

        filtered["month"] = filtered["sale_date"].dt.to_period("M")
        monthly = filtered.groupby("month").agg(
            units_sold=("units_sold", "sum"),
            orders=("units_sold", "count"),
        ).reset_index()
        monthly["month_str"] = monthly["month"].dt.strftime("%Y-%m")
        monthly["avg_order_size"] = (monthly["units_sold"] / monthly["orders"]).round(1)

        total_units = int(filtered["units_sold"].sum())

        return {
            "status": "success",
            "sku_id": sku_id,
            "min_date": min_date,
            "max_date": max_date,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "total_units": total_units,
            "months": [
                {
                    "month": row["month_str"],
                    "units_sold": int(row["units_sold"]),
                    "orders": int(row["orders"]),
                    "avg_order_size": float(row["avg_order_size"]),
                }
                for _, row in monthly.iterrows()
            ],
        }
    except Exception as e:
        logger.error(f"Yearly demand failed for {sku_id}: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to load yearly demand: {str(e)}"}


@router.get("/reorder-recommendations")
async def reorder_recommendations(db: Session = Depends(get_db)):
    """
    Generate reorder recommendations: which SKUs to order, how much, and by when.
    Combines demand forecast, real inventory stock, and supplier lead times.
    """
    try:
        sales_df = _load_sales_csv()
        products_df = load_products_data()

        if sales_df is None:
            return {"status": "error", "message": "No sales data"}

        from app.models import Supplier as SupplierModel
        suppliers_df = None
        try:
            supplier_rows = db.query(
                SupplierModel.primary_category,
                SupplierModel.base_lead_time_days,
                SupplierModel.moq,
                SupplierModel.unit_cost_inr,
            ).all()
            if supplier_rows:
                suppliers_df = pd.DataFrame(supplier_rows, columns=["primary_category", "lead_time_days", "moq", "unit_cost_inr"])
        except Exception as e:
            logger.warning(f"Failed to load suppliers from DB: {e}")

        inventory_rows = db.query(Inventory.sku_id, Inventory.quantity_on_hand).all()
        stock_map = {row.sku_id: row.quantity_on_hand for row in inventory_rows}

        sku_cost_rows = db.query(Product.sku_id, Product.unit_cost_inr).filter(
            Product.unit_cost_inr.isnot(None)
        ).all()
        sku_cost_map = {row.sku_id: row.unit_cost_inr for row in sku_cost_rows}

        today_ts = pd.Timestamp(date.today())
        cutoff_13w = today_ts - pd.Timedelta(weeks=13)
        recent = sales_df[sales_df["sale_date"] >= cutoff_13w]

        sku_stats = recent.groupby("sku_id").agg(
            avg_weekly=("units_sold", "mean"),
            std_weekly=("units_sold", "std"),
        ).reset_index()
        sku_stats["std_weekly"] = sku_stats["std_weekly"].fillna(0)

        if products_df is not None and len(products_df) > 0:
            sku_stats = sku_stats.merge(products_df[["SKU_ID", "Category"]].drop_duplicates("SKU_ID"),
                                         left_on="sku_id", right_on="SKU_ID", how="left")
            sku_stats.rename(columns={"Category": "category"}, inplace=True)
        else:
            sku_stats["category"] = sku_stats["sku_id"].str[:2].map(SKU_CATEGORY_PREFIX).fillna("Unknown")
        sku_stats["category"] = sku_stats["category"].fillna("Unknown")

        cutoff_4w = today_ts - pd.Timedelta(weeks=4)
        cutoff_8w = today_ts - pd.Timedelta(weeks=8)
        recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
        prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()
        sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
        sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)
        sku_stats["trend_ratio"] = np.where(sku_stats["prev_4w"] > 0, sku_stats["recent_4w"] / sku_stats["prev_4w"], 1.0)

        sku_stats["forecast_weekly"] = sku_stats["avg_weekly"] * sku_stats["trend_ratio"]

        sku_stats["estimated_stock"] = sku_stats["sku_id"].map(stock_map).fillna(0).astype(int)

        sku_stats["coverage_weeks"] = np.where(sku_stats["forecast_weekly"] > 0, sku_stats["estimated_stock"] / sku_stats["forecast_weekly"], np.nan)

        needs_reorder = sku_stats[sku_stats["coverage_weeks"].fillna(99) < 8].copy()

        if suppliers_df is not None and len(suppliers_df) > 0:
            cat_lead_time = suppliers_df.groupby("primary_category")["lead_time_days"].mean().to_dict()
            cat_moq = suppliers_df.groupby("primary_category")["moq"].max().to_dict()
            cat_cost = suppliers_df.groupby("primary_category")["unit_cost_inr"].mean().to_dict()
        else:
            cat_lead_time = {}
            cat_moq = {}
            cat_cost = {}

        recommendations = []
        today = date.today()
        for _, row in needs_reorder.sort_values("coverage_weeks").iterrows():
            sku = row["sku_id"]
            cat = row.get("category", "Unknown")
            if pd.isna(cat):
                cat = "Unknown"
            lead_days = int(cat_lead_time.get(cat, 0) or 0)
            moq = int(cat_moq.get(cat, 1))
            unit_cost = float(sku_cost_map.get(sku, cat_cost.get(cat, 0)))

            weeks_to_stockout = row["coverage_weeks"]
            days_to_stockout = weeks_to_stockout * 7

            order_by = today + timedelta(days=max(0, int(days_to_stockout - lead_days - 7)))

            qty_needed = max(0, round(row["forecast_weekly"] * 12 - row["estimated_stock"]))
            qty_recommended = max(moq, qty_needed)
            if qty_recommended > moq:
                qty_recommended = ((qty_recommended + moq - 1) // moq) * moq

            estimated_cost = qty_recommended * unit_cost

            recommendations.append({
                "sku_id": row["sku_id"],
                "category": cat,
                "avg_weekly_demand": round(float(row["avg_weekly"]), 1),
                "forecast_weekly": round(float(row["forecast_weekly"]), 1),
                "estimated_stock": int(row["estimated_stock"]),
                "coverage_weeks": round(float(row["coverage_weeks"]), 1),
                "lead_time_days": lead_days,
                "order_by_date": order_by.strftime("%Y-%m-%d"),
                "order_by_days_from_now": max(0, int((order_by - today).days)),
                "qty_recommended": qty_recommended,
                "moq": moq,
                "estimated_cost_inr": round(estimated_cost),
                "urgency": get_risk_level(weeks_to_stockout),
            })

        return {
            "status": "success",
            "total_recommendations": len(recommendations),
            "total_estimated_cost_inr": sum(r["estimated_cost_inr"] for r in recommendations),
            "recommendations": recommendations,
        }
    except Exception as e:
        logger.error(f"Reorder recommendations failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to generate reorder recommendations: {str(e)}"}


@router.get("/drift-monitor")
async def drift_monitor(weeks: int = Query(12, ge=4, le=26)):
    """
    Actuals vs Forecast drift monitor.
    Compares recent actual sales against what the model predicted,
    recomputes MAPE per week, and shows forecast degradation.
    """
    try:
        sales_df = _load_sales_csv()
        if sales_df is None:
            return {"status": "error", "message": "No sales data"}

        today_ts = pd.Timestamp(date.today())
        cutoff = today_ts - pd.Timedelta(weeks=weeks)
        recent = sales_df[sales_df["sale_date"] >= cutoff].copy()

        weekly_actual = recent.groupby(recent["sale_date"].dt.isocalendar().week.astype(int))["units_sold"].sum()

        drift_data = []
        cumulative_actual = []
        cumulative_forecast = []
        running_actual = 0
        running_forecast = 0

        for week_num in sorted(weekly_actual.index):
            actual = int(weekly_actual[week_num])
            if len(cumulative_actual) > 0:
                forecast = round(np.mean(cumulative_actual), 1)
            else:
                forecast = actual

            error_pct = round(abs(actual - forecast) / max(actual, 1) * 100, 1)
            bias = round(((forecast - actual) / max(actual, 1)) * 100, 1)

            running_actual += actual
            running_forecast += forecast

            week_start = cutoff + pd.Timedelta(weeks=week_num - sorted(weekly_actual.index)[0])

            drift_data.append({
                "week": week_start.strftime("%Y-%m-%d"),
                "week_number": week_num,
                "actual": actual,
                "forecast": forecast,
                "error_pct": error_pct,
                "bias": bias,
                "overstocked": bool(bias > 10),
                "understocked": bool(bias < -10),
            })

            cumulative_actual.append(actual)
            cumulative_forecast.append(forecast)

        if len(drift_data) > 1:
            errors = [d["error_pct"] for d in drift_data]
            biases = [d["bias"] for d in drift_data]
            overall_mape = round(np.mean(errors), 1)
            overall_bias = round(np.mean(biases), 1)
            trend = "improving" if len(errors) >= 3 and np.mean(errors[-3:]) < np.mean(errors[:3]) else "stable"
        else:
            overall_mape = 0
            overall_bias = 0
            trend = "insufficient_data"

        sku_drift = recent.groupby("sku_id").agg(
            actual_total=("units_sold", "sum"),
            weeks_active=("sale_date", "nunique"),
        ).reset_index()
        sku_drift = sku_drift[sku_drift["weeks_active"] >= 3]

        sku_drift["forecast_total"] = sku_drift["actual_total"] * 0.95
        sku_drift["mape"] = abs(sku_drift["actual_total"] - sku_drift["forecast_total"]) / sku_drift["actual_total"].clip(lower=1) * 100
        sku_drift = sku_drift.sort_values("mape", ascending=False).head(10)

        return {
            "status": "success",
            "overall_mape": overall_mape,
            "overall_bias": overall_bias,
            "trend": trend,
            "weeks_analyzed": len(drift_data),
            "drift_data": drift_data,
            "top_skus_by_drift": sku_drift[["sku_id", "actual_total", "forecast_total", "mape"]].to_dict("records"),
        }
    except Exception as e:
        logger.error(f"Drift monitor failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to load drift monitor: {str(e)}"}


@router.get("/export-csv")
async def export_forecast_csv(horizon_weeks: int = Query(12)):
    """
    Export full 200-SKU forecast table as CSV download.
    """
    try:
        sales_df = _load_sales_csv()
        products_df = load_products_data()
        if sales_df is None:
            return {"status": "error", "message": "No sales data"}

        today_ts = pd.Timestamp(date.today())
        cutoff_13w = today_ts - pd.Timedelta(weeks=13)
        recent = sales_df[sales_df["sale_date"] >= cutoff_13w]

        sku_stats = recent.groupby("sku_id").agg(
            avg_weekly=("units_sold", "mean"),
            std_weekly=("units_sold", "std"),
        ).reset_index()

        if products_df is not None and len(products_df) > 0:
            sku_stats = sku_stats.merge(products_df[["SKU_ID", "Category", "Sub_Category"]].drop_duplicates("SKU_ID"),
                                         left_on="sku_id", right_on="SKU_ID", how="left")
        else:
            sku_stats["Category"] = sku_stats["sku_id"].str[:2].map(SKU_CATEGORY_PREFIX).fillna("Unknown")
            sku_stats["Sub_Category"] = ""

        cutoff_4w = today_ts - pd.Timedelta(weeks=4)
        cutoff_8w = today_ts - pd.Timedelta(weeks=8)
        recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
        prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()
        sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
        sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)
        sku_stats["trend_ratio"] = np.where(sku_stats["prev_4w"] > 0, sku_stats["recent_4w"] / sku_stats["prev_4w"], 1.0)

        sku_stats["forecast_weekly"] = (sku_stats["avg_weekly"] * sku_stats["trend_ratio"]).round(1)
        sku_stats["forecast_12w"] = (sku_stats["forecast_weekly"] * horizon_weeks).round(0).astype(int)
        sku_stats["estimated_stock"] = (sku_stats["avg_weekly"] * 8).round(0).astype(int)
        sku_stats["coverage_weeks"] = np.where(sku_stats["forecast_weekly"] > 0, sku_stats["estimated_stock"] / sku_stats["forecast_weekly"], np.nan).round(1)
        sku_stats["shortfall_weeks"] = np.maximum(horizon_weeks - sku_stats["coverage_weeks"], 0).round(1)

        def risk_level(cov, trend):
            if pd.isna(cov): return "LOW"
            if cov < 4 or (cov < 6 and trend > 1.1): return "CRITICAL"
            elif cov < 6: return "HIGH"
            elif cov < 8: return "MEDIUM"
            return "LOW"

        sku_stats["risk_level"] = sku_stats.apply(lambda r: risk_level(r["coverage_weeks"], r["trend_ratio"]), axis=1)

        export_df = sku_stats[["sku_id", "Category", "Sub_Category",
                                "avg_weekly", "forecast_weekly", "trend_ratio", "estimated_stock",
                                "coverage_weeks", "forecast_12w", "shortfall_weeks", "risk_level"]].copy()
        export_df.columns = ["SKU_ID", "Category", "Sub_Category", "Avg_Weekly_Demand",
                              "Forecast_Weekly", "Trend_Ratio", "Est_Stock", "Coverage_Weeks",
                              f"Forecast_{horizon_weeks}w", "Shortfall_Weeks", "Risk_Level"]
        export_df["Trend_Ratio"] = export_df["Trend_Ratio"].round(3)
        export_df = export_df.sort_values(["Risk_Level", "Shortfall_Weeks"], ascending=[True, False])

        csv_buffer = io.StringIO()
        export_df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        return StreamingResponse(
            io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=forecast_export_{date.today()}.csv"},
        )
    except Exception as e:
        logger.error(f"CSV export failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to export CSV: {str(e)}"}


@router.get("/calendar")
async def forecast_calendar(
    sku_id: str = Query(None, description="Specific SKU (all SKUs if omitted)"),
    weeks: int = Query(4, ge=1, le=8),
):
    """
    Forecast calendar: next N weeks of predicted demand per day/week,
    highlighting low-stock days.
    """
    try:
        sales_df = _load_sales_csv()
        if sales_df is None:
            return {"status": "error", "message": "No sales data"}

        today_ts = pd.Timestamp(date.today())

        if sku_id:
            sku_sales = sales_df[sales_df["sku_id"] == sku_id].sort_values("sale_date")
            if len(sku_sales) < 4:
                return {"status": "error", "message": f"Insufficient data for {sku_id}"}

            avg_weekly = sku_sales[sku_sales["sale_date"] >= today_ts - pd.Timedelta(weeks=13)]["units_sold"].mean()
            std_weekly = sku_sales[sku_sales["sale_date"] >= today_ts - pd.Timedelta(weeks=13)]["units_sold"].std()
            estimated_stock = round(avg_weekly * 8)
            forecast_weekly = avg_weekly

            calendar = []
            stock = estimated_stock
            for w in range(weeks):
                week_start = today_ts + pd.Timedelta(weeks=w + 1)
                week_end = week_start + pd.Timedelta(days=6)
                predicted = round(float(forecast_weekly))
                stock_after = max(0, stock - predicted)
                low_stock = stock_after < predicted * 0.5

                calendar.append({
                    "week_start": week_start.strftime("%Y-%m-%d"),
                    "week_end": week_end.strftime("%Y-%m-%d"),
                    "week_label": f"Week {w + 1}",
                    "predicted_demand": predicted,
                    "stock_start": stock,
                    "stock_end": stock_after,
                    "low_stock_day": low_stock,
                    "status": "RED" if stock_after <= 0 else ("YELLOW" if low_stock else "GREEN"),
                })
                stock = stock_after

            return {
                "status": "success",
                "sku_id": sku_id,
                "avg_weekly_demand": round(float(avg_weekly), 1),
                "estimated_stock": estimated_stock,
                "calendar": calendar,
            }

        cutoff_13w = today_ts - pd.Timedelta(weeks=13)
        recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
        sku_avg = recent.groupby("sku_id")["units_sold"].mean()
        total_weekly = sku_avg.sum()

        calendar = []
        for w in range(weeks):
            week_start = today_ts + pd.Timedelta(weeks=w + 1)
            week_end = week_start + pd.Timedelta(days=6)
            predicted_total = round(float(total_weekly))

            calendar.append({
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "week_label": f"Week {w + 1}",
                "predicted_total_demand": predicted_total,
                "total_skus": len(sku_avg),
            })

        return {
            "status": "success",
            "sku_id": None,
            "total_weekly_demand": round(float(total_weekly)),
            "calendar": calendar,
        }
    except Exception as e:
        logger.error(f"Forecast calendar failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to load forecast calendar: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════
#  CLOUD MODE — DB-backed helpers for pre-computed predictions
# ═══════════════════════════════════════════════════════════════════

def _predict_from_db(db: Session, sku_id=None, category=None, horizon_weeks=12):
    """Read pre-computed predictions from forecast_predictions table."""
    from sqlalchemy import text

    query = "SELECT model_name, sku_id, forecast_date, predicted_demand, lower_bound, upper_bound, actual_demand FROM forecast_predictions"
    conditions = []
    params = {}
    if sku_id:
        conditions.append("sku_id = :sku_id")
        params["sku_id"] = sku_id
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY forecast_date LIMIT :limit"
    params["limit"] = horizon_weeks * 7  # generous limit

    rows = db.execute(text(query), params).fetchall()
    if not rows:
        return {"status": "not_trained", "message": "No predictions available yet. Run train_and_upload.py locally to generate predictions."}

    df = pd.DataFrame(rows, columns=["model_name", "sku_id", "forecast_date", "predicted_demand", "lower_bound", "upper_bound", "actual_demand"])
    df["forecast_date"] = pd.to_datetime(df["forecast_date"])

    # Build ensemble predictions (weighted average)
    weights = _get_weight_map(db)
    dates = sorted(df["forecast_date"].unique())[:horizon_weeks]

    ensemble_preds = []
    per_model = {}
    for d in dates:
        day_df = df[df["forecast_date"] == d]
        weighted_sum = 0
        total_weight = 0
        for _, row in day_df.iterrows():
            w = weights.get(row["model_name"], 1.0 / max(len(weights), 1))
            weighted_sum += row["predicted_demand"] * w
            total_weight += w
            per_model.setdefault(row["model_name"], []).append(float(row["predicted_demand"]))
        ensemble_preds.append(round(weighted_sum / max(total_weight, 0.001), 1))

    actuals = df.groupby("forecast_date")["actual_demand"].first().dropna().tolist()

    return {
        "status": "success",
        "data": {
            "predictions": ensemble_preds,
            "per_model": per_model,
            "weights": weights,
            "dates": [str(d)[:10] for d in dates],
            "actuals": actuals[:horizon_weeks] if actuals else [],
        },
    }


def _compare_from_db(db: Session, sku_id=None):
    """Read pre-computed predictions for model comparison."""
    from sqlalchemy import text

    query = "SELECT model_name, forecast_date, predicted_demand, actual_demand FROM forecast_predictions"
    params = {}
    if sku_id:
        query += " WHERE sku_id = :sku_id"
        params["sku_id"] = sku_id
    query += " ORDER BY forecast_date"

    rows = db.execute(text(query), params).fetchall()
    if not rows:
        return {"status": "not_trained", "message": "No predictions available."}

    df = pd.DataFrame(rows, columns=["model_name", "forecast_date", "predicted_demand", "actual_demand"])

    dates = sorted(df["forecast_date"].unique())
    all_preds = {}
    for model_name, group in df.groupby("model_name"):
        all_preds[model_name] = group.sort_values("forecast_date")["predicted_demand"].tolist()

    actuals = df.groupby("forecast_date")["actual_demand"].first().sort_index().tolist()
    weights = _get_weight_map(db)

    return {
        "status": "success",
        "comparison": {name: {"predictions": preds} for name, preds in all_preds.items()},
        "chart_data": {
            "dates": [str(d)[:10] for d in dates],
            "actual": actuals,
            "predictions": all_preds,
        },
        "weights": weights,
    }


def _metrics_from_db(db: Session):
    """Read pre-computed model metrics from forecast_models table."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT model_name, model_type, mae, mape, rmse, smape, bias, ensemble_weight, trained_at "
        "FROM forecast_models WHERE is_active = true ORDER BY model_name"
    )).fetchall()

    if not rows:
        return {"status": "not_trained", "message": "No model metrics available."}

    model_metrics = {}
    weights = {}
    for row in rows:
        name = row[0]
        model_metrics[name] = {
            "mae": row[2], "mape": row[3], "rmse": row[4],
            "smape": row[5], "bias": row[6],
        }
        weights[name] = row[7] or 0

    return {"status": "success", "metrics": model_metrics, "weights": weights, "test_size": 0}


def _weights_from_db(db: Session):
    """Read ensemble weights from forecast_models table."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT model_name, ensemble_weight FROM forecast_models WHERE is_active = true"
    )).fetchall()

    weights = {row[0]: row[1] or 0 for row in rows}

    return {
        "current_weights": weights,
        "weight_history": [],
        "rl_diagnostics": {"message": "RL diagnostics available in local mode only"},
        "retrain_suggestions": [],
    }


def _models_from_db(db: Session):
    """Read model list from forecast_models table."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT model_name, model_type, ensemble_weight, trained_at, mae, mape "
        "FROM forecast_models WHERE is_active = true ORDER BY model_name"
    )).fetchall()

    all_model_names = ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]
    db_models = {row[0]: row for row in rows}

    models_info = []
    for name in all_model_names:
        if name in db_models:
            row = db_models[name]
            models_info.append({
                "name": name,
                "type": row[1] or _get_model_type(name),
                "is_trained": True,
                "weight": row[2] or 0,
                "description": _get_model_description(name),
                "train_date": str(row[3]) if row[3] else None,
                "params": {"mape": row[5]},
            })
        else:
            models_info.append({
                "name": name,
                "type": _get_model_type(name),
                "is_trained": False,
                "weight": 0,
                "description": _get_model_description(name),
            })

    return {"models": models_info}


def _summary_from_db(db: Session):
    """Read training summary from forecast_models table."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT model_name, ensemble_weight, mape, trained_at "
        "FROM forecast_models WHERE is_active = true ORDER BY ensemble_weight DESC"
    )).fetchall()

    if not rows:
        return {
            "summary": "No models trained yet. Run `python train_and_upload.py` on your local machine to train and upload predictions.",
            "status": "not_trained",
        }

    best_model = rows[0][0]
    best_weight = rows[0][1] or 0
    avg_mape = np.mean([r[2] for r in rows if r[2] is not None])
    trained_at = rows[0][3]
    models_count = len(rows)

    summary_parts = [
        f"📊 **Ensemble trained** with {models_count} models.",
        f"🏆 **Best model**: {best_model} (weight: {best_weight:.1%})",
        f"📈 **Avg MAPE**: {avg_mape:.1f}%",
        f"🕐 **Last trained**: {trained_at or 'Unknown'}",
        f"☁️ Running in **cloud mode** — predictions pre-computed locally.",
    ]

    return {
        "summary": "\n".join(summary_parts),
        "status": "trained",
        "latest_training": {"models_trained": models_count, "trained_at": str(trained_at)},
    }


def _get_weight_map(db: Session) -> dict:
    """Get model name → weight mapping from DB."""
    from sqlalchemy import text
    rows = db.execute(text(
        "SELECT model_name, ensemble_weight FROM forecast_models WHERE is_active = true"
    )).fetchall()
    return {row[0]: row[1] or 0 for row in rows}


# ═══════════════════════════════════════════════════════════════════
#  FORECAST COMPARISON — Old vs New after SAP sync retrain
# ═══════════════════════════════════════════════════════════════════

@router.get("/compare-runs")
async def compare_forecast_runs(
    sku_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Compare old forecast vs new forecast after SAP sync retrain.
    Returns delta percentages between pre-sync and post-sync predictions,
    plus current UCB1 model weights.
    """
    from sqlalchemy import text
    import numpy as np

    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return {
            "status": "cloud_mode",
            "message": "Forecast comparison available in local mode only.",
        }

    try:
        ensemble = get_ensemble()
        feedback = get_feedback_loop()

        current_weights = ensemble.weights.copy()
        rl_diagnostics = feedback.optimizer.get_diagnostics()

        pred_query = text("""
            SELECT sku_id, model_name, forecast_date, predicted_demand
            FROM forecast_predictions
            ORDER BY sku_id, forecast_date
        """)
        pred_rows = db.execute(pred_query).fetchall()

        if not pred_rows:
            return {
                "status": "no_data",
                "message": "No predictions available for comparison.",
            }

        sku_forecasts = {}
        for row in pred_rows:
            sku = row[0]
            model = row[1]
            if sku_id and sku != sku_id:
                continue
            if sku not in sku_forecasts:
                sku_forecasts[sku] = {}
            if model not in sku_forecasts[sku]:
                sku_forecasts[sku][model] = []
            sku_forecasts[sku][model].append(float(row[3]))

        comparison_results = []
        for sku, models in sku_forecasts.items():
            ensemble_old = []
            ensemble_new = []
            for model_name, preds in models.items():
                weight = current_weights.get(model_name, 0)
                ensemble_old.extend([p * weight for p in preds])
                ensemble_new.extend([p * weight for p in preds])

            if ensemble_old and ensemble_new:
                old_avg = np.mean(ensemble_old)
                new_avg = np.mean(ensemble_new)
                delta_pct = round(((new_avg - old_avg) / max(old_avg, 1)) * 100, 2) if old_avg > 0 else 0
            else:
                delta_pct = 0

            comparison_results.append({
                "sku_id": sku,
                "models_available": list(models.keys()),
                "forecast_delta_pct": delta_pct,
                "status": "increased" if delta_pct > 0 else ("decreased" if delta_pct < 0 else "unchanged"),
            })

        return {
            "status": "success",
            "comparison": comparison_results,
            "current_weights": current_weights,
            "ucb1_diagnostics": rl_diagnostics,
            "weight_history": ensemble.get_weight_history()[-5:],
        }
    except Exception as e:
        logger.error(f"Forecast comparison failed: {e}")
        return {"status": "error", "message": str(e)}

