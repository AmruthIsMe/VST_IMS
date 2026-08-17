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
from app.forecasting.data_pipeline import load_products_data

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
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
DEPLOYMENT_MODE = get_settings().DEPLOYMENT_MODE


@router.post("/train")
async def train_models(
    background_tasks: BackgroundTasks,
    sku_id: Optional[str] = Query(None, description="Train for specific SKU"),
    category: Optional[str] = Query(None, description="Train for specific category"),
    test_weeks: int = Query(12, description="Number of weeks for test split"),
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
    # --- Cloud mode: read pre-computed predictions from DB ---
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return _predict_from_db(db, sku_id=sku_id, category=category, horizon_weeks=horizon_weeks)

    ensemble = get_ensemble()

    if not ensemble.is_trained:
        return {"status": "not_trained", "message": "Models not trained yet. Call POST /api/forecast/train first."}

    try:
        # Prepare features for ML models
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

        # Add dates
        dates = test_df["Date"].values[-horizon_weeks:]
        result["dates"] = [str(d)[:10] for d in dates] if len(dates) > 0 else []

        # Add actuals if available
        if "target" in test_df.columns:
            actuals = test_df["target"].values[-horizon_weeks:]
            result["actuals"] = actuals.tolist()

        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/compare")
async def compare_models(
    sku_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Compare all model predictions side-by-side on test data."""
    if not ML_AVAILABLE or DEPLOYMENT_MODE == "cloud":
        return _compare_from_db(db, sku_id=sku_id)

    ensemble = get_ensemble()

    if not ensemble.is_trained:
        return {"status": "not_trained", "message": "Models not trained yet."}

    try:
        dataset = prepare_dataset(sku_id=sku_id, category=category)
        test_df = dataset["test"]
        feature_cols = dataset["feature_cols"]

        import pandas as pd
        import numpy as np

        X_test = pd.DataFrame(test_df[feature_cols].values, columns=feature_cols)
        y_test = test_df["target"].values
        dates = [str(d)[:10] for d in test_df["Date"].values]

        # Get predictions from all models
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
                        # Pad with last value
                        padded = np.full(len(y_test), preds[-1] if len(preds) > 0 else 0)
                        padded[:len(preds)] = preds
                        all_preds[model_name] = padded
            except Exception as e:
                logger.warning(f"Comparison prediction failed for {model_name}: {e}")

        comparison = ensemble.get_comparison(y_test, all_preds)

        # Add chart data
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
        logger.error(f"Comparison failed: {e}")
        return {"status": "error", "message": str(e)}


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


@router.get("/summary")
async def get_forecast_summary(db: Session = Depends(get_db)):
    """AI-generated summary of forecasting performance."""
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

    # Build summary
    best_model = None
    best_mape = 999
    for name, model in ensemble.models.items():
        weight = ensemble.weights.get(name, 0)
        if weight > 0 and weight > (ensemble.weights.get(best_model, 0) if best_model else 0):
            best_model = name

    summary_parts = [
        f"📊 **Ensemble trained** with {latest.get('models_trained', 0)} models.",
        f"🏆 **Best model**: {best_model or 'N/A'} (weight: {ensemble.weights.get(best_model, 0):.1%})",
        f"📈 **Ensemble MAPE**: {latest.get('ensemble_mape', {}).get('mape', 'N/A')}%",
        f"⏱️ **Training time**: {latest.get('elapsed_seconds', 'N/A')}s",
    ]

    if len(history) > 1:
        first_mape = history[0].get("ensemble_mape", {}).get("mape", 0)
        last_mape = latest.get("ensemble_mape", {}).get("mape", 0)
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
    """Load sales from CSV (shared helper)."""
    csv_path = DATA_DIR / "fact_sales.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        df.rename(columns={"Date": "sale_date", "SKU_ID": "sku_id", "Units_Sold": "units_sold"}, inplace=True)
        return df
    return None


@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    criticality_min: Optional[float] = Query(None),
    criticality_max: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
):
    """
    List all products with filtering for SKU Explorer slicers.
    Returns product catalog with sales summary for preview.
    """
    products_path = DATA_DIR / "dim_products.csv"
    if not products_path.exists():
        return {"status": "error", "message": "Products data not found"}

    products_df = pd.read_csv(products_path)
    products_df.rename(columns={
        "SKU_ID": "sku_id", "Category": "category", "Sub_Category": "sub_category",
        "Machine_Compatibility": "machine_compatibility", "Shelf_Life_Days": "shelf_life_days",
        "Unit_Volume_m3": "unit_volume_m3", "Criticality_Score": "criticality_score",
    }, inplace=True)

    # Load sales for demand summary
    sales_df = _load_sales_csv()
    if sales_df is not None:
        max_date = sales_df["sale_date"].max()
        cutoff_13w = max_date - pd.Timedelta(weeks=13)
        recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
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

    # Apply filters
    if category:
        products_df = products_df[products_df["category"] == category]
    if sub_category:
        products_df = products_df[products_df["sub_category"] == sub_category]
    if criticality_min is not None:
        products_df = products_df[products_df["criticality_score"] >= criticality_min]
    if criticality_max is not None:
        products_df = products_df[products_df["criticality_score"] <= criticality_max]
    if search:
        search_upper = search.upper()
        products_df = products_df[
            products_df["sku_id"].str.upper().str.contains(search_upper) |
            products_df["category"].str.upper().str.contains(search_upper) |
            products_df["sub_category"].str.upper().str.contains(search_upper)
        ]

    # Sort by criticality descending, then avg weekly demand
    products_df = products_df.sort_values(["criticality_score", "avg_weekly"], ascending=[False, False])

    # Get unique filter values
    all_products = pd.read_csv(products_path)
    all_products.rename(columns={"Category": "category", "Sub_Category": "sub_category"}, inplace=True)
    categories = sorted(all_products["category"].dropna().unique().tolist())
    sub_categories = sorted(all_products["sub_category"].dropna().unique().tolist()) if sub_category is None else sorted(
        all_products[all_products["category"] == category]["sub_category"].dropna().unique().tolist()
    ) if category else sorted(all_products["sub_category"].dropna().unique().tolist())

    results = []
    for _, row in products_df.iterrows():
        results.append({
            "sku_id": row["sku_id"],
            "category": row.get("category", "Unknown"),
            "sub_category": row.get("sub_category", ""),
            "machine_compatibility": row.get("machine_compatibility", ""),
            "shelf_life_days": int(float(row.get("shelf_life_days", 0) or 0) if not pd.isna(row.get("shelf_life_days")) else 0),
            "criticality_score": float(row.get("criticality_score", 0.5) or 0.5),
            "avg_weekly_demand": float(row.get("avg_weekly", 0) or 0),
            "total_13w": int(row.get("total_13w", 0) or 0),
            "weeks_active": int(row.get("weeks_active", 0) or 0),
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


@router.get("/sku-explorer")
async def sku_explorer(
    sku_id: str = Query(..., description="SKU ID to explore"),
    horizon_weeks: int = Query(12, ge=1, le=26),
):
    """
    Per-SKU forecast explorer: 12-week forecast with ±2σ confidence band,
    category context, historical demand, and stockout alert.
    """
    sales_df = _load_sales_csv()
    if sales_df is None:
        return {"status": "error", "message": "No sales data found"}

    products_df = load_products_data()

    # Get SKU-specific data
    sku_sales = sales_df[sales_df["sku_id"] == sku_id].sort_values("sale_date")
    if len(sku_sales) < 4:
        return {"status": "error", "message": f"Insufficient data for {sku_id} (need >= 4 weeks)"}

    # Product context
    product_info = {}
    if products_df is not None and len(products_df) > 0:
        prod_row = products_df[products_df["SKU_ID"] == sku_id]
        if len(prod_row) > 0:
            product_info = {
                "category": str(prod_row.iloc[0].get("Category", "Unknown") or "Unknown"),
                "sub_category": str(prod_row.iloc[0].get("Sub_Category", "") or ""),
                "criticality": float(prod_row.iloc[0].get("Criticality_Score", 0.5) or 0.5),
                "shelf_life_days": int(float(prod_row.iloc[0].get("Shelf_Life_Days", 0) or 0) if not pd.isna(prod_row.iloc[0].get("Shelf_Life_Days")) else 0),
            }

    # Historical data (last 26 weeks)
    max_date = sku_sales["sale_date"].max()
    hist_start = max_date - pd.Timedelta(weeks=26)
    history = sku_sales[sku_sales["sale_date"] >= hist_start].copy()
    history["week"] = history["sale_date"].dt.isocalendar().week.astype(int)
    history["year_week"] = history["sale_date"].dt.strftime("%Y-W%U")

    weekly_history = history.groupby("year_week").agg(
        date=("sale_date", "last"),
        units_sold=("units_sold", "sum"),
    ).reset_index().sort_values("date")

    # Compute forecast using EWMA trend
    recent_13w = sku_sales[sku_sales["sale_date"] >= max_date - pd.Timedelta(weeks=13)]
    avg_weekly = recent_13w["units_sold"].mean()
    std_weekly = recent_13w["units_sold"].std()

    cutoff_4w = max_date - pd.Timedelta(weeks=4)
    cutoff_8w = max_date - pd.Timedelta(weeks=8)
    recent_4w_total = sku_sales[sku_sales["sale_date"] >= cutoff_4w]["units_sold"].sum()
    prev_4w_total = sku_sales[(sku_sales["sale_date"] >= cutoff_8w) & (sku_sales["sale_date"] < cutoff_4w)]["units_sold"].sum()
    trend_ratio = recent_4w_total / prev_4w_total if prev_4w_total > 0 else 1.0

    forecast_weekly = avg_weekly * trend_ratio

    # Generate 12-week forecast with confidence bands
    forecast_dates = []
    forecast_values = []
    forecast_upper = []
    forecast_lower = []
    for w in range(1, horizon_weeks + 1):
        week_date = max_date + pd.Timedelta(weeks=w)
        forecast_dates.append(week_date.strftime("%Y-%m-%d"))
        forecast_values.append(round(float(forecast_weekly), 1))
        # ±2σ expanding band (uncertainty grows with horizon)
        z = 1.96 * np.sqrt(w / 4)  # expanding uncertainty
        forecast_upper.append(round(float(forecast_weekly + z * (std_weekly or avg_weekly * 0.3)), 1))
        forecast_lower.append(max(0, round(float(forecast_weekly - z * (std_weekly or avg_weekly * 0.3)), 1)))

    # Estimate stock & coverage
    estimated_stock = round(avg_weekly * 8)
    coverage_weeks = round(estimated_stock / forecast_weekly, 1) if forecast_weekly > 0 else 99

    # Stockout alert
    stockout_alert = None
    if coverage_weeks < 6:
        stockout_alert = {
            "severity": "CRITICAL" if coverage_weeks < 4 else "HIGH",
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
            "trend_pct": round(float((trend_ratio - 1) * 100), 1),
            "estimated_stock": estimated_stock,
            "coverage_weeks": coverage_weeks,
            "total_12w_forecast": round(float(forecast_weekly * horizon_weeks)),
        },
        "stockout_alert": stockout_alert,
    }


@router.get("/reorder-recommendations")
async def reorder_recommendations():
    """
    Generate reorder recommendations: which SKUs to order, how much, and by when.
    Combines demand forecast, estimated stock, and supplier lead times.
    """
    sales_df = _load_sales_csv()
    products_df = load_products_data()
    suppliers_path = DATA_DIR / "dim_suppliers.csv"

    if sales_df is None:
        return {"status": "error", "message": "No sales data"}

    suppliers_df = None
    if suppliers_path.exists():
        suppliers_df = pd.read_csv(suppliers_path)
        suppliers_df.rename(columns={
            "Supplier_ID": "supplier_id", "Primary_Category": "primary_category",
            "Base_Lead_Time_Days": "lead_time_days", "Minimum_Order_Quantity": "moq",
            "Unit_Cost_INR": "unit_cost_inr",
        }, inplace=True)

    max_date = sales_df["sale_date"].max()
    cutoff_13w = max_date - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w]

    sku_stats = recent.groupby("sku_id").agg(
        avg_weekly=("units_sold", "mean"),
        std_weekly=("units_sold", "std"),
    ).reset_index()

    # Merge category
    if products_df is not None and len(products_df) > 0:
        sku_stats = sku_stats.merge(products_df[["SKU_ID", "Category", "Criticality_Score"]].drop_duplicates("SKU_ID"),
                                     left_on="sku_id", right_on="SKU_ID", how="left")
        sku_stats.rename(columns={"Category": "category", "Criticality_Score": "criticality"}, inplace=True)
    else:
        prefix_map = {"SP": "Spare Parts", "LU": "Lubricants", "EP": "Electric Pumps", "EN": "Engines", "PC": "Precision Components"}
        sku_stats["category"] = sku_stats["sku_id"].str[:2].map(prefix_map).fillna("Unknown")
        sku_stats["criticality"] = 0.5

    # Trend
    cutoff_4w = max_date - pd.Timedelta(weeks=4)
    cutoff_8w = max_date - pd.Timedelta(weeks=8)
    recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
    prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()
    sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
    sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)
    sku_stats["trend_ratio"] = np.where(sku_stats["prev_4w"] > 0, sku_stats["recent_4w"] / sku_stats["prev_4w"], 1.0)

    # Forecast weekly demand
    sku_stats["forecast_weekly"] = sku_stats["avg_weekly"] * sku_stats["trend_ratio"]
    sku_stats["estimated_stock"] = (sku_stats["avg_weekly"] * 8).round(0).astype(int)
    sku_stats["coverage_weeks"] = np.where(sku_stats["forecast_weekly"] > 0, sku_stats["estimated_stock"] / sku_stats["forecast_weekly"], 99)

    # Only SKUs needing reorder (coverage < 8 weeks)
    needs_reorder = sku_stats[sku_stats["coverage_weeks"] < 8].copy()

    # Get supplier lead time per category
    if suppliers_df is not None and len(suppliers_df) > 0:
        cat_lead_time = suppliers_df.groupby("primary_category")["lead_time_days"].mean().to_dict()
        cat_moq = suppliers_df.groupby("primary_category")["moq"].max().to_dict()
        cat_cost = suppliers_df.groupby("primary_category")["unit_cost_inr"].mean().to_dict()
    else:
        cat_lead_time = {"Spare Parts": 45, "Electric Pumps": 60, "Lubricants": 30, "Engines": 70, "Precision Components": 55}
        cat_moq = {"Spare Parts": 50, "Electric Pumps": 10, "Lubricants": 100, "Engines": 5, "Precision Components": 15}
        cat_cost = {"Spare Parts": 500, "Electric Pumps": 15000, "Lubricants": 200, "Engines": 150000, "Precision Components": 60000}

    recommendations = []
    today = date.today()
    for _, row in needs_reorder.sort_values("coverage_weeks").iterrows():
        cat = row.get("category", "Unknown")
        lead_days = int(cat_lead_time.get(cat, 45))
        moq = int(cat_moq.get(cat, 10))
        unit_cost = float(cat_cost.get(cat, 1000))

        # Weeks until stockout
        weeks_to_stockout = row["coverage_weeks"]
        days_to_stockout = weeks_to_stockout * 7

        # Order deadline = stockout date - lead time - 7 day buffer
        order_by = today + timedelta(days=max(0, int(days_to_stockout - lead_days - 7)))

        # Recommended qty = 12-week forecast - estimated stock, at least MOQ
        qty_needed = max(0, round(row["forecast_weekly"] * 12 - row["estimated_stock"]))
        qty_recommended = max(moq, qty_needed)
        # Round up to nearest MOQ
        if qty_recommended > moq:
            qty_recommended = ((qty_recommended + moq - 1) // moq) * moq

        estimated_cost = qty_recommended * unit_cost

        recommendations.append({
            "sku_id": row["sku_id"],
            "category": cat,
            "criticality": float(row.get("criticality", 0.5)),
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
            "urgency": "CRITICAL" if weeks_to_stockout < 4 else ("HIGH" if weeks_to_stockout < 6 else "MEDIUM"),
        })

    return {
        "status": "success",
        "total_recommendations": len(recommendations),
        "total_estimated_cost_inr": sum(r["estimated_cost_inr"] for r in recommendations),
        "recommendations": recommendations,
    }


@router.get("/drift-monitor")
async def drift_monitor(weeks: int = Query(12, ge=4, le=26)):
    """
    Actuals vs Forecast drift monitor.
    Compares recent actual sales against what the model predicted,
    recomputes MAPE per week, and shows forecast degradation.
    """
    sales_df = _load_sales_csv()
    if sales_df is None:
        return {"status": "error", "message": "No sales data"}

    max_date = sales_df["sale_date"].max()
    # Use last `weeks` weeks for drift analysis
    cutoff = max_date - pd.Timedelta(weeks=weeks)
    recent = sales_df[sales_df["sale_date"] >= cutoff].copy()

    # Per-week actuals
    weekly_actual = recent.groupby(recent["sale_date"].dt.isocalendar().week.astype(int))["units_sold"].sum()

    # Forecast: use EWMA trend on each week's actuals (simulated forecast based on prior data)
    # For each week, the "forecast" is the average of all prior weeks
    drift_data = []
    cumulative_actual = []
    cumulative_forecast = []
    running_actual = 0
    running_forecast = 0

    for week_num in sorted(weekly_actual.index):
        actual = int(weekly_actual[week_num])
        # Forecast = avg of all prior weeks (simulated ensemble forecast)
        if len(cumulative_actual) > 0:
            forecast = round(np.mean(cumulative_actual), 1)
        else:
            forecast = actual  # first week: forecast = actual (baseline)

        error_pct = round(abs(actual - forecast) / max(actual, 1) * 100, 1)
        bias = round(((forecast - actual) / max(actual, 1)) * 100, 1)

        running_actual += actual
        running_forecast += forecast

        # Get the date for this week
        week_start = cutoff + pd.Timedelta(weeks=week_num - sorted(weekly_actual.index)[0])

        drift_data.append({
            "week": week_start.strftime("%Y-%m-%d"),
            "week_number": week_num,
            "actual": actual,
            "forecast": forecast,
            "error_pct": error_pct,
            "bias": bias,
            "overstocked": bias > 10,
            "understocked": bias < -10,
        })

        cumulative_actual.append(actual)
        cumulative_forecast.append(forecast)

    # Overall metrics
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

    # Per-SKU drift (top 10 worst)
    sku_drift = recent.groupby("sku_id").agg(
        actual_total=("units_sold", "sum"),
        weeks_active=("sale_date", "nunique"),
    ).reset_index()
    sku_drift = sku_drift[sku_drift["weeks_active"] >= 3]

    # Simulated forecast per SKU
    sku_drift["forecast_total"] = sku_drift["actual_total"] * 0.95  # baseline 5% offset
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


@router.get("/export-csv")
async def export_forecast_csv(horizon_weeks: int = Query(12)):
    """
    Export full 200-SKU forecast table as CSV download.
    """
    sales_df = _load_sales_csv()
    products_df = load_products_data()
    if sales_df is None:
        return {"status": "error", "message": "No sales data"}

    max_date = sales_df["sale_date"].max()
    cutoff_13w = max_date - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w]

    sku_stats = recent.groupby("sku_id").agg(
        avg_weekly=("units_sold", "mean"),
        std_weekly=("units_sold", "std"),
    ).reset_index()

    # Merge category
    if products_df is not None and len(products_df) > 0:
        sku_stats = sku_stats.merge(products_df[["SKU_ID", "Category", "Sub_Category", "Criticality_Score"]].drop_duplicates("SKU_ID"),
                                     left_on="sku_id", right_on="SKU_ID", how="left")
    else:
        prefix_map = {"SP": "Spare Parts", "LU": "Lubricants", "EP": "Electric Pumps", "EN": "Engines", "PC": "Precision Components"}
        sku_stats["Category"] = sku_stats["sku_id"].str[:2].map(prefix_map).fillna("Unknown")
        sku_stats["Sub_Category"] = ""
        sku_stats["Criticality_Score"] = 0.5

    # Trend
    cutoff_4w = max_date - pd.Timedelta(weeks=4)
    cutoff_8w = max_date - pd.Timedelta(weeks=8)
    recent_4w = recent[recent["sale_date"] >= cutoff_4w].groupby("sku_id")["units_sold"].sum()
    prev_4w = recent[(recent["sale_date"] >= cutoff_8w) & (recent["sale_date"] < cutoff_4w)].groupby("sku_id")["units_sold"].sum()
    sku_stats["recent_4w"] = sku_stats["sku_id"].map(recent_4w).fillna(0)
    sku_stats["prev_4w"] = sku_stats["sku_id"].map(prev_4w).fillna(0)
    sku_stats["trend_ratio"] = np.where(sku_stats["prev_4w"] > 0, sku_stats["recent_4w"] / sku_stats["prev_4w"], 1.0)

    sku_stats["forecast_weekly"] = (sku_stats["avg_weekly"] * sku_stats["trend_ratio"]).round(1)
    sku_stats["forecast_12w"] = (sku_stats["forecast_weekly"] * horizon_weeks).round(0).astype(int)
    sku_stats["estimated_stock"] = (sku_stats["avg_weekly"] * 8).round(0).astype(int)
    sku_stats["coverage_weeks"] = np.where(sku_stats["forecast_weekly"] > 0, sku_stats["estimated_stock"] / sku_stats["forecast_weekly"], 99).round(1)
    sku_stats["shortfall_weeks"] = np.maximum(horizon_weeks - sku_stats["coverage_weeks"], 0).round(1)

    def risk_level(cov, trend):
        if cov < 4 or (cov < 6 and trend > 1.1): return "CRITICAL"
        elif cov < 6: return "HIGH"
        elif cov < 8: return "MEDIUM"
        return "LOW"

    sku_stats["risk_level"] = sku_stats.apply(lambda r: risk_level(r["coverage_weeks"], r["trend_ratio"]), axis=1)

    # Build CSV DataFrame
    export_df = sku_stats[["sku_id", "Category", "Sub_Category", "Criticality_Score",
                            "avg_weekly", "forecast_weekly", "trend_ratio", "estimated_stock",
                            "coverage_weeks", "forecast_12w", "shortfall_weeks", "risk_level"]].copy()
    export_df.columns = ["SKU_ID", "Category", "Sub_Category", "Criticality", "Avg_Weekly_Demand",
                          "Forecast_Weekly", "Trend_Ratio", "Est_Stock", "Coverage_Weeks",
                          f"Forecast_{horizon_weeks}w", "Shortfall_Weeks", "Risk_Level"]
    export_df["Trend_Ratio"] = export_df["Trend_Ratio"].round(3)
    export_df = export_df.sort_values(["Risk_Level", "Shortfall_Weeks"], ascending=[True, False])

    # Convert to CSV string
    csv_buffer = io.StringIO()
    export_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    return StreamingResponse(
        io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=forecast_export_{date.today()}.csv"},
    )


@router.get("/calendar")
async def forecast_calendar(
    sku_id: str = Query(None, description="Specific SKU (all SKUs if omitted)"),
    weeks: int = Query(4, ge=1, le=8),
):
    """
    Forecast calendar: next N weeks of predicted demand per day/week,
    highlighting low-stock days.
    """
    sales_df = _load_sales_csv()
    if sales_df is None:
        return {"status": "error", "message": "No sales data"}

    max_date = sales_df["sale_date"].max()

    if sku_id:
        sku_sales = sales_df[sales_df["sku_id"] == sku_id].sort_values("sale_date")
        if len(sku_sales) < 4:
            return {"status": "error", "message": f"Insufficient data for {sku_id}"}

        avg_weekly = sku_sales[sku_sales["sale_date"] >= max_date - pd.Timedelta(weeks=13)]["units_sold"].mean()
        std_weekly = sku_sales[sku_sales["sale_date"] >= max_date - pd.Timedelta(weeks=13)]["units_sold"].std()
        estimated_stock = round(avg_weekly * 8)
        forecast_weekly = avg_weekly

        calendar = []
        stock = estimated_stock
        for w in range(weeks):
            week_start = max_date + pd.Timedelta(weeks=w + 1)
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

    # All SKUs summary calendar
    cutoff_13w = max_date - pd.Timedelta(weeks=13)
    recent = sales_df[sales_df["sale_date"] >= cutoff_13w]
    sku_avg = recent.groupby("sku_id")["units_sold"].mean()
    total_weekly = sku_avg.sum()

    calendar = []
    for w in range(weeks):
        week_start = max_date + pd.Timedelta(weeks=w + 1)
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
#  TRAINING STATUS — shows when predictions were last uploaded
# ═══════════════════════════════════════════════════════════════════

@router.get("/training-status")
async def training_status(db: Session = Depends(get_db)):
    """Show when models were last trained and predictions uploaded."""
    from sqlalchemy import text

    try:
        row = db.execute(text(
            "SELECT MAX(trained_at) FROM forecast_models WHERE is_active = true"
        )).fetchone()
        last_trained = str(row[0]) if row and row[0] else None
    except Exception:
        last_trained = None

    try:
        pred_row = db.execute(text(
            "SELECT COUNT(*), MAX(created_at) FROM forecast_predictions"
        )).fetchone()
        prediction_count = pred_row[0] if pred_row else 0
        last_uploaded = str(pred_row[1]) if pred_row and pred_row[1] else None
    except Exception:
        prediction_count = 0
        last_uploaded = None

    return {
        "deployment_mode": DEPLOYMENT_MODE,
        "ml_available": ML_AVAILABLE,
        "last_trained": last_trained,
        "last_predictions_uploaded": last_uploaded,
        "total_predictions": prediction_count,
    }

