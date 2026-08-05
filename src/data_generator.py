"""
data_generator.py — Synthetic data generation for VST supply chain MVP.

Generates 4 relational tables with realistic business logic:
  1. dim_products   — SKU master (200 SKUs across 5 categories)
  2. dim_suppliers   — Supplier profiles (30 suppliers, 4 countries)
  3. fact_sales      — Weekly sales transactions with seasonality
  4. fact_external   — Monsoon, crop season, and macro-economic indices

All randomness is seeded for reproducibility.
"""

import os
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from src.config import (
    BASE_STOCKOUT_RATE,
    BASE_UNIT_COSTS,
    CATEGORIES,
    DATE_END,
    DATE_START,
    DATA_DIR,
    FREQ,
    FULFILLMENT_REGIONS,
    MACHINE_TYPES,
    MOQ_RANGES,
    PEAK_STOCKOUT_RATE,
    RANDOM_SEED,
    SUPPLIER_PROFILES,
    TOTAL_SKUS,
    TOTAL_SUPPLIERS,
)

warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 1: dim_products
# ══════════════════════════════════════════════════════════════════════════════
def generate_dim_products(rng: np.random.Generator) -> pd.DataFrame:
    """Generate product dimension table with realistic SKU attributes."""
    rows = []
    sku_counter = {}

    for cat_name, cat_cfg in CATEGORIES.items():
        n_skus = max(1, int(TOTAL_SKUS * cat_cfg["share"]))
        prefix = cat_cfg["prefix"]
        sub_cats = cat_cfg["sub_categories"]
        sku_counter[cat_name] = 0

        for i in range(n_skus):
            sku_counter[cat_name] += 1
            sub_cat = rng.choice(sub_cats)
            # Build a short sub-category code (first 3 chars uppercase)
            sub_code = sub_cat[:3].upper()
            sku_id = f"{prefix}-{sub_code}-{sku_counter[cat_name]:04d}"

            # Shelf life
            if cat_cfg["shelf_life_days"] is None:
                shelf_life = None
            else:
                low, high = cat_cfg["shelf_life_days"]
                shelf_life = int(rng.integers(low, high + 1))

            # Unit volume
            vol_low, vol_high = cat_cfg["unit_volume_m3"]
            unit_volume = round(rng.uniform(vol_low, vol_high), 4)

            # Criticality score
            crit_low, crit_high = cat_cfg["criticality_range"]
            criticality = int(rng.integers(crit_low, crit_high + 1))

            # Machine compatibility (1–3 machines per SKU)
            n_machines = rng.integers(1, 4)
            machines = rng.choice(MACHINE_TYPES, size=n_machines, replace=False)
            machine_compat = ", ".join(machines)

            rows.append(
                {
                    "SKU_ID": sku_id,
                    "Category": cat_name,
                    "Sub_Category": sub_cat,
                    "Machine_Compatibility": machine_compat,
                    "Shelf_Life_Days": shelf_life,
                    "Unit_Volume_m3": unit_volume,
                    "Criticality_Score": criticality,
                }
            )

    df = pd.DataFrame(rows)
    # Ensure Shelf_Life_Days is nullable integer
    df["Shelf_Life_Days"] = df["Shelf_Life_Days"].astype("Int64")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 2: dim_suppliers
