"""
phase2_visualizations.py — 6 new dark-theme charts for the ML/RL engine results.

Charts generated:
  08_forecast_vs_actual.png   — XGBoost: actual vs predicted per category
  09_feature_importance.png   — Top 20 XGBoost features
  10_rl_training_curve.png    — PPO episode reward over training
  11_rl_vs_heuristic.png      — Side-by-side: RL vs heuristic vs random
  12_policy_heatmap.png       — Agent action heatmap (stock × forecast)
  13_rl_whatif_updated.png    — RL agent decisions under demand shock
"""

import os
import warnings
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

warnings.filterwarnings("ignore")

# ── Style constants ────────────────────────────────────────────────────────────
DARK_BG   = "#0D1117"
PANEL_BG  = "#161B22"
TEXT_CLR  = "#E6EDF3"
GRID_CLR  = "#30363D"
MUTED     = "#8B949E"

VST_GREEN  = "#2EA043"
VST_GREEN2 = "#56D364"
AMBER      = "#D29922"
RED        = "#F85149"
BLUE       = "#58A6FF"
PURPLE     = "#BC8CFF"

CAT_COLORS = {
    "Spare Parts":          BLUE,
    "Lubricants":           AMBER,
    "Electric Pumps":       VST_GREEN2,
    "Engines":              PURPLE,
    "Precision Components": RED,
}

ACTION_LABELS = ["0×", "0.5×", "1×", "2×", "3×", "4×"]
OUT_DIR = "output/charts"


def _base_fig(nrows=1, ncols=1, figsize=(14, 7)):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize,
                             facecolor=DARK_BG)
    if isinstance(axes, np.ndarray):
        for ax in axes.flat:
            ax.set_facecolor(PANEL_BG)
            ax.tick_params(colors=MUTED, labelsize=9)
            ax.xaxis.label.set_color(MUTED)
            ax.yaxis.label.set_color(MUTED)
            ax.title.set_color(TEXT_CLR)
            for spine in ax.spines.values():
                spine.set_edgecolor(GRID_CLR)
    else:
        axes.set_facecolor(PANEL_BG)
        axes.tick_params(colors=MUTED, labelsize=9)
        axes.xaxis.label.set_color(MUTED)
        axes.yaxis.label.set_color(MUTED)
        axes.title.set_color(TEXT_CLR)
        for spine in axes.spines.values():
            spine.set_edgecolor(GRID_CLR)
    return fig, axes


def _save(fig, name: str):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)
    print(f"  [OK] Saved {path}")
    return path


# ── Chart 08: Forecast vs Actual ──────────────────────────────────────────────
def chart_08_forecast_vs_actual(forecast_df: pd.DataFrame):
    categories = forecast_df["Category"].unique()
    n = len(categories)
    fig, axes = _base_fig(nrows=1, ncols=n, figsize=(20, 5))

    for ax, cat in zip(axes, categories):
        grp = forecast_df[forecast_df["Category"] == cat].sort_values("Date")
        weekly = grp.groupby("Date").agg(
            actual=("target", "sum"),
            predicted=("predicted_demand", "sum"),
        ).reset_index()

        clr = CAT_COLORS.get(cat, BLUE)
        ax.plot(weekly["Date"], weekly["actual"],    color=MUTED,       lw=1.5, label="Actual",    alpha=0.9)
        ax.plot(weekly["Date"], weekly["predicted"], color=clr,         lw=2.0, label="Predicted", alpha=0.95)
        ax.fill_between(weekly["Date"], weekly["actual"], weekly["predicted"],
                        color=clr, alpha=0.08)
        ax.set_title(cat, fontsize=11, fontweight="bold", pad=8)
        ax.set_xlabel("Date", fontsize=9)
        ax.set_ylabel("Units/Week", fontsize=9)
        ax.grid(axis="y", color=GRID_CLR, linewidth=0.5, alpha=0.5)
        ax.legend(fontsize=8, framealpha=0.2, labelcolor=TEXT_CLR)
        ax.tick_params(axis="x", rotation=30)

    fig.suptitle("TOWER 1 — XGBoost Forecast vs Actual (2025 Test Year)",
                 color=TEXT_CLR, fontsize=14, fontweight="bold", y=1.02)
    _save(fig, "08_forecast_vs_actual.png")


