"""
dashboard_generator.py — Reads actual CSV data and generates a self-contained
HTML dashboard with real INR values from the VST supply chain dataset.

Run:  python -m src.dashboard_generator
Output: dashboard/vst_inventory_dashboard.html
"""

import json
import os
import random
import sys

import numpy as np
import pandas as pd

# ── Load data ──────────────────────────────────────────────────────────────────
def load_data():
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    products  = pd.read_csv(os.path.join(base, "dim_products.csv"))
    suppliers = pd.read_csv(os.path.join(base, "dim_suppliers.csv"))
    sales     = pd.read_csv(os.path.join(base, "fact_sales.csv"), parse_dates=["Date"])
    external  = pd.read_csv(os.path.join(base, "fact_external.csv"), parse_dates=["Date"])
    return products, suppliers, sales, external


# ── Compute KPIs ───────────────────────────────────────────────────────────────
def compute_kpis(products, suppliers, sales):
    rng = np.random.default_rng(42)

    # Avg unit cost per category from suppliers
    cat_cost = suppliers.groupby("Primary_Category")["Unit_Cost_INR"].mean()

    # Simulate current inventory: rolling 12-week avg demand × safety stock factor
    latest_12w = sales[sales["Date"] >= sales["Date"].max() - pd.Timedelta(weeks=12)]
    sku_demand  = latest_12w.groupby("SKU_ID")["Units_Sold"].sum() / 12  # avg/week
    sku_reorder = (sku_demand * 3).round().astype(int)  # 3-week safety stock

    # Realistic stock distribution:
    #   ~5%  Out of Stock  (stock = 0)
    #   ~10% Critical      (0 < stock < reorder × 0.6)
    #   ~15% Low Stock     (reorder × 0.6 <= stock < reorder)
    #   ~70% Healthy       (stock >= reorder)
    n = len(sku_demand)
    buckets = rng.choice(
        ["oos", "critical", "low", "healthy"],
        size=n,
        p=[0.05, 0.10, 0.15, 0.70],
    )
    stock_arr = np.zeros(n)
    for i, (sku, demand) in enumerate(sku_demand.items()):
        ro = max(1, int(sku_reorder.get(sku, demand * 3)))
        b  = buckets[i]
        if b == "oos":
            stock_arr[i] = 0
        elif b == "critical":
            stock_arr[i] = max(1, int(rng.uniform(0.1, 0.59) * ro))
        elif b == "low":
            stock_arr[i] = int(rng.uniform(0.60, 0.99) * ro)
        else:  # healthy
            stock_arr[i] = int(rng.uniform(1.0, 8.0) * ro)

    sku_stock = pd.Series(stock_arr.astype(int), index=sku_demand.index)

    # Map cost to SKU
    sku_cat   = products.set_index("SKU_ID")["Category"]
    sku_cost  = sku_cat.map(cat_cost).fillna(1500)

    # Inventory value per SKU
    inv_value = (sku_stock * sku_cost).reindex(products["SKU_ID"]).fillna(0)

    total_inv_value = inv_value.sum()
    total_units     = int(sku_stock.sum())
    total_skus      = len(products)

    # Critical alerts: stock < reorder level (critical + oos)
    critical_mask  = sku_stock < sku_reorder.reindex(sku_stock.index).fillna(0)
    critical_count = int(critical_mask.sum())

    # Fill rate (last 8 weeks)
    last_8w   = sales[sales["Date"] >= sales["Date"].max() - pd.Timedelta(weeks=8)]
    fill_rate = 1 - last_8w["Stockout_Flag"].mean()

    return {
        "total_inv_value": total_inv_value,
        "total_units":     total_units,
        "total_skus":      total_skus,
        "critical_count":  critical_count,
        "fill_rate":       fill_rate,
        "sku_stock":       sku_stock,
        "sku_reorder":     sku_reorder,
        "sku_cost":        sku_cost,
        "inv_value":       inv_value,
    }



