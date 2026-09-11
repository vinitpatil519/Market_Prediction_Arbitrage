from __future__ import annotations

from backend.app.services.pairing import build_signature, pair_markets, similarity
from engine.models import Venue
from engine.normalizer import MarketRef, Normalizer


def signature(title: str, venue: Venue = Venue.POLYMARKET):
    return build_signature(MarketRef(venue=venue, market_id="x", event_key="x", title=title))


def test_same_question_phrased_differently_matches():
    left = signature("Will the Fed cut rates at the March meeting?")
    right = signature("Fed cuts rates at the March meeting", Venue.KALSHI)
    assert similarity(left, right) > 0.55


def test_different_thresholds_never_match():
    # The prose is nearly identical and the numbers are the whole contract.
    left = signature("CPI above 3.0% year over year")
    right = signature("CPI above 4.0% year over year", Venue.KALSHI)
    assert similarity(left, right) == 0.0


def test_opposite_directions_never_match():
    left = signature("Bitcoin closes above $100,000")
    right = signature("Bitcoin closes below $100,000", Venue.KALSHI)
    assert similarity(left, right) == 0.0


def test_formatting_of_numbers_is_ignored():
    left = signature("Bitcoin above $100,000 this quarter")
    right = signature("Bitcoin above 100000 this quarter", Venue.KALSHI)
    assert similarity(left, right) > 0.55


def test_unrelated_questions_do_not_match():
    left = signature("Fed cuts rates in March")
    right = signature("OPEC announces a production cut", Venue.KALSHI)
    assert similarity(left, right) < 0.55


def test_pairing_rewrites_event_keys_for_matched_markets():
    normalizer = Normalizer()
    normalizer.register(
        MarketRef(Venue.POLYMARKET, "pm1", "pm:pm1", "Will the Fed cut rates in March?")
    )
    normalizer.register(MarketRef(Venue.KALSHI, "KX1", "kx:KX1", "Fed cuts rates in March"))
    normalizer.register(MarketRef(Venue.KALSHI, "KX2", "kx:KX2", "Yankees win the World Series"))

    matches = pair_markets(normalizer)
    assert len(matches) == 1

    keys = {ref.market_id: ref.event_key for ref in normalizer.markets}
    assert keys["pm1"] == keys["KX1"]
    assert keys["KX2"] != keys["pm1"]


def test_each_market_is_paired_at_most_once():
    normalizer = Normalizer()
    normalizer.register(MarketRef(Venue.POLYMARKET, "pm1", "a", "Fed cuts rates in March"))
    normalizer.register(MarketRef(Venue.POLYMARKET, "pm2", "b", "Fed cuts rates in March"))
    normalizer.register(MarketRef(Venue.KALSHI, "KX1", "c", "Fed cuts rates in March"))
    assert len(pair_markets(normalizer)) == 1
