"""
Data Pipeline for VST IMS Demand Forecasting.
Loads sales data, engineers features, and prepares train/test splits
with temporal integrity for time-series forecasting.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


def load_sales_data(db: Session = None) -> pd.DataFrame:
    """Load sales data from DB or CSV fallback."""
    if db:
        try:
            query = text("""
                SELECT s.sale_date as Date, s.sku_id as SKU_ID, 
                       s.units_sold as Units_Sold, s.fulfillment_region as Fulfillment_Region,
                       s.stockout_flag as Stockout_Flag
                FROM sales s ORDER BY s.sale_date
            """)
            df = pd.read_sql(query, db.bind)
            if len(df) > 100:
                return df
        except Exception:
            pass

    csv_path = DATA_DIR / "fact_sales.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        return df
    raise FileNotFoundError("No sales data found in DB or CSV.")


def load_products_data() -> pd.DataFrame:
    """Load product dimension data."""
    csv_path = DATA_DIR / "dim_products.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def load_suppliers_data() -> pd.DataFrame:
    """Load supplier dimension data."""
    csv_path = DATA_DIR / "dim_suppliers.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def load_external_factors() -> pd.DataFrame:
    """Load external factors (monsoon, crop season, macro index)."""
    csv_path = DATA_DIR / "fact_external.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        return df
    return pd.DataFrame()


def get_category_for_sku(sku_id: str, products_df: pd.DataFrame = None) -> str:
    """Derive category from SKU prefix or products table."""
    if products_df is not None and len(products_df) > 0:
        match = products_df[products_df["SKU_ID"] == sku_id]
        if len(match) > 0:
            return match.iloc[0]["Category"]

    prefix_map = {
        "SP": "Spare Parts",
        "LU": "Lubricants",
        "EP": "Electric Pumps",
        "EN": "Engines",
        "PC": "Precision Components",
    }
    prefix = sku_id[:2] if len(sku_id) >= 2 else ""
    return prefix_map.get(prefix, "Unknown")


def engineer_features(df: pd.DataFrame, external_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Create time-series features for each SKU:
    - Lag features (1w, 2w, 4w, 8w, 13w, 26w, 52w)
    - Rolling statistics (mean, std for 4w, 13w, 26w)
    - Calendar features (week_of_year, month, quarter, day_of_year)
    - Seasonal flags (kharif, rabi, monsoon, post-harvest)
    - External factors merge
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["SKU_ID", "Date"]).reset_index(drop=True)

    # --- Lag features ---
    lag_periods = [1, 2, 4, 8, 13, 26, 52]
    for lag in lag_periods:
        df[f"lag_{lag}w"] = df.groupby("SKU_ID")["Units_Sold"].shift(lag)

    # --- Rolling statistics ---
    for window in [4, 13, 26]:
        grp = df.groupby("SKU_ID")["Units_Sold"]
        df[f"rolling_mean_{window}w"] = grp.transform(
            lambda x: x.shift(1).rolling(window, min_periods=1).mean()
        )
        df[f"rolling_std_{window}w"] = grp.transform(
            lambda x: x.shift(1).rolling(window, min_periods=1).std()
        )
        df[f"rolling_min_{window}w"] = grp.transform(
            lambda x: x.shift(1).rolling(window, min_periods=1).min()
        )
        df[f"rolling_max_{window}w"] = grp.transform(
            lambda x: x.shift(1).rolling(window, min_periods=1).max()
        )

    # --- Calendar features ---
    df["week_of_year"] = df["Date"].dt.isocalendar().week.astype(int)
    df["month"] = df["Date"].dt.month
    df["quarter"] = df["Date"].dt.quarter
    df["day_of_year"] = df["Date"].dt.dayofyear
    df["year"] = df["Date"].dt.year

    # --- Seasonal flags (India agricultural calendar) ---
    # Kharif: Jun-Oct (monsoon crops)
    df["is_kharif"] = df["month"].isin([6, 7, 8, 9, 10]).astype(int)
    # Rabi: Nov-Mar (winter crops)
    df["is_rabi"] = df["month"].isin([11, 12, 1, 2, 3]).astype(int)
    # Monsoon: Jun-Sep
    df["is_monsoon"] = df["month"].isin([6, 7, 8, 9]).astype(int)
    # Post-harvest maintenance: Nov-Dec
    df["is_post_harvest"] = df["month"].isin([11, 12]).astype(int)
    # Pre-monsoon buying spike: Apr-May
    df["is_pre_monsoon"] = df["month"].isin([4, 5]).astype(int)

    # --- Cyclical encoding for week and month ---
    df["week_sin"] = np.sin(2 * np.pi * df["week_of_year"] / 52)
    df["week_cos"] = np.cos(2 * np.pi * df["week_of_year"] / 52)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    # --- Year-over-year change ---
    df["yoy_change"] = df.groupby("SKU_ID")["Units_Sold"].pct_change(periods=52)

    # --- Trend feature (weeks since start) ---
    min_dates = df.groupby("SKU_ID")["Date"].transform("min")
    df["weeks_since_start"] = ((df["Date"] - min_dates).dt.days / 7).astype(int)

    # --- Merge external factors ---
    if external_df is not None and len(external_df) > 0:
        external_df = external_df.copy()
        external_df["Date"] = pd.to_datetime(external_df["Date"])
        # Map crop sowing season to numeric
        season_map = {"Kharif": 1, "Rabi": 2, "Summer": 3, "None": 0}
        if "Crop_Sowing_Season" in external_df.columns:
            external_df["crop_season_num"] = (
                external_df["Crop_Sowing_Season"].map(season_map).fillna(0).astype(int)
            )
        df = df.merge(
            external_df[["Date"] + [c for c in external_df.columns if c not in ["Date", "Crop_Sowing_Season"]]],
            on="Date",
            how="left",
        )

    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return the list of feature columns (excluding target and identifiers)."""
    exclude = {
        "Date", "SKU_ID", "Units_Sold", "Fulfillment_Region",
        "Stockout_Flag", "Category", "target",
    }
    return [c for c in df.columns if c not in exclude and df[c].dtype in [np.float64, np.int64, np.int32, np.float32, int, float]]


