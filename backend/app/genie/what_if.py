"""
What-If Scenario Simulator for Genie Chatbot.

Answers questions like:
  - "What if lead time from China increases by 15 days?"
  - "What if demand for Spare Parts spikes by 25%?"
  - "Which items are at risk of shelf-life expiry?"
  - "What if a Japan supplier can't deliver for 8 weeks?"

Each method returns a plain dict; the orchestration layer (engine) and
what-if agent are responsible for turning that dict into a markdown summary.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app.forecasting.data_pipeline import (
    load_products_data,
    load_sales_data,
    load_suppliers_data,
)

logger = logging.getLogger(__name__)


class WhatIfSimulator:
    """Runs supply-chain what-if simulations using inventory + sales data."""

    def __init__(self):
        self._products: Optional[pd.DataFrame] = None
        self._suppliers: Optional[pd.DataFrame] = None
        self._sales: Optional[pd.DataFrame] = None

    # ── Data loading (lazy, cached per-instance) ──────────────────────
    def _load_data(self, db=None):
        """Load products/suppliers from CSV dims and sales from the LIVE DB
        when a session is provided (CSV only as last resort)."""
        if self._sales is None or db is not None:
            try:
                df = load_sales_data(db)
                if db is not None or self._sales is None:
                    self._sales = df
            except Exception:
                if self._sales is None:
                    self._sales = pd.DataFrame()
        if self._products is None:
            try:
                self._products = load_products_data()
            except Exception:
                self._products = pd.DataFrame()
        if self._suppliers is None:
            try:
                self._suppliers = load_suppliers_data()
            except Exception:
                self._suppliers = pd.DataFrame()

    # ── Burn-rate + stock helpers ─────────────────────────────────────
    def _burn_rates(self, weeks: int = 13) -> dict:
        """Per-SKU average weekly demand over the most recent `weeks` window."""
        if self._sales is None or len(self._sales) == 0:
            return {}
        df = self._sales.copy()
        df["Date"] = pd.to_datetime(df["Date"])
        cutoff = df["Date"].max() - timedelta(weeks=weeks)
        recent = df[df["Date"] >= cutoff]
        if len(recent) == 0:
            return {}
        rates = recent.groupby("SKU_ID")["Units_Sold"].mean()
        return {k: float(v) for k, v in rates.items()}

    def _estimated_stock(self, burn_rate: float, coverage_weeks: int = 8) -> float:
        """No live inventory table exists in the schema yet, so we estimate
        on-hand stock from the historical burn rate × 8 weeks coverage.
        This mirrors the convention used by the reorder-recommendations endpoint."""
        return round(burn_rate * coverage_weeks)

    def _trend_ratio(self, sku_id: str) -> float:
        """Last-4w / previous-4w ratio. > 1 means accelerating demand."""
        if self._sales is None or len(self._sales) == 0:
            return 1.0
        df = self._sales[self._sales["SKU_ID"] == sku_id].copy()
        if len(df) == 0:
            return 1.0
        df["Date"] = pd.to_datetime(df["Date"])
        max_date = df["Date"].max()
        recent_4w = df[df["Date"] >= max_date - timedelta(weeks=4)]["Units_Sold"].sum()
        prev_4w = df[
            (df["Date"] >= max_date - timedelta(weeks=8))
            & (df["Date"] < max_date - timedelta(weeks=4))
        ]["Units_Sold"].sum()
        return float(recent_4w / prev_4w) if prev_4w > 0 else 1.0

    # ── Scenario: lead-time increase ──────────────────────────────────
    def lead_time_impact(
        self,
        supplier_id: str = None,
        origin_country: str = None,
        additional_days: int = 15,
        db=None,
    ) -> dict:
        """If lead time from supplier/country rises by X days, which SKUs shortfall?"""
        self._load_data(db)
        suppliers, products = self._suppliers, self._products
        if suppliers is None or products is None or len(suppliers) == 0:
            return {"scenario": "Lead time impact", "error": "Supplier / product data unavailable"}

        if supplier_id:
            affected = suppliers[suppliers["Supplier_ID"] == supplier_id]
            scope_label = supplier_id
        elif origin_country:
            affected = suppliers[
                suppliers["Origin_Country"].str.contains(origin_country, case=False, na=False)
            ]
            scope_label = origin_country
        else:
            affected = suppliers
            scope_label = "all origins"

        if len(affected) == 0:
            return {
                "scenario": f"Lead time +{additional_days}d from {scope_label}",
                "error": "No matching suppliers",
            }

        affected_cats = affected["Primary_Category"].unique().tolist()
        burn = self._burn_rates()
        at_risk = []
        for _, prod in products.iterrows():
            cat = prod["Category"]
            if cat not in affected_cats:
                continue
            sku_id = prod["SKU_ID"]
            weekly = burn.get(sku_id, 5.0)
            cat_sup = affected[affected["Primary_Category"] == cat]
            base_lead_days = float(cat_sup["Base_Lead_Time_Days"].mean()) if len(cat_sup) > 0 else 30
            new_lead_weeks = (base_lead_days + additional_days) / 7
            estimated_stock = self._estimated_stock(weekly)
            coverage_weeks = estimated_stock / max(weekly, 0.1)
            if coverage_weeks < new_lead_weeks:
                at_risk.append({
                    "sku_id": sku_id,
                    "category": cat,
                    "weekly_demand": round(weekly, 1),
                    "estimated_stock": int(estimated_stock),
                    "coverage_weeks": round(coverage_weeks, 1),
                    "new_lead_weeks": round(new_lead_weeks, 1),
                    "shortfall_weeks": round(new_lead_weeks - coverage_weeks, 1),
                    "risk_level": "CRITICAL" if coverage_weeks < new_lead_weeks * 0.5 else "HIGH",
                })

        at_risk.sort(key=lambda x: -x["shortfall_weeks"])
        return {
            "scenario": f"Lead time from {scope_label} +{additional_days} days",
            "affected_suppliers": int(len(affected)),
            "affected_categories": affected_cats,
            "total_at_risk_skus": len(at_risk),
            "critical_count": sum(1 for r in at_risk if r["risk_level"] == "CRITICAL"),
            "at_risk_skus": at_risk[:20],
            "recommendation": self._lead_time_recommendation(at_risk, additional_days),
        }

    # ── Scenario: demand spike ────────────────────────────────────────
    def demand_spike_impact(
        self,
        category: str = None,
        spike_percent: float = 20.0,
        db=None,
    ) -> dict:
        """If demand for a category grows by X%, which SKUs run short?"""
        self._load_data(db)
        products = self._products
        if products is None or len(products) == 0:
            return {"scenario": "Demand spike", "error": "Product data unavailable"}

        if category:
            products = products[
                products["Category"].str.contains(category, case=False, na=False)
            ]

        burn = self._burn_rates()
        impacted = []
        multiplier = 1 + spike_percent / 100
        for _, prod in products.iterrows():
            sku_id = prod["SKU_ID"]
            base = burn.get(sku_id, 5.0)
            new_demand = base * multiplier
            stock = self._estimated_stock(base)
            cov_before = stock / max(base, 0.1)
            cov_after = stock / max(new_demand, 0.1)
            if cov_after < 6:
                impacted.append({
                    "sku_id": sku_id,
                    "category": prod["Category"],
                    "current_weekly_demand": round(base, 1),
                    "projected_weekly_demand": round(new_demand, 1),
                    "estimated_stock": int(stock),
                    "coverage_before_weeks": round(cov_before, 1),
                    "coverage_after_weeks": round(cov_after, 1),
                    "additional_stock_needed": round((new_demand - base) * 8),
                })

        impacted.sort(key=lambda x: x["coverage_after_weeks"])
        return {
            "scenario": f"{spike_percent}% demand increase for {category or 'all categories'}",
            "total_impacted_skus": len(impacted),
            "impacted_skus": impacted[:20],
            "total_additional_units_needed": int(sum(i["additional_stock_needed"] for i in impacted)),
        }

    # ── Scenario: shelf-life / expiry risk ────────────────────────────
    def shelf_life_risk(self, threshold_days: int = 90, db=None) -> dict:
        """Identify items whose shelf life is at risk of expiry."""
        self._load_data(db)
        products = self._products
        if products is None or len(products) == 0:
            return {"scenario": "Shelf-life risk", "error": "Product data unavailable"}

        has_shelf = products[
            products["Shelf_Life_Days"].notna() & (products["Shelf_Life_Days"] > 0)
        ]
        at_risk = []
        if len(has_shelf) == 0:
            lubricants = products[products["Category"] == "Lubricants"]
            for _, prod in lubricants.iterrows():
                at_risk.append({
                    "sku_id": prod["SKU_ID"],
                    "category": prod["Category"],
                    "sub_category": prod.get("Sub_Category", ""),
                    "shelf_life_days": 1095,
                    "risk_level": "MONITOR",
                })
            return {
                "scenario": f"Items with shelf life ≤ {threshold_days} days",
                "note": "Shelf-life data not populated. Showing lubricants (typical 3-year shelf life) for monitoring.",
                "at_risk_items": at_risk[:10],
                "recommendation": "Add batch / manufacturing date tracking for accurate expiry monitoring.",
            }

        for _, prod in has_shelf.iterrows():
            sl = float(prod["Shelf_Life_Days"])
            if sl <= threshold_days:
                at_risk.append({
                    "sku_id": prod["SKU_ID"],
                    "category": prod["Category"],
                    "sub_category": prod.get("Sub_Category", ""),
                    "shelf_life_days": int(sl),
                    "risk_level": "HIGH" if sl <= threshold_days / 2 else "MEDIUM",
                })

        return {
            "scenario": f"Items with shelf life ≤ {threshold_days} days",
            "total_at_risk": len(at_risk),
            "at_risk_items": at_risk,
        }

    # ── Scenario: supplier failure ────────────────────────────────────
    def supplier_failure(
        self,
        supplier_id: str = None,
        origin_country: str = None,
        failure_weeks: int = 8,
        db=None,
    ) -> dict:
        """If a supplier/country is unavailable for X weeks, which SKUs stockout?"""
        self._load_data(db)
        suppliers, products = self._suppliers, self._products
        if suppliers is None or products is None:
            return {"scenario": "Supplier failure", "error": "Data unavailable"}

        if supplier_id:
            failed = suppliers[suppliers["Supplier_ID"] == supplier_id]
        elif origin_country:
            failed = suppliers[
                suppliers["Origin_Country"].str.contains(origin_country, case=False, na=False)
            ]
        else:
            return {"scenario": "Supplier failure", "error": "Specify supplier_id or origin_country"}

        if len(failed) == 0:
            return {"scenario": "Supplier failure", "error": "No matching suppliers"}

        affected_cats = failed["Primary_Category"].unique().tolist()
        affected_products = products[products["Category"].isin(affected_cats)]
        burn = self._burn_rates()

        risk = []
        for _, prod in affected_products.iterrows():
            sku_id = prod["SKU_ID"]
            demand = burn.get(sku_id, 5.0)
            stock = self._estimated_stock(demand)
            runway = stock / max(demand, 0.1)
            if runway < failure_weeks:
                risk.append({
                    "sku_id": sku_id,
                    "category": prod["Category"],
                    "weekly_demand": round(demand, 1),
                    "estimated_stock": int(stock),
                    "runway_weeks": round(runway, 1),
                    "weeks_short": round(failure_weeks - runway, 1),
                    "stockout_date_estimate": (datetime.now() + timedelta(weeks=runway)).strftime("%Y-%m-%d"),
                })

        risk.sort(key=lambda x: x["runway_weeks"])
        sup_info = failed.iloc[0] if len(failed) > 0 else pd.Series()
        return {
            "scenario": f"{'Supplier ' + supplier_id if supplier_id else origin_country} unavailable for {failure_weeks} weeks",
            "affected_categories": affected_cats,
            "total_products_affected": int(len(affected_products)),
            "products_at_stockout_risk": len(risk),
            "stockout_risk_items": risk[:15],
            "supplier_details": {
                "id": supplier_id or "Multiple",
                "origin": str(sup_info.get("Origin_Country", origin_country or "Unknown")),
                "normal_lead_time_days": int(sup_info.get("Base_Lead_Time_Days", 0)) if len(failed) > 0 else None,
            },
            "recommendations": [
                "Identify alternate domestic suppliers for critical items.",
                "Place emergency orders for items with < 4 weeks runway.",
                "Negotiate expedited shipping for items already in transit.",
                f"Monitor {len(risk)} SKUs daily until supply resumes.",
            ],
        }

    # ── Recommendation helper ─────────────────────────────────────────
    @staticmethod
    def _lead_time_recommendation(at_risk: list, additional_days: int) -> str:
        if not at_risk:
            return "✅ No SKUs at immediate risk from this lead time increase."
        critical = sum(1 for r in at_risk if r["risk_level"] == "CRITICAL")
        return (
            f"⚠️ {len(at_risk)} SKUs at risk ({critical} CRITICAL). "
            f"Recommend: (1) Place expedited orders for CRITICAL items, "
            f"(2) Increase safety stock by {additional_days // 7 + 1} weeks for affected categories, "
            f"(3) Explore alternate suppliers for diversification."
        )


# ── Singleton ────────────────────────────────────────────────────────
_simulator: Optional[WhatIfSimulator] = None


def get_simulator() -> WhatIfSimulator:
    global _simulator
    if _simulator is None:
        _simulator = WhatIfSimulator()
    return _simulator
