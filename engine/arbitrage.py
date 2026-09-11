"""Arbitrage detection across and within venues.

Every arb this engine trades reduces to the same shape: assemble a basket of
binary legs that pays exactly $1.00 at settlement no matter how the event
resolves, and check whether the basket costs less than $1.00 to assemble.

  * Buying YES and NO on one venue costs `ask_yes + ask_no` and pays $1.
  * Selling YES and NO on one venue is the mirror image: shorting YES at bid
    `p` is identical to buying NO at `1 - p`, so the basket costs
    `2 - bid_yes - bid_no` and still pays $1.
  * Buying YES on Polymarket and NO on Kalshi pays $1 too, provided both
    venues resolve the same real-world event the same way. That proviso is the
    entire risk of the strategy and is carried explicitly as `fill_probability`.

Because all three reduce to "cost of a $1 payout", the detector prices them
with one function and the README's `Edge = 1 - (YesAsk + NoAsk)` falls out as
the special case where both legs are buys at the touch.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from engine.fees import FeeModel, fee_model_for
from engine.models import ArbType, MarketBook, Opportunity, OpportunityLeg, Side, Venue
from engine.slippage import SlippageModel

#: A basket of binary legs that pays exactly this much at settlement.
PAYOUT = 1.0


@dataclass(slots=True)
class DetectorConfig:
    #: Minimum net edge per contract pair, in dollars, to report at all.
    min_net_edge: float = 0.002
    #: Hard ceiling on contracts per opportunity, regardless of depth.
    max_position_size: float = 5_000.0
    #: Books older than this are stale and are skipped.
    max_book_age: float = 5.0
    #: Number of linear size candidates evaluated in addition to the ladder
    #: breakpoints. Fees with a fixed per-order component make net edge
    #: non-monotonic in size, so a single point is not enough.
    size_grid: int = 24
    #: Baseline probability both legs fill and settle consistently. Same-venue
    #: baskets only carry order-race risk; cross-venue baskets additionally
    #: carry resolution-source risk, which is rare but not negligible.
    same_venue_fill_prob: float = 0.995
    cross_venue_fill_prob: float = 0.985
    #: Penalty applied per level of depth consumed beyond the touch. Deeper
    #: clips sit in the queue longer and are likelier to be picked off.
    fill_prob_depth_penalty: float = 0.0005
    #: Penalty applied per second of book staleness.
    fill_prob_staleness_penalty: float = 0.005
    slippage: SlippageModel = field(default_factory=SlippageModel)
    fee_models: dict[Venue, FeeModel] = field(default_factory=dict)
    #: Disable to screen a single venue only.
    enable_cross_venue: bool = True
    enable_same_venue: bool = True

    def fee_model(self, venue: Venue) -> FeeModel:
        return self.fee_models.get(venue) or fee_model_for(venue)


@dataclass(frozen=True, slots=True)
class _LegSpec:
    book: MarketBook
    side: Side
    action: str  # "buy" or "sell"

    def levels(self):
        ladder = self.book.ladder(self.side)
        return ladder.asks if self.action == "buy" else ladder.bids


@dataclass(frozen=True, slots=True)
class _PricedBasket:
    legs: list[OpportunityLeg]
    size: float
    cost_per_pair: float
    net_edge: float
    total_cost: float
    profit: float
    levels_consumed: int


class ArbitrageDetector:
    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()

    # ------------------------------------------------------------------ scan

    def scan(self, books: list[MarketBook]) -> list[Opportunity]:
        """Screen every book for every arb shape, best net edge first."""
        fresh = [b for b in books if self._is_tradeable(b)]
        opportunities: list[Opportunity] = []

        if self.config.enable_same_venue:
            for book in fresh:
                opportunities.extend(self._scan_same_venue(book))

        if self.config.enable_cross_venue:
            by_event: dict[str, list[MarketBook]] = defaultdict(list)
            for book in fresh:
                by_event[book.event_key].append(book)
            for event_books in by_event.values():
                opportunities.extend(self._scan_cross_venue(event_books))

        opportunities.sort(key=lambda o: o.net_edge, reverse=True)
        return _deduplicate(opportunities)

    def _is_tradeable(self, book: MarketBook) -> bool:
        if book.is_crossed:
            return False
        if book.age > self.config.max_book_age:
            return False
        return bool(book.yes.asks or book.yes.bids or book.no.asks or book.no.bids)

    # ------------------------------------------------------------- same venue

    def _scan_same_venue(self, book: MarketBook) -> list[Opportunity]:
        out: list[Opportunity] = []

        under = self._evaluate(
            [_LegSpec(book, Side.YES, "buy"), _LegSpec(book, Side.NO, "buy")],
            ArbType.SAME_VENUE_UNDER,
            book.event_key,
            book.title,
        )
        if under:
            out.append(under)

        over = self._evaluate(
            [_LegSpec(book, Side.YES, "sell"), _LegSpec(book, Side.NO, "sell")],
            ArbType.SAME_VENUE_OVER,
            book.event_key,
            book.title,
        )
        if over:
            out.append(over)

        return out

    # ------------------------------------------------------------ cross venue

    def _scan_cross_venue(self, books: list[MarketBook]) -> list[Opportunity]:
        out: list[Opportunity] = []
        if len(books) < 2:
            return out

        for i, first in enumerate(books):
            for second in books[i + 1 :]:
                if first.venue == second.venue:
                    continue
                combos = [
                    # Long the basket: YES here, NO there. Pays $1 either way.
                    [_LegSpec(first, Side.YES, "buy"), _LegSpec(second, Side.NO, "buy")],
                    [_LegSpec(second, Side.YES, "buy"), _LegSpec(first, Side.NO, "buy")],
                    # Short the basket: collect more than $1 of premium for a
                    # liability that can only ever be $1.
                    [_LegSpec(first, Side.YES, "sell"), _LegSpec(second, Side.NO, "sell")],
                    [_LegSpec(second, Side.YES, "sell"), _LegSpec(first, Side.NO, "sell")],
                ]
                for combo in combos:
                    opportunity = self._evaluate(
                        combo, ArbType.CROSS_VENUE, first.event_key, first.title
                    )
                    if opportunity:
                        out.append(opportunity)
        return out

    # ---------------------------------------------------------------- pricing

    def _evaluate(
        self,
        specs: list[_LegSpec],
        arb_type: ArbType,
        event_key: str,
        title: str,
    ) -> Opportunity | None:
        slippage = self.config.slippage
        leg_levels = [spec.levels() for spec in specs]
        if any(not levels for levels in leg_levels):
            return None

        cap = min(
            min(slippage.available_size(levels) for levels in leg_levels),
            self.config.max_position_size,
        )
        if cap <= 0:
            return None

        gross = self._gross_edge(specs)
        if gross is None:
            return None

        best: _PricedBasket | None = None
        for size in self._candidate_sizes(leg_levels, cap):
            basket = self._price(specs, size)
            if basket is None or basket.net_edge < self.config.min_net_edge:
                continue
            # Maximise total dollars, not edge per contract: a 3c edge on 20
            # contracts is worse than a 1.5c edge on 400.
            if best is None or basket.profit > best.profit:
                best = basket

        if best is None:
            return None

        fill_prob = self._fill_probability(arb_type, specs, best.levels_consumed)
        return Opportunity(
            id=self._opportunity_id(arb_type, event_key, specs),
            arb_type=arb_type,
            event_key=event_key,
            title=title,
            legs=best.legs,
            gross_edge=gross,
            net_edge=best.net_edge,
            max_size=best.size,
            capital_required=best.total_cost,
            expected_profit=best.profit,
            fill_probability=fill_prob,
            ts=max(spec.book.ts for spec in specs),
        )

    def _price(self, specs: list[_LegSpec], size: float) -> _PricedBasket | None:
        """Price the whole basket at one clip size, fees and slippage included."""
        slippage = self.config.slippage
        legs: list[OpportunityLeg] = []
        total_cost = 0.0
        levels_consumed = 0

        for spec in specs:
            buying = spec.action == "buy"
            walk = slippage.fill(spec.levels(), size, buying=buying)
            if not walk.complete or walk.filled <= 0:
                return None

            fee = self.config.fee_model(spec.book.venue).trade_fee(walk.avg_price, walk.filled)
            slip = (
                walk.avg_price - walk.touch_price
                if buying
                else walk.touch_price - walk.avg_price
            )
            leg = OpportunityLeg(
                venue=spec.book.venue,
                market_id=spec.book.market_id,
                side=spec.side,
                action=spec.action,
                touch_price=walk.touch_price,
                avg_price=walk.avg_price,
                size=walk.filled,
                fee=fee,
                slippage=slip,
                levels_consumed=walk.levels_consumed,
            )
            legs.append(leg)
            total_cost += leg.cash_out
            levels_consumed += walk.levels_consumed

        cost_per_pair = total_cost / size
        net_edge = PAYOUT - cost_per_pair
        return _PricedBasket(
            legs=legs,
            size=size,
            cost_per_pair=cost_per_pair,
            net_edge=net_edge,
            total_cost=total_cost,
            profit=net_edge * size,
            levels_consumed=levels_consumed,
        )

    def _gross_edge(self, specs: list[_LegSpec]) -> float | None:
        """Edge at the touch, before fees and before eating any depth."""
        cost = 0.0
        for spec in specs:
            levels = spec.levels()
            if not levels:
                return None
            touch = levels[0].price
            cost += touch if spec.action == "buy" else (1.0 - touch)
        return PAYOUT - cost

    def _candidate_sizes(self, leg_levels: list[list], cap: float) -> list[float]:
        """Sizes worth pricing: every ladder breakpoint plus a linear grid.

        Breakpoints matter because average price is piecewise-linear in size
        with kinks exactly where a level is exhausted; the grid matters because
        fixed per-order fees make small clips uneconomic and the optimum can
        sit between two kinks.
        """
        sizes: set[float] = {round(cap, 4)}
        for levels in leg_levels:
            running = 0.0
            for level in self.config.slippage.effective_levels(levels):
                running += level.size
                if running >= cap:
                    break
                sizes.add(round(running, 4))
        for step in range(1, self.config.size_grid + 1):
            sizes.add(round(cap * step / self.config.size_grid, 4))
        return sorted(size for size in sizes if size > 1e-6)

    def _fill_probability(
        self, arb_type: ArbType, specs: list[_LegSpec], levels_consumed: int
    ) -> float:
        base = (
            self.config.cross_venue_fill_prob
            if arb_type is ArbType.CROSS_VENUE
            else self.config.same_venue_fill_prob
        )
        extra_levels = max(0, levels_consumed - len(specs))
        base -= extra_levels * self.config.fill_prob_depth_penalty
        oldest = max(spec.book.age for spec in specs)
        base -= oldest * self.config.fill_prob_staleness_penalty
        return min(0.999, max(0.01, base))

    @staticmethod
    def _opportunity_id(arb_type: ArbType, event_key: str, specs: list[_LegSpec]) -> str:
        parts = [arb_type.value, event_key]
        parts += [
            f"{s.book.venue.value}:{s.book.market_id}:{s.side.value}:{s.action}" for s in specs
        ]
        digest = hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]
        return f"{arb_type.value}-{digest}"


def _deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Collapse baskets that are the same trade written two ways.

    Shorting NO is the same exposure as buying YES, so a venue whose ask
    ladder is a reflection of its bid ladder - which is exactly how Kalshi
    works - produces a buy-buy basket and a sell-sell basket with identical
    legs and identical prices. They are one opportunity, and showing both
    doubles the apparent size of the screen.
    """
    seen: set[tuple] = set()
    out: list[Opportunity] = []
    for opportunity in opportunities:
        exposure = tuple(
            sorted(
                (
                    leg.venue.value,
                    (leg.side if leg.action == "buy" else leg.side.opposite).value,
                    round(leg.avg_price, 6),
                    round(leg.size, 4),
                )
                for leg in opportunity.legs
            )
        )
        key = (opportunity.event_key, exposure)
        if key in seen:
            continue
        seen.add(key)
        out.append(opportunity)
    return out


def divergence_by_event(books: list[MarketBook]) -> list[dict]:
    """Cross-venue mid-price divergence per event, for the divergence chart.

    This is the signal *before* costs: it says the two venues disagree, not
    that the disagreement is harvestable. The detector decides the latter.
    """
    by_event: dict[str, list[MarketBook]] = defaultdict(list)
    for book in books:
        by_event[book.event_key].append(book)

    out: list[dict] = []
    for event_key, event_books in by_event.items():
        mids = {b.venue.value: b.mid for b in event_books if b.mid is not None}
        if len(mids) < 2:
            continue
        values = list(mids.values())
        spread = max(values) - min(values)
        out.append(
            {
                "eventKey": event_key,
                "title": event_books[0].title,
                "mids": {venue: round(mid, 4) for venue, mid in mids.items()},
                "divergence": round(spread, 5),
                "divergenceBps": round(spread * 10_000, 1),
                "richVenue": max(mids, key=mids.__getitem__),
                "cheapVenue": min(mids, key=mids.__getitem__),
                "ts": max(b.ts for b in event_books),
            }
        )
    out.sort(key=lambda row: row["divergence"], reverse=True)
    return out