def prepare_dataset(
    sku_id: str = None,
    category: str = None,
    test_weeks: int = 12,
    db: Session = None,
) -> dict:
    """
    Full pipeline: load → engineer → split.
    Returns dict with train/test DataFrames, feature columns, and metadata.
    """
    sales_df = load_sales_data(db)
    products_df = load_products_data()
    external_df = load_external_factors()

    # Merge category info
    if "Category" not in sales_df.columns:
        if len(products_df) > 0:
            sku_cat = products_df[["SKU_ID", "Category"]].drop_duplicates()
            sales_df = sales_df.merge(sku_cat, on="SKU_ID", how="left")
        else:
            sales_df["Category"] = sales_df["SKU_ID"].apply(
                lambda x: get_category_for_sku(x)
            )

    # Filter by SKU or category
    if sku_id:
        sales_df = sales_df[sales_df["SKU_ID"] == sku_id].copy()
    elif category:
        sales_df = sales_df[sales_df["Category"] == category].copy()

    if len(sales_df) == 0:
        raise ValueError(f"No data found for sku_id={sku_id}, category={category}")

    # Engineer features
    featured_df = engineer_features(sales_df, external_df)

    # Target column
    featured_df["target"] = featured_df["Units_Sold"]

    # Drop rows with NaN in critical lag features (warm-up period)
    featured_df = featured_df.dropna(subset=["lag_4w", "rolling_mean_4w"])

    # Temporal split
    all_dates = sorted(featured_df["Date"].unique())
    if len(all_dates) <= test_weeks:
        split_idx = len(all_dates) // 2
    else:
        split_idx = len(all_dates) - test_weeks
    split_date = all_dates[split_idx]

    train_df = featured_df[featured_df["Date"] < split_date].copy()
    test_df = featured_df[featured_df["Date"] >= split_date].copy()

    feature_cols = get_feature_columns(featured_df)

    # Fill remaining NaN and Inf in features with 0
    train_df[feature_cols] = train_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    test_df[feature_cols] = test_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    return {
        "train": train_df,
        "test": test_df,
        "feature_cols": feature_cols,
        "split_date": str(split_date),
        "sku_ids": list(featured_df["SKU_ID"].unique()),
        "total_rows": len(featured_df),
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }


def prepare_timeseries_for_sku(sku_id: str, db: Session = None) -> pd.DataFrame:
    """
    Get a clean weekly time-series for a single SKU (for ARIMA/SARIMA/Prophet).
    Returns DataFrame with Date index and Units_Sold values.
    """
    sales_df = load_sales_data(db)
    sku_data = sales_df[sales_df["SKU_ID"] == sku_id].copy()
    sku_data["Date"] = pd.to_datetime(sku_data["Date"])
    sku_data = sku_data.sort_values("Date")

    # Aggregate to weekly (in case of duplicates)
    ts = sku_data.groupby("Date")["Units_Sold"].sum().reset_index()
    ts = ts.set_index("Date").asfreq("W-MON", fill_value=0)

    return ts
