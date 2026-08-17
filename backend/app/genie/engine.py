"""
GenieEngine  ──  Main Orchestrator for the Genie Chatbot.

Routes a user message to the appropriate agent(s), collects results,
and synthesizes a final answer with a reasoning trace.

Architecture:
  User message
    → Guardrails (input validation)
    → Planner LLM (decide which agents to invoke)
    → Agent execution (SqlAgent / StockAdvisorAgent / WhatIfAgent)
    → Response synthesizer (LLM with reasoning trace)
    → Guardrails (output validation)
    → Return to user

The response includes a `reasoning_trace` dict that the frontend renders
as the "expert reasoning" panel so users see exactly how the answer was
built (Expert A data → Expert B data → math → conclusion).
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.genie.guardrails import GenieGuardrails
from app.genie.sql_agent import get_sql_agent
from app.genie.stock_advisor_agent import get_stock_advisor
from app.genie.what_if_agent import get_what_if_agent
from app.genie.llm_client import get_gemini_model

logger = logging.getLogger(__name__)


# ── Planner prompt (used to decide which agents to invoke) ───────────
PLANNER_SYSTEM = """You are a planning router for the VST inventory assistant Genie.
Given a user message, decide which agent(s) to invoke.  Return ONLY a
JSON object with this exact shape:

{
  "agents": ["sql" | "stock_advisor" | "what_if"],
  "primary": "sql" | "stock_advisor" | "what_if",
  "reasoning": "one sentence explaining why"
}

