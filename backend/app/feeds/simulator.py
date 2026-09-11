"""Synthetic two-venue market simulator.

This is not decoration. Live Polymarket and Kalshi credentials are not
available in every environment, and a screener you cannot run is a screener
you cannot verify, so the default feed generates books with the statistical
properties that make the detector's job non-trivial:

* A latent true probability per event, mean-reverting so prices are correlated
  through time rather than independent noise.
* A slow per-venue pricing bias, which is what real cross-venue divergence
  looks like: the venues disagree persistently, not tick-by-tick.
* Occasional dislocation shocks that jump one venue's bias, opening a window
  that closes again over the next few seconds.
* Venue-accurate book structure. Polymarket gets two independent token books
  with a 0.1c tick; Kalshi gets bid-only ladders on a 1c tick whose asks are
  reflections, exactly as the real feed behaves.

The events deliberately span the probability range. Kalshi's fee is
`0.07 * p * (1 - p)`, so it costs 1.75c per contract at a coin flip and 0.6c
in the tails - which means profitable cross-venue arbitrage clusters at the
tails, and a simulator that only generated 50c markets would make the whole
strategy look dead.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from backend.app.feeds.base import Feed
from engine.models import Ladder, Level, MarketBook, Side, Venue
from engine.normalizer import MarketRef, Normalizer

EVENT_TEMPLATES: list[tuple[str, str, float]] = [
    ("fed-cut-march", "Fed cuts rates at the March meeting", 0.62),
    ("cpi-above-3", "CPI prints above 3.0% year over year", 0.34),
    ("btc-100k", "Bitcoin closes above $100,000 this quarter", 0.71),
    ("gov-shutdown", "US government shutdown before year end", 0.12),
    ("nvda-beat", "NVDA beats consensus EPS this quarter", 0.83),
    ("recession-2026", "NBER declares a recession in 2026", 0.09),
    ("opec-cut", "OPEC+ announces a production cut", 0.46),
    ("spx-5000", "S&P 500 closes below 5,000 this month", 0.17),
    ("election-turnout", "Turnout exceeds 62% in the general election", 0.55),
    ("ai-regulation", "Federal AI bill passes the Senate", 0.23),
]

#: Per-venue microstructure. Kalshi's 1c tick alone is a 1c minimum spread,
#: which is most of a typical arb edge.
VENUE_PROFILE: dict[Venue, dict] = {
    Venue.POLYMARKET: {"tick": 0.001, "half_spread": 0.006, "depth": 900.0, "levels": 8},
    Venue.KALSHI: {"tick": 0.01, "half_spread": 0.012, "depth": 550.0, "levels": 6},
}


@dataclass(slots=True)
class _EventState:
    key: str
    title: str
    p_true: float
    #: Persistent per-venue mispricing, mean-reverting toward zero.
    bias: dict[Venue, float] = field(default_factory=dict)
    #: Independent drift of the NO token's book against the YES token.
    token_skew: dict[Venue, float] = field(default_factory=dict)
    #: Ticks remaining on an active dislocation.
    shock_ttl: int = 0


class SimulatedWorld:
    """Shared latent state. Both venue feeds read the same truth."""

    def __init__(self, *, events: int, hz: float, seed: int, dislocation_rate: float) -> None:
        self.hz = max(0.5, hz)
        self.dislocation_rate = dislocation_rate
        self._rng = random.Random(seed)
        self._start = time.time()
        self._tick = 0
        templates = EVENT_TEMPLATES[: max(1, min(events, len(EVENT_TEMPLATES)))]
        self.events: dict[str, _EventState] = {
            key: _EventState(
                key=key,
                title=title,
                p_true=p0,
                bias={venue: 0.0 for venue in VENUE_PROFILE},
                token_skew={venue: 0.0 for venue in VENUE_PROFILE},
            )
            for key, title, p0 in templates
        }

    # -------------------------------------------------------------- dynamics

    def sync(self) -> None:
        """Advance the world to wall-clock time. Safe to call from any feed."""
        target = int((time.time() - self._start) * self.hz)
        while self._tick < target:
            self._advance()
            self._tick += 1

    def _advance(self) -> None:
        rng = self._rng
        for event in self.events.values():
            # Latent probability: mean-reverting toward its own anchor so the
            # series wanders without escaping to 0 or 1.
            shock = rng.gauss(0.0, 0.004)
            event.p_true = _clip(event.p_true + shock, 0.03, 0.97)

            for venue in VENUE_PROFILE:
                # Ornstein-Uhlenbeck bias: venues disagree persistently.
                bias = event.bias[venue]
                bias = bias * 0.94 + rng.gauss(0.0, 0.0018)
                event.bias[venue] = _clip(bias, -0.08, 0.08)

                skew = event.token_skew[venue] * 0.90 + rng.gauss(0.0, 0.0012)
                event.token_skew[venue] = _clip(skew, -0.02, 0.02)

            if event.shock_ttl > 0:
                event.shock_ttl -= 1
            elif rng.random() < self.dislocation_rate:
                self._inject_dislocation(event)

    def _inject_dislocation(self, event: _EventState) -> None:
        """Jump one venue's bias, opening a window that decays shut."""
        rng = self._rng
        venue = rng.choice(list(VENUE_PROFILE))
        magnitude = rng.uniform(0.015, 0.055) * rng.choice((-1.0, 1.0))
        event.bias[venue] = _clip(event.bias[venue] + magnitude, -0.10, 0.10)
        event.shock_ttl = rng.randint(int(self.hz), int(self.hz * 6))
        # Same-venue dislocations are rarer and live in the token skew.
        if rng.random() < 0.25:
            event.token_skew[venue] = -abs(rng.uniform(0.008, 0.022))

    # ----------------------------------------------------------------- books

    def build_book(self, venue: Venue, event: _EventState) -> MarketBook:
        profile = VENUE_PROFILE[venue]
        tick = profile["tick"]
        rng = self._rng
        mid = _clip(event.p_true + event.bias[venue], 0.02, 0.98)
        half_spread = max(tick, profile["half_spread"] * rng.uniform(0.7, 1.3))
        skew = event.token_skew[venue]
        depth = profile["depth"]
        levels = profile["levels"]

        yes_bid = _round_tick(mid - half_spread, tick)
        # The NO book is quoted independently, so its implied YES price drifts
        # from the YES book by `skew`. Negative skew is the same-venue arb.
        no_bid = _round_tick((1.0 - mid) - half_spread + skew, tick)

        if venue is Venue.KALSHI:
            # Kalshi publishes bids only; asks are reflections of the other side.
            yes_bids = self._ladder(yes_bid, tick, levels, depth, descending=True)
            no_bids = self._ladder(no_bid, tick, levels, depth, descending=True)
            book = MarketBook(
                venue=venue,
                market_id=_market_id(venue, event.key),
                event_key=event.key,
                title=event.title,
                yes=Ladder(bids=yes_bids, asks=_reflect(no_bids)),
                no=Ladder(bids=no_bids, asks=_reflect(yes_bids)),
                tick=tick,
            )
        else:
            yes_ask = _round_tick(mid + half_spread, tick)
            no_ask = _round_tick((1.0 - mid) + half_spread + skew, tick)
            book = MarketBook(
                venue=venue,
                market_id=_market_id(venue, event.key),
                event_key=event.key,
                title=event.title,
                yes=Ladder(
                    bids=self._ladder(yes_bid, tick, levels, depth, descending=True),
                    asks=self._ladder(yes_ask, tick, levels, depth, descending=False),
                ),
                no=Ladder(
                    bids=self._ladder(no_bid, tick, levels, depth, descending=True),
                    asks=self._ladder(no_ask, tick, levels, depth, descending=False),
                ),
                tick=tick,
            )
        return book

    def _ladder(
        self, touch: float, tick: float, levels: int, depth: float, *, descending: bool
    ) -> list[Level]:
        rng = self._rng
        out: list[Level] = []
        for index in range(levels):
            offset = tick * index * rng.uniform(1.0, 2.2)
            price = touch - offset if descending else touch + offset
            price = _round_tick(price, tick)
            if not 0.0 < price < 1.0:
                break
            # Size grows away from the touch: the front of the queue is thin.
            size = depth * (0.45 + 0.25 * index) * rng.uniform(0.6, 1.4)
            out.append(Level(price, round(size, 1)))
        return out