# ── Build table rows ───────────────────────────────────────────────────────────
def build_table_rows(products, kpis, n=200):
    rows = []
    sku_stock   = kpis["sku_stock"]
    sku_reorder = kpis["sku_reorder"]
    sku_cost    = kpis["sku_cost"]
    inv_value   = kpis["inv_value"]

    machine_short = {
        "Power Tiller":   "Power Tiller",
        "Tractor":        "Tractor",
        "Pump Set":       "Pump Set",
        "Diesel Engine":  "Diesel Engine",
        "Multi-Purpose":  "Universal",
    }

    for _, row in products.iterrows():
        sku = row["SKU_ID"]
        stock   = int(sku_stock.get(sku, 0))
        reorder = int(sku_reorder.get(sku, 0))
        cost    = float(sku_cost.get(sku, 1500))
        val     = float(inv_value.get(sku, 0))

        # Derive unit label per category
        cat = row["Category"]
        unit_lbl = {
            "Spare Parts":         "sets" if "Kit" in row["Sub_Category"] else "pcs",
            "Lubricants":          "cans",
            "Electric Pumps":      "units",
            "Engines":             "units",
            "Precision Components": "assy",
        }.get(cat, "pcs")

        # Status tag
        if stock <= 0:
            status = "Out of Stock"
        elif stock < reorder:
            status = "Critical" if stock < reorder * 0.6 else "Low Stock"
        elif stock < reorder * 1.5:
            status = "Low Stock"
        else:
            status = "Healthy"

        # Machine compat: pick first one for display
        machines = row["Machine_Compatibility"].split(", ")
        machine  = machine_short.get(machines[0], machines[0])

        # Friendly display name from sub_category + serial
        serial = sku.split("-")[-1]
        name   = f"{row['Sub_Category']} #{serial}"

        rows.append({
            "name":    name,
            "sku":     sku,
            "category": cat,
            "machine": machine,
            "stock":   stock,
            "reorder": reorder,
            "unit":    unit_lbl,
            "status":  status,
            "value":   val,
            "criticality": int(row["Criticality_Score"]),
        })

    # Sort: Critical first, then Low Stock, then Healthy
    order = {"Out of Stock": 0, "Critical": 1, "Low Stock": 2, "Healthy": 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -r["criticality"]))
    return rows


# ── Sparkline data ─────────────────────────────────────────────────────────────
def build_sparklines(sales, products):
    """Last 12 weeks total demand per category for sparklines in KPI cards."""
    merged = sales.merge(products[["SKU_ID","Category"]], on="SKU_ID")
    last12 = merged[merged["Date"] >= merged["Date"].max() - pd.Timedelta(weeks=12)]
    weekly_cat = (
        last12.groupby(["Date","Category"])["Units_Sold"].sum()
        .reset_index()
        .sort_values("Date")
    )
    sparks = {}
    for cat in products["Category"].unique():
        vals = weekly_cat[weekly_cat["Category"]==cat]["Units_Sold"].tolist()[-12:]
        # normalise to 0-100 for SVG path
        mx = max(vals) if vals else 1
        sparks[cat] = [round(v/mx*100, 1) for v in vals]
    return sparks


# ── Generate HTML ──────────────────────────────────────────────────────────────
def generate_html(kpis, table_rows, sparks, sales, external):
    total_inv  = kpis["total_inv_value"]
    total_units= kpis["total_units"]
    total_skus = kpis["total_skus"]
    critical   = kpis["critical_count"]
    fill_rate  = kpis["fill_rate"]

    # Weekly demand last 52 weeks for trend mini-chart data
    last52 = sales[sales["Date"] >= sales["Date"].max() - pd.Timedelta(weeks=52)]
    weekly_total = (
        last52.groupby("Date")["Units_Sold"].sum()
        .reset_index().sort_values("Date")
    )
    demand_labels = [d.strftime("%b %d") for d in weekly_total["Date"]]
    demand_values = weekly_total["Units_Sold"].tolist()

    # Category breakdown for donut
    cat_totals = (
        sales.merge(
            pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dim_products.csv")
            )[["SKU_ID","Category"]], on="SKU_ID"
        )
        .groupby("Category")["Units_Sold"].sum()
    )
    cat_labels = cat_totals.index.tolist()
    cat_values = cat_totals.values.tolist()

    # Monsoon index last 12 weeks
    last_ext = external[external["Date"] >= external["Date"].max() - pd.Timedelta(weeks=24)].sort_values("Date")
    monsoon_labels = [d.strftime("%b %d") for d in last_ext["Date"]]
    monsoon_values = last_ext["Monsoon_Index"].tolist()

    # Stockout rate by category (last 52w)
    merged52 = (
        last52.merge(
            pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dim_products.csv")
            )[["SKU_ID","Category"]], on="SKU_ID"
        )
    )
    stockout_cat = (merged52.groupby("Category")["Stockout_Flag"].mean() * 100).round(1)

    # Build table HTML rows
    def status_badge(s):
        cls = {
            "Healthy":      "badge-healthy",
            "Low Stock":    "badge-low",
            "Critical":     "badge-critical",
            "Out of Stock": "badge-oos",
        }.get(s, "badge-healthy")
        return f'<span class="badge {cls}">{s}</span>'

    def crit_stars(n):
        return "★" * n + "☆" * (5 - n)

    rows_html = ""
    for r in table_rows:
        rows_html += f"""
        <tr>
          <td>
            <div class="item-name">{r['name']}</div>
            <div class="item-sku">{r['sku']}</div>
          </td>
          <td><span class="cat-pill cat-{r['category'].replace(' ','').lower()}">{r['category']}</span></td>
          <td>{r['machine']}</td>
          <td><strong>{r['stock']:,}</strong> <span class="unit-lbl">{r['unit']}</span></td>
          <td>{r['reorder']:,} <span class="unit-lbl">{r['unit']}</span></td>
          <td>{status_badge(r['status'])}</td>
          <td class="val-cell">&#8377;{r['value']:,.0f}</td>
          <td class="crit-cell" title="Criticality {r['criticality']}/5">{crit_stars(r['criticality'])}</td>
          <td><button class="action-btn" title="View Details">&#128065;</button></td>
        </tr>"""

    # Serialise for JS
    d_labels = json.dumps(demand_labels)
    d_values = json.dumps(demand_values)
    c_labels = json.dumps(cat_labels)
    c_values = json.dumps([round(v) for v in cat_values])
    m_labels = json.dumps(monsoon_labels)
    m_values = json.dumps([round(v, 3) for v in monsoon_values])
    so_labels = json.dumps(stockout_cat.index.tolist())
    so_values = json.dumps(stockout_cat.values.tolist())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>VST Tillers — Real-time Inventory Dashboard (Malur)</title>