Rules:
- "stock_advisor": use when the user asks about ordering, restocking, need-to-buy, projected-demand, will-we-run-out, reorder, month-ahead, December-style questions.
- "sql": use when the user asks a factual data lookup (how many, what is the average, list suppliers, show products, etc.) with no forecasting component.
- "what_if": use when the user poses a hypothetical scenario (what if..., simulate..., impact of...).
- If ambiguous, prefer "stock_advisor" over "sql" because it is more informative.
- Never return an empty agents list.
"""


class GenieEngine:
    """
    The main Genie chatbot engine.

    Manages:
      - conversation history (in-memory + optional DB persistence)
      - input guardrails
      - agent routing
      - response synthesis
      - reasoning trace for the frontend
    """

    def __init__(self):
        self.guardrails = GenieGuardrails()
        self.conversations: dict[str, list] = {}

    # ── Public API ──────────────────────────────────────────────────
    async def chat(
        self,
        message: str,
        conversation_id: str = None,
        db: Session = None,
    ) -> dict:
        """
        Process a user message and return a rich response.

        Returns dict with:
          response:           final NL answer (markdown)
          intent:             "inventory_query" | "forecast_query" | "what_if" | "reorder_advice" | "general"
          confidence:         {level, tag, description}
          conversation_id:    session id
          data_sources:       list[str]
          reasoning_trace:    dict with expert_a, expert_b, math, sql, tool results
          data:               optional raw data (SQL rows, etc.)
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        # ── Step 1: Input guardrails ────────────────────────────────
        validation = self.guardrails.validate_input(message)
        if not validation["is_safe"]:
            return {
                "response": validation["message"],
                "intent": "blocked",
                "confidence": {"level": "high", "tag": "🔒 Safety"},
                "conversation_id": conversation_id,
                "data_sources": [],
                "reasoning_trace": {},
                "data": None,
            }

        sanitized = validation.get("sanitized", message)

        # ── Step 2: Plan (which agents?) ────────────────────────────
        plan = self._plan(sanitized)
        agents = plan.get("agents", ["sql"])
        primary = plan.get("primary", agents[0])

        # ── Step 3: Execute agents ──────────────────────────────────
        trace = {}
        data_sources = []
        combined_text_parts = []

        for agent_name in agents:
            if agent_name == "sql" and db:
                result = self._run_sql_agent(sanitized, db)
                trace["sql"] = result
                if not result.get("error"):
                    data_sources.append("db:products,sales")
                    if result.get("rows"):
                        combined_text_parts.append(self._format_sql_result(result))

            elif agent_name == "stock_advisor" and db:
                result = self._run_stock_advisor(sanitized, db)
                trace["stock_advisor"] = result
                data_sources.extend(result.get("data_sources", []))
                if result.get("summary", {}).get("text"):
                    combined_text_parts.append(result["summary"]["text"])

            elif agent_name == "what_if":
                result = self._run_what_if(sanitized)
                trace["what_if"] = result
                data_sources.extend(result.get("data_sources", []))
                if result.get("summary", {}).get("text"):
                    combined_text_parts.append(result["summary"]["text"])

        # ── Step 4: Synthesize final response ───────────────────────
        if combined_text_parts:
            # Multiple agents contributed — merge with Gemini
            response_text = self._synthesize_multi(
                sanitized, combined_text_parts, trace
            )
        elif trace:
            # Agents ran but produced no text — build a useful fallback from trace data
            response_text = self._trace_fallback(sanitized, trace, primary)
        else:
            # No agents invoked at all — general assistant
            response_text = self._general_response(sanitized, db)

        # ── Step 5: Output guardrails ──────────────────────────────
        response_text = self.guardrails.validate_output(response_text)

        # ── Step 6: Confidence classification ───────────────────────
        confidence = self.guardrails.classify_confidence(data_sources)

        # Determine intent for the frontend
        intent = self._infer_intent(primary, trace)

        # ── Step 7: Save to conversation history ────────────────────
        self.conversations[conversation_id].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat(),
        })
        self.conversations[conversation_id].append({
            "role": "assistant",
            "content": response_text,
            "intent": intent,
            "data_sources": data_sources,
            "confidence": confidence,
            "trace_summary": {
                k: {"tool": v.get("tool"), "count": v.get("count", v.get("row_count", 0))}
                for k, v in trace.items()
                if isinstance(v, dict)
            },
            "timestamp": datetime.now().isoformat(),
        })

        return {
            "response": response_text,
            "intent": intent,
            "confidence": confidence,
            "conversation_id": conversation_id,
            "data_sources": data_sources,
            "reasoning_trace": self._serialize_trace(trace),
            "data": self._extract_data(trace),
        }

    def get_suggestions(self, db: Session = None) -> list[dict]:
        """Quick-action suggestions for the chat UI."""
        return [
            {"text": "Which SKUs will stock out in the next 8 weeks?",
             "query": "Which SKUs will stock out in the next 8 weeks?"},
            {"text": "What's the total inventory value across all categories?",
             "query": "What's the total inventory value across all categories?"},
            {"text": "What if a major supplier from Japan shuts down for 6 weeks?",
             "query": "What if a major supplier from Japan shuts down for 6 weeks?"},
            {"text": "Show top 10 highest-demand Spare Parts this month",
             "query": "Show me the top 10 highest-demand Spare Parts this month"},
            {"text": "Which Electric Pumps need urgent reorder?",
             "query": "Which Electric Pumps need urgent reorder?"},
            {"text": "Compare avg lead times across all supplier countries",
             "query": "Compare average lead times across all supplier countries"},
        ]

    # ── Agent runners ───────────────────────────────────────────────
    def _run_sql_agent(self, message: str, db: Session) -> dict:
        agent = get_sql_agent()
        return agent.run(message, db)

    def _run_stock_advisor(self, message: str, db: Session) -> dict:
        agent = get_stock_advisor()
        return agent.run(message, db)

    def _run_what_if(self, message: str) -> dict:
        agent = get_what_if_agent()
        return agent.run(message)

    # ── Planner (Gemini or rule-based) ──────────────────────────────
    def _plan(self, message: str) -> dict:
        """Decide which agents to invoke."""
        model = get_gemini_model()
        if model:
            try:
                prompt = PLANNER_SYSTEM + f'\n\nUser message: "{message}"\n\nRespond with JSON only.'
                response = model.generate_content(prompt)
                import json, re
                raw = response.text.strip()
                # Strip markdown fences if present
                m = re.match(r"^```(?:json)?\s*(.*?)```$", raw, re.DOTALL | re.IGNORECASE)
                if m:
                    raw = m.group(1).strip()
                plan = json.loads(raw)
                agents = plan.get("agents", [])
                primary = plan.get("primary", agents[0] if agents else "sql")
                if agents:
                    return {"agents": agents, "primary": primary}
                # Gemini returned empty agents — fall through to rule-based
                logger.warning("Gemini planner returned empty agents, using rule-based")
            except Exception as e:
                logger.warning("Planner LLM failed: %s", e)

        # Rule-based fallback
        return self._rule_based_plan(message)

    def _rule_based_plan(self, message: str) -> dict:
        q = message.lower()

        # What-if / scenario
        if any(kw in q for kw in ["what if", "what happens if", "simulate", "scenario",
                                    "if lead time", "if demand", "if supplier fail",
                                    "if a major", "impact of", "suppose", "assume",
                                    "shut down", "disruption", "fails for"]):
            return {"agents": ["what_if"], "primary": "what_if"}

        # Stock advisor (reorder / month-ahead questions)
        if any(kw in q for kw in [
            "need to order", "need more stock", "reorder", "should i order",
            "do we have enough", "will we run out", "projected demand",
            "for december", "for january", "for february", "for march",
            "for april", "for may", "for june", "for july", "for august",
            "for september", "for october", "for november",
            "next month", "next week", "how many should we order",
            "shortfall", "shortage", "stockout risk",
            "do we need", "will it stock out",
            "stock out", "stockout", "urgent reorder", "run short",
        ]):
            return {"agents": ["stock_advisor"], "primary": "stock_advisor"}

        # SQL query (factual lookup)
        if any(kw in q for kw in [
            "how many", "what is", "show me", "list", "count",
            "average", "total", "which", "who", "what's the",
            "what are", "describe", "give me", "find",
            "compare", "top 10", "highest", "lowest",
            "inventory value", "lead time", "suppliers from",
        ]):
            return {"agents": ["sql"], "primary": "sql"}

        # Default: try stock advisor (most useful)
        return {"agents": ["stock_advisor"], "primary": "stock_advisor"}

    # ── Multi-agent synthesis ────────────────────────────────────────
    def _synthesize_multi(self, question: str, parts: list[str], trace: dict) -> str:
        """Merge outputs from multiple agents into one coherent answer."""
        model = get_gemini_model()
        combined = "\n\n---\n\n".join(parts)

        if model:
            try:
                prompt = (
                    f"You are Genie, the VST inventory assistant. A user asked:\n"
                    f"\"{question}\"\n\n"
                    f"Multiple agents contributed these results:\n\n{combined}\n\n"
                    f"Merge them into one concise, actionable markdown response. "
                    f"Include the key numbers, risk tags, and recommendations. "
                    f"Keep under 400 words. Do not repeat the same data twice."
                )
                response = model.generate_content(prompt)
                return response.text
            except Exception as e:
                logger.warning("Gemini synthesis failed: %s", e)

        # Fallback: concatenate the largest part
        return combined

    def _trace_fallback(self, message: str, trace: dict, primary: str) -> str:
        """Build a useful response when agents ran but produced no summary text."""
        parts = []

        # SQL agent ran
        sql = trace.get("sql", {})
        if sql:
            rows = sql.get("rows", [])
            if sql.get("error"):
                return f"I tried to query the database but encountered an error: {sql['error']}"
            if rows:
                cols = sql.get("columns", list(rows[0].keys()) if rows else [])
                header = "| " + " | ".join(cols) + " |"
                sep = "| " + " | ".join(["---"] * len(cols)) + " |"
                body = [header, sep]
                for row in rows[:15]:
                    vals = [str(row.get(c, "")) for c in cols]
                    body.append("| " + " | ".join(vals) + " |")
                return "\n".join(body)
            return "I queried the database but found no matching results for your question."

        # Stock advisor ran
        sa = trace.get("stock_advisor", {})
        if sa:
            math_result = sa.get("math", {})
            need = math_result.get("skus_needing_reorder", 0)
            total = math_result.get("total_recommended_units", 0)
            if need > 0:
                return (
                    f"Based on current inventory and forecasts, "
                    f"**{need} SKU(s)** may run short by a total of **{total} units**. "
                    f"Check the reasoning trace below for the full breakdown."
                )
            return "Current inventory levels look adequate based on the analysis. No urgent reorders needed."

        # What-if ran
        wi = trace.get("what_if", {})
        if wi:
            result = wi.get("result", {})
            if result.get("error"):
                return f"What-if simulation error: {result['error']}"
            tool = wi.get("tool", "scenario")
            return f"What-if simulation completed for **{tool}**. Check the reasoning trace for details."

        return "I analyzed your question but couldn't generate a summary. Please try rephrasing."

    def _general_response(self, message: str, db: Session = None) -> str:
        """Handle greetings, help, and unrecognised questions."""
        q = message.lower().strip()
        if any(w in q for w in ["hello", "hi", "hey"]):
            return (
                "Hello! I'm **Genie**, your VST inventory assistant.\n\n"
                "I can help with:\n"
                "- **Stock advisory** — \"Do we need to order more Spare Parts for December?\"\n"
                "- **Data queries** — \"How many SKUs are there per category?\"\n"
                "- **What-if scenarios** — \"What if lead time from China increases by 15 days?\"\n\n"
                "What would you like to know?"
            )
        if any(w in q for w in ["help", "what can"]):
            return (
                "## Genie Can Help With\n\n"
                "| Question Type | Example |\n"
                "|---|---|\n"
                "| Stock Advisory | \"Do we need to order more Spare Parts for December?\" |\n"
                "| Data Lookup | \"How many SKUs are in Engines?\" |\n"
                "| Forecast Status | \"What's the demand forecast for next 8 weeks?\" |\n"
                "| What-If | \"What if lead time from China increases by 20 days?\" |\n"
                "| Risk | \"Which items are at risk of expiring?\" |\n"
                "| Suppliers | \"Show me all Japanese suppliers\" |\n"
            )
        if any(w in q for w in ["thank", "thanks"]):
            return "You're welcome! Let me know if you have any other questions about VST inventory."
        if any(w in q for w in ["bye", "goodbye"]):
            return "Goodbye! Feel free to come back anytime you need help with VST inventory."

        return (
            "I'm Genie, your VST inventory assistant. I can help with:\n"
            "- **Stock advisory** — will we run out, what to order\n"
            "- **Data queries** — inventory, products, suppliers\n"
            "- **What-if scenarios** — simulate disruptions\n\n"
            "Try: *\"Do we need to order more Spare Parts for December?\"*"
        )

    # ── Helpers ──────────────────────────────────────────────────────
    def _format_sql_result(self, result: dict) -> str:
        """Format SQL rows as a markdown table."""
        rows = result.get("rows", [])
        columns = result.get("columns", [])
        if not rows or not columns:
            return result.get("summary") or "No results found."

        # Build markdown table
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join(["---"] * len(columns)) + " |"
        body_lines = [header, sep]
        for row in rows[:20]:
            vals = [str(row.get(c, "")) for c in columns]
            body_lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(body_lines)

    def _infer_intent(self, primary: str, trace: dict) -> str:
        if primary == "stock_advisor":
            return "reorder_advice"
        if primary == "what_if":
            return "what_if"
        if primary == "sql":
            # Check if SQL result is forecast-related
            sql_result = trace.get("sql", {})
            sql_text = (sql_result.get("sql") or "").lower()
            if "forecast" in sql_text:
                return "forecast_query"
            return "inventory_query"
        return "general"

    @staticmethod
    def _serialize_trace(trace: dict) -> dict:
        """Strip large row arrays from the trace before sending to frontend;
        keep only summary metadata. Actual data goes in `data` field."""
        serialized = {}
        for key, val in trace.items():
            if not isinstance(val, dict):
                serialized[key] = val
                continue
            entry = {}
            for k, v in val.items():
                if k == "rows":
                    entry["row_count"] = len(v) if isinstance(v, list) else 0
                    entry["sample"] = v[:3] if isinstance(v, list) else []
                elif k in ("expert_a", "expert_b", "math"):
                    entry[k] = v  # stock advisor sub-results kept in full
                elif k == "result":
                    entry[k] = v  # what-if result kept in full
                else:
                    entry[k] = v
            serialized[key] = entry
        return serialized

    @staticmethod
    def _extract_data(trace: dict) -> Optional[dict]:
        """Pull raw data suitable for the frontend data panel."""
        data = {}
        sql = trace.get("sql", {})
        if sql.get("rows"):
            data["sql_rows"] = sql["rows"]
            data["sql_columns"] = sql.get("columns", [])
            data["sql_query"] = sql.get("sql", "")
        sa = trace.get("stock_advisor", {})
        if sa:
            data["stock_advisor"] = {
                "expert_a": sa.get("expert_a"),
                "expert_b": sa.get("expert_b"),
                "math": sa.get("math"),
            }
        wi = trace.get("what_if", {})
        if wi.get("result"):
            data["what_if"] = wi["result"]
        return data if data else None


# ── Singleton ────────────────────────────────────────────────────────
_engine: Optional[GenieEngine] = None


def get_genie_engine() -> GenieEngine:
    global _engine
    if _engine is None:
        _engine = GenieEngine()
    return _engine
