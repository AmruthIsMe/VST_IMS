"""
eda_visualizations.py — Exploratory Data Analysis charts for VST supply chain.

Generates 5 visualization groups:
  1. Macro KPI Dashboard (inventory value, fill rate, stockout risk)
  2. Demand Trends by Category (historical demand with moving averages)
  3. Inventory Tracking Simulation (stock levels, safety stock, pipeline)
  4. Lead Time Analysis (distribution by supplier country)
  5. RL What-If Sandbox (demand shock simulation)
"""

import os
import warnings

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

from src.config import (
    CATEGORIES,
    COLOR_PALETTE,
    FIGURE_DPI,
    OUTPUT_DIR,
    SUPPLIER_PROFILES,
)

warnings.filterwarnings("ignore")

# ── Style Setup ──
plt.rcParams.update({
    "figure.facecolor": "#0D1117",
    "axes.facecolor": "#161B22",
    "axes.edgecolor": "#30363D",
    "axes.labelcolor": "#C9D1D9",
    "text.color": "#C9D1D9",
    "xtick.color": "#8B949E",
    "ytick.color": "#8B949E",
    "grid.color": "#21262D",
    "grid.alpha": 0.6,
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "figure.titlesize": 16,
    "figure.titleweight": "bold",
    "legend.facecolor": "#161B22",
    "legend.edgecolor": "#30363D",
    "legend.fontsize": 9,
})

# Custom color palette (dark theme friendly)
CAT_COLORS = {
    "Spare Parts": "#58A6FF",
    "Lubricants": "#3FB950",
    "Electric Pumps": "#F0883E",
    "Engines": "#BC8CFF",
    "Precision Components": "#FF7B72",
}
ACCENT = "#58A6FF"
GREEN = "#3FB950"
RED = "#F85149"
AMBER = "#D29922"
PURPLE = "#BC8CFF"


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _save_fig(fig, name: str):
    _ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"  [OK] Saved: {path}")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 1. MACRO KPI DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
