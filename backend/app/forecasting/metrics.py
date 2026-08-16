"""
Error Metrics Module for VST IMS Demand Forecasting.
Computes MAE, MAPE, RMSE, SMAPE, Bias, and Coverage for model evaluation.
"""

import numpy as np
import pandas as pd
from typing import Optional


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(actual - predicted)))


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error. Skips zeros in actual."""
    mask = actual != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Symmetric Mean Absolute Percentage Error. Handles zeros gracefully."""
    denominator = np.abs(actual) + np.abs(predicted)
    mask = denominator != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(2 * np.abs(actual[mask] - predicted[mask]) / denominator[mask]) * 100)


def bias(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Forecast Bias. Positive = over-forecasting, Negative = under-forecasting.
    Expressed as percentage of mean actual.
    """
    mean_actual = np.mean(actual)
    if mean_actual == 0:
        return 0.0
    return float((np.mean(predicted) - np.mean(actual)) / mean_actual * 100)


def coverage(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> float:
    """Percentage of actuals falling within the prediction interval [lower, upper]."""
    within = (actual >= lower) & (actual <= upper)
    return float(np.mean(within) * 100)


def compute_all_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    lower_bound: Optional[np.ndarray] = None,
    upper_bound: Optional[np.ndarray] = None,
) -> dict:
    """Compute all error metrics in one call."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    result = {
        "mae": round(mae(actual, predicted), 4),
        "mape": round(mape(actual, predicted), 2),
        "rmse": round(rmse(actual, predicted), 4),
        "smape": round(smape(actual, predicted), 2),
        "bias": round(bias(actual, predicted), 2),
        "n_samples": len(actual),
    }

    if lower_bound is not None and upper_bound is not None:
        lower_bound = np.asarray(lower_bound, dtype=float)
        upper_bound = np.asarray(upper_bound, dtype=float)
        result["coverage"] = round(coverage(actual, lower_bound, upper_bound), 2)

    return result


def compute_metrics_by_group(
    df: pd.DataFrame,
    actual_col: str,
    predicted_col: str,
    group_col: str,
) -> list[dict]:
    """Compute metrics grouped by a column (e.g., Category, SKU_ID)."""
    results = []
    for group_name, group_df in df.groupby(group_col):
        actual = group_df[actual_col].values
        predicted = group_df[predicted_col].values
        metrics = compute_all_metrics(actual, predicted)
        metrics[group_col] = group_name
        results.append(metrics)
    return sorted(results, key=lambda x: x["mape"])


def prediction_intervals(
    predicted: np.ndarray,
    residual_std: float,
    confidence: float = 0.95,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate prediction intervals from predicted values and residual standard deviation.
    Uses normal approximation.
    """
    from scipy.stats import norm
    z = norm.ppf(1 - (1 - confidence) / 2)
    lower = predicted - z * residual_std
    upper = predicted + z * residual_std
    return np.maximum(lower, 0), upper


def error_improvement_over_time(
    error_history: list[dict],
) -> dict:
    """
    Track how errors have changed over successive re-training cycles.
    Input: list of dicts with keys 'date', 'model', 'mape', 'mae', 'rmse'
    """
    if not error_history:
        return {"trend": "no_data", "improvement_pct": 0}

    df = pd.DataFrame(error_history)
    if len(df) < 2:
        return {"trend": "insufficient_data", "improvement_pct": 0}

    first_mape = df["mape"].iloc[0]
    last_mape = df["mape"].iloc[-1]

    if first_mape == 0:
        return {"trend": "stable", "improvement_pct": 0}

    improvement = (first_mape - last_mape) / first_mape * 100

    return {
        "trend": "improving" if improvement > 0 else "degrading",
        "improvement_pct": round(improvement, 2),
        "first_mape": first_mape,
        "latest_mape": last_mape,
        "n_cycles": len(df),
    }
