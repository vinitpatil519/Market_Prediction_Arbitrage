"""Opportunity screening endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from backend.app.db import OpportunityRow, SessionLocal
from backend.app.services.engine_runner import get_runner

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("")
async def list_opportunities(
    arb_type: str | None = None,
    event_key: str | None = None,
    min_edge: float = Query(default=0.0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    runner = get_runner()
    rows = runner.opportunities
    if arb_type:
        rows = [o for o in rows if o.arb_type.value == arb_type]
    if event_key:
        rows = [o for o in rows if o.event_key == event_key]
    if min_edge:
        rows = [o for o in rows if o.net_edge >= min_edge]
    rows = rows[:limit]

    sized = runner.sizer.allocate(rows, runner.settings.bankroll)
    return {
        "count": len(rows),
        "bankroll": runner.settings.bankroll,
        "opportunities": [
            {**opportunity.to_dict(), "kelly": result.to_dict()}
            for opportunity, result in sized
        ],
    }


@router.get("/summary")
async def summary() -> dict:
    """Screen-level aggregates for the dashboard header."""
    runner = get_runner()
    rows = runner.opportunities
    by_type: dict[str, int] = {}
    for opportunity in rows:
        by_type[opportunity.arb_type.value] = by_type.get(opportunity.arb_type.value, 0) + 1
    return {
        "live": len(rows),
        "byType": by_type,
        "bestNetEdge": round(max((o.net_edge for o in rows), default=0.0), 6),
        "bestNetEdgeBps": round(max((o.net_edge_bps for o in rows), default=0.0), 1),
        "totalScreenedProfit": round(sum(o.expected_profit for o in rows), 2),
        "totalCapitalRequired": round(sum(o.capital_required for o in rows), 2),
        "stats": runner.stats.to_dict(),
        "config": runner.config_dict(),
    }


@router.get("/history")
async def history(
    limit: int = Query(default=200, ge=1, le=2_000),
    min_edge: float = Query(default=0.0, ge=0),
) -> dict:
    """Persisted opportunities, newest first."""
    async with SessionLocal() as session:
        statement = (
            select(OpportunityRow)
            .where(OpportunityRow.net_edge >= min_edge)
            .order_by(OpportunityRow.id.desc())
            .limit(limit)
        )
        result = await session.execute(statement)
        rows = result.scalars().all()
        total = await session.scalar(select(func.count(OpportunityRow.id)))

    return {
        "total": total or 0,
        "rows": [
            {
                "opportunityId": row.opportunity_id,
                "ts": row.ts,
                "arbType": row.arb_type,
                "eventKey": row.event_key,
                "title": row.title,
                "grossEdge": row.gross_edge,
                "netEdge": row.net_edge,
                "netEdgeBps": round(row.net_edge * 10_000, 1),
                "maxSize": row.max_size,
                "capitalRequired": row.capital_required,
                "expectedProfit": row.expected_profit,
                "fillProbability": row.fill_probability,
                "legs": row.legs,
            }
            for row in rows
        ],
    }


@router.get("/{opportunity_id}")
async def get_opportunity(opportunity_id: str) -> dict:
    runner = get_runner()
    opportunity = runner.find_opportunity(opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity no longer live")
    kelly = runner.sizer.size(opportunity, runner.settings.bankroll)
    return {**opportunity.to_dict(), "kelly": kelly.to_dict()}
