"""
Forecasting Models for VST IMS.
Six individual models with a common interface for training, prediction, and serialization.
"""

import numpy as np
import pandas as pd
import logging
import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "trained_models"
MODELS_DIR.mkdir(exist_ok=True)


class BaseForecaster(ABC):
    """Common interface for all forecasting models."""

    def __init__(self, name: str, model_type: str):
        self.name = name
        self.model_type = model_type
        self.model = None
        self.is_trained = False
        self.train_date = None
        self.params = {}

    @abstractmethod
    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        """Train the model. Returns training metrics."""
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame, **kwargs) -> np.ndarray:
        """Generate predictions."""
        pass

    def save(self, sku_id: str = "global"):
        """Persist model to disk."""
        import joblib
        path = MODELS_DIR / f"{self.name}_{sku_id}.joblib"
        joblib.dump({"model": self.model, "params": self.params, "train_date": self.train_date}, path)
        return str(path)

    def load(self, sku_id: str = "global") -> bool:
        """Load model from disk."""
        import joblib
        path = MODELS_DIR / f"{self.name}_{sku_id}.joblib"
        if path.exists():
            data = joblib.load(path)
            self.model = data["model"]
            self.params = data.get("params", {})
            self.train_date = data.get("train_date")
            self.is_trained = True
            return True
        return False

    def get_params(self) -> dict:
        return self.params


# ──────────────────────────────────────────────────────────────────────
# 1. XGBoost
# ──────────────────────────────────────────────────────────────────────
class XGBoostForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("xgboost", "gradient_boosting")
        self.params = {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 3,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
        }

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        from xgboost import XGBRegressor
        self.model = XGBRegressor(
            **self.params,
            random_state=42,
            verbosity=0,
            tree_method="hist",
        )
        self.model.fit(X, y, eval_set=[(X, y)], verbose=False)
        self.is_trained = True
        self.train_date = pd.Timestamp.now().isoformat()

        preds = self.model.predict(X)
        train_mae = float(np.mean(np.abs(y - preds)))
        return {"train_mae": train_mae, "n_features": X.shape[1]}

    def predict(self, X: pd.DataFrame, **kwargs) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("XGBoost model not trained.")
        preds = self.model.predict(X)
        return np.maximum(preds, 0)  # demand can't be negative

    def get_feature_importance(self) -> dict:
        if self.model is None:
            return {}
        importance = self.model.feature_importances_
        if hasattr(self.model, "feature_names_in_"):
            names = self.model.feature_names_in_
        else:
            names = [f"f{i}" for i in range(len(importance))]
        return dict(sorted(zip(names, importance.tolist()), key=lambda x: -x[1])[:15])


# ──────────────────────────────────────────────────────────────────────
# 2. LightGBM
# ──────────────────────────────────────────────────────────────────────
class LightGBMForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("lightgbm", "gradient_boosting")
        self.params = {
            "n_estimators": 300,
            "max_depth": 7,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 10,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "num_leaves": 63,
        }

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        from lightgbm import LGBMRegressor
        self.model = LGBMRegressor(
            **self.params,
            random_state=42,
            verbose=-1,
        )
        self.model.fit(X, y)
        self.is_trained = True
        self.train_date = pd.Timestamp.now().isoformat()

        preds = self.model.predict(X)
        train_mae = float(np.mean(np.abs(y - preds)))
        return {"train_mae": train_mae, "n_features": X.shape[1]}

    def predict(self, X: pd.DataFrame, **kwargs) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("LightGBM model not trained.")
        preds = self.model.predict(X)
        return np.maximum(preds, 0)


# ──────────────────────────────────────────────────────────────────────
# 3. ARIMA
# ──────────────────────────────────────────────────────────────────────
class ARIMAForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("arima", "time_series")
        self.params = {"order": (2, 1, 2)}

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        """
        For ARIMA, X is ignored. We train on the raw time-series y.
        Pass ts (DatetimeIndex series) via kwargs['ts'] if available.
        """
        from statsmodels.tsa.arima.model import ARIMA

        ts = kwargs.get("ts", y)
        try:
            model = ARIMA(ts.values.astype(float), order=self.params["order"])
            self.model = model.fit()
            self.is_trained = True
            self.train_date = pd.Timestamp.now().isoformat()

            fitted = self.model.fittedvalues
            train_mae = float(np.mean(np.abs(ts.values[1:] - fitted[1:])))
            return {"train_mae": train_mae, "aic": float(self.model.aic)}
        except Exception as e:
            logger.warning(f"ARIMA training failed: {e}")
            self.is_trained = False
            return {"error": str(e)}

    def predict(self, X: pd.DataFrame = None, **kwargs) -> np.ndarray:
        horizon = kwargs.get("horizon", 12)
        if not self.is_trained or self.model is None:
            return np.zeros(horizon)
        try:
            forecast = self.model.forecast(steps=horizon)
            return np.maximum(forecast, 0)
        except Exception:
            return np.zeros(horizon)