# ══════════════════════════════════════════════════════════════════════════════
def generate_dim_suppliers(
    rng: np.random.Generator, products_df: pd.DataFrame
) -> pd.DataFrame:
    """Generate supplier dimension table with origin-specific profiles."""
    rows = []
    supplier_counter = 0

    for country, profile in SUPPLIER_PROFILES.items():
        n_suppliers = max(1, int(TOTAL_SUPPLIERS * profile["count_share"]))
        code = profile["code"]

        for i in range(n_suppliers):
            supplier_counter += 1
            supplier_id = f"SUP-{code}-{supplier_counter:03d}"

            # Lead time
            lt_low, lt_high = profile["base_lead_time_days"]
            base_lead_time = int(rng.integers(lt_low, lt_high + 1))

            # Volatility (coefficient of variation)
            vol_low, vol_high = profile["lead_time_volatility"]
            volatility = round(rng.uniform(vol_low, vol_high), 3)

            # Assign a primary category this supplier serves
            primary_cat = rng.choice(profile["primary_categories"])

            # Unit cost based on category + country premium
            cost_low, cost_high = BASE_UNIT_COSTS.get(
                primary_cat, (500, 5000)
            )
            unit_cost = round(
                rng.uniform(cost_low, cost_high) * profile["cost_multiplier"],
                2,
            )

            # MOQ
            moq_low, moq_high = MOQ_RANGES.get(primary_cat, (10, 100))
            moq = int(rng.integers(moq_low, moq_high + 1))

            rows.append(
                {
                    "Supplier_ID": supplier_id,
                    "Origin_Country": country,
                    "Primary_Category": primary_cat,
                    "Base_Lead_Time_Days": base_lead_time,
                    "Lead_Time_Volatility": volatility,
                    "Minimum_Order_Quantity": moq,
                    "Unit_Cost_INR": unit_cost,
                }
            )

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 4: fact_external (built before fact_sales, since sales uses it)
# ══════════════════════════════════════════════════════════════════════════════
def generate_fact_external(rng: np.random.Generator) -> pd.DataFrame:
    """Generate external factors table: monsoon, crop seasons, macro index."""
    dates = pd.date_range(start=DATE_START, end=DATE_END, freq=FREQ)
    rows = []

    # Macro-economic index: slow random walk between 0.8 and 1.2
    macro = 1.0
    macro_values = []
    for _ in dates:
        macro += rng.normal(0, 0.005)
        macro = np.clip(macro, 0.75, 1.25)
        macro_values.append(round(macro, 4))

    for i, date in enumerate(dates):
        month = date.month

        # ── Monsoon Index (0–1): peaks Jun–Sep ──
        if month in (6, 7, 8, 9):
            # Core monsoon months
            base_monsoon = 0.7 + 0.3 * np.sin(
                np.pi * (month - 5.5) / 4.5
            )
        elif month == 5:
            base_monsoon = 0.3  # Pre-monsoon buildup
        elif month == 10:
            base_monsoon = 0.25  # Retreating monsoon
        else:
            base_monsoon = 0.05 + rng.uniform(0, 0.05)

        # Add year-to-year variance
        monsoon_index = np.clip(
            base_monsoon + rng.normal(0, 0.05), 0, 1
        )

        # ── Crop Sowing Season ──
        if month in (6, 7, 8, 9, 10):
            season = "Kharif"
        elif month in (11, 12, 1, 2, 3):
            season = "Rabi"
        else:
            season = "Off-Season"

        rows.append(
            {
                "Date": date,
                "Monsoon_Index": round(monsoon_index, 4),
                "Crop_Sowing_Season": season,
                "Macro_Economic_Index": macro_values[i],
            }
        )

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 3: fact_sales
# ══════════════════════════════════════════════════════════════════════════════
def _get_seasonality_multiplier(
    date: pd.Timestamp, seasonality_cfg: dict, monsoon_index: float
) -> float:
    """Compute demand multiplier based on category seasonality profile."""
    month = date.month
    stype = seasonality_cfg["type"]
    peak_mult = seasonality_cfg["multiplier"]

    if stype == "monsoon_spike":
        # Pumps: heavy spike in May–Jun (pre-monsoon buying), elevated Jul–Aug
        if month in (5, 6):
            return peak_mult * (0.8 + 0.4 * monsoon_index)
        elif month in (7, 8):
            return 1.0 + (peak_mult - 1.0) * 0.5 * monsoon_index
        else:
            return 1.0

    elif stype == "post_harvest":
        # Spare parts: spike Nov–Dec (maintenance after Kharif harvest)
        if month in (11, 12):
            return peak_mult
        elif month in (1, 2):
            return 1.0 + (peak_mult - 1.0) * 0.3  # Lingering demand
        else:
            return 1.0

    elif stype == "sowing_aligned":
        # Engines: uptick during sowing preparation
        if month in (5, 6, 10, 11):
            return peak_mult
        else:
            return 1.0

    elif stype == "mild_uptick":
        # Lubricants: mild increase during active farming
        if month in (6, 7, 8, 9, 10, 11):
            return peak_mult
        else:
            return 1.0

    else:  # "steady"
        return 1.0