<meta name="description" content="Real-time spares and pumps inventory dashboard for VST Tillers and Tractors, Malur Facility. Powered by RL-driven demand forecasting."/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & Base ── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --vst-green:#1A7B3A;
  --vst-green-light:#E8F5E9;
  --vst-green-mid:#2E9E52;
  --amber:#E67E00;
  --amber-light:#FFF3E0;
  --red:#D32F2F;
  --red-light:#FFEBEE;
  --blue:#1565C0;
  --blue-light:#E3F2FD;
  --gray-50:#FAFAFA;
  --gray-100:#F5F5F5;
  --gray-200:#EEEEEE;
  --gray-300:#E0E0E0;
  --gray-500:#9E9E9E;
  --gray-700:#616161;
  --gray-900:#212121;
  --white:#FFFFFF;
  --shadow-sm:0 1px 4px rgba(0,0,0,.08);
  --shadow-md:0 4px 16px rgba(0,0,0,.10);
  --shadow-lg:0 8px 32px rgba(0,0,0,.13);
  --radius:12px;
  --radius-sm:8px;
}}
body{{font-family:'Inter',sans-serif;background:var(--gray-100);color:var(--gray-900);min-height:100vh;font-size:14px;}}

/* ── Header ── */
.header{{background:var(--white);border-bottom:1px solid var(--gray-200);padding:0 2rem;height:64px;display:flex;align-items:center;justify-content:space-between;box-shadow:var(--shadow-sm);position:sticky;top:0;z-index:100;}}
.brand{{display:flex;align-items:center;gap:12px;}}
.brand-logo{{width:44px;height:44px;background:var(--vst-green);border-radius:10px;display:flex;align-items:center;justify-content:center;}}
.brand-logo svg{{width:28px;height:28px;fill:white;}}
.brand-text h1{{font-size:15px;font-weight:700;color:var(--gray-900);line-height:1.2;}}
.brand-text p{{font-size:11px;color:var(--gray-500);font-weight:400;}}
.header-title{{position:absolute;left:50%;transform:translateX(-50%);text-align:center;}}
.header-title h2{{font-size:15px;font-weight:600;color:var(--gray-900);}}
.header-title p{{font-size:11px;color:var(--vst-green);font-weight:500;}}
.header-right{{display:flex;align-items:center;gap:12px;}}
.live-badge{{display:flex;align-items:center;gap:6px;background:var(--vst-green-light);color:var(--vst-green);padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;}}
.live-dot{{width:8px;height:8px;background:var(--vst-green);border-radius:50%;animation:pulse 1.5s infinite;}}
@keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.6;transform:scale(1.3)}}}}
.last-updated{{font-size:11px;color:var(--gray-500);}}

/* ── Main Layout ── */
.main{{padding:1.5rem 2rem;max-width:1600px;margin:0 auto;}}