class SimulatorFeed(Feed):
    """One venue's view of the shared simulated world."""

    def __init__(self, venue: Venue, normalizer: Normalizer, world: SimulatedWorld) -> None:
        super().__init__(venue, normalizer)
        self.world = world

    async def discover(self) -> None:
        for event in self.world.events.values():
            market_id = _market_id(self.venue, event.key)
            self.normalizer.register(
                MarketRef(
                    venue=self.venue,
                    market_id=market_id,
                    event_key=event.key,
                    title=event.title,
                    token_ids=(
                        {Side.YES: f"{market_id}-yes", Side.NO: f"{market_id}-no"}
                        if self.venue is Venue.POLYMARKET
                        else {}
                    ),
                )
            )
        self.status.markets = len(self.world.events)
        self.status.connected = True

    async def stream(self) -> AsyncIterator[MarketBook]:
        interval = 1.0 / self.world.hz
        try:
            while True:
                self.world.sync()
                for event in self.world.events.values():
                    self._mark()
                    yield self.world.build_book(self.venue, event)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self.status.connected = False
            raise


def _market_id(venue: Venue, event_key: str) -> str:
    if venue is Venue.KALSHI:
        return f"KX{event_key.upper().replace('-', '')}"
    return f"0x{abs(hash(event_key)) % (16**12):012x}"


def _reflect(bids: list[Level]) -> list[Level]:
    return [Level(round(1.0 - level.price, 6), level.size) for level in bids]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 6)
