"""
SQL Agent  ──  Expert A for Genie.

Responsibility:
    Take a natural-language inventory question and turn it into a syntactically
    correct, READ-ONLY SQL query against the live VST IMS database. Execute it
    and return (sql, rows, summary) to the orchestrator.

This is TASK 1 of the Genie spec:
  "You are a highly precise, analytical AI agent acting as a backend
   PostgreSQL expert for an inventory management system. Your sole purpose
   is to translate user natural-language questions into syntactically correct,
   read-only SQL queries."

Implementation notes:
- The LLM (Gemini) is the NL→SQL translator.  It is given the live schema
  (from schema_extractor) and a strict system prompt.
- The agent's `validate_sql` guardrail rejects anything that is not a single
  SELECT - even if the LLM tries to be clever.
- We attempt LLM twice (allowing one self-correction) on schema errors.
- Even without a Gemini key the agent still works as a deterministic SQL
  builder for a small set of canonical questions (see `_fallback_sql`).
"""

import logging
import os
import re
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.genie.guardrails import GenieGuardrails
from app.genie.schema_extractor import get_schema_text_cached
from app.genie.llm_client import get_gemini_model

logger = logging.getLogger(__name__)

ERROR_NO_SCHEMA = "ERROR: Insufficient data schema to answer query."


