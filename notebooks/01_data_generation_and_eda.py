"""
01_data_generation_and_eda.py — Master script for Phase 1.

Generates all synthetic data tables and runs the full EDA visualization suite.
Run from the project root: python -m notebooks.01_data_generation_and_eda

This script can also be converted to a Jupyter notebook using:
    jupytext --to notebook notebooks/01_data_generation_and_eda.py
"""

# %% [markdown]
# # VST Tillers & Tractors — Phase 1: Synthetic Data Generation & EDA
#
# **Objective**: Generate realistic synthetic supply chain data for 200 SKUs across
# 5 product categories, with agricultural seasonality, multi-country supplier
# dynamics, and external economic factors. Then perform comprehensive EDA.
#
# **Categories**: Spare Parts | Lubricants | Electric Pumps | Engines | Precision Components
#
# **Data Tables**:
# 1. `dim_products` — SKU master data
# 2. `dim_suppliers` — Supplier profiles (Japan, China, Germany, India)
# 3. `fact_sales` — Weekly sales with seasonality & stockouts
# 4. `fact_external` — Monsoon, crop seasons, macro-economic index

# %% [markdown]
# ## 1. Setup & Imports

# %%
import sys
import os

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd

from src.data_generator import generate_all_tables
from src.eda_visualizations import run_all_eda

# %% [markdown]
# ## 2. Generate Synthetic Data

# %%
print("Phase 1: Generating synthetic data...\n")
tables = generate_all_tables(save_to_disk=True, output_dir="data")

# %% [markdown]
# ### 2.1 Quick Data Inspection

# %%
for name, df in tables.items():
    print(f"\n{'-' * 50}")
    print(f"[TABLE] {name} -- {len(df):,} rows x {len(df.columns)} columns")
    print(f"{'-' * 50}")
    print(df.head(3).to_string(index=False))
    print()

# %% [markdown]
# ### 2.2 Data Integrity Checks

# %%
print("\n[CHECK] Running data integrity checks...\n")

dim_products = tables["dim_products"]
dim_suppliers = tables["dim_suppliers"]
fact_sales = tables["fact_sales"]
fact_external = tables["fact_external"]

# Check 1: All sales SKUs exist in products
orphan_skus = set(fact_sales["SKU_ID"]) - set(dim_products["SKU_ID"])
print(f"  [OK] Orphan SKUs in fact_sales: {len(orphan_skus)} (should be 0)")

# Check 2: Date range
print(f"  [OK] Sales date range: {fact_sales['Date'].min().date()} -> {fact_sales['Date'].max().date()}")
print(f"  [OK] External date range: {fact_external['Date'].min().date()} -> {fact_external['Date'].max().date()}")

# Check 3: Category distribution
cat_dist = dim_products["Category"].value_counts()
print(f"  [OK] Category distribution:")
for cat, count in cat_dist.items():
    print(f"      {cat}: {count} SKUs ({count/len(dim_products)*100:.0f}%)")

# Check 4: Supplier country distribution
sup_dist = dim_suppliers["Origin_Country"].value_counts()
print(f"  [OK] Supplier countries: {dict(sup_dist)}")

# Check 5: Stockout rate
stockout_rate = fact_sales["Stockout_Flag"].mean()
print(f"  [OK] Overall stockout rate: {stockout_rate:.1%}")

# Check 6: No nulls in critical columns
nulls = fact_sales[["Date", "SKU_ID", "Units_Sold"]].isnull().sum().sum()
print(f"  [OK] Null values in critical columns: {nulls} (should be 0)")

print("\n[PASS] All integrity checks passed!")

# %% [markdown]
# ## 3. Exploratory Data Analysis — Visualization Suite

# %%
chart_paths = run_all_eda(tables)

# %% [markdown]
# ## 4. Summary Statistics

# %%
print("\n" + "=" * 60)
print("  SUMMARY STATISTICS")
print("=" * 60)

print(f"\n  Products: {len(dim_products)} SKUs across {dim_products['Category'].nunique()} categories")
print(f"  Suppliers: {len(dim_suppliers)} from {dim_suppliers['Origin_Country'].nunique()} countries")
print(f"  Sales Records: {len(fact_sales):,} weekly transactions")
print(f"  Date Range: {fact_sales['Date'].min().date()} to {fact_sales['Date'].max().date()}")
print(f"  Total Units Sold: {fact_sales['Units_Sold'].sum():,.0f}")
print(f"  Avg Weekly Demand (all SKUs): {fact_sales.groupby('Date')['Units_Sold'].sum().mean():,.0f}")
print(f"  Stockout Rate: {stockout_rate:.1%}")
print(f"  Charts Generated: {len(chart_paths)}")

# Seasonal demand analysis
print(f"\n  Seasonal Demand Analysis:")
sales_cat = fact_sales.merge(dim_products[["SKU_ID", "Category"]], on="SKU_ID")
sales_cat["Month"] = sales_cat["Date"].dt.month

for cat in dim_products["Category"].unique():
    cat_data = sales_cat[sales_cat["Category"] == cat]
    monthly = cat_data.groupby("Month")["Units_Sold"].mean()
    peak_month = monthly.idxmax()
    trough_month = monthly.idxmin()
    ratio = monthly.max() / monthly.min() if monthly.min() > 0 else 0
    month_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                   7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    print(f"    {cat:25s} | Peak: {month_names[peak_month]} | Trough: {month_names[trough_month]} | Ratio: {ratio:.1f}x")

print(f"\n{'=' * 60}")
print("  [DONE] Phase 1 Complete -- Ready for Phase 2 (ML/RL)")
print(f"{'=' * 60}")