# ──────────────────────────────────────────────────────────────────────
# 4. SARIMA
# ──────────────────────────────────────────────────────────────────────
class SARIMAForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("sarima", "time_series")
        self.params = {
            "order": (1, 1, 1),
            "seasonal_order": (1, 1, 1, 52),  # Weekly seasonality
        }

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        ts = kwargs.get("ts", y)
        try:
            # Use shorter seasonal period for stability
            seasonal_order = self.params["seasonal_order"]
            if len(ts) < seasonal_order[3] * 2:
                seasonal_order = (1, 0, 1, 13)  # Quarterly if not enough data

            model = SARIMAX(
                ts.values.astype(float),
                order=self.params["order"],
                seasonal_order=seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            self.model = model.fit(disp=False, maxiter=100)
            self.is_trained = True
            self.train_date = pd.Timestamp.now().isoformat()

            fitted = self.model.fittedvalues
            valid_idx = min(seasonal_order[3], len(ts) - 1)
            train_mae = float(np.mean(np.abs(ts.values[valid_idx:] - fitted[valid_idx:])))
            return {"train_mae": train_mae, "aic": float(self.model.aic)}
        except Exception as e:
            logger.warning(f"SARIMA training failed: {e}")
            self.is_trained = False
            return {"error": str(e)}

    def predict(self, X: pd.DataFrame = None, **kwargs) -> np.ndarray:
        horizon = kwargs.get("horizon", 12)
        if not self.is_trained or self.model is None:
            return np.zeros(horizon)
        try:
            forecast = self.model.forecast(steps=horizon)
            return np.maximum(forecast, 0)
        except Exception:
            return np.zeros(horizon)


# ──────────────────────────────────────────────────────────────────────
# 5. Prophet
# ──────────────────────────────────────────────────────────────────────
class ProphetForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("prophet", "additive")
        self.params = {
            "changepoint_prior_scale": 0.05,
            "seasonality_prior_scale": 10,
            "yearly_seasonality": True,
            "weekly_seasonality": False,
        }

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        from prophet import Prophet

        ts = kwargs.get("ts", None)
        if ts is not None and hasattr(ts, "index") and hasattr(ts.index, "to_series"):
            prophet_df = pd.DataFrame({
                "ds": ts.index.to_series().reset_index(drop=True),
                "y": ts.values.flatten(),
            })
        else:
            dates = kwargs.get("dates", pd.date_range("2022-01-03", periods=len(y), freq="W-MON"))
            prophet_df = pd.DataFrame({"ds": dates, "y": y.values})

        self.model = Prophet(
            changepoint_prior_scale=self.params["changepoint_prior_scale"],
            seasonality_prior_scale=self.params["seasonality_prior_scale"],
            yearly_seasonality=self.params["yearly_seasonality"],
            weekly_seasonality=self.params["weekly_seasonality"],
        )
        self.model.add_seasonality(name="monsoon", period=26, fourier_order=5)
        self.model.fit(prophet_df)

        self.is_trained = True
        self.train_date = pd.Timestamp.now().isoformat()

        fitted = self.model.predict(prophet_df)
        train_mae = float(np.mean(np.abs(prophet_df["y"].values - fitted["yhat"].values)))
        return {"train_mae": train_mae}

    def predict(self, X: pd.DataFrame = None, **kwargs) -> np.ndarray:
        horizon = kwargs.get("horizon", 12)
        if not self.is_trained or self.model is None:
            return np.zeros(horizon)
        try:
            future = self.model.make_future_dataframe(periods=horizon, freq="W-MON")
            forecast = self.model.predict(future)
            preds = forecast["yhat"].values[-horizon:]
            return np.maximum(preds, 0)
        except Exception:
            return np.zeros(horizon)


# ──────────────────────────────────────────────────────────────────────
# 6. Holt-Winters (Exponential Smoothing)
# ──────────────────────────────────────────────────────────────────────
class HoltWintersForecaster(BaseForecaster):
    def __init__(self):
        super().__init__("holt_winters", "exponential_smoothing")
        self.params = {
            "seasonal_periods": 52,
            "trend": "add",
            "seasonal": "add",
        }

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        ts = kwargs.get("ts", y)
        values = ts.values.astype(float).flatten()

        # Adjust seasonal periods if not enough data
        sp = self.params["seasonal_periods"]
        if len(values) < sp * 2:
            sp = min(13, len(values) // 2)
            if sp < 2:
                sp = None

        try:
            if sp and sp >= 2:
                model = ExponentialSmoothing(
                    values,
                    trend=self.params["trend"],
                    seasonal=self.params["seasonal"],
                    seasonal_periods=sp,
                )
            else:
                model = ExponentialSmoothing(
                    values,
                    trend=self.params["trend"],
                    seasonal=None,
                )

            self.model = model.fit(optimized=True)
            self.is_trained = True
            self.train_date = pd.Timestamp.now().isoformat()

            fitted = self.model.fittedvalues
            start = sp if sp else 1
            train_mae = float(np.mean(np.abs(values[start:] - fitted[start:])))
            return {"train_mae": train_mae}
        except Exception as e:
            logger.warning(f"Holt-Winters training failed: {e}")
            self.is_trained = False
            return {"error": str(e)}

    def predict(self, X: pd.DataFrame = None, **kwargs) -> np.ndarray:
        horizon = kwargs.get("horizon", 12)
        if not self.is_trained or self.model is None:
            return np.zeros(horizon)
        try:
            forecast = self.model.forecast(horizon)
            return np.maximum(forecast, 0)
        except Exception:
            return np.zeros(horizon)


# ──────────────────────────────────────────────────────────────────────
# Model Registry
# ──────────────────────────────────────────────────────────────────────
MODEL_REGISTRY = {
    "xgboost": XGBoostForecaster,
    "lightgbm": LightGBMForecaster,
    "arima": ARIMAForecaster,
    "sarima": SARIMAForecaster,
    "prophet": ProphetForecaster,
    "holt_winters": HoltWintersForecaster,
}


def get_all_models() -> dict[str, BaseForecaster]:
    """Instantiate all registered models."""
    return {name: cls() for name, cls in MODEL_REGISTRY.items()}


def get_model(name: str) -> BaseForecaster:
    """Instantiate a specific model by name."""
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model: {name}. Available: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[name]()
