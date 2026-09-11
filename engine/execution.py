"""Execution simulation and Monte Carlo PnL.

Two things are simulated here and they answer different questions.

`ExecutionSimulator.execute` answers "if I send this basket right now, what do
I actually own and what is it worth under each resolution?". It re-walks the
live book rather than trusting the detector's snapshot, and it models the case
the detector cannot: one leg fills and the other does not, leaving a naked
directional position whose PnL now depends on how the event resolves.

`monte_carlo` answers "if I run this edge a thousand times, what does the
equity curve look like?". Arbitrage returns are tiny and frequent, so the
interesting number is not the expected value - it is the drawdown you have to
sit through and how often a leg-risk event wipes out a month of edge.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field

from engine.kelly import KellySizer
from engine.models import ArbType, MarketBook, Opportunity, OpportunityLeg, Side, Venue


def effective_side(leg: OpportunityLeg) -> Side:
    """The outcome this leg pays out on.

    Shorting YES is economically long NO, so a sell leg pays on the opposite
    outcome from the token it names.
    """
    return leg.side if leg.action == "buy" else leg.side.opposite


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    venue: Venue
    market_id: str
    side: Side
    action: str
    requested_size: float
    filled_size: float
    avg_price: float
    fee: float
    cash_out: float
    complete: bool

    def to_dict(self) -> dict:
        return {
            "venue": self.venue.value,
            "marketId": self.market_id,
            "side": self.side.value,
            "action": self.action,
            "requestedSize": round(self.requested_size, 4),
            "filledSize": round(self.filled_size, 4),
            "avgPrice": round(self.avg_price, 6),
            "fee": round(self.fee, 6),
            "cashOut": round(self.cash_out, 4),
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    opportunity_id: str
    arb_type: ArbType
    fills: list[SimulatedFill]
    requested_size: float
    capital_deployed: float
    #: PnL if the event resolves YES / NO, in dollars.
    pnl_if_yes: float
    pnl_if_no: float
    #: True when every leg filled in full and the basket is riskless.
    hedged: bool
    #: Worst case across both resolutions.
    worst_case: float
    realized_edge: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "opportunityId": self.opportunity_id,
            "arbType": self.arb_type.value,
            "fills": [f.to_dict() for f in self.fills],
            "requestedSize": round(self.requested_size, 4),
            "capitalDeployed": round(self.capital_deployed, 2),
            "pnlIfYes": round(self.pnl_if_yes, 4),
            "pnlIfNo": round(self.pnl_if_no, 4),
            "hedged": self.hedged,
            "worstCase": round(self.worst_case, 4),
            "realizedEdge": round(self.realized_edge, 6),
            "notes": self.notes,
        }


class ExecutionSimulator:
    """Replays an opportunity against live books with realistic failure modes."""

    def __init__(self, detector_config=None) -> None:
        from engine.arbitrage import DetectorConfig  # local import breaks a cycle

        self.config = detector_config or DetectorConfig()

    def execute(
        self,
        opportunity: Opportunity,
        books: dict[tuple[str, str], MarketBook],
        *,
        size: float | None = None,
        drop_legs: set[int] | None = None,
    ) -> SimulatedTrade:
        """Send the basket. `drop_legs` forces specific legs to miss."""
        target = size if size is not None else opportunity.max_size
        drop = drop_legs or set()
        fills: list[SimulatedFill] = []
        notes: list[str] = []

        for index, leg in enumerate(opportunity.legs):
            book = books.get((leg.venue.value, leg.market_id))
            if book is None:
                notes.append(f"leg {index} ({leg.venue.value}) has no live book")
                fills.append(self._missed(leg, target))
                continue
            if index in drop:
                notes.append(f"leg {index} ({leg.venue.value} {leg.side.value}) missed")
                fills.append(self._missed(leg, target))
                continue

            ladder = book.ladder(leg.side)
            buying = leg.action == "buy"
            levels = ladder.asks if buying else ladder.bids
            walk = self.config.slippage.fill(levels, target, buying=buying)
            if walk.filled <= 0:
                notes.append(f"leg {index} found no liquidity")
                fills.append(self._missed(leg, target))
                continue

            fee = self.config.fee_model(leg.venue).trade_fee(walk.avg_price, walk.filled)
            cash_out = (
                walk.avg_price * walk.filled + fee
                if buying
                else (1.0 - walk.avg_price) * walk.filled + fee
            )
            if not walk.complete:
                notes.append(
                    f"leg {index} partially filled: {walk.filled:.0f}/{target:.0f}"
                )
            fills.append(
                SimulatedFill(
                    venue=leg.venue,
                    market_id=leg.market_id,
                    side=leg.side,
                    action=leg.action,
                    requested_size=target,
                    filled_size=walk.filled,
                    avg_price=walk.avg_price,
                    fee=fee,
                    cash_out=cash_out,
                    complete=walk.complete,
                )
            )

        capital = sum(f.cash_out for f in fills)
        pnl_yes = self._settle(opportunity.legs, fills, Side.YES) - capital
        pnl_no = self._settle(opportunity.legs, fills, Side.NO) - capital
        hedged = all(f.complete and f.filled_size > 0 for f in fills) and abs(
            pnl_yes - pnl_no
        ) < 1e-6
        realized = (min(pnl_yes, pnl_no) / target) if target > 0 else 0.0

        return SimulatedTrade(
            opportunity_id=opportunity.id,
            arb_type=opportunity.arb_type,
            fills=fills,
            requested_size=target,
            capital_deployed=capital,
            pnl_if_yes=pnl_yes,
            pnl_if_no=pnl_no,
            hedged=hedged,
            worst_case=min(pnl_yes, pnl_no),
            realized_edge=realized,
            notes=notes,
        )

    @staticmethod
    def _settle(legs: list[OpportunityLeg], fills: list[SimulatedFill], outcome: Side) -> float:
        """Cash received at settlement for a given resolution."""
        total = 0.0
        for leg, fill in zip(legs, fills, strict=True):
            if effective_side(leg) is outcome:
                total += fill.filled_size
        return total

    @staticmethod
    def _missed(leg: OpportunityLeg, size: float) -> SimulatedFill:
        return SimulatedFill(
            venue=leg.venue,
            market_id=leg.market_id,
            side=leg.side,
            action=leg.action,
            requested_size=size,
            filled_size=0.0,
            avg_price=0.0,
            fee=0.0,
            cash_out=0.0,
            complete=False,
        )


# --------------------------------------------------------------- monte carlo


@dataclass(slots=True)
class MonteCarloParams:
    bankroll: float = 10_000.0
    trades: int = 250
    paths: int = 500
    #: Net edge per contract pair, in dollars. 0.015 = 1.5c.
    net_edge: float = 0.015
    #: Cost of assembling one $1 basket.
    cost_per_pair: float = 0.985
    fill_probability: float = 0.985
    #: Expected fraction of stake lost when the hedge breaks.
    loss_fraction: float = 0.5
    kelly_multiplier: float = 0.25
    max_fraction_per_trade: float = 0.20
    seed: int | None = 7


def monte_carlo(params: MonteCarloParams) -> dict:
    """Simulate repeated Kelly-sized arbitrage bets.

    Each trade is a Bernoulli draw: the hedge holds and pays the net edge, or
    it breaks and costs `loss_fraction` of the stake. Wealth compounds, so the
    output is a distribution of paths rather than a single expected value.
    """
    from engine.kelly import expected_log_growth, kelly_fraction

    rng = random.Random(params.seed)
    cost = max(1e-6, min(0.999999, params.cost_per_pair))
    win_payoff = max(0.0, (1.0 - cost) / cost)

    full_f = kelly_fraction(params.fill_probability, win_payoff, params.loss_fraction)
    f = min(full_f * params.kelly_multiplier, params.max_fraction_per_trade)

    curves: list[list[float]] = []
    terminals: list[float] = []
    drawdowns: list[float] = []
    ruin = 0

    for _ in range(params.paths):
        wealth = params.bankroll
        peak = wealth
        max_dd = 0.0
        curve = [wealth]
        for _ in range(params.trades):
            stake = wealth * f
            if rng.random() < params.fill_probability:
                wealth += stake * win_payoff
            else:
                wealth -= stake * params.loss_fraction
            wealth = max(0.0, wealth)
            peak = max(peak, wealth)
            if peak > 0:
                max_dd = max(max_dd, (peak - wealth) / peak)
            curve.append(wealth)
        curves.append(curve)
        terminals.append(wealth)
        drawdowns.append(max_dd)
        if wealth < params.bankroll * 0.5:
            ruin += 1

    percentile_curves = _percentile_curves(curves, (0.05, 0.25, 0.5, 0.75, 0.95))
    returns = [t / params.bankroll - 1.0 for t in terminals]

    return {
        "params": {
            "bankroll": params.bankroll,
            "trades": params.trades,
            "paths": params.paths,
            "netEdge": params.net_edge,
            "costPerPair": cost,
            "fillProbability": params.fill_probability,
            "lossFraction": params.loss_fraction,
            "kellyMultiplier": params.kelly_multiplier,
        },
        "sizing": {
            "fullKellyFraction": round(full_f, 6),
            "appliedFraction": round(f, 6),
            "winPayoff": round(win_payoff, 6),
            "expectedLogGrowth": round(
                expected_log_growth(f, params.fill_probability, win_payoff, params.loss_fraction),
                8,
            ),
        },
        "curves": percentile_curves,
        "stats": {
            "medianTerminal": round(statistics.median(terminals), 2),
            "meanTerminal": round(statistics.fmean(terminals), 2),
            "p5Terminal": round(_quantile(sorted(terminals), 0.05), 2),
            "p95Terminal": round(_quantile(sorted(terminals), 0.95), 2),
            "medianReturn": round(statistics.median(returns), 6),
            "medianMaxDrawdown": round(statistics.median(drawdowns), 6),
            "worstMaxDrawdown": round(max(drawdowns) if drawdowns else 0.0, 6),
            "probHalved": round(ruin / max(1, params.paths), 4),
            "sharpe": round(_sharpe(returns, params.trades), 4),
        },
    }


def _percentile_curves(curves: list[list[float]], quantiles: tuple[float, ...]) -> dict:
    if not curves:
        return {}
    length = len(curves[0])
    out: dict[str, list[float]] = {f"p{int(q * 100)}": [] for q in quantiles}
    for step in range(length):
        column = sorted(curve[step] for curve in curves)
        for q in quantiles:
            out[f"p{int(q * 100)}"].append(round(_quantile(column, q), 2))
    return out


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[int(position)]
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _sharpe(returns: list[float], periods: int) -> float:
    """Annualisation is meaningless without a calendar, so this is a
    per-campaign Sharpe: mean terminal return over its own dispersion."""
    if len(returns) < 2:
        return 0.0
    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns)
    if stdev <= 1e-12:
        return 0.0
    return (mean / stdev) * math.sqrt(max(1, periods))


def size_and_simulate(
    opportunity: Opportunity, bankroll: float, sizer: KellySizer | None = None, **overrides
) -> dict:
    """Kelly-size a live opportunity, then Monte Carlo that exact bet."""
    sizer = sizer or KellySizer()
    result = sizer.size(opportunity, bankroll)
    cost_per_pair = (
        sum(leg.cash_out for leg in opportunity.legs) / opportunity.max_size
        if opportunity.max_size > 0
        else 1.0
    )
    params = MonteCarloParams(
        bankroll=bankroll,
        net_edge=opportunity.net_edge,
        cost_per_pair=cost_per_pair,
        fill_probability=opportunity.fill_probability,
        kelly_multiplier=sizer.kelly_multiplier,
        max_fraction_per_trade=sizer.max_fraction_per_trade,
        loss_fraction=sizer.loss_fraction,
        **overrides,
    )
    return {"kelly": result.to_dict(), "monteCarlo": monte_carlo(params)}
