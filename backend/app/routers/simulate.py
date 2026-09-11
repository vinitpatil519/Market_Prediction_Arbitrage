"""Execution simulation, Kelly sizing and Monte Carlo endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.db import SessionLocal, SimulatedTradeRow
from backend.app.schemas import ExecuteRequest, KellyRequest, MonteCarloRequest
from backend.app.services.engine_runner import get_runner
from engine.execution import MonteCarloParams, monte_carlo
from engine.kelly import KellySizer

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


@router.post("/execute")
async def execute(request: ExecuteRequest) -> dict:
    """Replay an opportunity against the live books, fees and slippage included."""
    runner = get_runner()
    opportunity = runner.find_opportunity(request.opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity no longer live")

    trade = runner.simulator.execute(
        opportunity,
        runner.books,
        size=request.size,
        drop_legs=set(request.drop_legs),
    )

    if request.persist and runner.settings.persist:
        try:
            async with SessionLocal() as session:
                session.add(
                    SimulatedTradeRow(
                        ts=opportunity.ts,
                        opportunity_id=trade.opportunity_id,
                        arb_type=trade.arb_type.value,
                        size=trade.requested_size,
                        capital_deployed=trade.capital_deployed,
                        pnl_if_yes=trade.pnl_if_yes,
                        pnl_if_no=trade.pnl_if_no,
                        hedged=trade.hedged,
                        realized_edge=trade.realized_edge,
                        fills=[fill.to_dict() for fill in trade.fills],
                    )
                )
                await session.commit()
        except Exception:
            pass

    return {
        "trade": trade.to_dict(),
        "opportunity": opportunity.to_dict(),
    }


@router.post("/kelly")
async def kelly(request: KellyRequest) -> dict:
    runner = get_runner()
    opportunity = runner.find_opportunity(request.opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity no longer live")

    sizer = KellySizer(
        kelly_multiplier=request.kelly_multiplier or runner.sizer.kelly_multiplier,
        max_fraction_per_trade=request.max_fraction_per_trade
        or runner.sizer.max_fraction_per_trade,
        loss_fraction=request.loss_fraction or runner.sizer.loss_fraction,
    )
    result = sizer.size(opportunity, request.bankroll)
    return {
        "opportunityId": opportunity.id,
        "netEdge": round(opportunity.net_edge, 6),
        "kelly": result.to_dict(),
    }


@router.post("/montecarlo")
async def montecarlo(request: MonteCarloRequest) -> dict:
    """Compound the same edge many times and return the path distribution."""
    return monte_carlo(
        MonteCarloParams(
            bankroll=request.bankroll,
            trades=request.trades,
            paths=request.paths,
            net_edge=request.net_edge,
            cost_per_pair=request.cost_per_pair,
            fill_probability=request.fill_probability,
            loss_fraction=request.loss_fraction,
            kelly_multiplier=request.kelly_multiplier,
            max_fraction_per_trade=request.max_fraction_per_trade,
            seed=request.seed,
        )
    )