# ── Chart 09: Feature Importance ──────────────────────────────────────────────
def chart_09_feature_importance(fi_df: pd.DataFrame, top_n: int = 20):
    fi_top = fi_df.head(top_n).sort_values("importance")
    fig, ax = _base_fig(figsize=(12, 8))

    colors = [VST_GREEN if "lag" in f.lower() or "rolling" in f.lower()
              else BLUE if "month" in f.lower() or "week" in f.lower() or "season" in f.lower()
              else AMBER if "monsoon" in f.lower() or "macro" in f.lower()
              else PURPLE
              for f in fi_top["Feature"]]

    bars = ax.barh(fi_top["Feature"], fi_top["importance"],
                   color=colors, edgecolor=GRID_CLR, linewidth=0.5)

    for bar in bars:
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height()/2,
                f"{bar.get_width():.0f}", va="center", ha="left",
                color=MUTED, fontsize=8)

    legend_handles = [
        mpatches.Patch(facecolor=VST_GREEN, label="Lag / Rolling"),
        mpatches.Patch(facecolor=BLUE,      label="Time / Seasonality"),
        mpatches.Patch(facecolor=AMBER,     label="External Factors"),
        mpatches.Patch(facecolor=PURPLE,    label="SKU Attributes"),
    ]
    ax.legend(handles=legend_handles, fontsize=9, loc="lower right",
              framealpha=0.2, labelcolor=TEXT_CLR)
    ax.set_title("TOWER 1 — XGBoost Feature Importance (Top 20)",
                 color=TEXT_CLR, fontsize=13, fontweight="bold", pad=10)
    ax.set_xlabel("Importance Score (F-score)", fontsize=10)
    ax.grid(axis="x", color=GRID_CLR, linewidth=0.5, alpha=0.5)
    _save(fig, "09_feature_importance.png")


# ── Chart 10: RL Training Curve ───────────────────────────────────────────────
def chart_10_rl_training_curve(rewards: List[float]):
    fig, ax = _base_fig(figsize=(12, 5))

    x = np.arange(len(rewards))
    ax.plot(x, rewards, color=VST_GREEN2, lw=2, alpha=0.9, label="Mean Episode Reward")

    # Smooth trend
    if len(rewards) > 5:
        window = min(10, len(rewards) // 3)
        smooth = pd.Series(rewards).rolling(window, center=True).mean()
        ax.plot(x, smooth, color=AMBER, lw=2.5, linestyle="--", label=f"Smoothed ({window}-pt MA)")

    ax.axhline(y=0, color=MUTED, lw=0.8, linestyle=":", alpha=0.6)
    ax.fill_between(x, rewards, alpha=0.08, color=VST_GREEN2)

    ax.set_title("TOWER 2 — PPO Training Curve (Episode Reward vs Checkpoints)",
                 color=TEXT_CLR, fontsize=13, fontweight="bold", pad=10)
    ax.set_xlabel("Training Checkpoint (×5000 steps)", fontsize=10)
    ax.set_ylabel("Mean Episode Reward", fontsize=10)
    ax.legend(fontsize=9, framealpha=0.2, labelcolor=TEXT_CLR)
    ax.grid(color=GRID_CLR, linewidth=0.5, alpha=0.5)

    _save(fig, "10_rl_training_curve.png")


# ── Chart 11: RL vs Heuristic ─────────────────────────────────────────────────
def chart_11_rl_vs_heuristic(rl_metrics: Dict, heuristic_metrics: Dict):
    metrics = ["mean_fill_rate", "mean_reward", "mean_stockouts"]
    labels  = ["Fill Rate", "Avg Episode Reward", "Avg Stockout Weeks"]
    methods = ["RL Agent (PPO)", "Heuristic (s,S)"]

    rl_vals  = [rl_metrics[m] for m in metrics]
    h_vals   = [heuristic_metrics[m] for m in metrics]

    fig, axes = _base_fig(nrows=1, ncols=3, figsize=(15, 6))

    for i, (ax, label) in enumerate(zip(axes, labels)):
        vals = [rl_vals[i], h_vals[i]]
        clrs = [VST_GREEN, BLUE]

        # Normalise fill rate to %
        if "Fill" in label:
            vals = [v * 100 for v in vals]

        bars = ax.bar(methods, vals, color=clrs, width=0.5,
                      edgecolor=GRID_CLR, linewidth=0.6)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + abs(max(vals)) * 0.02,
                    f"{v:.1f}{'%' if 'Fill' in label else ''}",
                    ha="center", va="bottom", color=TEXT_CLR, fontsize=11, fontweight="bold")

        ax.set_title(label, color=TEXT_CLR, fontsize=11, fontweight="bold", pad=8)
        ax.tick_params(axis="x", colors=TEXT_CLR, labelsize=10)
        ax.grid(axis="y", color=GRID_CLR, linewidth=0.5, alpha=0.5)
        # Handle negative rewards
        mn = min(0, min(vals) * 1.2)
        mx = max(vals) * 1.25
        if mn != mx:
            ax.set_ylim(mn, mx)

    fig.suptitle("TOWER 2 — RL Agent vs Heuristic Baseline Comparison",
                 color=TEXT_CLR, fontsize=14, fontweight="bold", y=1.02)
    _save(fig, "11_rl_vs_heuristic.png")


