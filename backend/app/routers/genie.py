"""
Genie Chatbot API Router for VST IMS.

Endpoints:
  POST /api/genie/chat          — main chat endpoint (routes to SQL / StockAdvisor / WhatIf agents)
  GET  /api/genie/suggestions   — quick-action suggestions for the chat UI
  POST /api/genie/what-if       — structured what-if simulation (direct tool call)
  GET  /api/genie/history       — conversation history
  GET  /api/genie/capabilities  — describes what Genie can do
  POST /api/genie/export-csv    — export stock advisory shortfall table as CSV download
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import date
import csv
import io
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.genie.engine import get_genie_engine
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/genie", tags=["genie"])
limiter = Limiter(key_func=get_remote_address)


# ── Request / Response models ─────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: str
    confidence: dict
    conversation_id: str
    data_sources: list[str] = []
    reasoning_trace: Optional[dict] = None
    data: Optional[dict] = None


class WhatIfRequest(BaseModel):
    scenario_type: str  # lead_time | demand_spike | shelf_life | supplier_failure
    parameters: dict = {}


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Send a message to Genie.  The engine routes to the appropriate agent
    (SQL Expert, Stock Advisor, What-If Simulator) and returns a
    unified response with a reasoning trace.
    """
    engine = get_genie_engine()
    result = await engine.chat(
        message=body.message,
        conversation_id=body.conversation_id,
        db=db,
    )
    return ChatResponse(
        response=result["response"],
        intent=result.get("intent", "general"),
        confidence=result.get("confidence", {"level": "low", "tag": "AI Insight"}),
        conversation_id=result["conversation_id"],
        data_sources=result.get("data_sources", []),
        reasoning_trace=result.get("reasoning_trace"),
        data=result.get("data"),
    )


@router.get("/suggestions")
async def get_suggestions(db: Session = Depends(get_db)):
    """Quick-action suggestions for the chat UI."""
    engine = get_genie_engine()
    suggestions = engine.get_suggestions(db)
    return {"suggestions": suggestions}


@router.post("/what-if")
async def run_what_if(request: WhatIfRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Run a structured what-if scenario simulation directly (without chat).
    Useful for programmatic access or the What-If simulator page.
    """
    from app.genie.what_if import get_simulator
    simulator = get_simulator()
    params = request.parameters

    # Guardrail: clamp numeric parameters into sane ranges
    g = get_genie_engine().guardrails
    try:
        if request.scenario_type == "lead_time":
            result = simulator.lead_time_impact(
                supplier_id=params.get("supplier_id"),
                origin_country=params.get("origin_country", "China"),
                additional_days=int(g.clamp_number(params.get("additional_days", 15), 0, 365, 15)),
                db=db,
            )
        elif request.scenario_type == "demand_spike":
            result = simulator.demand_spike_impact(
                category=params.get("category"),
                spike_percent=float(g.clamp_number(params.get("spike_percent", 20), -80, 500, 20)),
                db=db,
            )
        elif request.scenario_type == "shelf_life":
            result = simulator.shelf_life_risk(
                threshold_days=int(g.clamp_number(params.get("threshold_days", 90), 7, 3650, 90)),
                db=db,
            )
        elif request.scenario_type == "supplier_failure":
            result = simulator.supplier_failure(
                supplier_id=params.get("supplier_id"),
                origin_country=params.get("origin_country"),
                failure_weeks=int(g.clamp_number(params.get("failure_weeks", 8), 1, 104, 8)),
                db=db,
            )
        else:
            return {"status": "error", "message": f"Unknown scenario type: {request.scenario_type}"}

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error("What-if simulation failed: %s", e)
        return {"status": "error", "message": str(e)}


@router.get("/history")
async def get_history(conversation_id: str):
    """Get conversation history for a specific session."""
    engine = get_genie_engine()
    history = engine.conversations.get(conversation_id, [])
    return {
        "conversation_id": conversation_id,
        "messages": history,
        "message_count": len(history),
    }


@router.get("/capabilities")
async def get_capabilities():
    """Describe what Genie can do — used by the frontend for onboarding tooltips."""
    return {
        "capabilities": [
            {
                "name": "Stock Advisory",
                "description": "Combine live inventory data with demand forecasts to recommend what to order and how much.",
                "example": "Do we need to order more Spare Parts for December?",
            },
            {
                "name": "Data Queries (SQL)",
                "description": "Ask natural-language questions about inventory, products, suppliers, and sales data.",
                "example": "How many SKUs are there per category?",
            },
            {
                "name": "What-If Scenarios",
                "description": "Simulate supply-chain disruptions: lead-time increases, demand spikes, supplier failures, shelf-life expiry.",
                "example": "What if lead time from China increases by 15 days?",
            },
            {
                "name": "Forecast Status",
                "description": "Check the status of demand forecasting models and ensemble performance.",
                "example": "What's the demand forecast for next 8 weeks?",
            },
        ]
    }


# ── Export endpoint ───────────────────────────────────────────────────

class ExportRequest(BaseModel):
    reasoning_trace: dict
    format: str = "csv"


@router.post("/export-csv")
async def export_stock_advisory(request: ExportRequest):
    """
    Export the stock advisory shortfall table as CSV.
    The frontend passes the reasoning_trace from the previous chat response
    so we don't need to re-run the entire pipeline.
    """
    trace = request.reasoning_trace
    sa_trace = trace.get("stock_advisor", {})
    math_data = sa_trace.get("math", {})
    skus = math_data.get("skus", [])

    if not skus:
        return {"status": "error", "message": "No stock advisory data to export."}

    # Filter to only SKUs with shortfall > 0
    reorder_skus = [s for s in skus if s.get("shortfall", 0) > 0]

    if not reorder_skus:
        return {"status": "error", "message": "No SKUs need reorder — nothing to export."}

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    header = [
        "SKU ID", "Category", "Sub-Category", "Criticality",
        "Current Stock", "Avg Weekly Demand", "Coverage (weeks)",
        "Projected Monthly Demand", "Forecast Source",
        "Shortfall", "Recommended Order", "Urgency",
    ]
    writer.writerow(header)

    for s in reorder_skus:
        writer.writerow([
            s.get("sku_id", ""),
            s.get("category", ""),
            s.get("sub_category", ""),
            s.get("criticality", ""),
            s.get("current_stock", ""),
            s.get("avg_weekly_demand", ""),
            s.get("coverage_weeks", ""),
            s.get("projected_monthly_demand", ""),
            s.get("forecast_source", ""),
            s.get("shortfall", ""),
            s.get("recommend", ""),
            s.get("urgency", ""),
        ])

    output.seek(0)
    filename = f"genie_reorder_{date.today().isoformat()}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
