from __future__ import annotations

import pytest

from engine.arbitrage import ArbitrageDetector, DetectorConfig
from engine.models import Ladder, Level, MarketBook, Venue
from engine.slippage import SlippageModel


@pytest.fixture
def frictionless() -> SlippageModel:
    """No latency decay and no adverse tick, so depth cost is the only cost."""
    return SlippageModel(latency_ms=0.0, decay_per_100ms=0.0, adverse_tick=0.0)


@pytest.fixture
def detector(frictionless: SlippageModel) -> ArbitrageDetector:
    return ArbitrageDetector(DetectorConfig(slippage=frictionless, min_net_edge=0.0001))


def book(
    venue: Venue,
    market_id: str,
    *,
    yes_bid: float,
    yes_ask: float,
    no_bid: float,
    no_ask: float,
    size: float = 1_000.0,
    event_key: str = "ev",
) -> MarketBook:
    return MarketBook(
        venue=venue,
        market_id=market_id,
        event_key=event_key,
        title="Test event",
        yes=Ladder(bids=[Level(yes_bid, size)], asks=[Level(yes_ask, size)]),
        no=Ladder(bids=[Level(no_bid, size)], asks=[Level(no_ask, size)]),
    )
