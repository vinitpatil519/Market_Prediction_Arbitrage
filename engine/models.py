"""Canonical data model shared by every engine module.

Prices are always dollars-per-contract in [0, 1]. A binary contract pays $1.00
if its side resolves true and $0.00 otherwise, so "price" and "implied
probability" are the same number and can be used interchangeably.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

TICK = 0.001
DOLLAR = 1.0


class Venue(StrEnum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class Side(StrEnum):
    YES = "yes"
    NO = "no"

    @property
    def opposite(self) -> Side:
        return Side.NO if self is Side.YES else Side.YES


class ArbType(StrEnum):
    #: Buy YES + NO on the same venue for less than $1.00.
    SAME_VENUE_UNDER = "same_venue_under"
    #: Sell YES + NO on the same venue for more than $1.00.
    SAME_VENUE_OVER = "same_venue_over"
    #: Buy YES on one venue and NO on the other for less than $1.00.
    CROSS_VENUE = "cross_venue"


@dataclass(frozen=True, slots=True)
class Level:
    """One price level of resting liquidity."""

    price: float
    size: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.price <= 1.0:
            raise ValueError(f"price {self.price} outside [0, 1]")
        if self.size < 0:
            raise ValueError(f"size {self.size} is negative")

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass(slots=True)
class Ladder:
    """One side of a book: resting bids and resting asks for a single token."""

    bids: list[Level] = field(default_factory=list)
    asks: list[Level] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bids.sort(key=lambda level: level.price, reverse=True)
        self.asks.sort(key=lambda level: level.price)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return self.best_bid if self.best_ask is None else self.best_ask
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def depth(self, side: str) -> float:
        levels = self.bids if side == "bids" else self.asks
        return sum(level.size for level in levels)

    def mirrored(self) -> Ladder:
        """The complementary token's ladder implied by no-arbitrage.

        Owning one NO contract is economically identical to being short one YES
        contract, so a resting YES bid at p is a synthetic NO ask at 1 - p.
        Venues that only publish a single token book are filled in this way.
        """
        return Ladder(
            bids=[Level(round(1.0 - lv.price, 6), lv.size) for lv in self.asks],
            asks=[Level(round(1.0 - lv.price, 6), lv.size) for lv in self.bids],
        )

    def to_dict(self) -> dict:
        return {
            "bids": [[lv.price, lv.size] for lv in self.bids],
            "asks": [[lv.price, lv.size] for lv in self.asks],
        }


@dataclass(slots=True)
class MarketBook:
    """A single binary market on a single venue, both token ladders."""

    venue: Venue
    market_id: str
    #: Stable key shared by the same real-world event across venues.
    event_key: str
    title: str
    yes: Ladder = field(default_factory=Ladder)
    no: Ladder = field(default_factory=Ladder)
    ts: float = field(default_factory=time.time)
    #: Venue-reported tick size, used to round quotes to a tradeable price.
    tick: float = TICK

    def ladder(self, side: Side) -> Ladder:
        return self.yes if side is Side.YES else self.no

    def ensure_both_sides(self) -> MarketBook:
        """Fill an empty token ladder from its mirror image."""
        if not (self.no.bids or self.no.asks) and (self.yes.bids or self.yes.asks):
            self.no = self.yes.mirrored()
        elif not (self.yes.bids or self.yes.asks) and (self.no.bids or self.no.asks):
            self.yes = self.no.mirrored()
        return self

    @property
    def mid(self) -> float | None:
        """YES mid price: the venue's implied probability for the event."""
        return self.yes.mid

    @property
    def is_crossed(self) -> bool:
        """True when the book is internally inconsistent and unsafe to trade."""
        for ladder in (self.yes, self.no):
            if ladder.best_bid is not None and ladder.best_ask is not None:
                if ladder.best_bid > ladder.best_ask:
                    return True
        return False

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.ts)

    def to_dict(self) -> dict:
        return {
            "venue": self.venue.value,
            "marketId": self.market_id,
            "eventKey": self.event_key,
            "title": self.title,
            "yes": self.yes.to_dict(),
            "no": self.no.to_dict(),
            "mid": self.mid,
            "ts": self.ts,
            "tick": self.tick,
        }


@dataclass(slots=True)
class OpportunityLeg:
    """One side of a trade: what to buy or sell, where, at what average price."""

    venue: Venue
    market_id: str
    side: Side
    action: str  # "buy" or "sell"
    #: Top-of-book price before any depth is consumed.
    touch_price: float
    #: Size-weighted average fill price after walking the ladder.
    avg_price: float
    size: float
    fee: float
    #: avg_price - touch_price for a buy, touch_price - avg_price for a sell.
    slippage: float
    levels_consumed: int

    @property
    def notional(self) -> float:
        return self.avg_price * self.size

    @property
    def cash_out(self) -> float:
        """Cash leaving the account for this leg, fees included.

        Selling a binary contract is collateralised: the seller posts
        (1 - price) per contract and receives price, so cash out is the
        collateral net of the premium received.
        """
        if self.action == "buy":
            return self.avg_price * self.size + self.fee
        return (1.0 - self.avg_price) * self.size + self.fee

    def to_dict(self) -> dict:
        return {
            "venue": self.venue.value,
            "marketId": self.market_id,
            "side": self.side.value,
            "action": self.action,
            "touchPrice": round(self.touch_price, 6),
            "avgPrice": round(self.avg_price, 6),
            "size": round(self.size, 4),
            "fee": round(self.fee, 6),
            "slippage": round(self.slippage, 6),
            "levelsConsumed": self.levels_consumed,
            "notional": round(self.notional, 4),
        }


@dataclass(slots=True)
class Opportunity:
    """A fully priced, fee-adjusted, depth-limited arbitrage candidate."""

    id: str
    arb_type: ArbType
    event_key: str
    title: str
    legs: list[OpportunityLeg]
    #: Edge per contract pair at the touch, before fees and slippage.
    gross_edge: float
    #: Edge per contract pair after fees and depth-walked slippage.
    net_edge: float
    #: Profit-maximising clip: the size at which net_edge * size peaks, given
    #: finite depth and fees that do not scale linearly with size.
    max_size: float
    #: Capital required to put the full max_size on.
    capital_required: float
    #: Guaranteed dollar profit at max_size if both legs fill and resolve.
    expected_profit: float
    #: Probability both legs fill and the two markets resolve identically.
    fill_probability: float
    ts: float = field(default_factory=time.time)

    @property
    def net_edge_bps(self) -> float:
        return self.net_edge * 10_000

    @property
    def return_on_capital(self) -> float:
        if self.capital_required <= 0:
            return 0.0
        return self.expected_profit / self.capital_required

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "arbType": self.arb_type.value,
            "eventKey": self.event_key,
            "title": self.title,
            "legs": [leg.to_dict() for leg in self.legs],
            "grossEdge": round(self.gross_edge, 6),
            "netEdge": round(self.net_edge, 6),
            "netEdgeBps": round(self.net_edge_bps, 2),
            "maxSize": round(self.max_size, 4),
            "capitalRequired": round(self.capital_required, 2),
            "expectedProfit": round(self.expected_profit, 4),
            "returnOnCapital": round(self.return_on_capital, 6),
            "fillProbability": round(self.fill_probability, 4),
            "venues": sorted({leg.venue.value for leg in self.legs}),
            "ts": self.ts,
        }
