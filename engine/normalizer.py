"""Venue payload normalisation.

The two venues publish structurally different books and the difference is not
cosmetic:

* Polymarket runs a CLOB per outcome token. Each token has a real two-sided
  book, so YES asks and NO asks are independent quotes and can genuinely sum
  to less than $1.00. Prices are decimal dollars.

* Kalshi publishes resting *bids only*, on both the yes and no side. There is
  no separate ask book: an offer to sell YES at 60c is stored as a bid to buy
  NO at 40c. So the YES ask ladder must be reconstructed as `1 - no_bid`.
  Prices are integer cents.

Getting this wrong is the classic way to hallucinate arbitrage - reading
Kalshi's `no` array as asks makes every market look like a 40c edge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from engine.models import Ladder, Level, MarketBook, Side, Venue


@dataclass(frozen=True, slots=True)
class MarketRef:
    venue: Venue
    market_id: str
    event_key: str
    title: str
    #: Polymarket only: token id per side.
    token_ids: dict[Side, str] = field(default_factory=dict)


class Normalizer:
    """Registry plus payload decoders. One instance per running engine."""

    def __init__(self) -> None:
        self._markets: dict[tuple[str, str], MarketRef] = {}
        self._token_index: dict[str, tuple[str, Side]] = {}

    # -------------------------------------------------------------- registry

    def register(self, ref: MarketRef) -> None:
        self._markets[(ref.venue.value, ref.market_id)] = ref
        for side, token_id in ref.token_ids.items():
            self._token_index[token_id] = (ref.market_id, side)

    def lookup(self, venue: Venue, market_id: str) -> MarketRef | None:
        return self._markets.get((venue.value, market_id))

    def resolve_token(self, token_id: str) -> tuple[str, Side] | None:
        return self._token_index.get(token_id)

    @property
    def markets(self) -> list[MarketRef]:
        return list(self._markets.values())

    def event_keys(self) -> set[str]:
        return {ref.event_key for ref in self._markets.values()}

    # ----------------------------------------------------------- polymarket

    def polymarket_book(self, payload: dict) -> MarketBook | None:
        """Decode a Polymarket CLOB `book` message.

        The message carries one token's ladder, so a full market needs both
        the YES and NO messages; callers merge them via `merge`.
        """
        asset_id = payload.get("asset_id") or payload.get("assetId")
        market_id = payload.get("market") or payload.get("market_id")
        resolved = self.resolve_token(asset_id) if asset_id else None
        if resolved:
            market_id, side = resolved
        elif market_id:
            side = Side(str(payload.get("side", "yes")).lower())
        else:
            return None

        ref = self.lookup(Venue.POLYMARKET, market_id)
        if ref is None:
            return None

        ladder = Ladder(
            bids=[_level(entry) for entry in payload.get("bids", [])],
            asks=[_level(entry) for entry in payload.get("asks", [])],
        )
        ts = _timestamp(payload.get("timestamp"))

        book = MarketBook(
            venue=Venue.POLYMARKET,
            market_id=market_id,
            event_key=ref.event_key,
            title=ref.title,
            ts=ts,
            tick=float(payload.get("tick_size", 0.001) or 0.001),
        )
        if side is Side.YES:
            book.yes = ladder
        else:
            book.no = ladder
        return book

    # ---------------------------------------------------------------- kalshi

    def kalshi_book(self, payload: dict) -> MarketBook | None:
        """Decode a Kalshi `orderbook_snapshot` message.

        Both arrays are bids. The ask side of each token is the reflection of
        the other token's bids about $1.00.
        """
        message = payload.get("msg", payload)
        ticker = message.get("market_ticker") or message.get("ticker")
        if not ticker:
            return None
        ref = self.lookup(Venue.KALSHI, ticker)
        if ref is None:
            return None

        yes_bids = [_cent_level(entry) for entry in message.get("yes") or []]
        no_bids = [_cent_level(entry) for entry in message.get("no") or []]

        book = MarketBook(
            venue=Venue.KALSHI,
            market_id=ticker,
            event_key=ref.event_key,
            title=ref.title,
            yes=Ladder(bids=yes_bids, asks=_reflect(no_bids)),
            no=Ladder(bids=no_bids, asks=_reflect(yes_bids)),
            ts=_timestamp(message.get("ts")),
            tick=0.01,
        )
        return book

    # ----------------------------------------------------------------- merge

    @staticmethod
    def merge(existing: MarketBook | None, incoming: MarketBook) -> MarketBook:
        """Fold a single-token update into the market's full book."""
        if existing is None:
            return incoming.ensure_both_sides()
        if incoming.yes.bids or incoming.yes.asks:
            existing.yes = incoming.yes
        if incoming.no.bids or incoming.no.asks:
            existing.no = incoming.no
        existing.ts = incoming.ts
        return existing


def _level(entry) -> Level:
    if isinstance(entry, dict):
        return Level(float(entry["price"]), float(entry["size"]))
    return Level(float(entry[0]), float(entry[1]))


def _cent_level(entry) -> Level:
    """Kalshi quotes integer cents; the engine works in dollars."""
    if isinstance(entry, dict):
        price, size = entry["price"], entry["size"]
    else:
        price, size = entry[0], entry[1]
    return Level(round(float(price) / 100.0, 6), float(size))


def _reflect(bids: list[Level]) -> list[Level]:
    """Turn one token's bids into the other token's asks."""
    return [Level(round(1.0 - level.price, 6), level.size) for level in bids]


def _timestamp(raw) -> float:
    if raw is None:
        return time.time()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return time.time()
    # Venues send seconds, milliseconds or microseconds depending on the feed.
    if value > 1e14:
        return value / 1e6
    if value > 1e11:
        return value / 1e3
    return value
