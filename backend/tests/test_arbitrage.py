from __future__ import annotations

import pytest

from backend.tests.conftest import book
from engine.arbitrage import ArbitrageDetector, DetectorConfig, divergence_by_event
from engine.fees import FeeModel, PolymarketFeeModel
from engine.models import ArbType, Ladder, Level, MarketBook, Venue
from engine.slippage import SlippageModel


def free(venue: Venue) -> FeeModel:
    return FeeModel(venue=venue)


@pytest.fixture
def no_fee_detector(frictionless):
    return ArbitrageDetector(
        DetectorConfig(
            slippage=frictionless,
            min_net_edge=0.0001,
            fee_models={venue: free(venue) for venue in Venue},
        )
    )


def test_no_arbitrage_on_a_fairly_priced_book(no_fee_detector):
    # Asks sum to 1.02: the spread is the market maker's, not yours.
    fair = book(Venue.POLYMARKET, "m1", yes_bid=0.49, yes_ask=0.51, no_bid=0.49, no_ask=0.51)
    assert no_fee_detector.scan([fair]) == []


def test_same_venue_under_one_dollar_is_detected(no_fee_detector):
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.44, yes_ask=0.46, no_bid=0.50, no_ask=0.52)
    found = [o for o in no_fee_detector.scan([cheap]) if o.arb_type is ArbType.SAME_VENUE_UNDER]
    assert len(found) == 1
    # README's formula: 1 - (YesAsk + NoAsk) = 1 - (0.46 + 0.52) = 0.02.
    assert found[0].gross_edge == pytest.approx(0.02)
    assert found[0].net_edge == pytest.approx(0.02)
    assert found[0].expected_profit == pytest.approx(0.02 * 1_000)


def test_same_venue_over_one_dollar_is_detected(no_fee_detector):
    # Bids sum to 1.03, so selling both sides collects more than the $1 you
    # can ever owe.
    rich = book(Venue.POLYMARKET, "m1", yes_bid=0.53, yes_ask=0.55, no_bid=0.50, no_ask=0.52)
    found = [o for o in no_fee_detector.scan([rich]) if o.arb_type is ArbType.SAME_VENUE_OVER]
    assert len(found) == 1
    assert found[0].gross_edge == pytest.approx(0.03)
    assert all(leg.action == "sell" for leg in found[0].legs)


def test_cross_venue_arbitrage_pairs_opposite_sides(no_fee_detector):
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.55, no_ask=0.57)
    rich = book(Venue.KALSHI, "K1", yes_bid=0.53, yes_ask=0.55, no_bid=0.45, no_ask=0.47)
    found = [o for o in no_fee_detector.scan([cheap, rich]) if o.arb_type is ArbType.CROSS_VENUE]
    assert found
    best = found[0]
    # Buy YES at 0.45 on the cheap venue, NO at 0.47 on the rich one.
    assert best.gross_edge == pytest.approx(0.08)
    assert {leg.venue for leg in best.legs} == {Venue.POLYMARKET, Venue.KALSHI}


def test_cross_venue_requires_a_shared_event_key(no_fee_detector):
    a = book(
        Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.55, no_ask=0.57, event_key="a"
    )
    b = book(
        Venue.KALSHI, "K1", yes_bid=0.53, yes_ask=0.55, no_bid=0.45, no_ask=0.47, event_key="b"
    )
    assert not [o for o in no_fee_detector.scan([a, b]) if o.arb_type is ArbType.CROSS_VENUE]


def test_equivalent_baskets_are_reported_once(no_fee_detector):
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.55, no_ask=0.57)
    rich = book(Venue.KALSHI, "K1", yes_bid=0.53, yes_ask=0.55, no_bid=0.45, no_ask=0.47)
    found = no_fee_detector.scan([cheap, rich])
    exposures = {
        tuple(sorted((leg.venue.value, leg.side.value, leg.action) for leg in o.legs))
        for o in found
    }
    assert len(exposures) == len(found)


def test_fees_can_erase_a_gross_edge(frictionless):
    # A 1c gross edge at 50c on Kalshi: the fee alone is 1.75c per contract.
    from engine.fees import KalshiFeeModel

    detector = ArbitrageDetector(
        DetectorConfig(
            slippage=frictionless,
            min_net_edge=0.0001,
            fee_models={Venue.KALSHI: KalshiFeeModel(), Venue.POLYMARKET: PolymarketFeeModel()},
        )
    )
    thin = book(Venue.KALSHI, "K1", yes_bid=0.48, yes_ask=0.495, no_bid=0.48, no_ask=0.495)
    assert thin.yes.best_ask + thin.no.best_ask < 1.0  # gross edge exists
    assert detector.scan([thin]) == []  # net edge does not


