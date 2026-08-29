"""
Stock Advisor Agent  ──  Expert A + B + Math for Genie.

The "Big Picture" from the Genie spec:
    You are giving the chatbot the ability to combine current reality (inventory
    data) with future predictions (forecasting data) so it can give you
    actionable advice in plain English, rather than you having to look up both
    systems separately and do the math yourself.

Flow:
  1. Parse the user question to extract:
       - target SKUs  (specific SKU or "all" / category)
       - target month  (e.g. December → month number)
  2. Expert A — current stock:
       - SqlAgent queries sales × products to compute per-SKU
         burn_rate (avg weekly demand over last 13 weeks) and
         estimated_stock (burn_rate × 8 weeks, since no live
         inventory table exists yet).
  3. Expert B — projected demand for target month:
       a. Try `forecasts` table (ensemble predictions, per-week).
       b. Fallback: EWMA trend-based projection (recent-4w / prev-4w ratio).
  4. Do the math:
       shortfall = projected_demand - estimated_stock
       recommend = max(0, shortfall) rounded to MOQ if available.
  5. Synthesize response using Gemini (or a rule-based fallback).
"""

import logging
import re
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.genie.sql_agent import get_sql_agent
from app.genie.llm_client import get_gemini_model
from app.forecasting.data_pipeline import load_products_data, load_sales_data
from app.forecasting.constants import get_risk_level

logger = logging.getLogger(__name__)


# ── Month name → number mapping ──────────────────────────────────────
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Number of weeks per month (approx, for month→week count).
WEEKS_PER_MONTH = 4.33


