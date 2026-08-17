"""
What-If Agent  ──  Scenario Simulator wrapper for Genie.

Turns natural-language scenario questions into structured calls to the
WhatIfSimulator.  Unlike the stock advisor, this agent uses a fixed
set of tool types (lead_time, demand_spike, shelf_life, supplier_failure)
selected by keyword matching in the user question.
"""

import logging
import re
from typing import Optional

from app.genie.what_if import get_simulator

logger = logging.getLogger(__name__)


# ── Tool definitions ──────────────────────────────────────────────────
TOOLS = {
    "lead_time": {
        "keywords": ["lead time", "delay", "late", "slower", "shipping"],
        "description": "Simulate what happens if supplier lead time increases.",
    },
    "demand_spike": {
        "keywords": ["demand", "spike", "increase", "surge", "more demand"],
        "description": "Simulate what happens if demand for a category increases by X%.",
    },
    "shelf_life": {
        "keywords": ["shelf life", "expire", "expiry", "idle", "sitting", "stale"],
        "description": "Identify items at risk of shelf-life expiry.",
    },
    "supplier_failure": {
        "keywords": ["supplier fail", "can't deliver", "unavailable", "disruption", "shutdown", "shut down", "shut"],
        "description": "Simulate what happens if a supplier/country is unavailable for X weeks.",
    },
}