class SqlAgent:
    """Translates natural language -> read-only SQL -> executed rows."""

    def __init__(self, guardrails: Optional[GenieGuardrails] = None):
        self.guardrails = guardrails or GenieGuardrails()
        self.schema_text = get_schema_text_cached()
        self._system_prompt = self._build_system_prompt()

    # ── Public API ──────────────────────────────────────────────────
    def run(self, question: str, db: Session, max_rows: int = 200) -> dict:
        """
        Answer a natural-language question by generating + executing SQL.

        Returns a dict with keys:
          - question:  original NL question
          - sql:       the SQL executed (or None)
          - rows:      list of dict rows
          - columns:   column names in row order
          - row_count: number of rows returned
          - summary:   short NL summary of the result
          - error:     None on success, otherwise a human-readable message
        """
        # Try LLM route
        sql = self._llm_to_sql(question)
        if sql:
            is_safe, reason = self.guardrails.validate_sql(sql)
            if not is_safe:
                self.guardrails.sql_rejections += 1
                logger.warning("SqlAgent rejected LLM SQL: %s", reason)
                # Ask LLM to correct once
                sql = self._llm_to_sql(question, correction_hint=reason)

            if sql:
                is_safe, reason = self.guardrails.validate_sql(sql)
                if is_safe:
                    return self._execute(question, sql, db, max_rows)
                # Fall through to fallback

        # Deterministic fallback for canonical questions
        fb_sql = self._fallback_sql(question)
        if fb_sql:
            return self._execute(question, fb_sql, db, max_rows)

        return {
            "question": question,
            "sql": None,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "summary": None,
            "error": ERROR_NO_SCHEMA,
        }

    # ── LLM helpers ─────────────────────────────────────────────────
    def _llm_to_sql(
        self, question: str, correction_hint: Optional[str] = None
    ) -> Optional[str]:
        """Call Gemini with the SQL-generation system prompt and return
        raw SQL (no markdown) or None if the LLM is unavailable / refuses."""
        model = get_gemini_model()
        if model is None:
            return None

        today = date.today().isoformat()
        user_msg = (
            f"Today is {today}.\n\n"
            f"User question: {question}\n\n"
            f"Output ONLY the raw SQL query (no markdown, no explanation)."
        )
        if correction_hint:
            user_msg = (
                f"Your previous query was rejected because: {correction_hint}. "
                f"Rewrite it as a single read-only SELECT. " + user_msg
            )

        prompt = self._system_prompt + "\n\n" + user_msg
        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()
        except Exception as e:
            logger.warning("Gemini SQL generation failed: %s", e)
            return None

        return self._strip_md(raw)

    # ── Executor ────────────────────────────────────────────────────
    def _execute(self, question: str, sql: str, db: Session, max_rows: int) -> dict:
        try:
            clean_sql = sql.rstrip().rstrip(";").strip()
            # Only append LIMIT if the SQL doesn't already have one
            upper = clean_sql.upper()
            if "LIMIT" not in upper:
                clean_sql = clean_sql + f" LIMIT {max_rows}"
            result = db.execute(text(clean_sql))
            columns = list(result.keys())
            rows = [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            logger.error("SqlAgent execution error: %s | SQL: %s", e, clean_sql)
            return {
                "question": question,
                "sql": clean_sql,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "summary": None,
                "error": f"SQL execution failed: {e}",
            }

        return {
            "question": question,
            "sql": clean_sql,
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "summary": self._summarize(rows),
            "error": None,
        }

    # ── Prompt construction ────────────────────────────────────────
    def _build_system_prompt(self) -> str:
        return f"""You are a highly precise, analytical AI agent acting as a backend SQLite expert for an inventory management system. Your sole purpose is to translate user natural-language questions into syntactically correct, read-only SQL queries.

You have access to the following database schema:

{self.schema_text}

CRITICAL RULES FOR SQL SYNTAX:
- You MUST write **SQLite-compatible SQL only**. This is NOT PostgreSQL.
- For date arithmetic, use: DATE('now', '-13 days'), DATE('now', '-90 days'), DATE('now', '-1 month'), DATE('now', '-13 weeks'), etc.
- NEVER use PostgreSQL syntax like: INTERVAL '13 weeks', CURRENT_DATE, DATE_SUB(), NOW(), etc.
- Do NOT include a LIMIT clause in your SQL — the system will add one automatically. Output ONLY the core SELECT statement.

SQL Generation Rules:
1.  Read-Only: You MUST ONLY generate SELECT statements. Never generate INSERT, UPDATE, DELETE, or DROP commands.
2.  Schema Strictness: Only use tables and columns explicitly defined in the schema above. Do not hallucinate columns.
3.  Current Context: Today's date is provided in the user message. Use DATE('now', '-N days') for date arithmetic.
4.  No Explanations: Do not provide any conversational text, pleasantries, or explanations.

Output Format:
Return ONLY the raw, executable SQL query. Do not wrap it in markdown formatting or backticks. If the user's question cannot be answered using the provided schema, return the exact string: "{ERROR_NO_SCHEMA}"
"""

    # ── Utilities ────────────────────────────────────────────────────
    @staticmethod
    def _strip_md(raw: str) -> str:
        """Remove ```sql ... ``` fences if the LLM ignored instructions."""
        s = raw.strip()
        # ```sql\n...\n```  or  ```\n...\n```
        m = re.match(r"^```(?:sql)?\s*(.*?)```$", s, re.DOTALL | re.IGNORECASE)
        if m:
            s = m.group(1).strip()
        # Trailing/leading stray backticks
        s = s.strip("`")
        return s.strip()

    @staticmethod
    def _summarize(rows: list[dict]) -> Optional[str]:
        """Tiny NL summary - the orchestrator usually rewrites with LLM anyway."""
        if not rows:
            return None
        n = len(rows)
        first = rows[0]
        # Pick the first non-id, non-uuid column for a hint
        for k, v in first.items():
            if k.lower() == "id" or k.endswith("_id"):
                continue
            return f"{n} row(s); first {k} = {v}"
        return f"{n} row(s) returned"

    # ── Deterministic fallback (offline mode) ───────────────────────
    def _fallback_sql(self, question: str) -> Optional[str]:
        """Cheap offline SQL builder for canonical questions. Helps when
        Gemini is unavailable."""
        q = question.lower().strip()

        # inventory value by category
        if "inventory value" in q or ("value" in q and "inventory" in q):
            return ("SELECT p.category, "
                    "COUNT(DISTINCT p.sku_id) AS skus, "
                    "SUM(i.quantity_on_hand) AS total_units, "
                    "ROUND(SUM(i.quantity_on_hand * i.unit_cost_inr), 2) AS inventory_value_inr "
                    "FROM products p "
                    "JOIN inventory i ON p.sku_id = i.sku_id "
                    "GROUP BY p.category ORDER BY inventory_value_inr DESC;")

        # top N highest demand items
        if "top" in q and ("demand" in q or "highest" in q):
            return ("SELECT s.sku_id, p.category, p.sub_category, "
                    "ROUND(AVG(s.units_sold), 1) AS avg_weekly_demand "
                    "FROM sales s JOIN products p ON s.product_id = p.id "
                    "GROUP BY s.sku_id, p.category, p.sub_category "
                    "ORDER BY avg_weekly_demand DESC LIMIT 10;")

        # compare lead times
        if "lead time" in q and ("compare" in q or "across" in q or "average" in q):
            return ("SELECT origin_country, COUNT(*) AS supplier_count, "
                    "ROUND(AVG(base_lead_time_days), 1) AS avg_lead_time_days, "
                    "MIN(base_lead_time_days) AS min_lead_days, "
                    "MAX(base_lead_time_days) AS max_lead_days "
                    "FROM suppliers GROUP BY origin_country ORDER BY avg_lead_time_days;")

        # count SKUs by category
        if "sku" in q and ("count" in q or "how many sku" in q or "total sku" in q):
            return ("SELECT category, COUNT(*) AS sku_count "
                    "FROM products GROUP BY category ORDER BY sku_count DESC;")

        # supplier list by country
        if "supplier" in q and any(c in q for c in ["japan", "china", "germany", "india", "domestic"]):
            for c in ["japan", "china", "germany", "india", "domestic"]:
                if c in q:
                    cap = c.title() if c != "domestic" else "Domestic"
                    return (f"SELECT supplier_id, supplier_name, primary_category, "
                            f"base_lead_time_days, moq, unit_cost_inr FROM suppliers "
                            f"WHERE origin_country = '{cap}' ORDER BY base_lead_time_days;")
            return None

        # product search by sub-category keyword
        if any(k in q for k in ["pump", "engine", "filter", "bearing", "seal", "gasket"]):
            for kw in ["pump", "engine", "filter", "bearing", "seal", "gasket"]:
                if kw in q:
                    return (f"SELECT sku_id, category, sub_category, "
                            f"machine_compatibility, criticality_score "
                            f"FROM products WHERE sub_category LIKE '%{kw.title()}%' "
                            f"OR sub_category LIKE '%{kw}%' LIMIT 20;")
            return None

        # total SKUs
        if "total" in q and "sku" in q:
            return "SELECT COUNT(*) AS total_skus FROM products;"

        # recent sales total (90d)
        if "sales" in q and ("last 90" in q or "recent" in q or "3 months" in q):
            return ("SELECT SUM(units_sold) AS total_units, COUNT(DISTINCT sku_id) AS active_skus "
                    "FROM sales WHERE sale_date >= date('now', '-90 days');")

        # low stock / critical items
        if "low stock" in q or "lowest stock" in q or "critical" in q or "stockout" in q:
            return ("SELECT p.sku_id, p.category, p.sub_category, "
                    "i.quantity_available, i.quantity_on_hand, i.unit_cost_inr "
                    "FROM products p JOIN inventory i ON p.sku_id = i.sku_id "
                    "ORDER BY i.quantity_available ASC LIMIT 15;")

        # current stock for a specific SKU
        import re as _re
        sku_m = _re.search(r"\b([A-Z]{2}-[A-Z]{3}-\d{4})\b", question.upper())
        if sku_m and any(k in q for k in ["stock", "available", "on hand", "inventory", "how many"]):
            s = sku_m.group(1)
            return ("SELECT i.sku_id, i.quantity_on_hand, i.quantity_reserved, "
                    f"i.quantity_available, i.last_sap_sync_at FROM inventory i "
                    f"WHERE i.sku_id = '{s}';")

        # shelf life / expiring
        if "shelf life" in q or "expir" in q:
            return ("SELECT sku_id, category, sub_category, shelf_life_days "
                    "FROM products WHERE shelf_life_days IS NOT NULL "
                    "ORDER BY shelf_life_days ASC LIMIT 15;")

        return None


# ── Singleton ────────────────────────────────────────────────────────
_sql_agent: Optional[SqlAgent] = None


def get_sql_agent() -> SqlAgent:
    global _sql_agent
    if _sql_agent is None:
        _sql_agent = SqlAgent()
    return _sql_agent
