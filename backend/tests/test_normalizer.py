from __future__ import annotations

import pytest

from engine.models import Side, Venue
from engine.normalizer import MarketRef, Normalizer


@pytest.fixture
def normalizer() -> Normalizer:
    n = Normalizer()
    n.register(
        MarketRef(
            venue=Venue.POLYMARKET,
            market_id="0xabc",
            event_key="ev",
            title="Test",
            token_ids={Side.YES: "tok-yes", Side.NO: "tok-no"},
        )
    )
    n.register(MarketRef(venue=Venue.KALSHI, market_id="KXTEST", event_key="ev", title="Test"))
    return n


def test_kalshi_cents_become_dollars(normalizer):
    payload = {"msg": {"market_ticker": "KXTEST", "yes": [[45, 100]], "no": [[52, 200]]}}
    book = normalizer.kalshi_book(payload)
    assert book.yes.best_bid == pytest.approx(0.45)
    assert book.no.best_bid == pytest.approx(0.52)


def test_kalshi_asks_are_reflections_of_the_other_sides_bids(normalizer):
    # This is the whole Kalshi gotcha: there is no ask book. An offer to sell
    # YES at 48c is stored as a bid to buy NO at 52c.
    payload = {"msg": {"market_ticker": "KXTEST", "yes": [[45, 100]], "no": [[52, 200]]}}
    book = normalizer.kalshi_book(payload)
    assert book.yes.best_ask == pytest.approx(0.48)
    assert book.no.best_ask == pytest.approx(0.55)
    assert book.yes.asks[0].size == 200


def test_reading_kalshi_no_bids_as_asks_would_hallucinate_an_edge(normalizer):
    payload = {"msg": {"market_ticker": "KXTEST", "yes": [[45, 100]], "no": [[52, 200]]}}
    book = normalizer.kalshi_book(payload)
    naive_edge = 1.0 - (book.yes.best_bid + book.no.best_bid)  # what the bug looks like
    real_edge = 1.0 - (book.yes.best_ask + book.no.best_ask)
    assert naive_edge > 0  # 3c of phantom arbitrage
    assert real_edge < 0  # the real book is 3c wide


def test_polymarket_tokens_route_to_the_right_side(normalizer):
    payload = {
        "event_type": "book",
        "asset_id": "tok-no",
        "bids": [{"price": "0.51", "size": "10"}],
        "asks": [{"price": "0.53", "size": "10"}],
    }
    book = normalizer.polymarket_book(payload)
    assert book.no.best_ask == pytest.approx(0.53)
    assert book.yes.best_ask is None


def test_merge_combines_both_token_books(normalizer):
    yes_side = normalizer.polymarket_book(
        {"event_type": "book", "asset_id": "tok-yes", "bids": [[0.44, 10]], "asks": [[0.46, 10]]}
    )
    no_side = normalizer.polymarket_book(
        {"event_type": "book", "asset_id": "tok-no", "bids": [[0.52, 10]], "asks": [[0.54, 10]]}
    )
    merged = normalizer.merge(normalizer.merge(None, yes_side), no_side)
    assert merged.yes.best_ask == pytest.approx(0.46)
    assert merged.no.best_ask == pytest.approx(0.54)


def test_unknown_markets_are_dropped_not_guessed(normalizer):
    unknown = {"msg": {"market_ticker": "UNKNOWN", "yes": [], "no": []}}
    assert normalizer.kalshi_book(unknown) is None
    assert normalizer.polymarket_book({"asset_id": "nope", "bids": [], "asks": []}) is None


def test_single_sided_book_is_filled_from_its_mirror(normalizer):
    yes_only = normalizer.polymarket_book(
        {"event_type": "book", "asset_id": "tok-yes", "bids": [[0.44, 10]], "asks": [[0.46, 10]]}
    )
    complete = normalizer.merge(None, yes_only)
    assert complete.no.best_ask == pytest.approx(0.56)
    assert complete.no.best_bid == pytest.approx(0.54)


@pytest.mark.parametrize(
    "raw,expected",
    [(1_700_000_000, 1_700_000_000), (1_700_000_000_000, 1_700_000_000)],
)
def test_timestamps_normalise_to_seconds(normalizer, raw, expected):
    from engine.normalizer import _timestamp

    assert _timestamp(raw) == pytest.approx(expected)