def plot_macro_kpis(
    fact_sales: pd.DataFrame,
    dim_products: pd.DataFrame,
    dim_suppliers: pd.DataFrame,
) -> str:
    """Generate macro-level KPI dashboard with inventory value, fill rate, stockout risk."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(
        "VST TILLERS — SUPPLY CHAIN KPI DASHBOARD",
        fontsize=18,
        fontweight="bold",
        color="#F0F6FC",
        y=1.02,
    )

    # ── KPI 1: Monthly Inventory Value (Estimated) ──
    ax = axes[0]
    # Merge sales with unit costs (approximate via category average)
    sales_with_cost = fact_sales.merge(
        dim_products[["SKU_ID", "Category"]], on="SKU_ID", how="left"
    )
    # Approximate unit cost from supplier data
    cat_avg_cost = dim_suppliers.groupby("Primary_Category")["Unit_Cost_INR"].mean()
    sales_with_cost["Est_Unit_Cost"] = sales_with_cost["Category"].map(cat_avg_cost).fillna(1000)
    sales_with_cost["Revenue"] = sales_with_cost["Units_Sold"] * sales_with_cost["Est_Unit_Cost"]

    monthly_value = (
        sales_with_cost.set_index("Date")
        .resample("ME")["Revenue"]
        .sum()
        / 1e7  # Convert to Crores (INR)
    )
    ax.fill_between(
        monthly_value.index, monthly_value.values, alpha=0.3, color=ACCENT
    )
    ax.plot(monthly_value.index, monthly_value.values, color=ACCENT, linewidth=2)
    ax.set_title("Monthly Inventory Value (₹ Cr)", fontsize=13)
    ax.set_ylabel("Value (₹ Crores)")
    ax.xaxis.set_major_locator(mticker.MaxNLocator(6))
    ax.tick_params(axis="x", rotation=30)
    # Add latest value annotation
    latest_val = monthly_value.iloc[-1]
    ax.annotate(
        f"₹{latest_val:.1f} Cr",
        xy=(monthly_value.index[-1], latest_val),
        fontsize=12,
        fontweight="bold",
        color=ACCENT,
        ha="right",
    )

    # ── KPI 2: Weekly Fill Rate ──
    ax = axes[1]
    weekly = fact_sales.set_index("Date").resample("W")
    fill_rate = 1 - weekly["Stockout_Flag"].mean()
    fill_rate_pct = fill_rate * 100

    ax.plot(fill_rate_pct.index, fill_rate_pct.values, color=GREEN, linewidth=1.5, alpha=0.7)
    # Rolling average
    rolling = fill_rate_pct.rolling(8).mean()
    ax.plot(rolling.index, rolling.values, color=GREEN, linewidth=2.5, label="8-week MA")
    ax.axhline(y=95, color=AMBER, linestyle="--", linewidth=1, alpha=0.7, label="95% Target")
    ax.fill_between(
        fill_rate_pct.index,
        fill_rate_pct.values,
        95,
        where=fill_rate_pct < 95,
        alpha=0.2,
        color=RED,
    )
    ax.set_title("Weekly Fill Rate (%)", fontsize=13)
    ax.set_ylabel("Fill Rate (%)")
    ax.set_ylim(75, 102)
    ax.legend(loc="lower left")
    ax.xaxis.set_major_locator(mticker.MaxNLocator(6))
    ax.tick_params(axis="x", rotation=30)

    # ── KPI 3: Stockout Risk by Category ──
    ax = axes[2]
    cat_stockout = (
        sales_with_cost.groupby("Category")["Stockout_Flag"]
        .mean()
        .sort_values(ascending=True)
        * 100
    )
    colors = [
        RED if v > 12 else AMBER if v > 8 else GREEN
        for v in cat_stockout.values
    ]
    bars = ax.barh(cat_stockout.index, cat_stockout.values, color=colors, height=0.6)
    ax.axvline(x=10, color="#F0F6FC", linestyle=":", linewidth=1, alpha=0.4)
    ax.set_title("Stockout Rate by Category (%)", fontsize=13)
    ax.set_xlabel("Stockout Rate (%)")
    for bar, val in zip(bars, cat_stockout.values):
        ax.text(
            val + 0.3, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}%", va="center", fontsize=10, color="#C9D1D9",
        )

    fig.tight_layout()
    return _save_fig(fig, "01_macro_kpi_dashboard")


# ══════════════════════════════════════════════════════════════════════════════
# 2. DEMAND TRENDS BY CATEGORY
# ══════════════════════════════════════════════════════════════════════════════
def plot_demand_trends(
    fact_sales: pd.DataFrame,
    dim_products: pd.DataFrame,
    fact_external: pd.DataFrame,
) -> str:
    """Line charts: historical demand per category with seasonal overlays."""
    sales_cat = fact_sales.merge(
        dim_products[["SKU_ID", "Category"]], on="SKU_ID", how="left"
    )

    categories = list(CATEGORIES.keys())
    fig, axes = plt.subplots(len(categories), 1, figsize=(18, 4 * len(categories)), sharex=True)
    fig.suptitle(
        "DEMAND TRENDS BY PRODUCT CATEGORY",
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    for i, cat in enumerate(categories):
        ax = axes[i]
        cat_data = sales_cat[sales_cat["Category"] == cat]
        weekly_demand = cat_data.set_index("Date").resample("W")["Units_Sold"].sum()

        color = CAT_COLORS[cat]

        # Raw weekly demand (thin line)
        ax.plot(
            weekly_demand.index, weekly_demand.values,
            color=color, alpha=0.3, linewidth=0.8,
        )
        # 4-week moving average (thick line)
        ma4 = weekly_demand.rolling(4).mean()
        ax.plot(
            ma4.index, ma4.values,
            color=color, linewidth=2.5, label=f"{cat} (4-wk MA)",
        )
        # 12-week moving average (proxy for forecast)
        ma12 = weekly_demand.rolling(12).mean()
        ax.plot(
            ma12.index, ma12.values,
            color="#F0F6FC", linewidth=1.5, linestyle="--", alpha=0.6,
            label="Trend (12-wk MA)",
        )

        # Shade monsoon season (Jun–Sep each year)
        for year in range(2022, 2026):
            ax.axvspan(
                pd.Timestamp(f"{year}-06-01"),
                pd.Timestamp(f"{year}-09-30"),
                alpha=0.08, color=ACCENT, zorder=0,
            )

        ax.set_ylabel("Units Sold")
        ax.set_title(f"  {cat}", fontsize=12, loc="left", color=color)
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Date")
    fig.tight_layout()
    return _save_fig(fig, "02_demand_trends_by_category")


# ══════════════════════════════════════════════════════════════════════════════
# 3. INVENTORY TRACKING SIMULATION
# ══════════════════════════════════════════════════════════════════════════════
def plot_inventory_tracking(
    fact_sales: pd.DataFrame,
    dim_products: pd.DataFrame,
    dim_suppliers: pd.DataFrame,
) -> str:
    """Area chart: simulated stock levels, safety stock, and incoming pipeline."""
    # Pick top 6 SKUs by total demand for detailed tracking
    top_skus = (
        fact_sales.groupby("SKU_ID")["Units_Sold"]
        .sum()
        .nlargest(6)
        .index.tolist()
    )

    fig, axes = plt.subplots(3, 2, figsize=(18, 14))
    fig.suptitle(
        "INVENTORY TRACKING — TOP 6 SKUs BY DEMAND",
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    rng = np.random.default_rng(99)

    for idx, sku_id in enumerate(top_skus):
        ax = axes[idx // 2, idx % 2]
        sku_data = (
            fact_sales[fact_sales["SKU_ID"] == sku_id]
            .set_index("Date")
            .resample("W")["Units_Sold"]
            .sum()
        )

        # Simulate inventory dynamics
        avg_weekly = sku_data.mean()
        safety_stock = avg_weekly * 3  # 3 weeks of safety stock
        initial_stock = avg_weekly * 8  # Start with 8 weeks of stock

        stock_levels = []
        pipeline = []
        current_stock = initial_stock
        incoming = 0

        for units in sku_data.values:
            current_stock += incoming  # Receive pipeline
            current_stock -= units     # Consume
            current_stock = max(0, current_stock)

            # Reorder if below reorder point (safety stock * 1.5)
            if current_stock < safety_stock * 1.5:
                incoming = avg_weekly * rng.integers(3, 8)
            else:
                incoming = 0

            stock_levels.append(current_stock)
            pipeline.append(incoming)

        dates = sku_data.index

        # Stacked area
        ax.fill_between(dates, stock_levels, alpha=0.4, color=ACCENT, label="Current Stock")
        ax.fill_between(dates, pipeline, alpha=0.3, color=PURPLE, label="Incoming Pipeline")
        ax.axhline(y=safety_stock, color=RED, linestyle="--", linewidth=1.5, label="Safety Stock")

        # Get category for title color
        cat = dim_products.loc[dim_products["SKU_ID"] == sku_id, "Category"].values[0]
        ax.set_title(f"{sku_id} ({cat})", fontsize=11, color=CAT_COLORS.get(cat, ACCENT))
        ax.set_ylabel("Units")
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.2)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(5))
        ax.tick_params(axis="x", rotation=30)

    fig.tight_layout()
    return _save_fig(fig, "03_inventory_tracking")


# ══════════════════════════════════════════════════════════════════════════════
# 4. LEAD TIME ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
def plot_lead_time_analysis(dim_suppliers: pd.DataFrame) -> str:
    """Histograms and box plots of lead time distribution by origin country."""
    rng = np.random.default_rng(42)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(
        "SUPPLIER LEAD TIME ANALYSIS BY ORIGIN",
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    countries = ["India", "China", "Japan", "Germany"]
    country_colors = {
        "India": GREEN,
        "China": RED,
        "Japan": PURPLE,
        "Germany": ACCENT,
    }

    # Generate simulated actual lead times based on base + volatility
    simulated_data = []
    for _, row in dim_suppliers.iterrows():
        base = row["Base_Lead_Time_Days"]
        vol = row["Lead_Time_Volatility"]
        # Simulate 50 shipments per supplier
        actual_times = rng.normal(base, base * vol, size=50)
        actual_times = np.clip(actual_times, base * 0.3, base * 2.5).astype(int)
        for t in actual_times:
            simulated_data.append({
                "Supplier_ID": row["Supplier_ID"],
                "Origin_Country": row["Origin_Country"],
                "Actual_Lead_Time_Days": t,
                "Base_Lead_Time_Days": base,
                "Volatility": vol,
            })

    sim_df = pd.DataFrame(simulated_data)

    for i, country in enumerate(countries):
        ax = axes[i // 2, i % 2]
        country_data = sim_df[sim_df["Origin_Country"] == country]["Actual_Lead_Time_Days"]
        color = country_colors[country]

        # Histogram
        ax.hist(
            country_data, bins=30, alpha=0.6, color=color, edgecolor="#30363D",
            density=True,
        )

        # KDE overlay
        if len(country_data) > 10:
            from scipy.stats import gaussian_kde
            kde = gaussian_kde(country_data)
            x_range = np.linspace(country_data.min(), country_data.max(), 200)
            ax.plot(x_range, kde(x_range), color="#F0F6FC", linewidth=2)

        # Stats annotation
        mean_lt = country_data.mean()
        std_lt = country_data.std()
        cv = std_lt / mean_lt if mean_lt > 0 else 0

        stats_text = (
            f"μ = {mean_lt:.0f} days\n"
            f"σ = {std_lt:.0f} days\n"
            f"CV = {cv:.2f}"
        )
        ax.text(
            0.97, 0.95, stats_text,
            transform=ax.transAxes, fontsize=10,
            verticalalignment="top", horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#21262D", edgecolor="#30363D"),
            color="#C9D1D9",
        )

        ax.set_title(f"  {country}", fontsize=13, loc="left", color=color)
        ax.set_xlabel("Lead Time (Days)")
        ax.set_ylabel("Density")

    fig.tight_layout()
    path1 = _save_fig(fig, "04a_lead_time_histograms")

    # ── Box Plot Comparison ──
    fig2, ax2 = plt.subplots(figsize=(14, 6))
    fig2.suptitle(
        "LEAD TIME DISTRIBUTION COMPARISON",
        fontsize=16, fontweight="bold", color="#F0F6FC",
    )

    box_data = [
        sim_df[sim_df["Origin_Country"] == c]["Actual_Lead_Time_Days"].values
        for c in countries
    ]

    bp = ax2.boxplot(
        box_data, labels=countries, patch_artist=True, widths=0.5,
        medianprops=dict(color="#F0F6FC", linewidth=2),
        whiskerprops=dict(color="#8B949E"),
        capprops=dict(color="#8B949E"),
        flierprops=dict(marker="o", markerfacecolor="#8B949E", markersize=4, alpha=0.5),
    )

    for patch, country in zip(bp["boxes"], countries):
        patch.set_facecolor(country_colors[country])
        patch.set_alpha(0.6)
        patch.set_edgecolor("#30363D")

    ax2.set_ylabel("Lead Time (Days)")
    ax2.set_xlabel("Origin Country")
    ax2.grid(True, axis="y", alpha=0.3)

    # Annotate China's high variance
    ax2.annotate(
        "!! Highest Variance",
        xy=(2, sim_df[sim_df["Origin_Country"] == "China"]["Actual_Lead_Time_Days"].max()),
        xytext=(2.5, sim_df[sim_df["Origin_Country"] == "China"]["Actual_Lead_Time_Days"].max() + 10),
        fontsize=10, color=RED, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=RED),
    )

    fig2.tight_layout()
    path2 = _save_fig(fig2, "04b_lead_time_boxplot")
    return path1


# ══════════════════════════════════════════════════════════════════════════════
# 5. RL WHAT-IF SANDBOX — Demand Shock Simulation
# ══════════════════════════════════════════════════════════════════════════════
def plot_demand_shock_whatif(
    fact_sales: pd.DataFrame,
    dim_products: pd.DataFrame,
) -> str:
    """Simulate a 20% demand spike scenario and show inventory impact."""
    # Focus on Electric Pumps (most monsoon-sensitive)
    pump_skus = dim_products[dim_products["Category"] == "Electric Pumps"]["SKU_ID"]
    pump_sales = fact_sales[fact_sales["SKU_ID"].isin(pump_skus)]

    weekly_demand = pump_sales.set_index("Date").resample("W")["Units_Sold"].sum()

    # Scenario: 20% demand spike starting at the last monsoon (Jun 2025)
    shock_start = pd.Timestamp("2025-06-01")
    shock_end = pd.Timestamp("2025-09-30")

    baseline = weekly_demand.copy()
    shocked = weekly_demand.copy()
    shock_mask = (shocked.index >= shock_start) & (shocked.index <= shock_end)
    shocked[shock_mask] = (shocked[shock_mask] * 1.20).astype(int)

    # Simulate inventory depletion
    rng = np.random.default_rng(42)
    avg_weekly = baseline.mean()
    safety_stock = avg_weekly * 4

    def simulate_inventory(demand_series):
        stock = avg_weekly * 10  # 10 weeks initial
        stock_hist = []
        for d in demand_series.values:
            # Simple reorder: if below safety stock, order 6 weeks' worth
            if stock < safety_stock:
                stock += avg_weekly * 6
            stock -= d
            stock = max(0, stock)
            stock_hist.append(stock)
        return pd.Series(stock_hist, index=demand_series.index)

    inv_baseline = simulate_inventory(baseline)
    inv_shocked = simulate_inventory(shocked)

    # ── Plot ──
    fig, axes = plt.subplots(2, 1, figsize=(18, 10), sharex=True)
    fig.suptitle(
        'RL WHAT-IF SANDBOX — "STRONG MONSOON" DEMAND SHOCK (+20%)',
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    # Panel 1: Demand comparison
    ax = axes[0]
    ax.plot(baseline.index, baseline.values, color=ACCENT, linewidth=1.5, alpha=0.7, label="Baseline Demand")
    ax.plot(shocked.index, shocked.values, color=RED, linewidth=2, label="Shocked Demand (+20%)")
    ax.fill_between(
        shocked.index, baseline.values, shocked.values,
        where=shock_mask, alpha=0.2, color=RED,
    )
    ax.axvspan(shock_start, shock_end, alpha=0.08, color=AMBER, zorder=0)
    ax.set_ylabel("Units (Electric Pumps)")
    ax.set_title("  Demand: Baseline vs. Shock Scenario", loc="left", fontsize=13)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Panel 2: Inventory impact
    ax = axes[1]
    ax.fill_between(inv_baseline.index, inv_baseline.values, alpha=0.4, color=ACCENT, label="Inventory (Baseline)")
    ax.fill_between(inv_shocked.index, inv_shocked.values, alpha=0.4, color=RED, label="Inventory (Shocked)")
    ax.axhline(y=safety_stock, color=AMBER, linestyle="--", linewidth=2, label=f"Safety Stock ({safety_stock:.0f})")
    ax.axvspan(shock_start, shock_end, alpha=0.08, color=AMBER, zorder=0)

    # Mark stockout zones
    stockout_mask = inv_shocked < safety_stock * 0.3
    if stockout_mask.any():
        ax.fill_between(
            inv_shocked.index, 0, inv_shocked.max() * 0.05,
            where=stockout_mask, alpha=0.3, color=RED, label="!! Critical Zone",
        )

    ax.set_ylabel("Inventory Units")
    ax.set_xlabel("Date")
    ax.set_title("  Inventory Impact: Risk of Stockout", loc="left", fontsize=13)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Add insight annotation
    ax.text(
        0.98, 0.05,
        "RL Agent (Phase 2) will learn to pre-emptively\nincrease orders when monsoon forecast is strong",
        transform=ax.transAxes, fontsize=10,
        ha="right", va="bottom",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#21262D", edgecolor=ACCENT, alpha=0.8),
        color="#C9D1D9",
    )

    fig.tight_layout()
    return _save_fig(fig, "05_demand_shock_whatif")


# ══════════════════════════════════════════════════════════════════════════════
# BONUS: External Factors Visualization
# ══════════════════════════════════════════════════════════════════════════════
def plot_external_factors(fact_external: pd.DataFrame) -> str:
    """Visualize monsoon index, crop seasons, and macro-economic trends."""
    fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
    fig.suptitle(
        "EXTERNAL FACTORS — AGRICULTURAL & ECONOMIC DRIVERS",
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    ext = fact_external.set_index("Date")

    # ── Monsoon Index ──
    ax = axes[0]
    ax.fill_between(ext.index, ext["Monsoon_Index"], alpha=0.4, color=ACCENT)
    ax.plot(ext.index, ext["Monsoon_Index"], color=ACCENT, linewidth=2)
    ax.set_title("  Monsoon Index (0–1)", loc="left", fontsize=13)
    ax.set_ylabel("Index")
    ax.set_ylim(-0.05, 1.1)
    # Shade monsoon months
    for year in range(2022, 2026):
        ax.axvspan(
            pd.Timestamp(f"{year}-06-01"),
            pd.Timestamp(f"{year}-09-30"),
            alpha=0.08, color=GREEN,
        )

    # ── Crop Season ──
    ax = axes[1]
    season_map = {"Kharif": 2, "Rabi": 1, "Off-Season": 0}
    season_colors = {"Kharif": GREEN, "Rabi": AMBER, "Off-Season": "#8B949E"}
    season_vals = ext["Crop_Sowing_Season"].map(season_map)

    for season, color in season_colors.items():
        mask = ext["Crop_Sowing_Season"] == season
        ax.fill_between(
            ext.index, 0, 1, where=mask, alpha=0.3, color=color, label=season,
        )
    ax.set_title("  Crop Sowing Seasons", loc="left", fontsize=13)
    ax.set_yticks([])
    ax.legend(loc="upper right", fontsize=9)

    # ── Macro-Economic Index ──
    ax = axes[2]
    ax.plot(ext.index, ext["Macro_Economic_Index"], color=PURPLE, linewidth=2)
    ax.axhline(y=1.0, color="#8B949E", linestyle=":", linewidth=1)
    ax.fill_between(
        ext.index,
        ext["Macro_Economic_Index"],
        1.0,
        where=ext["Macro_Economic_Index"] > 1.0,
        alpha=0.3,
        color=GREEN,
        label="Expansion",
    )
    ax.fill_between(
        ext.index,
        ext["Macro_Economic_Index"],
        1.0,
        where=ext["Macro_Economic_Index"] < 1.0,
        alpha=0.3,
        color=RED,
        label="Contraction",
    )
    ax.set_title("  Macro-Economic Index", loc="left", fontsize=13)
    ax.set_ylabel("Index")
    ax.set_xlabel("Date")
    ax.legend(loc="upper left", fontsize=9)

    fig.tight_layout()
    return _save_fig(fig, "06_external_factors")


# ══════════════════════════════════════════════════════════════════════════════
# BONUS: Data Quality Summary
# ══════════════════════════════════════════════════════════════════════════════
def plot_data_quality_summary(
    dim_products: pd.DataFrame,
    dim_suppliers: pd.DataFrame,
    fact_sales: pd.DataFrame,
    fact_external: pd.DataFrame,
) -> str:
    """Summary stats and distribution overview for data quality check."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(
        "DATA QUALITY & DISTRIBUTION OVERVIEW",
        fontsize=18, fontweight="bold", color="#F0F6FC", y=1.01,
    )

    # ── 1. SKU distribution by category ──
    ax = axes[0, 0]
    cat_counts = dim_products["Category"].value_counts()
    colors = [CAT_COLORS.get(c, ACCENT) for c in cat_counts.index]
    wedges, texts, autotexts = ax.pie(
        cat_counts.values, labels=cat_counts.index, autopct="%1.0f%%",
        colors=colors, textprops={"color": "#C9D1D9", "fontsize": 8},
        pctdistance=0.75, startangle=90,
    )
    for t in autotexts:
        t.set_fontsize(9)
        t.set_fontweight("bold")
    ax.set_title("SKU Distribution", fontsize=12)

    # ── 2. Criticality Score distribution ──
    ax = axes[0, 1]
    sns.histplot(
        dim_products["Criticality_Score"], bins=5, ax=ax,
        color=ACCENT, edgecolor="#30363D", alpha=0.7,
    )
    ax.set_title("Criticality Score Distribution", fontsize=12)
    ax.set_xlabel("Score")

    # ── 3. Supplier by country ──
    ax = axes[0, 2]
    country_counts = dim_suppliers["Origin_Country"].value_counts()
    country_colors_list = [
        {"India": GREEN, "China": RED, "Japan": PURPLE, "Germany": ACCENT}.get(c, "#8B949E")
        for c in country_counts.index
    ]
    bars = ax.bar(country_counts.index, country_counts.values, color=country_colors_list, width=0.6)
    ax.set_title("Suppliers by Country", fontsize=12)
    ax.set_ylabel("Count")
    for bar, val in zip(bars, country_counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.3, str(val),
                ha="center", fontsize=10, color="#C9D1D9")

    # ── 4. Weekly total demand over time ──
    ax = axes[1, 0]
    weekly_total = fact_sales.set_index("Date").resample("W")["Units_Sold"].sum()
    ax.plot(weekly_total.index, weekly_total.values, color=ACCENT, linewidth=1.5)
    ax.set_title("Total Weekly Demand", fontsize=12)
    ax.set_ylabel("Units")
    ax.tick_params(axis="x", rotation=30)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(5))

    # ── 5. Unit cost distribution by country ──
    ax = axes[1, 1]
    for country in ["India", "China", "Japan", "Germany"]:
        data = dim_suppliers[dim_suppliers["Origin_Country"] == country]["Unit_Cost_INR"]
        color = {"India": GREEN, "China": RED, "Japan": PURPLE, "Germany": ACCENT}[country]
        ax.hist(data, bins=15, alpha=0.5, color=color, label=country, edgecolor="#30363D")
    ax.set_title("Unit Cost Distribution (₹)", fontsize=12)
    ax.set_xlabel("INR")
    ax.legend(fontsize=8)

    # ── 6. Stockout flag over time ──
    ax = axes[1, 2]
    monthly_stockout = (
        fact_sales.set_index("Date")
        .resample("ME")["Stockout_Flag"]
        .mean() * 100
    )
    ax.bar(monthly_stockout.index, monthly_stockout.values, width=25, color=RED, alpha=0.6)
    ax.axhline(y=10, color=AMBER, linestyle="--", linewidth=1, label="10% Threshold")
    ax.set_title("Monthly Stockout Rate (%)", fontsize=12)
    ax.set_ylabel("Rate (%)")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=30)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(5))

    fig.tight_layout()
    return _save_fig(fig, "07_data_quality_summary")


