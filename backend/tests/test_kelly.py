from __future__ import annotations

import pytest

from backend.tests.conftest import book
from engine.arbitrage import ArbitrageDetector, DetectorConfig
from engine.fees import FeeModel
from engine.kelly import KellySizer, expected_log_growth, kelly_fraction
from engine.models import Venue


def test_classic_kelly_matches_the_textbook_case():
    # Even-money bet at 60/40 with total loss on a miss: f* = 2p - 1 = 0.20.
    assert kelly_fraction(0.60, 1.0, 1.0) == pytest.approx(0.20)


def test_kelly_is_zero_when_the_bet_is_not_profitable():
    assert kelly_fraction(0.40, 1.0, 1.0) == 0.0
    assert kelly_fraction(0.50, 1.0, 1.0) == 0.0


def test_partial_loss_raises_the_optimal_stake():
    # Same edge, but a miss only costs half the stake, so bet more.
    full_loss = kelly_fraction(0.60, 1.0, 1.0)
    half_loss = kelly_fraction(0.60, 1.0, 0.5)
    assert half_loss > full_loss


def test_kelly_maximises_log_growth():
    p, b, a = 0.75, 1.0, 1.0
    optimal = kelly_fraction(p, b, a)
    best = expected_log_growth(optimal, p, b, a)
    for offset in (-0.15, -0.05, 0.05, 0.15):
        assert expected_log_growth(optimal + offset, p, b, a) <= best + 1e-12


def test_thin_edges_are_rejected_because_of_break_risk():
    # A 20 bps edge cannot pay for a 0.5% chance of losing half the stake:
    # the expected cost of a break is 25 bps.
    sizer = KellySizer(loss_fraction=0.5)
    detector = ArbitrageDetector(
        DetectorConfig(min_net_edge=0.0001, fee_models={v: FeeModel(venue=v) for v in Venue})
    )
    thin = book(Venue.POLYMARKET, "m1", yes_bid=0.48, yes_ask=0.499, no_bid=0.48, no_ask=0.499)
    opportunity = detector.scan([thin])[0]
    result = sizer.size(opportunity, 10_000)
    assert result.stake == 0.0
    assert result.binding_constraint == "risk"


def test_a_wide_edge_is_capped_by_the_per_trade_limit():
    sizer = KellySizer(kelly_multiplier=0.25, max_fraction_per_trade=0.20)
    detector = ArbitrageDetector(
        DetectorConfig(min_net_edge=0.0001, fee_models={v: FeeModel(venue=v) for v in Venue})
    )
    wide = book(
        Venue.POLYMARKET, "m1", yes_bid=0.40, yes_ask=0.42, no_bid=0.50, no_ask=0.52, size=10_000
    )
    opportunity = detector.scan([wide])[0]
    result = sizer.size(opportunity, 10_000)
    assert result.binding_constraint in {"cap", "depth"}
    assert result.stake <= 10_000 * 0.20 + 1e-6


def test_depth_binds_before_bankroll_on_a_thin_book():
    sizer = KellySizer()
    detector = ArbitrageDetector(
        DetectorConfig(min_net_edge=0.0001, fee_models={v: FeeModel(venue=v) for v in Venue})
    )
    shallow = book(
        Venue.POLYMARKET, "m1", yes_bid=0.40, yes_ask=0.42, no_bid=0.50, no_ask=0.52, size=25
    )
    opportunity = detector.scan([shallow])[0]
    result = sizer.size(opportunity, 1_000_000)
    assert result.binding_constraint == "depth"
    assert result.contracts == pytest.approx(opportunity.max_size)


def test_allocation_never_exceeds_the_bankroll():
    sizer = KellySizer()
    detector = ArbitrageDetector(
        DetectorConfig(min_net_edge=0.0001, fee_models={v: FeeModel(venue=v) for v in Venue})
    )
    books = [
        book(
            Venue.POLYMARKET,
            f"m{index}",
            yes_bid=0.40,
            yes_ask=0.42,
            no_bid=0.50,
            no_ask=0.52,
            size=10_000,
            event_key=f"ev{index}",
        )
        for index in range(6)
    ]
    opportunities = detector.scan(books)
    allocations = sizer.allocate(opportunities, 10_000)
    assert sum(result.stake for _, result in allocations) <= 10_000 + 1e-6


def test_fractional_kelly_scales_the_stake_down():
    detector = ArbitrageDetector(
        DetectorConfig(min_net_edge=0.0001, fee_models={v: FeeModel(venue=v) for v in Venue})
    )
    wide = book(
        Venue.POLYMARKET, "m1", yes_bid=0.40, yes_ask=0.42, no_bid=0.50, no_ask=0.52, size=10_000
    )
    opportunity = detector.scan([wide])[0]
    full = KellySizer(kelly_multiplier=1.0, max_fraction_per_trade=1.0).size(opportunity, 10_000)
    quarter = KellySizer(kelly_multiplier=0.25, max_fraction_per_trade=1.0).size(
        opportunity, 10_000
    )
    assert quarter.stake < full.stake
