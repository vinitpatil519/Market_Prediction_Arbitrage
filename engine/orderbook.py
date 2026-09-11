"""Order book depth walking.

A marketable order does not fill at the touch, it eats the ladder. Every price
the rest of the engine uses for sizing comes from `walk_depth`, never from the
best bid/ask alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.models import Ladder, Level


@dataclass(frozen=True, slots=True)
class DepthWalk:
    """Result of consuming `filled` contracts from one side of a ladder."""

    filled: float
    #: Size-weighted average price paid or received.
    avg_price: float
    touch_price: float
    notional: float
    levels_consumed: int
    #: Requested size that no resting liquidity could cover.
    unfilled: float

    @property
    def slippage(self) -> float:
        """Absolute distance between the average fill and the touch."""
        return abs(self.avg_price - self.touch_price)

    @property
    def complete(self) -> bool:
        return self.unfilled <= 1e-9


def walk_depth(levels: list[Level], size: float) -> DepthWalk:
    """Consume `size` contracts from a pre-sorted list of price levels.

    The caller is responsible for passing asks (ascending) when buying and bids
    (descending) when selling; `Ladder` keeps both in the correct order.
    """
    if size <= 0 or not levels:
        touch = levels[0].price if levels else 0.0
        return DepthWalk(0.0, touch, touch, 0.0, 0, max(0.0, size))

    touch = levels[0].price
    remaining = size
    notional = 0.0
    consumed = 0

    for level in levels:
        if remaining <= 1e-9:
            break
        take = min(remaining, level.size)
        notional += take * level.price
        remaining -= take
        consumed += 1

    filled = size - remaining
    avg = notional / filled if filled > 0 else touch
    return DepthWalk(
        filled=filled,
        avg_price=avg,
        touch_price=touch,
        notional=notional,
        levels_consumed=consumed,
        unfilled=max(0.0, remaining),
    )


def max_size_within_price(levels: list[Level], limit_price: float, buying: bool) -> float:
    """Total size available at or better than `limit_price`."""
    total = 0.0
    for level in levels:
        if buying and level.price > limit_price + 1e-9:
            break
        if not buying and level.price < limit_price - 1e-9:
            break
        total += level.size
    return total


def cumulative_depth(ladder: Ladder, max_levels: int = 25) -> dict:
    """Cumulative size by price, the shape the depth chart renders."""

    def accumulate(levels: list[Level]) -> list[dict]:
        running = 0.0
        out: list[dict] = []
        for level in levels[:max_levels]:
            running += level.size
            out.append(
                {
                    "price": round(level.price, 4),
                    "size": round(level.size, 2),
                    "cumulative": round(running, 2),
                }
            )
        return out

    return {"bids": accumulate(ladder.bids), "asks": accumulate(ladder.asks)}


def book_imbalance(ladder: Ladder, levels: int = 5) -> float:
    """Signed top-of-book imbalance in [-1, 1]; positive means bid-heavy."""
    bid = sum(lv.size for lv in ladder.bids[:levels])
    ask = sum(lv.size for lv in ladder.asks[:levels])
    total = bid + ask
    if total <= 0:
        return 0.0
    return (bid - ask) / total


def microprice(ladder: Ladder, levels: int = 1) -> float | None:
    """Size-weighted mid, which leans toward the side with less resting size."""
    if not ladder.bids or not ladder.asks:
        return ladder.mid
    bid_size = sum(lv.size for lv in ladder.bids[:levels])
    ask_size = sum(lv.size for lv in ladder.asks[:levels])
    total = bid_size + ask_size
    if total <= 0:
        return ladder.mid
    best_bid = ladder.bids[0].price
    best_ask = ladder.asks[0].price
    return (best_bid * ask_size + best_ask * bid_size) / total
