"""
feature_engineering.py — Builds the ML training dataset for Tower 1 forecasting.

Joins fact_sales + fact_external + dim_products to produce:
  - Lag features (1w, 2w, 4w, 8w, 12w)
  - Rolling statistics (mean, std, 4-week and 12-week windows)
  - Seasonality encoding (month, week_of_year, is_kharif, is_rabi)
  - External factors (monsoon_index, macro_economic_index)
  - SKU attributes (category_code, criticality, unit_volume)
  - Target: units_sold (next week, 1-step ahead)

Train/test split: 2022-01-01 to 2024-12-31 | 2025-01-01 to 2025-12-31
"""

import os
import warnings
from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

DATA_DIR = "data"
TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"

# Lag weeks to include
LAG_WEEKS = [1, 2, 4, 8, 12]
ROLL_WINDOWS = [4, 12]


def load_raw_data(data_dir: str = DATA_DIR) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    products = pd.read_csv(os.path.join(data_dir, "dim_products.csv"))
    sales    = pd.read_csv(os.path.join(data_dir, "fact_sales.csv"), parse_dates=["Date"])
    external = pd.read_csv(os.path.join(data_dir, "fact_external.csv"), parse_dates=["Date"])
    return products, sales, external


def build_features(
    products: pd.DataFrame,
    sales: pd.DataFrame,
    external: pd.DataFrame,
    is_inference: bool = False,
) -> pd.DataFrame:
    """
    Construct a panel dataset: one row per (SKU_ID, Date) with all features.
    Returns a DataFrame sorted by (SKU_ID, Date).
    """
    print("  [1/6] Pivoting sales to wide format...")

    # Aggregate: take sum per SKU per week (handles multi-region entries)
    agg = (
        sales.groupby(["SKU_ID", "Date"])["Units_Sold"]
        .sum()
        .reset_index()
        .sort_values(["SKU_ID", "Date"])
    )

    print("  [2/6] Computing lag features...")
    def add_lags(grp: pd.DataFrame) -> pd.DataFrame:
        for lag in LAG_WEEKS:
            grp[f"demand_lag_{lag}w"] = grp["Units_Sold"].shift(lag)
        return grp

    agg = agg.groupby("SKU_ID", group_keys=False).apply(add_lags)

    print("  [3/6] Computing rolling statistics...")
    def add_rolling(grp: pd.DataFrame) -> pd.DataFrame:
        for w in ROLL_WINDOWS:
            grp[f"rolling_mean_{w}w"] = grp["Units_Sold"].shift(1).rolling(w).mean()
            grp[f"rolling_std_{w}w"]  = grp["Units_Sold"].shift(1).rolling(w).std()
        return grp

    agg = agg.groupby("SKU_ID", group_keys=False).apply(add_rolling)

    print("  [4/6] Merging external factors...")
    # Merge external on Date (weekly)
    ext_cols = ["Date", "Monsoon_Index", "Crop_Sowing_Season", "Macro_Economic_Index"]
    agg = agg.merge(external[ext_cols], on="Date", how="left")

    # Lagged monsoon (1 week back — known at decision time)
    agg = agg.sort_values(["SKU_ID", "Date"])
    agg["monsoon_lag_1w"] = agg.groupby("SKU_ID")["Monsoon_Index"].shift(1)

    print("  [5/6] Adding time/seasonality features...")
    agg["month"]        = agg["Date"].dt.month
    agg["week_of_year"] = agg["Date"].dt.isocalendar().week.astype(int)
    agg["year"]         = agg["Date"].dt.year
    agg["is_kharif"]    = agg["month"].isin([6, 7, 8, 9, 10]).astype(int)
    agg["is_rabi"]      = agg["month"].isin([11, 12, 1, 2, 3]).astype(int)
    # Season as ordinal
    season_map = {"Kharif": 2, "Rabi": 1, "Off-Season": 0}
    agg["season_code"] = agg["Crop_Sowing_Season"].map(season_map).fillna(0)
    # Sine/cosine encoding for cyclical month
    agg["month_sin"] = np.sin(2 * np.pi * agg["month"] / 12)
    agg["month_cos"] = np.cos(2 * np.pi * agg["month"] / 12)
    agg["week_sin"]  = np.sin(2 * np.pi * agg["week_of_year"] / 52)
    agg["week_cos"]  = np.cos(2 * np.pi * agg["week_of_year"] / 52)

    print("  [6/6] Merging SKU attributes...")
    # Encode category
    le = LabelEncoder()
    products["category_code"] = le.fit_transform(products["Category"])
    sku_feats = products[["SKU_ID", "Category", "category_code",
                           "Criticality_Score", "Unit_Volume_m3",
                           "Sub_Category"]].copy()
    # Sub-category code
    le2 = LabelEncoder()
    sku_feats["sub_cat_code"] = le2.fit_transform(sku_feats["Sub_Category"])

    agg = agg.merge(sku_feats, on="SKU_ID", how="left")

    # ── Target: next-week demand (1-step ahead) ──
    if not is_inference:
        agg["target"] = agg.groupby("SKU_ID")["Units_Sold"].shift(-1)

    # Drop rows with NaN in lags or target (edges of each SKU's series)
    feature_cols = (
        [f"demand_lag_{w}w" for w in LAG_WEEKS]
        + [f"rolling_mean_{w}w" for w in ROLL_WINDOWS]
        + [f"rolling_std_{w}w" for w in ROLL_WINDOWS]
        + ["Monsoon_Index", "monsoon_lag_1w", "Macro_Economic_Index",
           "month_sin", "month_cos", "week_sin", "week_cos",
           "is_kharif", "is_rabi", "season_code",
           "category_code", "sub_cat_code",
           "Criticality_Score", "Unit_Volume_m3"]
    )
    
    if not is_inference:
        feature_cols.append("target")
        
    agg = agg.dropna(subset=feature_cols)

    return agg


def split_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Train: up to TRAIN_END. Test: from TEST_START."""
    train = df[df["Date"] <= TRAIN_END].copy()
    test  = df[df["Date"] >= TEST_START].copy()
    return train, test


FEATURE_COLS = (
    [f"demand_lag_{w}w" for w in LAG_WEEKS]
    + [f"rolling_mean_{w}w" for w in ROLL_WINDOWS]
    + [f"rolling_std_{w}w" for w in ROLL_WINDOWS]
    + ["Monsoon_Index", "monsoon_lag_1w", "Macro_Economic_Index",
       "month_sin", "month_cos", "week_sin", "week_cos",
       "is_kharif", "is_rabi", "season_code",
       "category_code", "sub_cat_code",
       "Criticality_Score", "Unit_Volume_m3"]
)
TARGET_COL = "target"


if __name__ == "__main__":
    print("Building feature dataset...")
    products, sales, external = load_raw_data()
    df = build_features(products, sales, external)
    train, test = split_data(df)
    print(f"  Train: {len(train):,} rows ({train['Date'].min().date()} to {train['Date'].max().date()})")
    print(f"  Test : {len(test):,} rows ({test['Date'].min().date()} to {test['Date'].max().date()})")
    print(f"  Features: {len(FEATURE_COLS)}")
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(os.path.join(DATA_DIR, "features_panel.csv"), index=False)
    print(f"  Saved data/features_panel.csv")
