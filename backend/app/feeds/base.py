"""Feed interface.

A feed is an async iterator of normalized `MarketBook` updates plus a status
object the dashboard can show. Live venue feeds and the synthetic feed are
interchangeable behind this interface, which is what lets the whole stack run
without credentials.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from engine.models import MarketBook, Venue
from engine.normalizer import Normalizer


@dataclass(slots=True)
class FeedStatus:
    venue: str
    connected: bool = False
    messages: int = 0
    last_message_at: float | None = None
    reconnects: int = 0
    error: str | None = None
    markets: int = 0

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "connected": self.connected,
            "messages": self.messages,
            "lastMessageAt": self.last_message_at,
            "staleness": (
                round(time.time() - self.last_message_at, 2)
                if self.last_message_at
                else None
            ),
            "reconnects": self.reconnects,
            "error": self.error,
            "markets": self.markets,
        }


class Feed(ABC):
    def __init__(self, venue: Venue, normalizer: Normalizer) -> None:
        self.venue = venue
        self.normalizer = normalizer
        self.status = FeedStatus(venue=venue.value)

    @abstractmethod
    async def discover(self) -> None:
        """Populate the normalizer registry with this venue's markets."""

    @abstractmethod
    def stream(self) -> AsyncIterator[MarketBook]:
        """Yield normalized book updates until cancelled."""

    async def close(self) -> None:
        return None

    def _mark(self) -> None:
        self.status.messages += 1
        self.status.last_message_at = time.time()


async def backoff(attempt: int, *, base: float = 0.5, cap: float = 30.0) -> None:
    """Exponential backoff between reconnect attempts."""
    await asyncio.sleep(min(cap, base * (2 ** min(attempt, 6))))