# ══════════════════════════════════════════════════════════════════════════════
# Master Runner
# ══════════════════════════════════════════════════════════════════════════════
def run_all_eda(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Run all EDA visualizations and return list of saved chart paths."""
    print("\n" + "=" * 60)
    print("  VST Tillers — EDA Visualization Suite")
    print("=" * 60 + "\n")

    dp = tables["dim_products"]
    ds = tables["dim_suppliers"]
    fs = tables["fact_sales"]
    fe = tables["fact_external"]

    paths = []

    print("[1/7] Macro KPI Dashboard...")
    paths.append(plot_macro_kpis(fs, dp, ds))

    print("[2/7] Demand Trends by Category...")
    paths.append(plot_demand_trends(fs, dp, fe))

    print("[3/7] Inventory Tracking Simulation...")
    paths.append(plot_inventory_tracking(fs, dp, ds))

    print("[4/7] Lead Time Analysis...")
    paths.append(plot_lead_time_analysis(ds))

    print("[5/7] Demand Shock What-If...")
    paths.append(plot_demand_shock_whatif(fs, dp))

    print("[6/7] External Factors...")
    paths.append(plot_external_factors(fe))

    print("[7/7] Data Quality Summary...")
    paths.append(plot_data_quality_summary(dp, ds, fs, fe))

    print(f"\n{'=' * 60}")
    print(f"  [DONE] All {len(paths)} charts generated successfully!")
    print(f"{'=' * 60}\n")

    return paths
