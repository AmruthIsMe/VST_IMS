"""
Forecast Evaluation + RL Feedback Bridge.

After each SAP sync brings NEW actuals into the database:
1. Backfills actual_demand on previously stored forecast_predictions.
2. Feeds every (actual, predicted) pair into the UCB1 BanditWeightOptimizer,
   producing RL-adjusted ensemble weights (error detection signal).
3. Can regenerate a fresh 12-week forward forecast per SKU so that the next
   sync cycle has predictions to evaluate against (continuous loop).
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text as sql_text

from app.models import ForecastPrediction
from app.forecasting.data_pipeline import load_sales_data
from app.forecasting.rl_feedback import get_feedback_loop

logger = logging.getLogger(__name__)

MODEL_NAMES = ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]


def _week_monday(d):
    d = pd.Timestamp(d)
    return (d - pd.Timedelta(days=d.weekday())).normalize()


def _new_pred_row(**fields) -> dict:
    import uuid
    row = {
        'id': uuid.uuid4(),
        "created_at": datetime.utcnow(),
        "actual_demand": None,
    }
    row.update(fields)
    return row


def evaluate_and_update_rl(db) -> dict:
    """
    Compare stored predictions against newly synced actuals and update
    the RL bandit weights. Returns a summary dict for the sync report.
    """
    pending = db.query(ForecastPrediction).filter(
        ForecastPrediction.actual_demand.is_(None),
        ForecastPrediction.model_name != "ensemble",
    ).all()

    summary = {
        "status": "completed",
        "pending_predictions": len(pending),
        "actuals_matched": 0,
        "pairs_evaluated": 0,
        "models_updated": [],
        "rl_weights": {},
        "blended_weights": {},
        "message": "",
    }
    if not pending:
        summary["message"] = "No unevaluated stored predictions found (run a retrain first)."
        return summary

    sales_df = load_sales_data(db)
    sales_df["week"] = sales_df["Date"].apply(_week_monday)
    weekly_actuals = {
        (str(sku), week.to_pydatetime().date()): float(units)
        for (sku, week), units in sales_df.groupby(["SKU_ID", "week"])["Units_Sold"].sum().items()
    }

    pairs_by_model = {m: [] for m in MODEL_NAMES}
    matched_keys = set()
    for pred in pending:
        key = (pred.sku_id, pred.forecast_date)
        actual = weekly_actuals.get(key)
        if actual is None:
            continue
        pred.actual_demand = round(actual, 2)
        matched_keys.add(key)
        if pred.model_name in pairs_by_model:
            pairs_by_model[pred.model_name].append((actual, pred.predicted_demand))

    summary["actuals_matched"] = len(matched_keys)
    usable = {m: p for m, p in pairs_by_model.items() if p}
    if not usable:
        db.commit()
        summary["message"] = "Stored predictions exist but none overlap with available actuals yet."
        return summary

    feedback = get_feedback_loop([m for m in MODEL_NAMES])
    feedback.optimizer.batch_update(usable)
    rl_weights = feedback.optimizer.get_weights()
    summary["pairs_evaluated"] = sum(len(p) for p in usable.values())
    summary["models_updated"] = list(usable.keys())
    summary["rl_weights"] = rl_weights

    from app.forecasting.ensemble import get_ensemble
    ensemble = get_ensemble()
    blended = {}
    for m in MODEL_NAMES:
        base_w = ensemble.weights.get(m, 0.0)
        rl_w = rl_weights.get(m, 0.0)
        blended[m] = round(0.7 * base_w + 0.3 * rl_w, 4)
    total = sum(blended.values()) or 1.0
    blended = {m: round(w / total, 4) for m, w in blended.items()}
    ensemble.weights.update(blended)
    ensemble._save_history()
    summary["blended_weights"] = ensemble.weights.copy()
    summary["message"] = (
        f"RL loop updated: {summary['pairs_evaluated']} prediction/actual pairs "
        f"across {len(usable)} models fed to UCB1 bandit."
    )

    db.commit()
    return summary


def regenerate_forecasts(db, horizon_weeks: int = 12) -> dict:
    """
    Produce a fresh forward-looking forecast for every active SKU using the
    current trained ensemble and persist it to forecast_predictions
    (replacing previous rows). These become the baseline evaluated at the
    NEXT sync — closing the continuous learning loop.
    """
    from app.forecasting.ensemble import get_ensemble

    ensemble = get_ensemble()
    trained = {n: m for n, m in ensemble.models.items() if getattr(m, "is_trained", False)}
    if not trained:
        return {"status": "skipped", "message": "No trained models available.", "rows_stored": 0}

    sales_df = load_sales_data(db)
    sales_df["Date"] = pd.to_datetime(sales_df["Date"])
    global_last = sales_df["Date"].max()

    ts_models = [n for n in ("arima", "sarima", "prophet", "holt_winters") if n in trained]
    ml_models = [n for n in ("xgboost", "lightgbm") if n in trained]

    rows = []
    sku_count = 0
    for sku, grp in sales_df.groupby("SKU_ID"):
        series = grp.sort_values("Date")["Units_Sold"].astype(float)
        if len(series) < 8:
            continue
        values = series.values
        recent4 = values[-4:].mean()
        prev4 = values[-8:-4].mean()
        trend_ratio = float(np.clip(recent4 / prev4, 0.5, 2.0)) if prev4 > 0 else 1.0
        baseline = float(recent4 * trend_ratio)
        resid_std = float(max(values[-13:].std() if len(values) >= 13 else values.std(), 1.0))

        model_preds = {}
        for name in ts_models:
            try:
                model_preds[name] = np.asarray(
                    trained[name].predict(horizon=horizon_weeks), dtype=float
                )
            except Exception:
                continue
        for name in ml_models:
            model_preds[name] = np.full(horizon_weeks, baseline)

        if not model_preds:
            continue

        weights = {m: ensemble.weights.get(m, 0.0) for m in model_preds}
        w_total = sum(weights.values())
        if w_total > 0:
            ens = sum(model_preds[m] * w for m, w in weights.items()) / w_total
        else:
            ens = np.mean(list(model_preds.values()), axis=0)

        model_preds["ensemble"] = ens
        sku_count += 1

        for m_name, preds in model_preds.items():
            for wk in range(horizon_weeks):
                fdate = (_week_monday(global_last) + pd.Timedelta(weeks=wk + 1)).date()
                val = float(max(preds[wk], 0.0))
                z = 1.96 * np.sqrt((wk + 1) / 4.0)
                rows.append(_new_pred_row(
                    model_name=m_name,
                    sku_id=sku,
                    forecast_date=fdate,
                    predicted_demand=round(val, 1),
                    lower_bound=round(max(val - z * resid_std, 0.0), 1),
                    upper_bound=round(val + z * resid_std, 1),
                ))

    if not rows:
        return {"status": "skipped", "message": "No SKUs had enough history.", "rows_stored": 0}

    db.execute(sql_text("DELETE FROM forecast_predictions"))
    db.bulk_insert_mappings(ForecastPrediction, rows)
    db.commit()
    first_date = min(r["forecast_date"] for r in rows)
    last_date = max(r["forecast_date"] for r in rows)
    return {
        "status": "completed",
        "skus_forecasted": sku_count,
        "horizon_weeks": horizon_weeks,
        "rows_stored": len(rows),
        "forecast_window": f"{first_date} .. {last_date}",
        "message": f"Fresh {horizon_weeks}-week forecast stored for {sku_count} SKUs.",
    }
