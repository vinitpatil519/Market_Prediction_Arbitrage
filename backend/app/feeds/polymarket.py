"""Polymarket CLOB feed.

Discovery goes through the Gamma API, which is the only place the human
question text and the CLOB token ids live together. The market websocket is
public - no credentials - and pushes a full `book` snapshot per outcome token
plus incremental `price_change` deltas.

Each outcome token is a separate CLOB, so a Polymarket market needs both token
subscriptions before it has a complete two-sided picture.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

import httpx

from backend.app.config import get_settings
from backend.app.feeds.base import Feed, backoff
from engine.models import Level, MarketBook, Side, Venue
from engine.normalizer import MarketRef, Normalizer

#: Polymarket pings text frames; anything longer than this without traffic is
#: a dead socket, not a quiet market.
HEARTBEAT_TIMEOUT = 30.0


class PolymarketFeed(Feed):
    def __init__(self, normalizer: Normalizer) -> None:
        super().__init__(Venue.POLYMARKET, normalizer)
        self.settings = get_settings()
        self._token_ids: list[str] = []
        self._books: dict[str, MarketBook] = {}

    async def discover(self) -> None:
        url = f"{self.settings.polymarket_gamma_url}/markets"
        params = {
            "closed": "false",
            "active": "true",
            "limit": self.settings.live_market_limit,
            "order": "volume24hr",
            "ascending": "false",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self.status.error = f"discovery failed: {exc}"
            return

        markets = payload if isinstance(payload, list) else payload.get("data", [])
        for market in markets:
            token_ids = _parse_token_ids(market.get("clobTokenIds"))
            condition_id = market.get("conditionId") or market.get("id")
            question = market.get("question") or market.get("title") or ""
            if not token_ids or not condition_id or len(token_ids) < 2:
                continue
            self.normalizer.register(
                MarketRef(
                    venue=Venue.POLYMARKET,
                    market_id=str(condition_id),
                    # Replaced by the cross-venue matcher once Kalshi has also
                    # discovered; until then each market is its own event.
                    event_key=f"pm:{condition_id}",
                    title=question,
                    token_ids={Side.YES: token_ids[0], Side.NO: token_ids[1]},
                )
            )
            self._token_ids.extend(token_ids[:2])

        self.status.markets = len(self._token_ids) // 2
        if not self._token_ids:
            self.status.error = self.status.error or "no tradeable markets returned"

    async def stream(self) -> AsyncIterator[MarketBook]:
        if not self._token_ids:
            self.status.connected = False
            return

        import websockets  # optional dependency, only needed for live mode

        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    self.settings.polymarket_ws_url,
                    ping_interval=10,
                    ping_timeout=HEARTBEAT_TIMEOUT,
                    max_size=8 * 1024 * 1024,
                ) as socket:
                    await socket.send(
                        json.dumps({"assets_ids": self._token_ids, "type": "market"})
                    )
                    self.status.connected = True
                    self.status.error = None
                    attempt = 0

                    async for raw in socket:
                        for book in self._handle(raw):
                            self._mark()
                            yield book
            except asyncio.CancelledError:
                self.status.connected = False
                raise
            except Exception as exc:
                self.status.connected = False
                self.status.error = str(exc)
                self.status.reconnects += 1
                attempt += 1
                await backoff(attempt)

    def _handle(self, raw: str | bytes) -> list[MarketBook]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        messages = payload if isinstance(payload, list) else [payload]

        out: list[MarketBook] = []
        for message in messages:
            event_type = message.get("event_type")
            if event_type == "book":
                update = self.normalizer.polymarket_book(message)
            elif event_type == "price_change":
                update = self._apply_price_change(message)
            else:
                continue
            if update is None:
                continue
            merged = self.normalizer.merge(self._books.get(update.market_id), update)
            self._books[update.market_id] = merged
            out.append(merged)
        return out

    def _apply_price_change(self, message: dict) -> MarketBook | None:
        """Fold a delta into the last snapshot for that token.

        A delta with size 0 removes the level; anything else replaces it. The
        snapshot has to exist first, so deltas arriving before the initial
        `book` message are dropped rather than guessed at.
        """
        asset_id = message.get("asset_id") or message.get("assetId")
        resolved = self.normalizer.resolve_token(asset_id) if asset_id else None
        if resolved is None:
            return None
        market_id, side = resolved
        book = self._books.get(market_id)
        if book is None:
            return None

        ladder = book.ladder(side)
        for change in message.get("changes", []) or []:
            price = float(change.get("price", 0))
            size = float(change.get("size", 0))
            levels = ladder.bids if str(change.get("side", "")).upper() == "BUY" else ladder.asks
            _upsert(levels, price, size)
        ladder.bids.sort(key=lambda lv: lv.price, reverse=True)
        ladder.asks.sort(key=lambda lv: lv.price)
        book.ts = _timestamp(message.get("timestamp"))
        return book


def _upsert(levels: list[Level], price: float, size: float) -> None:
    for index, level in enumerate(levels):
        if abs(level.price - price) < 1e-9:
            if size <= 0:
                levels.pop(index)
            else:
                levels[index] = Level(price, size)
            return
    if size > 0:
        levels.append(Level(price, size))


def _parse_token_ids(raw) -> list[str]:
    """Gamma returns the token id array as a JSON-encoded string."""
    if isinstance(raw, list):
        return [str(token) for token in raw]
    if isinstance(raw, str):
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(token) for token in parsed]
    return []


def _timestamp(raw) -> float:
    import time

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return time.time()
    return value / 1000.0 if value > 1e11 else value