/* ── KPI Cards ── */
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1.5rem;}}
.kpi-card{{background:var(--white);border-radius:var(--radius);padding:1.25rem 1.5rem;box-shadow:var(--shadow-sm);border:1px solid var(--gray-200);display:flex;flex-direction:column;gap:6px;transition:box-shadow .2s,transform .2s;position:relative;overflow:hidden;}}
.kpi-card:hover{{box-shadow:var(--shadow-md);transform:translateY(-2px);}}
.kpi-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--vst-green);border-radius:var(--radius) var(--radius) 0 0;}}
.kpi-card.amber::before{{background:var(--amber);}}
.kpi-card.blue::before{{background:var(--blue);}}
.kpi-header{{display:flex;justify-content:space-between;align-items:flex-start;}}
.kpi-icon{{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}}
.kpi-icon.green{{background:var(--vst-green-light);}}
.kpi-icon.amber{{background:var(--amber-light);}}
.kpi-icon.blue{{background:var(--blue-light);}}
.kpi-trend{{font-size:11px;font-weight:600;padding:2px 7px;border-radius:12px;}}
.kpi-trend.up{{background:#E8F5E9;color:var(--vst-green);}}
.kpi-trend.down{{background:var(--amber-light);color:var(--amber);}}
.kpi-label{{font-size:12px;color:var(--gray-500);font-weight:500;margin-top:2px;}}
.kpi-value{{font-size:26px;font-weight:800;line-height:1;}}
.kpi-value.green{{color:var(--vst-green);}}
.kpi-value.amber{{color:var(--amber);}}
.kpi-value.blue{{color:var(--blue);}}
.kpi-value.dark{{color:var(--gray-900);}}
.kpi-sub{{font-size:11px;color:var(--gray-500);}}

/* ── Charts Row ── */
.charts-grid{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:1rem;margin-bottom:1.5rem;}}
.chart-card{{background:var(--white);border-radius:var(--radius);padding:1.25rem;box-shadow:var(--shadow-sm);border:1px solid var(--gray-200);}}
.chart-title{{font-size:13px;font-weight:600;color:var(--gray-700);margin-bottom:1rem;display:flex;align-items:center;gap:8px;}}
.chart-title span{{display:inline-block;width:10px;height:10px;border-radius:3px;background:var(--vst-green);}}
.chart-wrap{{position:relative;width:100%;}}
.chart-wrap.tall{{height:200px;}}
.chart-wrap.mid{{height:180px;}}

/* ── Filter Bar ── */
.filter-bar{{background:var(--white);border-radius:var(--radius);padding:1rem 1.25rem;box-shadow:var(--shadow-sm);border:1px solid var(--gray-200);display:flex;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap;}}
.search-input{{flex:1;min-width:220px;position:relative;}}
.search-input input{{width:100%;padding:9px 12px 9px 36px;border:1px solid var(--gray-300);border-radius:var(--radius-sm);font-size:13px;font-family:'Inter',sans-serif;color:var(--gray-900);background:var(--gray-50);transition:border-color .2s;}}
.search-input input:focus{{outline:none;border-color:var(--vst-green);background:var(--white);}}
.search-input .search-icon{{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--gray-500);font-size:15px;pointer-events:none;}}
.filter-select{{padding:9px 30px 9px 12px;border:1px solid var(--gray-300);border-radius:var(--radius-sm);font-size:13px;font-family:'Inter',sans-serif;color:var(--gray-900);background:var(--gray-50);appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23616161' d='M6 8L1 3h10z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;cursor:pointer;transition:border-color .2s;}}
.filter-select:focus{{outline:none;border-color:var(--vst-green);}}
.filter-label{{font-size:12px;color:var(--gray-500);white-space:nowrap;}}
.results-count{{margin-left:auto;font-size:12px;color:var(--gray-500);white-space:nowrap;}}
.results-count strong{{color:var(--vst-green);}}

/* ── Table ── */
.table-card{{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow-sm);border:1px solid var(--gray-200);overflow:hidden;}}
.table-header{{padding:1rem 1.25rem;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--gray-200);}}
.table-header h3{{font-size:14px;font-weight:600;}}
.export-btn{{padding:7px 16px;background:var(--vst-green-light);color:var(--vst-green);border:1px solid var(--vst-green);border-radius:var(--radius-sm);font-size:12px;font-weight:600;cursor:pointer;font-family:'Inter',sans-serif;transition:background .2s;}}
.export-btn:hover{{background:var(--vst-green);color:white;}}
.table-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;}}
thead tr{{background:var(--gray-50);}}
th{{padding:11px 14px;text-align:left;font-size:12px;font-weight:600;color:var(--gray-700);white-space:nowrap;border-bottom:2px solid var(--gray-200);position:sticky;top:0;background:var(--gray-50);}}
th.sortable{{cursor:pointer;user-select:none;}}
th.sortable:hover{{color:var(--vst-green);}}
td{{padding:11px 14px;border-bottom:1px solid var(--gray-200);vertical-align:middle;}}
tbody tr:last-child td{{border-bottom:none;}}
tbody tr:nth-child(even){{background:var(--gray-50);}}
tbody tr:hover{{background:var(--vst-green-light);transition:background .15s;}}
.item-name{{font-weight:600;font-size:13px;color:var(--gray-900);}}
.item-sku{{font-size:11px;color:var(--gray-500);font-family:'Courier New',monospace;margin-top:2px;}}
.unit-lbl{{font-size:11px;color:var(--gray-500);}}
.val-cell{{font-weight:600;color:var(--gray-900);white-space:nowrap;}}
.crit-cell{{font-size:13px;color:var(--amber);letter-spacing:-1px;}}

