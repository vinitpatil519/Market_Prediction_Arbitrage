"""Kalshi trade-api v2 feed.

Unlike Polymarket, Kalshi's websocket requires authentication even for market
data: every request carries an RSA-PSS signature over
`timestamp + method + path` using the account's private key. Without
credentials this feed reports itself as unavailable rather than failing the
process, and the engine runs single-venue.

The `orderbook_delta` channel sends one `orderbook_snapshot` per market
followed by incremental `orderbook_delta` messages. Both carry *bids only* on
the yes and no sides; the normalizer reconstructs the ask ladders.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator

import httpx

from backend.app.config import get_settings
from backend.app.feeds.base import Feed, backoff
from engine.models import Level, MarketBook, Side, Venue
from engine.normalizer import MarketRef, Normalizer


class KalshiFeed(Feed):
    def __init__(self, normalizer: Normalizer) -> None:
        super().__init__(Venue.KALSHI, normalizer)
        self.settings = get_settings()
        self._tickers: list[str] = []
        self._books: dict[str, MarketBook] = {}

    # ------------------------------------------------------------------ auth

    @property
    def has_credentials(self) -> bool:
        return bool(self.settings.kalshi_api_key_id and self.settings.kalshi_private_key_pem)

    def _sign(self, method: str, path: str) -> dict[str, str]:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method}{path}".encode()
        private_key = serialization.load_pem_private_key(
            self.settings.kalshi_private_key_pem.encode(), password=None
        )
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256.digest_size),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.settings.kalshi_api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    # ------------------------------------------------------------- discovery

    async def discover(self) -> None:
        if not self.has_credentials:
            self.status.error = "no Kalshi credentials; venue disabled"
            return

        path = "/trade-api/v2/markets"
        url = f"{self.settings.kalshi_rest_url}/markets"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(
                    url,
                    params={"status": "open", "limit": self.settings.live_market_limit},
                    headers=self._sign("GET", path),
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self.status.error = f"discovery failed: {exc}"
            return

        for market in payload.get("markets", []):
            ticker = market.get("ticker")
            if not ticker:
                continue
            title = market.get("title") or market.get("yes_sub_title") or ticker
            subtitle = market.get("yes_sub_title")
            if subtitle and subtitle not in title:
                title = f"{title} - {subtitle}"
            self.normalizer.register(
                MarketRef(
                    venue=Venue.KALSHI,
                    market_id=ticker,
                    event_key=f"kx:{ticker}",
                    title=title,
                )
            )
            self._tickers.append(ticker)

        self.status.markets = len(self._tickers)

    # ---------------------------------------------------------------- stream

    async def stream(self) -> AsyncIterator[MarketBook]:
        if not self._tickers:
            self.status.connected = False
            return

        import websockets

        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    self.settings.kalshi_ws_url,
                    additional_headers=self._sign("GET", "/trade-api/ws/v2"),
                    ping_interval=10,
                    max_size=8 * 1024 * 1024,
                ) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "id": 1,
                                "cmd": "subscribe",
                                "params": {
                                    "channels": ["orderbook_delta"],
                                    "market_tickers": self._tickers,
                                },
                            }
                        )
                    )
                    self.status.connected = True
                    self.status.error = None
                    attempt = 0

                    async for raw in socket:
                        book = self._handle(raw)
                        if book is not None:
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

    def _handle(self, raw: str | bytes) -> MarketBook | None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None

        message_type = payload.get("type")
        if message_type == "orderbook_snapshot":
            book = self.normalizer.kalshi_book(payload)
            if book is not None:
                self._books[book.market_id] = book
            return book
        if message_type == "orderbook_delta":
            return self._apply_delta(payload.get("msg", {}))
        return None

    def _apply_delta(self, message: dict) -> MarketBook | None:
        """Apply a single-level bid delta.

        `delta` is a signed change to the resting size at `price` on `side`.
        Because Kalshi stores asks as reflections of the other side's bids, a
        bid change on one token silently changes the other token's ask ladder,
        so both are rebuilt after every delta.
        """
        ticker = message.get("market_ticker")
        book = self._books.get(ticker) if ticker else None
        if book is None:
            return None

        side = Side.YES if str(message.get("side", "yes")).lower() == "yes" else Side.NO
        price = float(message.get("price", 0)) / 100.0
        delta = float(message.get("delta", 0))

        bids = book.ladder(side).bids
        _apply_size_delta(bids, price, delta)
        bids.sort(key=lambda level: level.price, reverse=True)

        # Rebuild both ask ladders from the (now updated) bid ladders.
        book.yes.asks = _reflect(book.no.bids)
        book.no.asks = _reflect(book.yes.bids)
        book.ts = time.time()
        return book


def _apply_size_delta(levels: list[Level], price: float, delta: float) -> None:
    for index, level in enumerate(levels):
        if abs(level.price - price) < 1e-9:
            size = level.size + delta
            if size <= 0:
                levels.pop(index)
            else:
                levels[index] = Level(price, size)
            return
    if delta > 0:
        levels.append(Level(price, delta))


def _reflect(bids: list[Level]) -> list[Level]:
    return [Level(round(1.0 - level.price, 6), level.size) for level in bids]
