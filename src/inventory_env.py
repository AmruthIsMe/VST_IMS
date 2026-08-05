"""
inventory_env.py — Tower 2: Custom Gymnasium environment for VST inventory management.

VSTInventoryEnv simulates a single SKU's inventory over a 52-week episode.
The RL agent chooses order quantities each week to maximise a reward that
balances fill rate, holding costs, and stockout penalties.

State  (7 features):
  [0] current_stock          — normalised by reorder_point
  [1] pipeline_quantity      — units on order (in transit), normalised
  [2] forecast_mean_4w       — XGBoost 4-week ahead demand forecast, normalised
  [3] monsoon_index          — [0, 1] current week external signal
  [4] weeks_to_lead_time     — normalised supplier lead time [0, 1]
  [5] criticality            — [0, 1] normalised criticality score (1-5 -> 0-1)
  [6] weeks_to_seasonal_peak — [0, 1] proximity to seasonal demand peak

Action space (Discrete 6):
  0 -> order 0 × weekly_demand
  1 -> order 0.5 × weekly_demand
  2 -> order 1 × weekly_demand
  3 -> order 2 × weekly_demand
  4 -> order 3 × weekly_demand
  5 -> order 4 × weekly_demand

Reward:
  +fill_rate * 10              — service level (core objective)
  -0.015 * stock * unit_vol   — holding cost (warehouse space)
  -criticality * missed * 0.5 — stockout penalty (weighted by SKU criticality)
"""

import warnings
from collections import deque
from typing import Dict, Optional, Tuple

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

warnings.filterwarnings("ignore")

# Action multipliers (order = multiplier × weekly demand)
ACTION_MULTIPLIERS = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0]

# Reward weights
W_FILL     = 10.0   # reward for fulfilling demand
W_HOLD     = 0.015  # penalty per unit × m3 held
W_STOCKOUT = 0.5    # penalty per missed unit × criticality


class VSTInventoryEnv(gym.Env):
    """
    Gymnasium environment simulating VST supply chain inventory for one SKU.

    Can be parametrised per SKU or run with randomised SKU selection
    (domain randomisation) for training a generalised shared policy.
    """

    metadata = {"render_modes": ["human"], "render_fps": 4}

    def __init__(
        self,
        sku_profiles: pd.DataFrame,
        demand_series: Dict[str, np.ndarray],
        forecast_series: Dict[str, np.ndarray],
        monsoon_series: np.ndarray,
        week_dates: pd.DatetimeIndex,
        episode_length: int = 52,
        randomise_sku: bool = True,
        fixed_sku: Optional[str] = None,
        render_mode: Optional[str] = None,
    ):
        super().__init__()

        self.sku_profiles   = sku_profiles        # DataFrame: SKU_ID, category, criticality, unit_vol, lead_time, ...
        self.demand_series  = demand_series        # {SKU_ID: np.array of weekly demand, aligned to week_dates}
        self.forecast_series = forecast_series     # {SKU_ID: np.array of forecasted demand}
        self.monsoon_series = monsoon_series       # np.array aligned to week_dates
        self.week_dates     = week_dates
        self.episode_length = episode_length
        self.randomise_sku  = randomise_sku
        self.fixed_sku      = fixed_sku
        self.render_mode    = render_mode

        # Spaces
        self.action_space = spaces.Discrete(len(ACTION_MULTIPLIERS))
        # 7-dim normalised state, all in [0, ~5]
        self.observation_space = spaces.Box(
            low   = np.zeros(7, dtype=np.float32),
            high  = np.full(7, 10.0, dtype=np.float32),
            dtype = np.float32,
        )

        # Internal state (set in reset)
        self._sku_id         = None
        self._profile        = None
        self._demand         = None
        self._forecast       = None
        self._t              = 0
        self._stock          = 0.0
        self._pipeline       = deque()  # (arrival_week, quantity)
        self._reorder_point  = 0.0
        self._weekly_demand  = 0.0     # baseline avg demand for this SKU
        self._rng            = np.random.default_rng(42)

        # Tracking
        self._total_reward   = 0.0
        self._fill_rates     = []
        self._stockouts      = 0

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _select_sku(self):
        if self.fixed_sku is not None:
            sku_id = self.fixed_sku
        elif self.randomise_sku:
            sku_id = self._rng.choice(self.sku_profiles["SKU_ID"].values)
        else:
            sku_id = self.sku_profiles["SKU_ID"].iloc[0]
        return sku_id

    def _get_profile(self, sku_id: str) -> pd.Series:
        return self.sku_profiles[self.sku_profiles["SKU_ID"] == sku_id].iloc[0]

    def _normalise_state(self) -> np.ndarray:
        prof = self._profile
        ro   = max(1.0, float(self._reorder_point))
        avg  = max(1.0, float(self._weekly_demand))

        # [0] stock normalised by reorder point (0 = empty, 1 = at reorder, 2+ = healthy)
        norm_stock = min(max(0.0, float(self._stock) / ro), 5.0)

        # [1] pipeline normalised
        pipeline_qty = sum(q for _, q in self._pipeline)
        norm_pipeline = min(max(0.0, float(pipeline_qty) / avg), 5.0)

        # [2] 4-week ahead forecast normalised
        if self._forecast is not None and len(self._forecast) > 0:
            t_curr   = min(self._t, len(self._forecast) - 1)
            t_future = min(t_curr + 4, len(self._forecast) - 1)
            slice_fc = self._forecast[t_curr : t_future + 1]
            fcast_mean = float(np.mean(slice_fc)) if len(slice_fc) > 0 else 0.0
            if np.isnan(fcast_mean):
                fcast_mean = 0.0
        else:
            fcast_mean = 0.0
        norm_forecast = min(max(0.0, fcast_mean / avg), 5.0)

        # [3] monsoon index (already [0, 1])
        t_idx = min(self._t_global, len(self.monsoon_series) - 1)
        monsoon = float(self.monsoon_series[t_idx])
        if np.isnan(monsoon):
            monsoon = 0.0

        # [4] lead time normalised (0 = instant, 1 = 90 days = 13 weeks)
        lead_weeks = float(prof["lead_time_weeks"])
        norm_lead = min(max(0.0, lead_weeks / 13.0), 1.0)

        # [5] criticality (0-1 from 1-5)
        norm_crit = (float(prof["Criticality_Score"]) - 1.0) / 4.0
        norm_crit = min(max(0.0, norm_crit), 1.0)

        # [6] weeks to seasonal peak (0 = at peak, 1 = far from peak)
        current_month = self.week_dates[t_idx].month
        peak_month_map = {
            "Spare Parts":          11,
            "Lubricants":           8,
            "Electric Pumps":       6,
            "Engines":              11,
            "Precision Components": 6,
        }
        peak_month = peak_month_map.get(prof["Category"], 6)
        diff = abs(current_month - peak_month)
        if diff > 6:
            diff = 12 - diff
        norm_peak = float(diff / 6.0)

        obs = np.array(
            [norm_stock, norm_pipeline, norm_forecast,
             monsoon, norm_lead, norm_crit, norm_peak],
            dtype=np.float32,
        )
        return np.nan_to_num(obs, nan=0.0, posinf=5.0, neginf=0.0)