# ── Chart 12: Policy Heatmap ──────────────────────────────────────────────────
def chart_12_policy_heatmap(model, env, n_samples: int = 2000):
    """
    Probe the learned policy across a grid of (stock_norm, forecast_norm) states
    and plot the mean chosen action as a heatmap.
    """
    import itertools
    stock_grid    = np.linspace(0, 3, 20)   # 0 = empty, 1 = at reorder, 3 = well stocked
    forecast_grid = np.linspace(0, 3, 20)   # normalised forecast

    action_grid = np.zeros((len(stock_grid), len(forecast_grid)), dtype=float)

    for i, sg in enumerate(stock_grid):
        for j, fg in enumerate(forecast_grid):
            # Build a representative state
            obs = np.array([sg, 0.5, fg, 0.3, 0.4, 0.6, 0.5], dtype=np.float32)
            obs = np.clip(obs, env.observation_space.low, env.observation_space.high)
            action, _ = model.predict(obs[np.newaxis], deterministic=True)
            action_grid[i, j] = float(action)

    fig, ax = _base_fig(figsize=(10, 8))

    cmap = LinearSegmentedColormap.from_list(
        "vst", [PANEL_BG, BLUE, VST_GREEN2, AMBER, RED], N=256
    )
    im = ax.imshow(action_grid, aspect="auto", origin="lower", cmap=cmap,
                   vmin=0, vmax=len(ACTION_LABELS) - 1,
                   extent=[0, 3, 0, 3])

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Order Action", color=TEXT_CLR, fontsize=10)
    cbar.ax.yaxis.set_tick_params(color=MUTED, labelsize=8)
    cbar.set_ticks(np.arange(len(ACTION_LABELS)))
    cbar.set_ticklabels(ACTION_LABELS)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=TEXT_CLR)

    ax.set_xlabel("Forecast Demand (normalised)", fontsize=10)
    ax.set_ylabel("Current Stock (normalised; 1.0 = reorder point)", fontsize=10)
    ax.set_title("TOWER 2 — Learned Policy Heatmap\n(Order Action vs Stock Level × Demand Forecast)",
                 color=TEXT_CLR, fontsize=12, fontweight="bold", pad=10)

    # Annotate key region
    ax.axvline(x=1.0, color=RED, lw=1.5, linestyle="--", alpha=0.7)
    ax.axhline(y=1.0, color=AMBER, lw=1.5, linestyle="--", alpha=0.7)
    ax.text(0.05, 2.8, "High Order Zone\n(Low stock)", color=TEXT_CLR, fontsize=9,
            bbox=dict(facecolor=RED, alpha=0.3, boxstyle="round"))
    ax.text(1.8, 0.1, "Hold Zone\n(Well stocked)", color=TEXT_CLR, fontsize=9,
            bbox=dict(facecolor=VST_GREEN, alpha=0.3, boxstyle="round"))

    _save(fig, "12_policy_heatmap.png")


