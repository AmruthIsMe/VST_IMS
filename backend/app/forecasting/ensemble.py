"""
Adaptive Ensemble for VST IMS Demand Forecasting.
Combines predictions from multiple models using dynamically adjusted weights
based on recent performance (inverse-error weighting with exponential decay).
"""

import numpy as np
import pandas as pd
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.forecasting import training_progress as progress

from app.forecasting.models import (
    get_all_models,
    BaseForecaster,
    XGBoostForecaster,
    LightGBMForecaster,
    ARIMAForecaster,
    SARIMAForecaster,
    ProphetForecaster,
    HoltWintersForecaster,
)
from app.forecasting.metrics import compute_all_metrics, prediction_intervals
from app.forecasting.data_pipeline import (
    prepare_dataset,
    prepare_timeseries_for_sku,
    get_feature_columns,
)

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "trained_models"
MODELS_DIR.mkdir(exist_ok=True)

WEIGHTS_FILE = MODELS_DIR / "ensemble_weights.json"
HISTORY_FILE = MODELS_DIR / "training_history.json"


class AdaptiveEnsemble:
    """
    Ensemble forecaster that adaptively weights individual models
    based on recent prediction errors.
    """

    ML_MODELS = ("xgboost", "lightgbm")
    TS_MODELS = ("arima", "sarima", "prophet", "holt_winters")

    def __init__(self):
        self.models: dict[str, BaseForecaster] = {}
        self.weights: dict[str, float] = {}
        self.weight_history: list[dict] = []
        self.training_history: list[dict] = []
        self.is_trained = False
        self._load_history()

    def _load_history(self):
        """Load saved weights and training history."""
        if WEIGHTS_FILE.exists():
            try:
                data = json.loads(WEIGHTS_FILE.read_text())
                self.weights = data.get("weights", {})
                self.weight_history = data.get("history", [])
            except Exception:
                pass
        if HISTORY_FILE.exists():
            try:
                self.training_history = json.loads(HISTORY_FILE.read_text())
            except Exception:
                pass

    def _save_history(self):
        """Persist weights and training history."""
        WEIGHTS_FILE.write_text(json.dumps({
            "weights": self.weights,
            "history": self.weight_history[-50:],  # keep last 50
        }, indent=2, default=str))
        HISTORY_FILE.write_text(json.dumps(
            self.training_history[-100:], indent=2, default=str
        ))

    def train_all_models(
        self,
        sku_id: str = None,
        category: str = None,
        test_weeks: int = 12,
    ) -> dict:
        """
        Train all 6 models and compute ensemble weights.
        Returns per-model metrics and ensemble performance.
        """
        start_time = datetime.now()
        results = {}

        # Prepare ML dataset
        try:
            dataset = prepare_dataset(sku_id=sku_id, category=category, test_weeks=test_weeks)
        except Exception as e:
            return {"error": f"Data preparation failed: {str(e)}"}

        train_df = dataset["train"]
        test_df = dataset["test"]
        feature_cols = dataset["feature_cols"]
        sku_ids = dataset["sku_ids"]

        X_train = train_df[feature_cols].values
        y_train = train_df["target"].values
        X_test = test_df[feature_cols].values
        y_test = test_df["target"].values

        # Convert to DataFrames for model interface
        X_train_df = pd.DataFrame(X_train, columns=feature_cols)
        X_test_df = pd.DataFrame(X_test, columns=feature_cols)

        all_test_preds = {}

        # --- Train ML models (XGBoost, LightGBM) on full feature set ---
        for model_name in self.ML_MODELS:
            progress.begin_model(model_name)
            try:
                model = get_all_models()[model_name]
                train_result = model.train(X_train_df, pd.Series(y_train))
                preds = model.predict(X_test_df)

                metrics = compute_all_metrics(y_test, preds)
                model.save(sku_id or category or "global")
                self.models[model_name] = model

                all_test_preds[model_name] = preds
                results[model_name] = {
                    "status": "trained",
                    "train_result": train_result,
                    "test_metrics": metrics,
                }
                progress.complete_model(model_name, metrics={"mape": metrics["mape"], "mae": metrics["mae"], "rmse": metrics["rmse"]})
                logger.info(f"{model_name} trained — MAPE: {metrics['mape']}%")
            except Exception as e:
                logger.error(f"{model_name} training failed: {e}")
                results[model_name] = {"status": "failed", "error": str(e)}
                progress.complete_model(model_name, error=str(e))

        # --- Train time-series models on first SKU (or aggregated) ---
        representative_sku = sku_id or (sku_ids[0] if sku_ids else None)
        if representative_sku:
            try:
                ts_data = prepare_timeseries_for_sku(representative_sku)
                ts_values = ts_data["Units_Sold"]

                # Split TS data the same way
                ts_train = ts_values.iloc[:-test_weeks] if len(ts_values) > test_weeks else ts_values
                ts_actual = ts_values.iloc[-test_weeks:].values if len(ts_values) > test_weeks else ts_values.values

                for model_name in self.TS_MODELS:
                    progress.begin_model(model_name)
                    try:
                        model = get_all_models()[model_name]
                        train_result = model.train(
                            pd.DataFrame(),
                            ts_train,
                            ts=ts_train,
                            dates=ts_data.index[:len(ts_train)],
                        )

                        if model.is_trained:
                            horizon = min(test_weeks, len(ts_actual))
                            preds = model.predict(horizon=horizon)

                            if len(preds) > len(ts_actual):
                                preds = preds[:len(ts_actual)]
                            elif len(preds) < len(ts_actual):
                                ts_actual_trimmed = ts_actual[:len(preds)]
                                metrics = compute_all_metrics(ts_actual_trimmed, preds)
                            else:
                                metrics = compute_all_metrics(ts_actual, preds)

                            if len(preds) == len(ts_actual):
                                metrics = compute_all_metrics(ts_actual, preds)

                            model.save(representative_sku)
                            self.models[model_name] = model
                            all_test_preds[model_name] = preds
                            results[model_name] = {
                                "status": "trained",
                                "train_result": train_result,
                                "test_metrics": metrics,
                            }
                            progress.complete_model(model_name, metrics={"mape": metrics.get("mape", 0), "mae": metrics.get("mae", 0), "rmse": metrics.get("rmse", 0)})
                            logger.info(f"{model_name} trained — MAPE: {metrics.get('mape', 'N/A')}%")
                        else:
                            err = train_result.get("error", "Training returned untrained model")
                            results[model_name] = {"status": "failed", "error": err}
                            progress.complete_model(model_name, error=err)
                    except Exception as e:
                        logger.error(f"{model_name} training failed: {e}")
                        results[model_name] = {"status": "failed", "error": str(e)}
                        progress.complete_model(model_name, error=str(e))
            except Exception as e:
                logger.error(f"Time-series data prep failed: {e}")
                for model_name in self.TS_MODELS:
                    results[model_name] = {"status": "skipped", "error": str(e)}

        # Count actually trained models
        models_trained_count = sum(1 for r in results.values() if r.get("status") == "trained")

        if models_trained_count == 0:
            logger.error("All models failed to train. No ensemble can be built.")
            elapsed = (datetime.now() - start_time).total_seconds()
            # Record the failed attempt
            self.training_history.append({
                "date": datetime.now().isoformat(),
                "sku_id": sku_id,
                "category": category,
                "elapsed_seconds": round(elapsed, 1),
                "models_trained": 0,
                "ensemble_mape": None,
                "weights": self.weights.copy(),
                "per_model": {
                    name: {"status": r.get("status"), "error": r.get("error")}
                    for name, r in results.items()
                },
                "error": "All models failed",
            })
            self._save_history()
            return {
                "models": results,
                "ensemble": {"status": "all_failed", "error": "All 6 models failed to train. Check backend logs for details."},
                "weights": self.weights,
                "metadata": {
                    "elapsed_seconds": round(elapsed, 1),
                    "train_rows": dataset.get("train_rows", 0),
                    "test_rows": dataset.get("test_rows", 0),
                    "split_date": dataset.get("split_date", ""),
                    "n_features": len(feature_cols),
                    "sku_count": len(sku_ids),
                    "models_trained": 0,
                },
                "error": "All models failed to train. Possible causes: insufficient data, missing dependencies, or data quality issues.",
            }

        # --- Compute ensemble weights based on test performance ---
        self._compute_weights(results)

        # --- Compute ensemble prediction ---
        ensemble_metrics = self._compute_ensemble_metrics(all_test_preds, y_test, test_df)

        elapsed = (datetime.now() - start_time).total_seconds()

        # Save training record
        def _per_model_snapshot(res: dict) -> dict:
            snap = {}
            for model_name, r in res.items():
                tm = r.get("test_metrics", {}) or {}
                snap[model_name] = {
                    "status": r.get("status"),
                    "mae": tm.get("mae"),
                    "mape": tm.get("mape"),
                    "rmse": tm.get("rmse"),
                    "smape": tm.get("smape"),
                    "bias": tm.get("bias"),
                }
            return snap

        training_record = {
            "date": datetime.now().isoformat(),
            "sku_id": sku_id,
            "category": category,
            "elapsed_seconds": round(elapsed, 1),
            "models_trained": models_trained_count,
            "ensemble_mape": ensemble_metrics.get("mape"),
            "weights": self.weights.copy(),
            "per_model": _per_model_snapshot(results),
            "dataset": {
                "train_rows": dataset["train_rows"],
                "test_rows": dataset["test_rows"],
                "split_date": str(dataset.get("split_date", "")),
                "n_features": len(feature_cols),
                "sku_count": len(sku_ids),
            },
        }
        self.training_history.append(training_record)
        self.is_trained = True
        self._save_history()

        return {
            "models": results,
            "ensemble": ensemble_metrics,
            "weights": self.weights,
            "metadata": {
                "elapsed_seconds": round(elapsed, 1),
                "train_rows": dataset["train_rows"],
                "test_rows": dataset["test_rows"],
                "split_date": dataset["split_date"],
                "n_features": len(feature_cols),
                "sku_count": len(sku_ids),
            },
        }

    def train_all_models_parallel(
        self,
        sku_id: str = None,
        category: str = None,
        test_weeks: int = 12,
        max_workers: int = 4,
    ) -> dict:
        """
        Train all 6 models in parallel using ThreadPoolExecutor.
        ML models share the dataset; TS models each prepare their own data.
        Returns the same shape as train_all_models().
        """
        start_time = datetime.now()
        results = {}

        try:
            dataset = prepare_dataset(sku_id=sku_id, category=category, test_weeks=test_weeks)
        except Exception as e:
            return {"error": f"Data preparation failed: {str(e)}"}

        train_df = dataset["train"]
        test_df = dataset["test"]
        feature_cols = dataset["feature_cols"]
        sku_ids = dataset["sku_ids"]

        X_train = train_df[feature_cols].values
        y_train = train_df["target"].values
        X_test = test_df[feature_cols].values
        y_test = test_df["target"].values

        X_train_df = pd.DataFrame(X_train, columns=feature_cols)
        X_test_df = pd.DataFrame(X_test, columns=feature_cols)

        all_test_preds = {}
        representative_sku = sku_id or (sku_ids[0] if sku_ids else None)

        def train_one_ml(model_name):
            progress.begin_model(model_name)
            try:
                model = get_all_models()[model_name]
                model.train(X_train_df, pd.Series(y_train))
                preds = model.predict(X_test_df)
                metrics = compute_all_metrics(y_test, preds)
                model.save(sku_id or category or "global")
                progress.complete_model(model_name, metrics={"mape": metrics["mape"], "mae": metrics["mae"], "rmse": metrics["rmse"]})
                return model_name, {
                    "status": "trained",
                    "test_metrics": metrics,
                    "predictions": preds,
                    "_model": model,
                }
            except Exception as e:
                logger.error(f"{model_name} training failed: {e}")
                progress.complete_model(model_name, error=str(e))
                return model_name, {"status": "failed", "error": str(e)}

        def train_one_ts(model_name):
            progress.begin_model(model_name)
            try:
                ts_data = prepare_timeseries_for_sku(representative_sku)
                ts_values = ts_data["Units_Sold"]
                ts_train = ts_values.iloc[:-test_weeks] if len(ts_values) > test_weeks else ts_values
                ts_actual = ts_values.iloc[-test_weeks:].values if len(ts_values) > test_weeks else ts_values.values

                model = get_all_models()[model_name]
                model.train(pd.DataFrame(), ts_train, ts=ts_train, dates=ts_data.index[:len(ts_train)])

                if not model.is_trained:
                    err = f"{model_name} training returned untrained model"
                    progress.complete_model(model_name, error=err)
                    return model_name, {"status": "failed", "error": err}

                horizon = min(test_weeks, len(ts_actual))
                preds = model.predict(horizon=horizon)
                if len(preds) > len(ts_actual):
                    preds = preds[:len(ts_actual)]

                metrics = compute_all_metrics(ts_actual[:len(preds)], preds)
                model.save(representative_sku)
                progress.complete_model(model_name, metrics={"mape": metrics.get("mape", 0), "mae": metrics.get("mae", 0), "rmse": metrics.get("rmse", 0)})
                return model_name, {
                    "status": "trained",
                    "test_metrics": metrics,
                    "predictions": preds,
                    "_model": model,
                }
            except Exception as e:
                logger.error(f"{model_name} training failed: {e}")
                progress.complete_model(model_name, error=str(e))
                return model_name, {"status": "failed", "error": str(e)}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for name in self.ML_MODELS:
                futures[executor.submit(train_one_ml, name)] = name
            if representative_sku:
                for name in self.TS_MODELS:
                    futures[executor.submit(train_one_ts, name)] = name

            for future in as_completed(futures):
                model_name, result = future.result()
                results[model_name] = result
                if result.get("status") == "trained":
                    if "predictions" in result:
                        all_test_preds[model_name] = result.pop("predictions")
                    trained_model = result.pop("_model", None)
                    if trained_model and getattr(trained_model, "is_trained", False):
                        self.models[model_name] = trained_model

        models_trained_count = sum(1 for r in results.values() if r.get("status") == "trained")

        if models_trained_count == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            self.training_history.append({
                "date": datetime.now().isoformat(),
                "sku_id": sku_id,
                "category": category,
                "elapsed_seconds": round(elapsed, 1),
                "models_trained": 0,
                "ensemble_mape": None,
                "weights": self.weights.copy(),
                "per_model": {
                    name: {"status": r.get("status"), "error": r.get("error")}
                    for name, r in results.items()
                },
                "error": "All models failed",
            })
            self._save_history()
            return {
                "models": results,
                "ensemble": {"status": "all_failed", "error": "All 6 models failed to train."},
                "weights": self.weights,
                "metadata": {
                    "elapsed_seconds": round(elapsed, 1),
                    "train_rows": dataset.get("train_rows", 0),
                    "test_rows": dataset.get("test_rows", 0),
                    "split_date": dataset.get("split_date", ""),
                    "n_features": len(feature_cols),
                    "sku_count": len(sku_ids),
                    "models_trained": 0,
                },
                "error": "All models failed to train.",
            }

        self._compute_weights(results)
        ensemble_metrics = self._compute_ensemble_metrics(all_test_preds, y_test, test_df)
        elapsed = (datetime.now() - start_time).total_seconds()

        def _per_model_snapshot(res: dict) -> dict:
            snap = {}
            for model_name, r in res.items():
                tm = r.get("test_metrics", {}) or {}
                snap[model_name] = {
                    "status": r.get("status"),
                    "mae": tm.get("mae"),
                    "mape": tm.get("mape"),
                    "rmse": tm.get("rmse"),
                    "smape": tm.get("smape"),
                    "bias": tm.get("bias"),
                }
            return snap

        training_record = {
            "date": datetime.now().isoformat(),
            "sku_id": sku_id,
            "category": category,
            "elapsed_seconds": round(elapsed, 1),
            "models_trained": models_trained_count,
            "ensemble_mape": ensemble_metrics.get("mape"),
            "weights": self.weights.copy(),
            "per_model": _per_model_snapshot(results),
            "dataset": {
                "train_rows": dataset["train_rows"],
                "test_rows": dataset["test_rows"],
                "split_date": str(dataset.get("split_date", "")),
                "n_features": len(feature_cols),
                "sku_count": len(sku_ids),
            },
        }
        self.training_history.append(training_record)
        self.is_trained = True
        self._save_history()

        return {
            "models": results,
            "ensemble": ensemble_metrics,
            "weights": self.weights,
            "metadata": {
                "elapsed_seconds": round(elapsed, 1),
                "train_rows": dataset["train_rows"],
                "test_rows": dataset["test_rows"],
                "split_date": dataset["split_date"],
                "n_features": len(feature_cols),
                "sku_count": len(sku_ids),
            },
        }

    def _compute_weights(self, results: dict):
        """
        Compute ensemble weights using inverse-MAPE weighting.
        Models with lower error get higher weights.
        """
        errors = {}
        for model_name, result in results.items():
            if result.get("status") == "trained":
                mape_val = result.get("test_metrics", {}).get("mape", 100)
                errors[model_name] = max(mape_val, 0.1)  # avoid division by zero

        if not errors:
            # All models failed — set zero weights for all
            self.weights = {m: 0.0 for m in results}
            return

        # Inverse error weighting
        inv_errors = {m: 1.0 / e for m, e in errors.items()}
        total = sum(inv_errors.values())
        self.weights = {m: round(w / total, 4) for m, w in inv_errors.items()}

        # Add zero weight for failed models
        for model_name in results:
            if model_name not in self.weights:
                self.weights[model_name] = 0.0

        # Record weight history
        self.weight_history.append({
            "date": datetime.now().isoformat(),
            "weights": self.weights.copy(),
        })

    def _compute_ensemble_metrics(
        self,
        all_preds: dict[str, np.ndarray],
        y_test: np.ndarray,
        test_df: pd.DataFrame = None,
    ) -> dict:
        """Compute weighted ensemble prediction and its metrics."""
        if not all_preds:
            return {"status": "no_predictions"}

        # Use ML model predictions (which align with test_df rows)
        ml_preds = {k: v for k, v in all_preds.items() if k in self.ML_MODELS}
        if not ml_preds:
            return {"status": "no_ml_predictions"}

        # Weighted average
        ensemble_pred = np.zeros(len(y_test))
        total_weight = 0
        for model_name, preds in ml_preds.items():
            w = self.weights.get(model_name, 0)
            if len(preds) == len(y_test):
                ensemble_pred += w * preds
                total_weight += w

        if total_weight > 0:
            ensemble_pred /= total_weight

        metrics = compute_all_metrics(y_test, ensemble_pred)

        # Prediction intervals
        residual_std = float(np.std(y_test - ensemble_pred))
        lower, upper = prediction_intervals(ensemble_pred, residual_std)
        metrics["coverage"] = round(
            float(np.mean((y_test >= lower) & (y_test <= upper)) * 100), 2
        )

        metrics["strategy"] = "weighted_average"
        return metrics

    def predict(
        self,
        X: pd.DataFrame = None,
        horizon: int = 12,
        model_name: str = None,
    ) -> dict:
        """
        Generate predictions using ensemble or a specific model.
        Returns predictions with confidence intervals.
        """
        if model_name and model_name in self.models:
            model = self.models[model_name]
            if model_name in self.ML_MODELS:
                preds = model.predict(X)
            else:
                preds = model.predict(horizon=horizon)
            return {
                "model": model_name,
                "predictions": preds.tolist(),
                "weight": self.weights.get(model_name, 0),
            }

        # Ensemble prediction
        all_preds = {}
        for name, model in self.models.items():
            try:
                if name in self.ML_MODELS and X is not None:
                    preds = model.predict(X)
                else:
                    preds = model.predict(horizon=horizon)
                all_preds[name] = preds
            except Exception as e:
                logger.warning(f"Prediction failed for {name}: {e}")

        if not all_preds:
            return {"error": "No models available for prediction"}

        # Find common length across ML models
        ml_preds = {k: v for k, v in all_preds.items() if k in self.ML_MODELS}
        if ml_preds:
            length = len(next(iter(ml_preds.values())))
            ensemble_pred = np.zeros(length)
            total_weight = 0
            for name, preds in ml_preds.items():
                w = self.weights.get(name, 0)
                if len(preds) == length:
                    ensemble_pred += w * preds
                    total_weight += w
            if total_weight > 0:
                ensemble_pred /= total_weight
        else:
            # Fallback to TS models
            ts_preds = {k: v for k, v in all_preds.items() if k in self.TS_MODELS}
            length = min(len(v) for v in ts_preds.values()) if ts_preds else horizon
            ensemble_pred = np.mean(
                [v[:length] for v in ts_preds.values()], axis=0
            )

        # Generate prediction intervals
        all_pred_arrays = [v[:len(ensemble_pred)] for v in all_preds.values() if len(v) >= len(ensemble_pred)]
        if len(all_pred_arrays) > 1:
            model_std = np.std(all_pred_arrays, axis=0)
        else:
            model_std = np.ones(len(ensemble_pred)) * np.mean(ensemble_pred) * 0.15

        lower = np.maximum(ensemble_pred - 1.96 * model_std, 0)
        upper = ensemble_pred + 1.96 * model_std

        return {
            "ensemble": ensemble_pred.tolist(),
            "lower_bound": lower.tolist(),
            "upper_bound": upper.tolist(),
            "individual_models": {
                name: preds.tolist() for name, preds in all_preds.items()
            },
            "weights": self.weights,
        }

    def get_comparison(self, y_test: np.ndarray, test_preds: dict) -> dict:
        """Compare all models side-by-side on test data."""
        comparison = []
        for model_name, preds in test_preds.items():
            actual = y_test[:len(preds)]
            metrics = compute_all_metrics(actual, preds)
            metrics["model"] = model_name
            metrics["weight"] = self.weights.get(model_name, 0)
            comparison.append(metrics)

        # Sort by MAPE (best first)
        comparison.sort(key=lambda x: x.get("mape", 999))

        best_model = comparison[0]["model"] if comparison else None
        return {
            "models": comparison,
            "best_model": best_model,
            "recommendation": self._generate_recommendation(comparison),
        }

    def _generate_recommendation(self, comparison: list[dict]) -> str:
        """Generate a human-readable recommendation based on model comparison."""
        if not comparison:
            return "No models trained yet. Run training first."

        best = comparison[0]
        worst = comparison[-1] if len(comparison) > 1 else best

        rec = f"🏆 **{best['model'].upper()}** is the best performer with MAPE of {best['mape']}%. "
        if best["bias"] > 5:
            rec += f"⚠️ It tends to over-forecast by {best['bias']}%. "
        elif best["bias"] < -5:
            rec += f"⚠️ It tends to under-forecast by {abs(best['bias'])}%. "

        if len(comparison) > 1:
            rec += f"The ensemble combines all models with adaptive weights for more robust predictions. "
            rec += f"Worst performer: {worst['model']} (MAPE: {worst['mape']}%)."

        return rec

    def get_weight_history(self) -> list[dict]:
        """Return the evolution of ensemble weights over time."""
        return self.weight_history

    def get_training_history(self) -> list[dict]:
        """Return history of all training sessions."""
        return self.training_history


# Singleton instance
_ensemble_instance: Optional[AdaptiveEnsemble] = None


def get_ensemble() -> AdaptiveEnsemble:
    """Get or create the singleton ensemble instance."""
    global _ensemble_instance
    if _ensemble_instance is None:
        _ensemble_instance = AdaptiveEnsemble()
    return _ensemble_instance