class StockAdvisorAgent:
    """
    Combines inventory reality (Expert A) with forecast predictions (Expert B)
    to produce an actionable reorder recommendation.
    """

    def __init__(self):
        self.sql_agent = get_sql_agent()

    # ── Public API ──────────────────────────────────────────────────
    def run(self, question: str, db: Session) -> dict:
        """
        Process a stock-advisory question.

        Returns:
          question:       original NL question
          expert_a:       dict — current stock per SKU {sku_id, category, burn_rate, estimated_stock, coverage_weeks}
          expert_b:       dict — forecast for target month {target_month, month_label, projected_demand_per_sku: [{sku_id, demand, source}]}
          math:           dict — per-SKU shortfall analysis {sku_id, shortfall, recommend, urgency}
          summary:        dict — natural-language summary text
          error:          None or error message
          data_sources:   list[str] — for confidence tagging
        """
        today = date.today()
        current_year = today.year
        target_month, target_skus, category_filter = self._parse_question(question, today)

        # ── Expert A: current stock ─────────────────────────────────
        expert_a = self._expert_a_stock(db, target_skus, category_filter)

        # Unknown SKU guardrail — don't fabricate an "all clear" for a
        # SKU that isn't in the database.
        if target_skus and expert_a.get("count", 0) == 0:
            missing = ", ".join(target_skus)
            return {
                "question": question,
                "expert_a": expert_a,
                "expert_b": {"skus": [], "count": 0},
                "math": {"skus": [], "count": 0, "total_shortfall_units": 0,
                         "total_recommended_units": 0, "skus_needing_reorder": 0},
                "summary": {
                    "text": (
                        f"I couldn't find **{missing}** in the product database. "
                        f"Please check the SKU code — valid codes look like "
                        f"`SP-FIL-0001`, `EN-DIE-0002`, `EP-MON-0012` "
                        f"(SP=Spare Parts, EN=Engines, EP=Electric Pumps, "
                        f"PC=Precision Components)."
                    ),
                    "source": "rule_based",
                },
                "error": None,
                "data_sources": [],
            }

        # ── Expert B: projected demand ──────────────────────────────
        expert_b = self._expert_b_demand(
            db, target_skus, category_filter, target_month, current_year
        )

        # ── Math: shortfall & recommendation ────────────────────────
        math_result = self._compute_shortfall(expert_a, expert_b, target_month)

        # ── Synthesize summary ──────────────────────────────────────
        summary_text = self._synthesize(question, expert_a, expert_b, math_result)

        data_sources = []
        if expert_a and expert_a.get("skus"):
            data_sources.append("db:sales")
        if expert_b and expert_b.get("skus"):
            data_sources.append("forecast:ensemble")

        return {
            "question": question,
            "expert_a": expert_a,
            "expert_b": expert_b,
            "math": math_result,
            "summary": summary_text,
            "error": None,
            "data_sources": data_sources,
        }

    # ── Parse the question ──────────────────────────────────────────
    def _parse_question(self, question: str, today: date) -> tuple[Optional[int], Optional[list], Optional[str]]:
        """Extract (target_month, target_sku_list, category_filter)."""
        q_lower = question.lower()

        # Target month
        target_month = None
        for name, num in MONTH_MAP.items():
            if name in q_lower:
                target_month = num
                break
        # If no explicit month, default to next month
        if target_month is None:
            target_month = today.month % 12 + 1

        # Target SKU(s)
        sku_match = re.findall(r"([A-Z]{2}-[A-Z]{3}-\d{4})", question, re.IGNORECASE)
        target_skus = [s.upper() for s in sku_match] if sku_match else None

        # Category filter (if no SKU given, try to extract category)
        category_filter = None
        if target_skus is None:
            for cat in ["Spare Parts", "Lubricants", "Electric Pumps", "Engines", "Precision Components"]:
                if cat.lower() in q_lower:
                    category_filter = cat
                    break
            # Shorthand
            if category_filter is None:
                if "spare" in q_lower:
                    category_filter = "Spare Parts"
                elif "pump" in q_lower:
                    category_filter = "Electric Pumps"
                elif "engine" in q_lower:
                    category_filter = "Engines"
                elif "lubricant" in q_lower:
                    category_filter = "Lubricants"

        return target_month, target_skus, category_filter

    # ── Expert A: current stock from DB ─────────────────────────────
    def _expert_a_stock(self, db: Session, target_skus: list = None, category: str = None) -> dict:
        """Compute per-SKU current stock + burn rate.

        Stock source (in priority order):
          1. Live `inventory` table (SAP-synced quantity_available).
          2. Fallback estimate = 13-week burn rate x 8 weeks coverage.
        Burn rate = AVG weekly demand over the 13 weeks before the most
        recent sale_date (not 'now'), because data may lag today.
        """
        try:
            max_date_result = db.execute(text("SELECT MAX(sale_date) FROM sales"))
            max_sale_date = max_date_result.scalar()
            if max_sale_date is None:
                return {"skus": [], "count": 0, "error": "No sales data found"}

            if isinstance(max_sale_date, str):
                max_dt = pd.to_datetime(max_sale_date).date()
            elif hasattr(max_sale_date, "date"):
                max_dt = max_sale_date.date()
            else:
                max_dt = max_sale_date

            cutoff_date = max_dt - timedelta(days=91)

            sql_parts = [
                "SELECT s.sku_id, p.category, p.sub_category, p.criticality_score,",
                "       AVG(s.units_sold) AS avg_weekly,",
                "       SUM(s.units_sold) AS total_units_13w,",
                "       COUNT(DISTINCT s.sale_date) AS weeks_active,",
                "       MAX(i.quantity_available) AS live_stock",
                "FROM sales s",
                "JOIN products p ON s.product_id = p.id",
                "LEFT JOIN inventory i ON i.sku_id = s.sku_id",
            ]
            conditions = [
                "s.sale_date >= :cutoff_date",
            ]
            params = {"cutoff_date": cutoff_date}

            if target_skus:
                placeholders = ", ".join(f"'{s}'" for s in target_skus)
                conditions.append(f"s.sku_id IN ({placeholders})")
            elif category:
                conditions.append("p.category = :cat")
                params["cat"] = category

            sql_parts.append("WHERE " + " AND ".join(conditions))
            sql_parts.append("GROUP BY s.sku_id, p.category, p.sub_category, p.criticality_score")
            sql_parts.append("ORDER BY avg_weekly DESC")

            sql = "\n".join(sql_parts)
            result = db.execute(text(sql), params)
            rows = [dict(row._mapping) for row in result.fetchall()]

            skus = []
            for r in rows:
                avg_weekly = float(r["avg_weekly"] or 0)
                live_stock = r.get("live_stock")
                if live_stock is not None:
                    estimated_stock = int(live_stock)
                    stock_source = "live_inventory"
                else:
                    estimated_stock = round(avg_weekly * 8)  # 8 weeks coverage
                    stock_source = "burn_rate_estimate"
                coverage_weeks = round(estimated_stock / avg_weekly, 1) if avg_weekly > 0 else 99
                skus.append({
                    "sku_id": r["sku_id"],
                    "category": r["category"],
                    "sub_category": r.get("sub_category", ""),
                    "avg_weekly_demand": round(avg_weekly, 1),
                    "total_units_13w": int(r["total_units_13w"] or 0),
                    "weeks_active": int(r["weeks_active"] or 0),
                    "estimated_stock": estimated_stock,
                    "stock_source": stock_source,
                    "coverage_weeks": coverage_weeks,
                })

            return {"skus": skus, "count": len(skus)}

        except Exception as e:
            logger.error("Expert A failed: %s", e)
            return {"skus": [], "count": 0, "error": str(e)}

    # ── Expert B: projected demand for target month ─────────────────
    def _expert_b_demand(
        self, db: Session, target_skus: list = None, category: str = None,
        target_month: int = None, target_year: int = None,
    ) -> dict:
        """Get projected demand for the target month per SKU.

        Strategy:
          1. Try `forecasts` table (ensemble predictions already stored).
          2. If insufficient, fall back to EWMA trend projection
             (last 4w average × trend ratio × weeks in month).
        """
        month_label = date(target_year, target_month, 1).strftime("%B %Y")
        result_skus = []

        # Strategy 1: ensemble forecasts table
        try:
            result_skus = self._demand_from_forecasts_table(
                db, target_skus, category, target_month, target_year
            )
        except Exception as e:
            logger.info("Forecast table fallback: %s", e)

        # If forecast table returned rows but all demands are zero, fall back to EWMA
        has_meaningful_forecast = any(
            s.get("monthly_demand", 0) > 0 for s in result_skus
        ) if result_skus else False

        # Strategy 2: EWMA trend (if no rows from forecasts table or all zero)
        if not result_skus or not has_meaningful_forecast:
            try:
                result_skus = self._demand_from_ewma(
                    db, target_skus, category, target_month, target_year
                )
            except Exception as e:
                logger.error("EWMA forecast failed: %s", e)

        return {
            "target_month": target_month,
            "month_label": month_label,
            "skus": result_skus,
            "count": len(result_skus),
        }

    def _demand_from_forecasts_table(
        self, db: Session, target_skus: list, category: str,
        target_month: int, target_year: int,
    ) -> list[dict]:
        """Query the forecasts table for predicted_demand in the target month."""
        start_date = date(target_year, target_month, 1)
        # End date is start of next month
        if target_month == 12:
            end_date = date(target_year + 1, 1, 1)
        else:
            end_date = date(target_year, target_month + 1, 1)

        # Check if target month exists
        r = db.execute(text(
            "SELECT COUNT(*) FROM forecasts "
            "WHERE forecast_date >= :start_date AND forecast_date < :end_date"
        ), {"start_date": start_date, "end_date": end_date})
        count = r.scalar() or 0

        if count == 0:
            # Fallback to EWMA
            return []

        sql_parts = [
            "SELECT f.sku_id, p.category, SUM(f.predicted_demand) AS monthly_demand,",
            "       COUNT(*) AS forecast_weeks,",
            "       AVG(f.predicted_demand) AS avg_weekly_forecast",
            "FROM forecasts f",
            "JOIN products p ON f.product_id = p.id",
        ]
        conditions = [
            "f.forecast_date >= :start_date AND f.forecast_date < :end_date",
        ]
        params = {"start_date": start_date, "end_date": end_date}

        if target_skus:
            placeholders = ", ".join(f"'{s}'" for s in target_skus)
            conditions.append(f"f.sku_id IN ({placeholders})")
        elif category:
            conditions.append("p.category = :cat")
            params["cat"] = category

        sql_parts.append("WHERE " + " AND ".join(conditions))
        sql_parts.append("GROUP BY f.sku_id, p.category")
        sql_parts.append("ORDER BY monthly_demand DESC")

        sql = "\n".join(sql_parts)
        result = db.execute(text(sql), params)
        rows = [dict(row._mapping) for row in result.fetchall()]

        return [
            {
                "sku_id": r["sku_id"],
                "category": r.get("category", ""),
                "monthly_demand": round(float(r["monthly_demand"] or 0), 1),
                "avg_weekly_forecast": round(float(r["avg_weekly_forecast"] or 0), 1),
                "forecast_weeks": int(r["forecast_weeks"] or 0),
                "source": "ensemble_forecast_table",
            }
            for r in rows
        ]

    def _demand_from_ewma(
        self, db: Session, target_skus: list, category: str,
        target_month: int, target_year: int,
    ) -> list[dict]:
        """EWMA trend-based projection: last 4w avg × trend_ratio × weeks_in_month."""
        try:
            # Find the latest sale date first
            max_date_result = db.execute(text("SELECT MAX(sale_date) FROM sales"))
            max_sale_date = max_date_result.scalar()
            if max_sale_date is None:
                return []
            
            if isinstance(max_sale_date, str):
                max_dt = pd.to_datetime(max_sale_date).date()
            elif hasattr(max_sale_date, "date"):
                max_dt = max_sale_date.date()
            else:
                max_dt = max_sale_date

            cutoff_date = max_dt - timedelta(days=56)

            # Get recent sales for the target SKUs (8 weeks before latest sale)
            sql_parts = [
                "SELECT s.sku_id, p.category, s.sale_date, s.units_sold",
                "FROM sales s",
                "JOIN products p ON s.product_id = p.id",
                "WHERE s.sale_date >= :cutoff_date",
            ]
            params = {"cutoff_date": cutoff_date}
            if target_skus:
                placeholders = ", ".join(f"'{s}'" for s in target_skus)
                sql_parts.append(f"AND s.sku_id IN ({placeholders})")
            elif category:
                sql_parts.append("AND p.category = :cat")
                params["cat"] = category

            sql = "\n".join(sql_parts)
            result = db.execute(text(sql), params)
            rows = [dict(row._mapping) for row in result.fetchall()]
            if not rows:
                return []


            df = pd.DataFrame(rows)
            df["sale_date"] = pd.to_datetime(df["sale_date"])
            max_date = df["sale_date"].max()

            # Recent 4 weeks
            recent_4w = df[df["sale_date"] >= max_date - pd.Timedelta(weeks=4)]
            prev_4w = df[
                (df["sale_date"] >= max_date - pd.Timedelta(weeks=8))
                & (df["sale_date"] < max_date - pd.Timedelta(weeks=4))
            ]

            sku_stats = []
            for sku_id in df["sku_id"].unique():
                sku_df = recent_4w[recent_4w["sku_id"] == sku_id]
                prev_sku = prev_4w[prev_4w["sku_id"] == sku_id]

                recent_total = float(sku_df["units_sold"].sum()) if len(sku_df) > 0 else 0
                prev_total = float(prev_sku["units_sold"].sum()) if len(prev_sku) > 0 else 0
                avg_weekly_recent = recent_total / 4 if len(sku_df) > 0 else 0
                trend_ratio = recent_total / prev_total if prev_total > 0 else 1.0

                # Project monthly demand = avg_weekly × trend × ~4.33 weeks
                projected_weekly = avg_weekly_recent * trend_ratio
                projected_monthly = round(projected_weekly * WEEKS_PER_MONTH, 1)

                # Get category from first match
                cat_row = df[df["sku_id"] == sku_id].iloc[0]

                sku_stats.append({
                    "sku_id": sku_id,
                    "category": cat_row.get("category", ""),
                    "monthly_demand": projected_monthly,
                    "avg_weekly_recent": round(avg_weekly_recent, 1),
                    "trend_ratio": round(trend_ratio, 3),
                    "source": "ewma_trend",
                })

            return sorted(sku_stats, key=lambda x: -x["monthly_demand"])

        except Exception as e:
            logger.error("EWMA projection failed: %s", e)
            return []

    # ── Math: shortfall & reorder recommendation ────────────────────
    def _compute_shortfall(self, expert_a: dict, expert_b: dict, target_month: int) -> dict:
        """Compare current stock to projected monthly demand, compute shortfall."""
        stock_map = {s["sku_id"]: s for s in expert_a.get("skus", [])}
        forecast_map = {s["sku_id"]: s for s in expert_b.get("skus", [])}

        # SKUs in either set
        all_skus = set(stock_map.keys()) | set(forecast_map.keys())

        results = []
        total_shortfall = 0
        total_recommended = 0
        for sku_id in sorted(all_skus):
            stock = stock_map.get(sku_id, {})
            forecast = forecast_map.get(sku_id, {})

            avg_weekly = stock.get("avg_weekly_demand", 0)
            estimated_stock = stock.get("estimated_stock", 0)
            coverage_weeks = stock.get("coverage_weeks", 0)
            monthly_demand = forecast.get("monthly_demand", avg_weekly * WEEKS_PER_MONTH)
            source = forecast.get("source", "not_available")

            shortfall = max(0, round(monthly_demand - estimated_stock))
            recommend = shortfall  # raw; MOQ rounding done in response
            urgency = get_risk_level(coverage_weeks, 1.0, shortfall)

            total_shortfall += shortfall
            total_recommended += recommend

            results.append({
                "sku_id": sku_id,
                "category": stock.get("category") or forecast.get("category", ""),
                "sub_category": stock.get("sub_category", ""),
                "current_stock": estimated_stock,
                "stock_source": stock.get("stock_source", "burn_rate_estimate"),
                "avg_weekly_demand": round(avg_weekly, 1),
                "coverage_weeks": round(coverage_weeks, 1),
                "projected_monthly_demand": round(monthly_demand, 1),
                "forecast_source": source,
                "shortfall": shortfall,
                "recommend": recommend,
                "urgency": urgency,
            })

        results.sort(key=lambda x: (-x["shortfall"],))

        return {
            "skus": results,
            "count": len(results),
            "total_shortfall_units": total_shortfall,
            "total_recommended_units": total_recommended,
            "skus_needing_reorder": sum(1 for r in results if r["shortfall"] > 0),
        }

    # ── LLM Synthesis ───────────────────────────────────────────────
    def _synthesize(self, question: str, expert_a: dict, expert_b: dict, math_result: dict) -> dict:
        """Use Gemini (or rule-based fallback) to synthesize a natural-language answer."""
        # Build context string
        ctx = self._build_context_str(expert_a, expert_b, math_result)

        model = get_gemini_model()
        if model:
            try:
                prompt = f"""You are Genie, the VST inventory assistant. A user asked:
"{question}"

Here is the reasoning from the two experts and the math:

{ctx}

Synthesize a concise, actionable reply in markdown. Include:
1. Current stock situation (X units).
2. Projected demand for the target month (Y units).
3. Shortfall (Z units) and recommended order qty.
4. Risk tag (CRITICAL / HIGH / MEDIUM / LOW) and any urgency.
5. A COMPLETE table listing EVERY SKU that needs reorder (shortfall > 0), sorted by urgency then shortfall descending.

Use tables where helpful. Keep under 800 words. Tag confidence as "Data + Forecast"."""
                response = model.generate_content(prompt)
                return {"text": response.text, "source": "gemini"}
            except Exception as e:
                logger.warning("Gemini synthesis failed: %s", e)

        # Rule-based fallback
        return {"text": self._rule_based_summary(expert_a, expert_b, math_result), "source": "rule_based"}

    def _build_context_str(self, expert_a: dict, expert_b: dict, math_result: dict) -> str:
        """Build a text block summarizing what Expert A, B, and math found."""
        lines = []

        # Expert A
        stock_skus = expert_a.get("skus", [])
        lines.append(f"## Expert A — Current Inventory ({len(stock_skus)} SKUs)")
        lines.append("| SKU | Category | Avg Weekly Demand | Est. Stock | Coverage (weeks) |")
        lines.append("|---|---|---|---|---|")
        for s in stock_skus[:50]:
            lines.append(
                f"| {s['sku_id']} | {s['category']} | {s['avg_weekly_demand']} | "
                f"{s['estimated_stock']} | {s['coverage_weeks']} |"
            )

        # Expert B
        month_label = expert_b.get("month_label", "target month")
        demand_skus = expert_b.get("skus", [])
        lines.append(f"\n## Expert B — Projected Demand for {month_label} ({len(demand_skus)} SKUs)")
        lines.append("| SKU | Monthly Demand | Source |")
        lines.append("|---|---|---|")
        for d in demand_skus[:50]:
            lines.append(f"| {d['sku_id']} | {d['monthly_demand']} | {d['source']} |")

        # Math
        lines.append(f"\n## Math — Shortfall Analysis")
        lines.append(f"Total shortfall: **{math_result['total_shortfall_units']}** units across {math_result['skus_needing_reorder']} SKUs")
        lines.append(f"Total recommended order: **{math_result['total_recommended_units']}** units")
        lines.append("\n| SKU | Stock | Projected Demand | Shortfall | Urgency |")
        lines.append("|---|---|---|---|---|")
        for r in math_result.get("skus", [])[:50]:
            lines.append(
                f"| {r['sku_id']} | {r['current_stock']} | {r['projected_monthly_demand']} | "
                f"{r['shortfall']} | **{r['urgency']}** |"
            )

        return "\n".join(lines)

    def _rule_based_summary(self, expert_a: dict, expert_b: dict, math_result: dict) -> str:
        """Offline fallback summary."""
        month_label = expert_b.get("month_label", "the target month")
        need = math_result["skus_needing_reorder"]
        total = math_result["total_recommended_units"]
        if need == 0:
            return (
                f"Based on current inventory and {month_label} forecasts, "
                f"**no SKUs are projected to run short.** "
                f"All categories have adequate coverage."
            )
        lines = [
            f"## Stock Advisory — {month_label}\n",
            f"**{need} SKU(s)** may run short by a total of **{total} units**.\n",
            "| SKU | Current Stock | Projected Demand | Shortfall | Urgency |",
            "|---|---|---|---|---|",
        ]
        for r in math_result.get("skus", [])[:50]:
            lines.append(
                f"| {r['sku_id']} | {r['current_stock']} | {r['projected_monthly_demand']} | "
                f"{r['shortfall']} | **{r['urgency']}** |"
            )
        lines.append(
            f"\n**Recommendation:** Place orders for the {need} SKUs above as soon as possible."
        )
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────────
_advisor: Optional[StockAdvisorAgent] = None


def get_stock_advisor() -> StockAdvisorAgent:
    global _advisor
    if _advisor is None:
        _advisor = StockAdvisorAgent()
    return _advisor
