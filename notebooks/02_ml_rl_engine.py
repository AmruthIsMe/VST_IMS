"""
02_ml_rl_engine.py — Phase 2 Master Orchestrator

End-to-end pipeline:
  Step 1: Build feature dataset from Phase 1 CSVs
  Step 2: Train XGBoost demand forecaster (Tower 1)
  Step 3: Train PPO RL inventory agent (Tower 2)
  Step 4: Generate all Phase 2 visualisations (charts 08-13)
  Step 5: Print final summary dashboard

Run from d:\vst:
  python notebooks/02_ml_rl_engine.py
"""

import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

# ── VST banner ─────────────────────────────────────────────────────────────────
BANNER = """
===========================================================
  VST Tillers & Tractors -- Supply Chain Intelligence
  Phase 2: ML/RL Engine
  Tower 1: XGBoost Demand Forecaster
  Tower 2: PPO Reinforcement Learning Agent
===========================================================
"""

def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def main():
    print(BANNER)
    start_all = time.time()

    # ── Step 1: Feature Engineering ──────────────────────────────────────────
    section("Step 1/4 -- Feature Engineering")
    from src.feature_engineering import (
        build_features, load_raw_data, split_data, FEATURE_COLS
    )

    products, sales, external = load_raw_data()
    panel_df = build_features(products, sales, external)
    train_df, test_df = split_data(panel_df)

    print(f"  Train rows : {len(train_df):,} (2022-2024)")
    print(f"  Test rows  : {len(test_df):,}  (2025)")
    print(f"  Features   : {len(FEATURE_COLS)}")

    # ── Step 2: Tower 1 — XGBoost Forecaster ─────────────────────────────────
    section("Step 2/4 -- Tower 1: XGBoost Demand Forecaster")
    t0 = time.time()
    from src.forecaster import run_forecaster, get_feature_importance

    model_xgb, forecast_df, metrics_df = run_forecaster(panel_df)
    fi_df = get_feature_importance(model_xgb)

    print(f"\n  Forecast Accuracy (Test 2025):")
    print(metrics_df.to_string(index=False))
    print(f"\n  Training time: {time.time()-t0:.1f}s")

    # Validation gate
    overall_mape = metrics_df[metrics_df["Category"] == "OVERALL"]["MAPE_%"].values[0]
    if overall_mape < 25:
        print(f"  [PASS] MAPE = {overall_mape:.1f}% (target < 25%)")
    else:
        print(f"  [WARN] MAPE = {overall_mape:.1f}% > 25%. Consider tuning hyperparams.")

    # ── Step 3: Tower 2 — RL Agent ────────────────────────────────────────────
    section("Step 3/4 -- Tower 2: PPO Reinforcement Learning Agent")
    t0 = time.time()
    from src.rl_agent import run_rl_agent
    from src.inventory_env import build_env_from_data

    model_rl, rl_metrics, heuristic_metrics, callback = run_rl_agent(run_training=True)
    print(f"\n  Training time: {time.time()-t0:.1f}s")

    print(f"\n  --- Results ---")
    print(f"  {'Metric':<25} {'RL Agent':>12} {'Heuristic':>12}")
    print(f"  {'-'*50}")
    for key, label in [
        ("mean_fill_rate", "Fill Rate"),
        ("mean_reward",    "Avg Reward"),
        ("mean_stockouts", "Stockout Weeks"),
    ]:
        rv = rl_metrics[key]
        hv = heuristic_metrics[key]
        fmt = "{:.1%}" if "fill" in key else "{:.2f}"
        print(f"  {label:<25} {fmt.format(rv):>12} {fmt.format(hv):>12}")

    improvement = (rl_metrics["mean_fill_rate"] - heuristic_metrics["mean_fill_rate"]) * 100
    print(f"\n  Fill Rate Improvement vs Heuristic: {improvement:+.2f} pp")

    # ── Step 4: Phase 2 Visualisations ───────────────────────────────────────
    section("Step 4/4 -- Generating Phase 2 Charts")
    from src.phase2_visualizations import generate_all_phase2_charts

    eval_env = build_env_from_data(train_mode=False)
    training_rewards = callback.rewards if callback.rewards else [0.0, 1.0, 2.0]

    generate_all_phase2_charts(
        forecast_df       = forecast_df,
        fi_df             = fi_df,
        training_rewards  = training_rewards,
        rl_metrics        = rl_metrics,
        heuristic_metrics = heuristic_metrics,
        model             = model_rl,
        env               = eval_env,
    )

    # ── Final Summary ─────────────────────────────────────────────────────────
    elapsed = time.time() - start_all
    section("Phase 2 Complete!")

    print(f"""
  Outputs generated:
  ------------------
  data/features_panel.csv         ({len(panel_df):,} rows, {len(FEATURE_COLS)} features)
  data/demand_forecast.csv        ({len(forecast_df):,} rows, 2025 predictions)
  models/xgb_forecaster.json      (trained XGBoost model)
  models/ppo_vst_inventory.zip    (trained PPO policy)
  output/metrics/forecast_metrics.csv
  output/metrics/rl_vs_heuristic.csv
  output/metrics/training_curve.csv
  output/charts/08_forecast_vs_actual.png
  output/charts/09_feature_importance.png
  output/charts/10_rl_training_curve.png
  output/charts/11_rl_vs_heuristic.png
  output/charts/12_policy_heatmap.png
  output/charts/13_rl_whatif_updated.png

  Key Metrics:
  ------------
  XGBoost MAPE (overall):   {overall_mape:.1f}%
  RL Fill Rate:             {rl_metrics['mean_fill_rate']:.1%}
  Heuristic Fill Rate:      {heuristic_metrics['mean_fill_rate']:.1%}
  Improvement:              {improvement:+.2f} pp

  Total runtime: {elapsed:.0f}s
  Dashboard:     http://localhost:8765/vst_inventory_dashboard.html
  Next step:     Phase 3 - Jupyter Notebook Walkthrough
""")


if __name__ == "__main__":
    main()