# ── Core Gym API ───────────────────────────────────────────────────────────
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        # Select SKU
        self._sku_id   = self._select_sku()
        self._profile  = self._get_profile(self._sku_id)
        self._demand   = self.demand_series[self._sku_id]
        self._forecast = self.forecast_series.get(self._sku_id, self._demand)

        # Validate demand length
        total_weeks = len(self._demand)
        max_start = max(0, total_weeks - self.episode_length - 1)
        self._t_start = int(self._rng.integers(0, max(1, max_start + 1)))
        self._t       = 0
        self._t_global = self._t_start

        # Initialise inventory to 4–8 weeks of avg demand
        self._weekly_demand = max(1.0, float(np.mean(self._demand)))
        self._reorder_point = self._weekly_demand * 3.0
        self._stock    = self._weekly_demand * float(self._rng.uniform(4.0, 8.0))
        self._pipeline = deque()

        # Episode tracking
        self._total_reward = 0.0
        self._fill_rates   = []
        self._stockouts    = 0

        return self._normalise_state(), {}

    def step(self, action: int):
        prof = self._profile

        # 1. Receive any arriving pipeline shipments
        new_pipeline = deque()
        received = 0.0
        for (arr_week, qty) in self._pipeline:
            if arr_week <= self._t:
                received += qty
            else:
                new_pipeline.append((arr_week, qty))
        self._pipeline = new_pipeline
        self._stock += received

        # 2. Demand realisation (actual demand from history + noise)
        t_idx = min(self._t_start + self._t, len(self._demand) - 1)
        actual_demand = max(0.0, float(self._demand[t_idx]))

        # 3. Fulfil demand
        fulfilled = min(self._stock, actual_demand)
        missed    = max(0.0, actual_demand - fulfilled)
        self._stock = max(0.0, self._stock - fulfilled)

        fill_rate = fulfilled / max(1.0, actual_demand)
        self._fill_rates.append(fill_rate)
        if missed > 0:
            self._stockouts += 1

        # 4. Place order
        order_qty = ACTION_MULTIPLIERS[action] * self._weekly_demand
        if order_qty > 0:
            lead_time_weeks = int(round(
                prof["lead_time_weeks"]
                * self._rng.normal(1.0, prof["lead_time_volatility"])
            ))
            lead_time_weeks = max(1, lead_time_weeks)
            arr_week = self._t + lead_time_weeks
            self._pipeline.append((arr_week, order_qty))

        # 5. Compute reward
        holding_cost  = W_HOLD * self._stock * prof["Unit_Volume_m3"]
        stockout_pen  = W_STOCKOUT * prof["Criticality_Score"] * missed
        reward = float(W_FILL * fill_rate - holding_cost - stockout_pen)

        self._total_reward += reward
        self._t        += 1
        self._t_global += 1

        terminated = self._t >= self.episode_length
        truncated  = False

        info = {
            "sku_id":      self._sku_id,
            "fill_rate":   fill_rate,
            "stock":       self._stock,
            "missed":      missed,
            "received":    received,
            "order_qty":   order_qty,
        }

        return self._normalise_state(), reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "human":
            prof = self._profile
            print(
                f"[t={self._t:3d}] SKU={self._sku_id} | "
                f"Stock={self._stock:7.1f} | "
                f"FR={self._fill_rates[-1]*100:.1f}% | "
                f"Reward={self._total_reward:.2f}"
            )