def generate_fact_sales(
    rng: np.random.Generator,
    products_df: pd.DataFrame,
    external_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate weekly sales data with realistic seasonality patterns."""
    dates = pd.date_range(start=DATE_START, end=DATE_END, freq=FREQ)
    region_names = list(FULFILLMENT_REGIONS.keys())
    region_probs = list(FULFILLMENT_REGIONS.values())

    # Build lookup: date -> monsoon_index
    ext_lookup = external_df.set_index("Date")["Monsoon_Index"].to_dict()

    rows = []
    for _, product in products_df.iterrows():
        sku_id = product["SKU_ID"]
        cat_name = product["Category"]
        cat_cfg = CATEGORIES[cat_name]
        seasonality_cfg = cat_cfg["seasonality"]
        criticality = product["Criticality_Score"]

        # Base demand for this SKU (fixed across time)
        demand_low, demand_high = cat_cfg["base_demand_weekly"]
        base_demand = rng.uniform(demand_low, demand_high)

        # Slight upward trend over 4 years (1–3% annual growth)
        annual_growth = rng.uniform(1.01, 1.03)

        for date in dates:
            # Years elapsed since start
            years_elapsed = (date - dates[0]).days / 365.25
            trend = annual_growth**years_elapsed

            # Monsoon index for this date
            monsoon_idx = ext_lookup.get(date, 0.1)

            # Seasonality
            seasonal_mult = _get_seasonality_multiplier(
                date, seasonality_cfg, monsoon_idx
            )

            # Compute demand
            demand = base_demand * trend * seasonal_mult

            # Add noise (Poisson-like for count data, with some variance)
            noise_std = max(1, demand * 0.15)
            units_sold = max(0, int(rng.normal(demand, noise_std)))

            # Fulfillment region
            region = rng.choice(region_names, p=region_probs)

            # Stockout flag — higher during peak seasons, higher for critical SKUs
            is_peak = seasonal_mult > 1.2
            stockout_prob = (
                PEAK_STOCKOUT_RATE if is_peak else BASE_STOCKOUT_RATE
            )
            # Higher criticality -> slightly higher stockout visibility
            stockout_prob *= 1 + (criticality - 3) * 0.05
            stockout_prob = np.clip(stockout_prob, 0.02, 0.25)
            stockout_flag = int(rng.random() < stockout_prob)

            rows.append(
                {
                    "Date": date,
                    "SKU_ID": sku_id,
                    "Units_Sold": units_sold,
                    "Fulfillment_Region": region,
                    "Stockout_Flag": stockout_flag,
                }
            )

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Master Generator
# ══════════════════════════════════════════════════════════════════════════════
def generate_all_tables(
    save_to_disk: bool = True,
    output_dir: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    """
    Generate all 4 synthetic tables and optionally save as CSVs.

    Returns a dict: {"dim_products": df, "dim_suppliers": df,
                      "fact_sales": df, "fact_external": df}
    """
    rng = np.random.default_rng(RANDOM_SEED)
    output_dir = output_dir or DATA_DIR

    print("=" * 60)
    print("  VST Tillers — Synthetic Data Generator")
    print("=" * 60)

    # 1. Products
    print("\n[1/4] Generating dim_products...")
    dim_products = generate_dim_products(rng)
    print(f"      -> {len(dim_products)} SKUs across {dim_products['Category'].nunique()} categories")

    # 2. Suppliers
    print("[2/4] Generating dim_suppliers...")
    dim_suppliers = generate_dim_suppliers(rng, dim_products)
    print(f"      -> {len(dim_suppliers)} suppliers from {dim_suppliers['Origin_Country'].nunique()} countries")

    # 3. External factors (needed before sales)
    print("[3/4] Generating fact_external...")
    fact_external = generate_fact_external(rng)
    print(f"      -> {len(fact_external)} weekly records ({DATE_START} to {DATE_END})")

    # 4. Sales
    print("[4/4] Generating fact_sales (this may take a moment)...")
    fact_sales = generate_fact_sales(rng, dim_products, fact_external)
    print(f"      -> {len(fact_sales):,} transaction records")
    print(f"      -> Stockout rate: {fact_sales['Stockout_Flag'].mean():.1%}")

    tables = {
        "dim_products": dim_products,
        "dim_suppliers": dim_suppliers,
        "fact_sales": fact_sales,
        "fact_external": fact_external,
    }

    # Save to disk
    if save_to_disk:
        os.makedirs(output_dir, exist_ok=True)
        for name, df in tables.items():
            path = os.path.join(output_dir, f"{name}.csv")
            df.to_csv(path, index=False)
            print(f"      [OK] Saved {path} ({len(df):,} rows)")

    print("\n" + "=" * 60)
    print("  Data generation complete!")
    print("=" * 60)

    return tables