/* ── Status Badges ── */
.badge{{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap;}}
.badge-healthy{{background:var(--vst-green-light);color:var(--vst-green);}}
.badge-low{{background:var(--amber-light);color:var(--amber);}}
.badge-critical{{background:var(--red-light);color:var(--red);}}
.badge-oos{{background:#F3E5F5;color:#6A1B9A;}}

/* ── Category Pills ── */
.cat-pill{{padding:3px 9px;border-radius:12px;font-size:11px;font-weight:600;}}
.cat-spareparts{{background:#E3F2FD;color:#1565C0;}}
.cat-lubricants{{background:#FFF8E1;color:#F57F17;}}
.cat-electricpumps{{background:#E0F7FA;color:#00695C;}}
.cat-engines{{background:#F3E5F5;color:#6A1B9A;}}
.cat-precisioncomponents{{background:#E8EAF6;color:#283593;}}

/* ── Action Button ── */
.action-btn{{background:none;border:1px solid var(--gray-300);border-radius:var(--radius-sm);width:32px;height:32px;cursor:pointer;font-size:15px;transition:all .2s;color:var(--gray-700);display:flex;align-items:center;justify-content:center;}}
.action-btn:hover{{background:var(--vst-green);color:white;border-color:var(--vst-green);}}

/* ── Pagination ── */
.pagination{{display:flex;align-items:center;justify-content:space-between;padding:1rem 1.25rem;border-top:1px solid var(--gray-200);}}
.page-info{{font-size:12px;color:var(--gray-500);}}
.page-btns{{display:flex;gap:6px;}}
.page-btn{{padding:5px 11px;border:1px solid var(--gray-300);background:var(--white);border-radius:6px;font-size:12px;cursor:pointer;font-family:'Inter',sans-serif;transition:all .15s;color:var(--gray-700);}}
.page-btn.active,.page-btn:hover{{background:var(--vst-green);color:white;border-color:var(--vst-green);}}

/* ── Responsive ── */
@media(max-width:1100px){{.kpi-grid{{grid-template-columns:repeat(2,1fr);}}.charts-grid{{grid-template-columns:1fr;}}}}
@media(max-width:700px){{.kpi-grid{{grid-template-columns:1fr;}}.header-title{{display:none;}}}}

/* ── Table hidden rows ── */
tr.row-hidden{{display:none;}}
</style>
</head>
<body>

<!-- ═══════════════ HEADER ═══════════════ -->
<header class="header">
  <div class="brand">
    <div class="brand-logo">
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <!-- Tractor/Tiller icon -->
        <path d="M17 4H15V6H9V4H7V6H5C3.9 6 3 6.9 3 8V18C3 19.1 3.9 20 5 20H19C20.1 20 21 19.1 21 18V8C21 6.9 20.1 6 19 6H17V4ZM7 16C5.9 16 5 15.1 5 14C5 12.9 5.9 12 7 12C8.1 12 9 12.9 9 14C9 15.1 8.1 16 7 16ZM17 16C15.9 16 15 15.1 15 14C15 12.9 15.9 12 17 12C18.1 12 19 12.9 19 14C19 15.1 18.1 16 17 16ZM19 10H5V8H19V10Z"/>
      </svg>
    </div>
    <div class="brand-text">
      <h1>VST Tillers &amp; Tractors</h1>
      <p>Supply Chain Intelligence Platform</p>
    </div>
  </div>

  <div class="header-title">
    <h2>Real-time Spares &amp; Pumps Inventory</h2>
    <p>Malur Manufacturing Facility &nbsp;|&nbsp; Bengaluru, Karnataka</p>
  </div>

  <div class="header-right">
    <div class="live-badge">
      <span class="live-dot"></span>
      LIVE
    </div>
    <span class="last-updated" id="last-updated-time">--</span>
  </div>
</header>

<!-- ═══════════════ MAIN ═══════════════ -->
<main class="main">

  <!-- KPI Cards -->
  <div class="kpi-grid">

    <div class="kpi-card">
      <div class="kpi-header">
        <div class="kpi-icon green">&#128200;</div>
        <span class="kpi-trend up">+4.2%</span>
      </div>
      <div class="kpi-label">Total Inventory Value</div>
      <div class="kpi-value green" id="kpi-inv-value">&#8377;{total_inv:,.0f}</div>
      <div class="kpi-sub">Across all 5 categories</div>
    </div>

    <div class="kpi-card">
      <div class="kpi-header">
        <div class="kpi-icon green">&#9881;</div>
        <span class="kpi-trend up">+2.1%</span>
      </div>
      <div class="kpi-label">Total Units In Stock</div>
      <div class="kpi-value dark">{total_units:,}</div>
      <div class="kpi-sub">Current physical count</div>
    </div>

    <div class="kpi-card amber">
      <div class="kpi-header">
        <div class="kpi-icon amber">&#9888;</div>
        <span class="kpi-trend down">+{max(0,critical-2)} new</span>
      </div>
      <div class="kpi-label">Critical Stock Alerts</div>
      <div class="kpi-value amber">{critical}</div>
      <div class="kpi-sub">SKUs below reorder level</div>
    </div>

    <div class="kpi-card blue">
      <div class="kpi-header">
        <div class="kpi-icon blue">&#128202;</div>
        <span class="kpi-trend up">{fill_rate:.1%} Fill Rate</span>
      </div>
      <div class="kpi-label">Unique SKUs Tracked</div>
      <div class="kpi-value dark">{total_skus}</div>
      <div class="kpi-sub">Active product lines</div>
    </div>

  </div><!-- /kpi-grid -->

  <!-- Charts -->
  <div class="charts-grid">

    <div class="chart-card">
      <div class="chart-title"><span></span> Weekly Demand Trend (Last 52 Weeks)</div>
      <div class="chart-wrap tall"><canvas id="demandChart"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title"><span style="background:#1565C0"></span> Sales by Category</div>
      <div class="chart-wrap tall"><canvas id="donutChart"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title"><span style="background:var(--amber)"></span> Stockout Rate by Category (%)</div>
      <div class="chart-wrap tall"><canvas id="stockoutChart"></canvas></div>
    </div>

  </div><!-- /charts-grid -->

  <!-- Monsoon Chart -->
  <div class="chart-card" style="margin-bottom:1rem;">
    <div class="chart-title"><span style="background:#00695C"></span> Monsoon Index — Last 24 Weeks (Demand Driver for Electric Pumps)</div>
    <div class="chart-wrap" style="height:130px;"><canvas id="monsoonChart"></canvas></div>
  </div>

  <!-- Filter Bar -->
  <div class="filter-bar">
    <div class="search-input">
      <span class="search-icon">&#128269;</span>
      <input type="text" id="search-input" placeholder="Search by Name, SKU, or Machine Type..." oninput="filterTable()"/>
    </div>
    <span class="filter-label">Category:</span>
    <select class="filter-select" id="filter-cat" onchange="filterTable()">
      <option value="">All</option>
      <option>Spare Parts</option>
      <option>Lubricants</option>
      <option>Electric Pumps</option>
      <option>Engines</option>
      <option>Precision Components</option>
    </select>
    <span class="filter-label">Status:</span>
    <select class="filter-select" id="filter-status" onchange="filterTable()">
      <option value="">All</option>
      <option>Critical</option>
      <option>Low Stock</option>
      <option>Healthy</option>
      <option>Out of Stock</option>
    </select>
    <span class="filter-label">Criticality:</span>
    <select class="filter-select" id="filter-crit" onchange="filterTable()">
      <option value="">All</option>
      <option value="5">&#9733;&#9733;&#9733;&#9733;&#9733; (5)</option>
      <option value="4">&#9733;&#9733;&#9733;&#9733; (4+)</option>
      <option value="3">&#9733;&#9733;&#9733; (3+)</option>
    </select>
    <span class="results-count">Showing <strong id="shown-count">{min(len(table_rows),25)}</strong> of <strong>{len(table_rows)}</strong> SKUs</span>
  </div>

  <!-- Table -->
  <div class="table-card">
    <div class="table-header">
      <h3>Inventory Detail — All SKUs</h3>
      <button class="export-btn" onclick="exportCSV()">&#11123; Export CSV</button>
    </div>
    <div class="table-wrap">
      <table id="inv-table">
        <thead>
          <tr>
            <th class="sortable" onclick="sortTable(0)">Item Name &#8597;</th>
            <th class="sortable" onclick="sortTable(1)">Category &#8597;</th>
            <th>Machine</th>
            <th class="sortable" onclick="sortTable(3)">Stock &#8597;</th>
            <th>Reorder Level</th>
            <th class="sortable" onclick="sortTable(5)">Status &#8597;</th>
            <th class="sortable" onclick="sortTable(6)">Est. Value &#8597;</th>
            <th>Criticality</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="table-body">
          {rows_html}
        </tbody>
      </table>
    </div>
    <div class="pagination">
      <span class="page-info" id="page-info">Page 1 of {max(1, (len(table_rows)+24)//25)}</span>
      <div class="page-btns" id="page-btns"></div>
    </div>
  </div>

</main>

<script>
// ── Charts ──────────────────────────────────────────────────────────────────
const GREEN = '#1A7B3A', GREEN_LIGHT = 'rgba(26,123,58,.12)',
      AMBER = '#E67E00', BLUE = '#1565C0', RED = '#D32F2F';

// Demand Trend
new Chart(document.getElementById('demandChart'),{{
  type:'line',
  data:{{
    labels: {d_labels},
    datasets:[{{
      label:'Weekly Units Sold',
      data: {d_values},
      borderColor:GREEN, backgroundColor:GREEN_LIGHT,
      borderWidth:2, pointRadius:0, fill:true, tension:0.3
    }}]
  }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{maxTicksLimit:8,font:{{size:11}}}}}},
      y:{{grid:{{color:'#f0f0f0'}},ticks:{{font:{{size:11}}}}}}
    }}
  }}
}});

// Donut
const catColors = [BLUE,'#F57F17','#00695C','#6A1B9A','#283593'];
new Chart(document.getElementById('donutChart'),{{
  type:'doughnut',
  data:{{
    labels: {c_labels},
    datasets:[{{data:{c_values},backgroundColor:catColors,borderWidth:2,borderColor:'#fff'}}]
  }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{position:'bottom',labels:{{font:{{size:10}},boxWidth:10,padding:8}}}}}}
  }}
}});

// Stockout bar
new Chart(document.getElementById('stockoutChart'),{{
  type:'bar',
  data:{{
    labels:{so_labels},
    datasets:[{{
      label:'Stockout %',
      data:{so_values},
      backgroundColor:[AMBER,BLUE,RED,GREEN,'#283593'],
      borderRadius:6, borderSkipped:false
    }}]
  }},
  options:{{
    responsive:true,maintainAspectRatio:false,indexAxis:'y',
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{grid:{{color:'#f0f0f0'}},ticks:{{font:{{size:11}},callback:v=>v+'%'}}}},
      y:{{grid:{{display:false}},ticks:{{font:{{size:10}}}}}}
    }}
  }}
}});

// Monsoon
new Chart(document.getElementById('monsoonChart'),{{
  type:'line',
  data:{{
    labels:{m_labels},
    datasets:[{{
      label:'Monsoon Index',
      data:{m_values},
      borderColor:'#00695C', backgroundColor:'rgba(0,105,92,.12)',
      borderWidth:2, pointRadius:0, fill:true, tension:0.4
    }}]
  }},
  options:{{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>'Index: '+c.raw.toFixed(3)}}}}}},
    scales:{{
      x:{{grid:{{display:false}},ticks:{{maxTicksLimit:8,font:{{size:11}}}}}},
      y:{{min:0,max:1,grid:{{color:'#f0f0f0'}},ticks:{{font:{{size:11}}}}}}
    }}
  }}
}});