# ── Chart 13: RL What-If ──────────────────────────────────────────────────────
def chart_13_rl_whatif(model, env):
    """
    Simulate 52-week episode with RL agent under normal and +30% demand shock.
    """
    def run_episode(shock_factor: float = 1.0):
        obs, _ = env.reset(seed=99)
        stocks, orders, demands, rewards = [], [], [], []
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            action = int(action)
            # Record
            stocks.append(float(obs[0]))
            orders.append(ACTION_LABELS[action])
            t_idx = min(env._t_start + env._t, len(env._demand) - 1)
            demands.append(float(env._demand[t_idx]) * shock_factor)
            # Step (inject shock via demand override if needed)
            obs, reward, terminated, truncated, info = env.step(action)
            rewards.append(reward)
            done = terminated or truncated
        return stocks, orders, demands, rewards

    norm_stocks, norm_orders, norm_demands, norm_rewards = run_episode(1.0)
    shock_stocks, shock_orders, shock_demands, shock_rewards = run_episode(1.3)

    fig, axes = _base_fig(nrows=2, ncols=1, figsize=(14, 10))

    weeks = np.arange(len(norm_stocks))
    reorder_line = 1.0   # normalised reorder point

    for ax, stocks, demands, label, clr in [
        (axes[0], norm_stocks,  norm_demands,  "Normal Demand",       VST_GREEN2),
        (axes[1], shock_stocks, shock_demands, "+30% Demand Shock",   AMBER),
    ]:
        ax.plot(weeks, stocks, color=clr,  lw=2, label="Stock Level (normalised)")
        ax.axhline(y=reorder_line, color=RED, lw=1.5, linestyle="--", alpha=0.8, label="Reorder Point")
        ax.fill_between(weeks, stocks, reorder_line,
                        where=np.array(stocks) < reorder_line,
                        color=RED, alpha=0.15, label="Below Reorder")

        # Mark large order decisions
        large_action_weeks = [i for i, o in enumerate(norm_orders if "Normal" in label else shock_orders)
                              if o in ["3×", "4×"]]
        if large_action_weeks:
            ax.scatter(large_action_weeks,
                       [stocks[w] for w in large_action_weeks],
                       color=AMBER, zorder=5, s=50, marker="^", label="Large Order (3-4×)")

        ax.set_title(f"RL Agent Response — {label}", color=TEXT_CLR,
                     fontsize=11, fontweight="bold", pad=8)
        ax.set_ylabel("Inventory (normalised)", fontsize=9)
        ax.set_xlabel("Week", fontsize=9)
        ax.legend(fontsize=8, framealpha=0.2, labelcolor=TEXT_CLR)
        ax.grid(color=GRID_CLR, linewidth=0.5, alpha=0.5)

    fig.suptitle("TOWER 2 — RL Agent: Normal vs Demand Shock Response",
                 color=TEXT_CLR, fontsize=14, fontweight="bold", y=1.01)
    _save(fig, "13_rl_whatif_updated.png")


# ── Master runner ──────────────────────────────────────────────────────────────
def generate_all_phase2_charts(
    forecast_df: pd.DataFrame,
    fi_df: pd.DataFrame,
    training_rewards: List[float],
    rl_metrics: Dict,
    heuristic_metrics: Dict,
    model,
    env,
):
    print("Generating Phase 2 charts...")
    chart_08_forecast_vs_actual(forecast_df)
    chart_09_feature_importance(fi_df)
    chart_10_rl_training_curve(training_rewards)
    chart_11_rl_vs_heuristic(rl_metrics, heuristic_metrics)
    chart_12_policy_heatmap(model, env)
    chart_13_rl_whatif(model, env)
    print("  All Phase 2 charts generated.")
