"""Slippage simulation.

Three separate costs are conflated by the word "slippage", and this module
keeps them apart:

1. Depth cost - the ladder is finite, so a big clip fills worse than the touch.
   Deterministic given the book; comes straight from `walk_depth`.
2. Latency decay - between the book snapshot and the order arriving, some of
   the resting size at the touch is gone. Modelled as a fraction of top-level
   liquidity removed before the walk.
3. Adverse selection - the quotes that survive your arrival are the ones that
   wanted to trade with you. Modelled as a fixed tick haircut on the fill.

Arbitrage edges on prediction markets are 1-3 cents wide, so ignoring any of
the three turns a profitable screen into a losing book.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.models import Level
from engine.orderbook import DepthWalk, walk_depth


@dataclass(frozen=True, slots=True)
class SlippageModel:
    """Converts a resting ladder into the ladder you can actually expect."""

    #: Round-trip time from snapshot to order acknowledgement.
    latency_ms: float = 250.0
    #: Fraction of top-of-book size that disappears per 100ms of latency.
    decay_per_100ms: float = 0.08
    #: Extra ticks of price paid on every fill, in dollars.
    adverse_tick: float = 0.0
    #: Cap on the fraction of a level's displayed size treated as real.
    displayed_size_credibility: float = 1.0

    def effective_levels(self, levels: list[Level]) -> list[Level]:
        """Haircut the ladder for latency decay and quote credibility."""
        if not levels:
            return []
        decay = min(0.95, self.decay_per_100ms * (self.latency_ms / 100.0))
        credibility = max(0.0, min(1.0, self.displayed_size_credibility))
        out: list[Level] = []
        for index, level in enumerate(levels):
            # Only the touch is exposed to full decay; deeper levels are
            # stickier because they were not the ones being picked off.
            level_decay = decay if index == 0 else decay * 0.5
            size = level.size * credibility * (1.0 - level_decay)
            if size > 1e-9:
                out.append(Level(level.price, size))
        return out

    def fill(self, levels: list[Level], size: float, *, buying: bool) -> DepthWalk:
        """Expected fill for a marketable order of `size` contracts."""
        walk = walk_depth(self.effective_levels(levels), size)
        if self.adverse_tick <= 0 or walk.filled <= 0:
            return walk
        direction = 1.0 if buying else -1.0
        adjusted = min(1.0, max(0.0, walk.avg_price + direction * self.adverse_tick))
        return DepthWalk(
            filled=walk.filled,
            avg_price=adjusted,
            touch_price=walk.touch_price,
            notional=adjusted * walk.filled,
            levels_consumed=walk.levels_consumed,
            unfilled=walk.unfilled,
        )

    def available_size(self, levels: list[Level]) -> float:
        return sum(level.size for level in self.effective_levels(levels))

    def cost_curve(
        self, levels: list[Level], *, buying: bool, points: int = 12
    ) -> list[dict]:
        """Average fill price as a function of clip size, for the UI."""
        total = self.available_size(levels)
        if total <= 0:
            return []
        out: list[dict] = []
        for step in range(1, points + 1):
            size = total * step / points
            walk = self.fill(levels, size, buying=buying)
            if walk.filled <= 0:
                continue
            out.append(
                {
                    "size": round(walk.filled, 2),
                    "avgPrice": round(walk.avg_price, 5),
                    "slippage": round(walk.slippage, 5),
                    "slippageBps": round(walk.slippage * 10_000, 1),
                }
            )
        return out

    def describe(self) -> dict:
        return {
            "latencyMs": self.latency_ms,
            "decayPer100ms": self.decay_per_100ms,
            "adverseTick": self.adverse_tick,
            "displayedSizeCredibility": self.displayed_size_credibility,
        }