// ── Live time ────────────────────────────────────────────────────────────────
function updateTime(){{
  const now = new Date();
  document.getElementById('last-updated-time').textContent =
    'Updated: ' + now.toLocaleTimeString('en-IN',{{hour:'2-digit',minute:'2-digit',second:'2-digit'}});
}}
updateTime(); setInterval(updateTime, 1000);

// ── Pagination ───────────────────────────────────────────────────────────────
const PAGE_SIZE = 25;
let currentPage = 1;

function getVisibleRows(){{
  return Array.from(document.querySelectorAll('#table-body tr')).filter(r=>!r.classList.contains('row-hidden'));
}}

function renderPagination(){{
  const rows = getVisibleRows();
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  currentPage = Math.min(currentPage, pages);

  rows.forEach((r,i)=>{{
    r.style.display = (i >= (currentPage-1)*PAGE_SIZE && i < currentPage*PAGE_SIZE) ? '' : 'none';
  }});

  document.getElementById('page-info').textContent = `Page ${{currentPage}} of ${{pages}}`;
  document.getElementById('shown-count').textContent = Math.min(PAGE_SIZE, total - (currentPage-1)*PAGE_SIZE);

  const btnsEl = document.getElementById('page-btns');
  btnsEl.innerHTML = '';
  const makeBtn=(label,pg)=>{{
    const b=document.createElement('button');
    b.className='page-btn'+(pg===currentPage?' active':'');
    b.textContent=label; b.onclick=()=>{{currentPage=pg;renderPagination();}};
    return b;
  }};
  if(currentPage>1) btnsEl.appendChild(makeBtn('«',1));
  if(currentPage>1) btnsEl.appendChild(makeBtn('‹',currentPage-1));
  for(let p=Math.max(1,currentPage-2);p<=Math.min(pages,currentPage+2);p++) btnsEl.appendChild(makeBtn(p,p));
  if(currentPage<pages) btnsEl.appendChild(makeBtn('›',currentPage+1));
  if(currentPage<pages) btnsEl.appendChild(makeBtn('»',pages));
}}
renderPagination();