def test_the_detector_trades_size_against_edge(no_fee_detector):
    # 2c of edge on 50 contracts, or 0.5c on 5,050. Total dollars win.
    deep = MarketBook(
        venue=Venue.POLYMARKET,
        market_id="deep",
        event_key="ev",
        title="t",
        yes=Ladder(asks=[Level(0.46, 50), Level(0.47, 5_000)]),
        no=Ladder(asks=[Level(0.52, 50), Level(0.525, 5_000)]),
    )
    found = [o for o in no_fee_detector.scan([deep]) if o.arb_type is ArbType.SAME_VENUE_UNDER]
    assert found
    assert found[0].gross_edge == pytest.approx(0.02)
    assert found[0].net_edge < found[0].gross_edge
    assert found[0].max_size > 50
    assert found[0].expected_profit > 0.02 * 50


def test_edge_is_capped_at_the_touch_when_depth_is_worthless(no_fee_detector):
    # The second level is priced through $1.00, so nothing past the touch is
    # tradeable and the clip stops at 50.
    shallow = MarketBook(
        venue=Venue.POLYMARKET,
        market_id="shallow",
        event_key="ev",
        title="t",
        yes=Ladder(asks=[Level(0.46, 50), Level(0.60, 5_000)]),
        no=Ladder(asks=[Level(0.52, 50), Level(0.60, 5_000)]),
    )
    found = [o for o in no_fee_detector.scan([shallow]) if o.arb_type is ArbType.SAME_VENUE_UNDER]
    assert found[0].max_size == pytest.approx(50)
    assert found[0].net_edge == pytest.approx(found[0].gross_edge)


def test_stale_books_are_skipped(no_fee_detector):
    stale = book(Venue.POLYMARKET, "m1", yes_bid=0.44, yes_ask=0.46, no_bid=0.50, no_ask=0.52)
    stale.ts -= 60
    assert no_fee_detector.scan([stale]) == []


def test_crossed_books_are_skipped(no_fee_detector):
    broken = book(Venue.POLYMARKET, "m1", yes_bid=0.60, yes_ask=0.46, no_bid=0.50, no_ask=0.52)
    assert broken.is_crossed
    assert no_fee_detector.scan([broken]) == []


def test_fill_probability_is_lower_for_cross_venue(no_fee_detector):
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.50, no_ask=0.52)
    rich = book(Venue.KALSHI, "K1", yes_bid=0.53, yes_ask=0.55, no_bid=0.45, no_ask=0.47)
    found = no_fee_detector.scan([cheap, rich])
    same = next(o for o in found if o.arb_type is ArbType.SAME_VENUE_UNDER)
    cross = next(o for o in found if o.arb_type is ArbType.CROSS_VENUE)
    assert cross.fill_probability < same.fill_probability


def test_divergence_reports_the_rich_and_cheap_venue():
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.55, no_ask=0.57)
    rich = book(Venue.KALSHI, "K1", yes_bid=0.53, yes_ask=0.55, no_bid=0.45, no_ask=0.47)
    rows = divergence_by_event([cheap, rich])
    assert len(rows) == 1
    assert rows[0]["cheapVenue"] == "polymarket"
    assert rows[0]["richVenue"] == "kalshi"
    assert rows[0]["divergence"] == pytest.approx(0.10)


def test_divergence_needs_two_venues():
    only_one = book(Venue.POLYMARKET, "m1", yes_bid=0.43, yes_ask=0.45, no_bid=0.55, no_ask=0.57)
    assert divergence_by_event([only_one]) == []


def test_latency_decay_reduces_tradeable_size(frictionless):
    laggy = ArbitrageDetector(
        DetectorConfig(
            slippage=SlippageModel(latency_ms=500, decay_per_100ms=0.10),
            min_net_edge=0.0001,
            fee_models={venue: free(venue) for venue in Venue},
        )
    )
    prompt = ArbitrageDetector(
        DetectorConfig(
            slippage=frictionless,
            min_net_edge=0.0001,
            fee_models={venue: free(venue) for venue in Venue},
        )
    )
    cheap = book(Venue.POLYMARKET, "m1", yes_bid=0.44, yes_ask=0.46, no_bid=0.50, no_ask=0.52)
    slow = laggy.scan([cheap])[0]
    fast = prompt.scan([cheap])[0]
    assert slow.max_size < fast.max_size