# ── Factory: build env from actual data ───────────────────────────────────────
def build_env_from_data(
    products_path: str = "data/dim_products.csv",
    suppliers_path: str = "data/dim_suppliers.csv",
    sales_path:    str = "data/fact_sales.csv",
    external_path: str = "data/fact_external.csv",
    forecast_path: str = "data/demand_forecast.csv",
    train_mode: bool = True,
    fixed_sku: Optional[str] = None,
) -> VSTInventoryEnv:
    """
    Construct and return a VSTInventoryEnv loaded with real data.
    """
    products  = pd.read_csv(products_path)
    suppliers = pd.read_csv(suppliers_path)
    sales     = pd.read_csv(sales_path, parse_dates=["Date"])
    external  = pd.read_csv(external_path, parse_dates=["Date"])

    # Avg lead time per category from suppliers
    cat_lt = suppliers.groupby("Primary_Category").agg(
        lead_time_days    = ("Base_Lead_Time_Days", "mean"),
        lead_time_volatility = ("Lead_Time_Volatility", "mean"),
    ).reset_index()
    cat_lt["lead_time_weeks"] = (cat_lt["lead_time_days"] / 7).round(1)

    # Build SKU profiles
    sku_profiles = products.merge(
        cat_lt.rename(columns={"Primary_Category": "Category"}),
        on="Category", how="left",
    )
    sku_profiles = sku_profiles.fillna({
        "lead_time_weeks": 4.0,
        "lead_time_volatility": 0.2,
        "lead_time_days": 28.0,
    })

    # Weekly demand per SKU
    TRAIN_END  = "2024-12-31"
    TEST_START = "2025-01-01"
    period_mask = sales["Date"] <= TRAIN_END if train_mode else sales["Date"] >= TEST_START

    period_sales = sales[period_mask]
    week_dates = pd.DatetimeIndex(
        period_sales.groupby("Date")["Units_Sold"].sum().index
    )

    demand_map = {}
    for sku_id, grp in period_sales.groupby("SKU_ID"):
        agg = grp.groupby("Date")["Units_Sold"].sum().reindex(week_dates, fill_value=0)
        demand_map[sku_id] = agg.values.astype(float)

    # Forecast map (if available)
    forecast_map = {}
    if os.path.exists(forecast_path):
        fc_df = pd.read_csv(forecast_path, parse_dates=["Date"])
        for sku_id, grp in fc_df.groupby("SKU_ID"):
            fc_agg = grp.groupby("Date")["predicted_demand"].sum().reindex(week_dates)
            if not fc_agg.isna().all():
                fc_clean = fc_agg.ffill().bfill().fillna(0.0).values.astype(float)
                forecast_map[sku_id] = fc_clean

    # Fall back to actual demand if forecast not available or mismatch length
    for sku_id in demand_map:
        if sku_id not in forecast_map or len(forecast_map[sku_id]) != len(week_dates):
            forecast_map[sku_id] = demand_map[sku_id].copy()

    # Monsoon series aligned to week_dates
    ext_aligned = external.set_index("Date")["Monsoon_Index"].reindex(week_dates, method="nearest").fillna(0)
    monsoon_arr = ext_aligned.values.astype(float)

    return VSTInventoryEnv(
        sku_profiles    = sku_profiles,
        demand_series   = demand_map,
        forecast_series = forecast_map,
        monsoon_series  = monsoon_arr,
        week_dates      = week_dates,
        episode_length  = 52,
        randomise_sku   = (fixed_sku is None),
        fixed_sku       = fixed_sku,
    )



import os