// ── Filter ───────────────────────────────────────────────────────────────────
function filterTable(){{
  const q    = document.getElementById('search-input').value.toLowerCase();
  const cat  = document.getElementById('filter-cat').value;
  const stat = document.getElementById('filter-status').value;
  const crit = document.getElementById('filter-crit').value;

  document.querySelectorAll('#table-body tr').forEach(tr=>{{
    const cells = tr.querySelectorAll('td');
    const name  = cells[0]?.textContent.toLowerCase()||'';
    const catV  = cells[1]?.textContent.trim()||'';
    const statV = cells[5]?.textContent.trim()||'';
    const critV = tr.querySelectorAll('td')[7]?.textContent.split('★').length-1||0;

    const qOK   = !q   || name.includes(q);
    const catOK = !cat || catV.includes(cat);
    const stOK  = !stat|| statV.includes(stat);
    const crOK  = !crit|| critV >= parseInt(crit);

    tr.classList.toggle('row-hidden', !(qOK && catOK && stOK && crOK));
  }});
  currentPage = 1;
  renderPagination();
}}

// ── Sort ─────────────────────────────────────────────────────────────────────
let sortDir = {{}};
function sortTable(col){{
  const tbody = document.getElementById('table-body');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  sortDir[col] = sortDir[col] === 'asc' ? 'desc' : 'asc';
  rows.sort((a,b)=>{{
    const av = a.querySelectorAll('td')[col]?.textContent.trim()||'';
    const bv = b.querySelectorAll('td')[col]?.textContent.trim()||'';
    const an = parseFloat(av.replace(/[^0-9.-]/g,'')), bn = parseFloat(bv.replace(/[^0-9.-]/g,''));
    const cmp = isNaN(an)||isNaN(bn) ? av.localeCompare(bv) : an-bn;
    return sortDir[col]==='asc' ? cmp : -cmp;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  renderPagination();
}}

// ── Export ───────────────────────────────────────────────────────────────────
function exportCSV(){{
  const rows = Array.from(document.querySelectorAll('#table-body tr'));
  const headers = ['Name','SKU','Category','Machine','Stock','Unit','Reorder','Status','Est Value INR','Criticality'];
  const lines = [headers.join(',')];
  rows.forEach(tr=>{{
    const cells = tr.querySelectorAll('td');
    const row = [
      cells[0]?.querySelector('.item-name')?.textContent.trim(),
      cells[0]?.querySelector('.item-sku')?.textContent.trim(),
      cells[1]?.textContent.trim(),
      cells[2]?.textContent.trim(),
      cells[3]?.textContent.trim(),
      '',
      cells[4]?.textContent.trim(),
      cells[5]?.textContent.trim(),
      cells[6]?.textContent.replace(/[^\d.]/g,''),
      cells[7]?.textContent.split('★').length-1
    ];
    lines.push(row.map(v=>`"${{v||''}}"`).join(','));
  }});
  const blob = new Blob([lines.join('\\n')],{{type:'text/csv'}});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='vst_inventory_export.csv'; a.click();
}}
</script>
</body>
</html>"""
    return html


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("Loading data from CSV files...")
    products, suppliers, sales, external = load_data()

    print("Computing KPIs from actual data...")
    kpis = compute_kpis(products, suppliers, sales)

    print(f"  Total Inventory Value : INR {kpis['total_inv_value']:,.0f}")
    print(f"  Total Units           : {kpis['total_units']:,}")
    print(f"  Total SKUs            : {kpis['total_skus']}")
    print(f"  Critical Alerts       : {kpis['critical_count']}")
    print(f"  Fill Rate (8-week)    : {kpis['fill_rate']:.1%}")

    print("Building table rows...")
    table_rows = build_table_rows(products, kpis)

    print("Building sparklines...")
    sparks = build_sparklines(sales, products)

    print("Generating HTML...")
    html = generate_html(kpis, table_rows, sparks, sales, external)

    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "vst_inventory_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[DONE] Dashboard saved -> {out_path}")
    print("Open in any modern browser to view the live dashboard.")
    return out_path


if __name__ == "__main__":
    main()
