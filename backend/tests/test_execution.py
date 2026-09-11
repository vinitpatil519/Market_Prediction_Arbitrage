from __future__ import annotations

import pytest

from backend.tests.conftest import book
from engine.arbitrage import ArbitrageDetector, DetectorConfig
from engine.execution import (
    ExecutionSimulator,
    MonteCarloParams,
    effective_side,
    monte_carlo,
)
from engine.fees import FeeModel
from engine.models import Side, Venue


@pytest.fixture
def setup(frictionless):
    config = DetectorConfig(
        slippage=frictionless,
        min_net_edge=0.0001,
        fee_models={venue: FeeModel(venue=venue) for venue in Venue},
    )
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.44, yes_ask=0.46, no_bid=0.50, no_ask=0.52)
    opportunity = ArbitrageDetector(config).scan([cheap])[0]
    books = {("polymarket", "m1"): cheap}
    return ExecutionSimulator(config), opportunity, books


def test_selling_yes_is_economically_long_no():
    from engine.models import OpportunityLeg

    leg = OpportunityLeg(
        venue=Venue.POLYMARKET,
        market_id="m1",
        side=Side.YES,
        action="sell",
        touch_price=0.5,
        avg_price=0.5,
        size=1,
        fee=0,
        slippage=0,
        levels_consumed=1,
    )
    assert effective_side(leg) is Side.NO


def test_a_complete_basket_pays_the_same_under_either_resolution(setup):
    simulator, opportunity, books = setup
    trade = simulator.execute(opportunity, books, size=100)
    assert trade.hedged
    assert trade.pnl_if_yes == pytest.approx(trade.pnl_if_no)
    # 100 pairs bought for 0.98 each, redeemed at 1.00.
    assert trade.pnl_if_yes == pytest.approx(2.0)


def test_a_broken_hedge_is_directional(setup):
    simulator, opportunity, books = setup
    trade = simulator.execute(opportunity, books, size=100, drop_legs={1})
    assert not trade.hedged
    assert trade.pnl_if_yes > 0 > trade.pnl_if_no
    assert trade.worst_case < 0
    assert trade.notes


def test_a_missing_venue_book_does_not_crash(setup):
    simulator, opportunity, _ = setup
    trade = simulator.execute(opportunity, {}, size=100)
    assert trade.capital_deployed == 0.0
    assert not trade.hedged
    assert len(trade.notes) == len(opportunity.legs)


def test_oversized_orders_partially_fill(setup):
    simulator, opportunity, books = setup
    trade = simulator.execute(opportunity, books, size=5_000)
    assert any(not fill.complete for fill in trade.fills)


def test_monte_carlo_is_deterministic_under_a_seed():
    params = MonteCarloParams(paths=50, trades=40, seed=11)
    assert monte_carlo(params)["stats"] == monte_carlo(params)["stats"]


def test_a_bigger_edge_compounds_to_more_wealth():
    small = monte_carlo(MonteCarloParams(paths=200, trades=100, cost_per_pair=0.995, seed=3))
    large = monte_carlo(MonteCarloParams(paths=200, trades=100, cost_per_pair=0.96, seed=3))
    assert large["stats"]["medianTerminal"] > small["stats"]["medianTerminal"]


def test_higher_break_risk_deepens_the_drawdown():
    # Same edge and same stake cap, so the only difference is how often the
    # hedge breaks. Shared seed makes the risky path's losses a superset.
    common = {"paths": 300, "trades": 150, "cost_per_pair": 0.90, "seed": 5}
    safe = monte_carlo(MonteCarloParams(fill_probability=0.9995, **common))
    risky = monte_carlo(MonteCarloParams(fill_probability=0.99, **common))
    assert risky["stats"]["worstMaxDrawdown"] > safe["stats"]["worstMaxDrawdown"]


def test_break_risk_can_make_a_real_edge_untradeable():
    # A 30 bps edge against a 1% chance of losing half the stake is negative
    # expectancy, so Kelly stakes nothing and the equity curve is flat.
    result = monte_carlo(
        MonteCarloParams(paths=50, trades=100, cost_per_pair=0.997, fill_probability=0.99, seed=5)
    )
    assert result["sizing"]["appliedFraction"] == 0.0
    assert result["stats"]["medianTerminal"] == pytest.approx(result["params"]["bankroll"])


def test_percentile_curves_are_ordered_and_complete():
    result = monte_carlo(MonteCarloParams(paths=200, trades=60, seed=9))
    curves = result["curves"]
    assert len(curves["p50"]) == 61
    for index in range(61):
        assert curves["p5"][index] <= curves["p50"][index] <= curves["p95"][index]