class WhatIfAgent:
    """Wraps the WhatIfSimulator with natural-language routing."""

    def __init__(self):
        self.simulator = get_simulator()

    def run(self, question: str) -> dict:
        """
        Detect the scenario type from the question, extract parameters,
        and delegate to the simulator.

        Returns a dict with:
          tool:          which tool was invoked
          params:        extracted parameters
          result:        raw simulator output (dict)
          summary:       dict with text (Gemini or rule-based)
          data_sources:  ["sim:..."] for confidence tagging
        """
        tool_type, params = self._detect_tool(question)

        if tool_type is None:
            return {
                "tool": None,
                "params": {},
                "result": {},
                "summary": {
                    "text": (
                        "I can run what-if simulations for you. Try asking:\n"
                        "- *\"What if lead time from China increases by 15 days?\"*\n"
                        "- *\"What if demand for Spare Parts spikes by 25%?\"*\n"
                        "- *\"Which items are at risk of shelf-life expiry?\"*\n"
                        "- *\"What if a Japan supplier fails for 8 weeks?\"*"
                    ),
                    "source": "rule_based",
                },
                "data_sources": [],
            }

        # Invoke the simulator
        result = self._invoke_simulator(tool_type, params)

        return {
            "tool": tool_type,
            "params": params,
            "result": result,
            "summary": self._build_summary(question, tool_type, result),
            "data_sources": [f"sim:{tool_type}"],
        }

    # ── Tool detection ──────────────────────────────────────────────
    def _detect_tool(self, question: str) -> tuple[Optional[str], dict]:
        """Match the question to a scenario type and extract parameters."""
        q_lower = question.lower()
        params = {}

        # Detect scenario type (most-specific first)
        if any(kw in q_lower for kw in TOOLS["supplier_failure"]["keywords"]):
            params = self._extract_supplier_params(q_lower)
            return "supplier_failure", params

        if any(kw in q_lower for kw in TOOLS["lead_time"]["keywords"]):
            params = self._extract_lead_time_params(q_lower)
            return "lead_time", params

        if any(kw in q_lower for kw in TOOLS["shelf_life"]["keywords"]):
            params = self._extract_shelf_life_params(q_lower)
            return "shelf_life", params

        if any(kw in q_lower for kw in TOOLS["demand_spike"]["keywords"]):
            params = self._extract_demand_spike_params(q_lower)
            return "demand_spike", params

        return None, {}

    # ── Parameter extraction ────────────────────────────────────────
    def _extract_number(self, q: str, default: int = 15) -> int:
        m = re.search(r"\d+", q)
        return int(m.group(0)) if m else default

    def _extract_country(self, q: str) -> Optional[str]:
        for c in ["china", "japan", "germany", "india"]:
            if c in q:
                return c.title()
        return None

    def _extract_category(self, q: str) -> Optional[str]:
        categories = ["Spare Parts", "Lubricants", "Electric Pumps", "Engines", "Precision Components"]
        for cat in categories:
            if cat.lower() in q:
                return cat
        # Shorthand
        if "pump" in q:
            return "Electric Pumps"
        if "engine" in q:
            return "Engines"
        if "spare" in q:
            return "Spare Parts"
        if "lubricant" in q:
            return "Lubricants"
        return None

    def _extract_supplier_params(self, q: str) -> dict:
        params = {"failure_weeks": self._extract_number(q, default=8)}
        country = self._extract_country(q)
        if country:
            params["origin_country"] = country
        sup_match = re.search(r"SUP-\w+-\d+", q, re.IGNORECASE)
        if sup_match:
            params["supplier_id"] = sup_match.group(0)
        return params

    def _extract_lead_time_params(self, q: str) -> dict:
        params = {"additional_days": self._extract_number(q, default=15)}
        country = self._extract_country(q)
        if country:
            params["origin_country"] = country
        return params

    def _extract_shelf_life_params(self, q: str) -> dict:
        params = {"threshold_days": self._extract_number(q, default=90)}
        return params

    def _extract_demand_spike_params(self, q: str) -> dict:
        params = {"spike_percent": float(self._extract_number(q, default=20))}
        cat = self._extract_category(q)
        if cat:
            params["category"] = cat
        return params

    # ── Simulator invocation ────────────────────────────────────────
    def _invoke_simulator(self, tool_type: str, params: dict) -> dict:
        try:
            if tool_type == "lead_time":
                return self.simulator.lead_time_impact(
                    supplier_id=params.get("supplier_id"),
                    origin_country=params.get("origin_country"),
                    additional_days=params.get("additional_days", 15),
                )
            elif tool_type == "demand_spike":
                return self.simulator.demand_spike_impact(
                    category=params.get("category"),
                    spike_percent=params.get("spike_percent", 20),
                )
            elif tool_type == "shelf_life":
                return self.simulator.shelf_life_risk(
                    threshold_days=params.get("threshold_days", 90),
                )
            elif tool_type == "supplier_failure":
                return self.simulator.supplier_failure(
                    supplier_id=params.get("supplier_id"),
                    origin_country=params.get("origin_country"),
                    failure_weeks=params.get("failure_weeks", 8),
                )
            else:
                return {"error": f"Unknown tool: {tool_type}"}
        except Exception as e:
            logger.error("WhatIf tool '%s' failed: %s", tool_type, e)
            return {"error": str(e)}

    # ── Summary builder ─────────────────────────────────────────────
    def _build_summary(self, question: str, tool_type: str, result: dict) -> dict:
        """Rule-based summary; the engine may re-synthesize with Gemini."""
        if result.get("error"):
            return {"text": f"Simulation error: {result['error']}", "source": "rule_based"}

        if tool_type == "lead_time":
            return self._summarize_lead_time(result)
        elif tool_type == "demand_spike":
            return self._summarize_demand_spike(result)
        elif tool_type == "shelf_life":
            return self._summarize_shelf_life(result)
        elif tool_type == "supplier_failure":
            return self._summarize_supplier_failure(result)
        return {"text": str(result), "source": "rule_based"}

    def _summarize_lead_time(self, r: dict) -> dict:
        total = r.get("total_at_risk_skus", 0)
        crit = r.get("critical_count", 0)
        if total == 0:
            return {"text": f"✅ {r['scenario']}: No SKUs at immediate risk.", "source": "rule_based"}
        lines = [
            f"## {r['scenario']}\n",
            f"**{total} SKUs at risk** ({crit} CRITICAL)\n",
            f"Affected categories: {', '.join(r.get('affected_categories', []))}\n",
            f"| SKU | Category | Weekly Demand | Coverage | New Lead | Shortfall | Risk |",
            f"|---|---|---|---|---|---|---|",
        ]
        for item in r.get("at_risk_skus", [])[:10]:
            lines.append(
                f"| {item['sku_id']} | {item['category']} | {item['weekly_demand']} | "
                f"{item['coverage_weeks']}w | {item['new_lead_weeks']}w | "
                f"{item['shortfall_weeks']}w | **{item['risk_level']}** |"
            )
        if r.get("recommendation"):
            lines.append(f"\n{r['recommendation']}")
        return {"text": "\n".join(lines), "source": "rule_based"}

    def _summarize_demand_spike(self, r: dict) -> dict:
        total = r.get("total_impacted_skus", 0)
        if total == 0:
            return {"text": f"✅ {r['scenario']}: No SKUs would run short.", "source": "rule_based"}
        lines = [
            f"## {r['scenario']}\n",
            f"**{total} SKUs impacted**\n",
            f"Total additional units needed: **{r.get('total_additional_units_needed', 0):,}**\n",
            f"| SKU | Category | Current Demand | New Demand | Coverage Before | After | Add'l Stock |",
            f"|---|---|---|---|---|---|---|",
        ]
        for item in r.get("impacted_skus", [])[:10]:
            lines.append(
                f"| {item['sku_id']} | {item['category']} | {item['current_weekly_demand']} | "
                f"{item['projected_weekly_demand']} | {item['coverage_before_weeks']}w | "
                f"{item['coverage_after_weeks']}w | {item['additional_stock_needed']} |"
            )
        return {"text": "\n".join(lines), "source": "rule_based"}

    def _summarize_shelf_life(self, r: dict) -> dict:
        items = r.get("at_risk_items", [])
        if not items:
            return {"text": f"✅ {r['scenario']}: No items at risk.", "source": "rule_based"}
        lines = [
            f"## {r['scenario']}\n",
            f"**{len(items)} items at risk**\n",
            f"| SKU | Category | Shelf Life (days) | Risk |",
            f"|---|---|---|---|",
        ]
        for item in items[:15]:
            lines.append(
                f"| {item.get('sku_id', 'N/A')} | {item.get('category', 'N/A')} | "
                f"{item.get('shelf_life_days', 'N/A')} | {item.get('risk_level', 'N/A')} |"
            )
        if r.get("note"):
            lines.append(f"\n*{r['note']}*")
        if r.get("recommendation"):
            lines.append(f"\n**Recommendation**: {r['recommendation']}")
        return {"text": "\n".join(lines), "source": "rule_based"}

    def _summarize_supplier_failure(self, r: dict) -> dict:
        risk_count = r.get("products_at_stockout_risk", 0)
        if risk_count == 0:
            return {"text": f"✅ {r['scenario']}: No products at stockout risk.", "source": "rule_based"}
        lines = [
            f"## {r['scenario']}\n",
            f"**{risk_count} products at stockout risk** "
            f"(out of {r.get('total_products_affected', 0)} affected)\n",
            f"Affected categories: {', '.join(r.get('affected_categories', []))}\n",
            f"| SKU | Category | Weekly Demand | Stock | Runway | Weeks Short | Stockout Est. |",
            f"|---|---|---|---|---|---|---|",
        ]
        for item in r.get("stockout_risk_items", [])[:10]:
            lines.append(
                f"| {item['sku_id']} | {item['category']} | {item['weekly_demand']} | "
                f"{item['estimated_stock']} | {item['runway_weeks']}w | "
                f"{item['weeks_short']}w | {item['stockout_date_estimate']} |"
            )
        if r.get("recommendations"):
            lines.append("\n**Recommendations:**")
            for rec in r["recommendations"]:
                lines.append(f"- {rec}")
        return {"text": "\n".join(lines), "source": "rule_based"}


# ── Singleton ────────────────────────────────────────────────────────
_agent: Optional[WhatIfAgent] = None


def get_what_if_agent() -> WhatIfAgent:
    global _agent
    if _agent is None:
        _agent = WhatIfAgent()
    return _agent
