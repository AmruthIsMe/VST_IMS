"""
forecaster.py — Tower 1: XGBoost demand forecasting model.

Trains a global XGBoost model on all 200 SKUs using the panel feature dataset.
Evaluates on 2025 test period and saves:
  - models/xgb_forecaster.json     (saved model)
  - data/demand_forecast.csv       (predictions on test set)
  - output/metrics/forecast_metrics.csv  (MAPE, RMSE per category)
"""

import json
import os
import warnings
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_squared_error

from src.feature_engineering import (
    FEATURE_COLS,
    TARGET_COL,
    build_features,
    load_raw_data,
    split_data,
)

warnings.filterwarnings("ignore")

MODEL_DIR   = "models"
METRICS_DIR = "output/metrics"
DATA_DIR    = "data"


# ── Metric helpers ─────────────────────────────────────────────────────────────
def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


# ── Training ───────────────────────────────────────────────────────────────────
def train_xgboost(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    params: Dict = None,
) -> Tuple[xgb.XGBRegressor, pd.DataFrame]:
    """
    Train a global XGBoost model and return (model, test_predictions_df).
    """
    if params is None:
        params = {
            "n_estimators":    500,
            "max_depth":       6,
            "learning_rate":   0.05,
            "subsample":       0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 3,
            "gamma":           0.1,
            "reg_alpha":       0.1,
            "reg_lambda":      1.0,
            "random_state":    42,
            "n_jobs":          -1,
            "tree_method":     "hist",
            "verbosity":       0,
        }

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_test  = test_df[FEATURE_COLS].values
    y_test  = test_df[TARGET_COL].values

    model = xgb.XGBRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # Predict and clip to >= 0
    preds = np.clip(model.predict(X_test), 0, None)

    # Attach predictions to test_df for downstream use
    result = test_df[["Date", "SKU_ID", "Category", TARGET_COL]].copy()
    result["predicted_demand"] = preds

    return model, result


# ── Evaluation ─────────────────────────────────────────────────────────────────
def evaluate_by_category(result_df: pd.DataFrame) -> pd.DataFrame:
    """Compute MAPE and RMSE per category and overall."""
    rows = []
    for cat, grp in result_df.groupby("Category"):
        rows.append({
            "Category": cat,
            "MAPE_%": round(mape(grp[TARGET_COL].values, grp["predicted_demand"].values), 2),
            "RMSE":    round(rmse(grp[TARGET_COL].values, grp["predicted_demand"].values), 2),
            "N_rows":  len(grp),
        })
    # Overall
    rows.append({
        "Category": "OVERALL",
        "MAPE_%": round(mape(result_df[TARGET_COL].values, result_df["predicted_demand"].values), 2),
        "RMSE":   round(rmse(result_df[TARGET_COL].values, result_df["predicted_demand"].values), 2),
        "N_rows": len(result_df),
    })
    return pd.DataFrame(rows)


# ── Save ───────────────────────────────────────────────────────────────────────
def save_outputs(model: xgb.XGBRegressor, result_df: pd.DataFrame, metrics_df: pd.DataFrame):
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(METRICS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    model_path = os.path.join(MODEL_DIR, "xgb_forecaster.json")
    model.save_model(model_path)

    forecast_path = os.path.join(DATA_DIR, "demand_forecast.csv")
    result_df.to_csv(forecast_path, index=False)

    metrics_path = os.path.join(METRICS_DIR, "forecast_metrics.csv")
    metrics_df.to_csv(metrics_path, index=False)

    print(f"  [OK] Model saved    -> {model_path}")
    print(f"  [OK] Forecasts      -> {forecast_path} ({len(result_df):,} rows)")
    print(f"  [OK] Metrics        -> {metrics_path}")


# ── Feature importance ─────────────────────────────────────────────────────────
def get_feature_importance(model: xgb.XGBRegressor) -> pd.DataFrame:
    scores = model.get_booster().get_fscore()
    df = (
        pd.DataFrame(list(scores.items()), columns=["feature_raw", "importance"])
        .sort_values("importance", ascending=False)
    )
    # Map raw feature indices back to names
    feat_map = {f"f{i}": name for i, name in enumerate(FEATURE_COLS)}
    df["Feature"] = df["feature_raw"].map(feat_map).fillna(df["feature_raw"])
    return df[["Feature", "importance"]]


# ── Master runner ──────────────────────────────────────────────────────────────
def run_forecaster(panel_df: pd.DataFrame = None) -> Tuple[xgb.XGBRegressor, pd.DataFrame, pd.DataFrame]:
    """
    Full forecaster pipeline. If panel_df is None, rebuilds features from CSVs.
    Returns (model, result_df, metrics_df).
    """
    if panel_df is None:
        print("  Loading raw data and building features...")
        products, sales, external = load_raw_data()
        panel_df = build_features(products, sales, external)

    train_df, test_df = split_data(panel_df)
    print(f"  Training XGBoost on {len(train_df):,} rows...")

    model, result_df = train_xgboost(train_df, test_df)
    metrics_df = evaluate_by_category(result_df)
    save_outputs(model, result_df, metrics_df)

    return model, result_df, metrics_df


if __name__ == "__main__":
    print("=" * 50)
    print("  Tower 1: XGBoost Demand Forecaster")
    print("=" * 50)
    model, result_df, metrics_df = run_forecaster()
    print("\n  Forecast Accuracy by Category:")
    print(metrics_df.to_string(index=False))
