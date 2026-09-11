"""Engine orchestration.

Owns the only mutable state in the process: the current book per market, the
current opportunity set, and the rolling history the charts read. Feeds write
books, the scan loop reads them, and websocket clients get pushed the result.

The scan is deliberately decoupled from the feed rate. A busy pair of venues
pushes thousands of book updates a second and re-running the detector on each
one would burn CPU recomputing an answer that has not changed; instead updates
mark the state dirty and a timer scans at most every `scan_interval`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass, field

from backend.app.cache import Cache, build_cache
from backend.app.config import Settings, get_settings
from backend.app.db import MarketSnapshot, OpportunityRow, SessionLocal, prune_opportunities
from backend.app.feeds.base import Feed
from backend.app.feeds.kalshi import KalshiFeed
from backend.app.feeds.polymarket import PolymarketFeed
from backend.app.feeds.simulator import SimulatedWorld, SimulatorFeed
from backend.app.services.pairing import pair_markets
from engine.arbitrage import ArbitrageDetector, DetectorConfig, divergence_by_event
from engine.execution import ExecutionSimulator
from engine.fees import KalshiFeeModel, PolymarketFeeModel
from engine.kelly import KellySizer
from engine.models import MarketBook, Opportunity, Venue
from engine.normalizer import Normalizer
from engine.slippage import SlippageModel


@dataclass(slots=True)
class RunnerStats:
    started_at: float = field(default_factory=time.time)
    scans: int = 0
    book_updates: int = 0
    opportunities_seen: int = 0
    #: Sum of expected profit across every opportunity ever printed. This is a
    #: screen statistic, not a PnL: the same dislocation is counted on every
    #: scan it survives.
    cumulative_screened_profit: float = 0.0
    last_scan_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "startedAt": self.started_at,
            "uptime": round(time.time() - self.started_at, 1),
            "scans": self.scans,
            "bookUpdates": self.book_updates,
            "opportunitiesSeen": self.opportunities_seen,
            "cumulativeScreenedProfit": round(self.cumulative_screened_profit, 2),
            "lastScanMs": round(self.last_scan_ms, 3),
        }


class EngineRunner:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.normalizer = Normalizer()
        self.books: dict[tuple[str, str], MarketBook] = {}
        self.opportunities: list[Opportunity] = []
        self.divergence: list[dict] = []
        self.stats = RunnerStats()
        self.cache: Cache | None = None

        self.detector = ArbitrageDetector(self._build_detector_config())
        self.sizer = self._build_sizer()
        self.simulator = ExecutionSimulator(self.detector.config)

        self.feeds: list[Feed] = []
        self._tasks: list[asyncio.Task] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._dirty = asyncio.Event()
        self._history: dict[str, deque] = {}
        self._edge_history: deque = deque(maxlen=self.settings.history_length)
        self._last_snapshot_write = 0.0
        self._running = False

    # ------------------------------------------------------------ config

    def _build_detector_config(self) -> DetectorConfig:
        s = self.settings
        return DetectorConfig(
            min_net_edge=s.min_net_edge,
            max_position_size=s.max_position_size,
            max_book_age=s.max_book_age,
            slippage=SlippageModel(
                latency_ms=s.latency_ms,
                decay_per_100ms=s.decay_per_100ms,
                adverse_tick=s.adverse_tick,
                displayed_size_credibility=s.displayed_size_credibility,
            ),
            fee_models={
                Venue.KALSHI: KalshiFeeModel(
                    taker_rate=s.kalshi_taker_rate,
                    maker_rate_per_contract=s.kalshi_maker_rate_per_contract,
                ),
                Venue.POLYMARKET: PolymarketFeeModel(
                    taker_rate=s.polymarket_taker_rate,
                    maker_rate=s.polymarket_maker_rate,
                    gas_cost_per_order=s.polymarket_gas_cost,
                ),
            },
        )

    def _build_sizer(self) -> KellySizer:
        return KellySizer(
            kelly_multiplier=self.settings.kelly_multiplier,
            max_fraction_per_trade=self.settings.max_fraction_per_trade,
            loss_fraction=self.settings.loss_fraction,
        )

    def apply_settings(self, updates: dict) -> dict:
        """Hot-reload engine parameters from the settings endpoint."""
        applied = {}
        for key, value in updates.items():
            if value is None or not hasattr(self.settings, key):
                continue
            setattr(self.settings, key, value)
            applied[key] = value
        if applied:
            self.detector = ArbitrageDetector(self._build_detector_config())
            self.sizer = self._build_sizer()
            self.simulator = ExecutionSimulator(self.detector.config)
            self._dirty.set()
        return applied

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.cache = await build_cache()
        self.feeds = self._build_feeds()

        for feed in self.feeds:
            await feed.discover()

        if self.settings.feed_mode == "live":
            pair_markets(self.normalizer)

        for feed in self.feeds:
            task = asyncio.create_task(self._consume(feed), name=f"feed:{feed.venue.value}")
            self._tasks.append(task)
        self._tasks.append(asyncio.create_task(self._scan_loop(), name="scan"))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        for feed in self.feeds:
            await feed.close()
        if self.cache:
            await self.cache.close()

    def _build_feeds(self) -> list[Feed]:
        if self.settings.feed_mode == "live":
            return [PolymarketFeed(self.normalizer), KalshiFeed(self.normalizer)]
        world = SimulatedWorld(
            events=self.settings.sim_events,
            hz=self.settings.sim_tick_hz,
            seed=self.settings.sim_seed,
            dislocation_rate=self.settings.sim_dislocation_rate,
        )
        return [
            SimulatorFeed(Venue.POLYMARKET, self.normalizer, world),
            SimulatorFeed(Venue.KALSHI, self.normalizer, world),
        ]

    # --------------------------------------------------------------- feeds

    async def _consume(self, feed: Feed) -> None:
        try:
            async for book in feed.stream():
                key = (book.venue.value, book.market_id)
                self.books[key] = book
                self.stats.book_updates += 1
                self._dirty.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            feed.status.connected = False
            feed.status.error = str(exc)

    # ---------------------------------------------------------------- scan

    async def _scan_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=1.0)
            except TimeoutError:
                pass
            self._dirty.clear()
            await self._scan_once()
            await asyncio.sleep(self.settings.scan_interval)

    async def _scan_once(self) -> None:
        started = time.perf_counter()
        books = list(self.books.values())
        if not books:
            return

        opportunities = self.detector.scan(books)
        divergence = divergence_by_event(books)

        self.opportunities = opportunities
        self.divergence = divergence
        self.stats.scans += 1
        self.stats.opportunities_seen += len(opportunities)
        self.stats.cumulative_screened_profit += sum(o.expected_profit for o in opportunities)
        self.stats.last_scan_ms = (time.perf_counter() - started) * 1000

        self._record_history(divergence, opportunities)
        await self._publish_cache()
        await self._broadcast()
        await self._persist(books, opportunities)

    def _record_history(self, divergence: list[dict], opportunities: list[Opportunity]) -> None:
        now = time.time()
        for row in divergence:
            history = self._history.setdefault(
                row["eventKey"], deque(maxlen=self.settings.history_length)
            )
            history.append({"ts": now, "divergence": row["divergence"], **row["mids"]})
        best = max((o.net_edge for o in opportunities), default=0.0)
        self._edge_history.append(
            {
                "ts": now,
                "bestNetEdge": round(best, 6),
                "count": len(opportunities),
                "totalProfit": round(sum(o.expected_profit for o in opportunities), 2),
            }
        )

    # ------------------------------------------------------------ publishing

    async def _publish_cache(self) -> None:
        if not self.cache:
            return
        await self.cache.set(
            "arb:opportunities",
            [o.to_dict() for o in self.opportunities[:50]],
            ttl=30,
        )
        await self.cache.set("arb:divergence", self.divergence, ttl=30)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def _broadcast(self) -> None:
        if not self._subscribers:
            return
        payload = self.snapshot(limit=25)
        for queue in list(self._subscribers):
            if queue.full():
                # A slow client must never back-pressure the scan loop; drop
                # its oldest frame instead. Book state is a snapshot, not a
                # log, so the client loses nothing by skipping a frame.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    # ----------------------------------------------------------- persistence

    async def _persist(self, books: list[MarketBook], opportunities: list[Opportunity]) -> None:
        if not self.settings.persist:
            return
        now = time.time()
        write_snapshots = now - self._last_snapshot_write >= self.settings.snapshot_interval
        if not write_snapshots and not opportunities:
            return

        try:
            async with SessionLocal() as session:
                if write_snapshots:
                    self._last_snapshot_write = now
                    session.add_all(
                        [
                            MarketSnapshot(
                                ts=book.ts,
                                venue=book.venue.value,
                                market_id=book.market_id,
                                event_key=book.event_key,
                                title=book.title[:512],
                                mid=book.mid,
                                yes_bid=book.yes.best_bid,
                                yes_ask=book.yes.best_ask,
                                no_bid=book.no.best_bid,
                                no_ask=book.no.best_ask,
                                yes_depth=book.yes.depth("asks"),
                                no_depth=book.no.depth("asks"),
                            )
                            for book in books
                        ]
                    )
                session.add_all(
                    [
                        OpportunityRow(
                            opportunity_id=o.id,
                            ts=o.ts,
                            arb_type=o.arb_type.value,
                            event_key=o.event_key,
                            title=o.title[:512],
                            gross_edge=o.gross_edge,
                            net_edge=o.net_edge,
                            max_size=o.max_size,
                            capital_required=o.capital_required,
                            expected_profit=o.expected_profit,
                            fill_probability=o.fill_probability,
                            legs=[leg.to_dict() for leg in o.legs],
                        )
                        for o in opportunities
                    ]
                )
                await session.commit()
                if self.stats.scans % 500 == 0:
                    await prune_opportunities(session, self.settings.max_stored_opportunities)
        except Exception:
            # Storage is for analysis, not for trading. A dead database must
            # not stop the screen.
            pass

    # ------------------------------------------------------------- accessors

    def snapshot(self, limit: int = 25) -> dict:
        sized = self.sizer.allocate(self.opportunities[:limit], self.settings.bankroll)
        return {
            "type": "snapshot",
            "ts": time.time(),
            "opportunities": [
                {**opportunity.to_dict(), "kelly": result.to_dict()}
                for opportunity, result in sized
            ],
            "divergence": self.divergence,
            "books": [book.to_dict() for book in self.books.values()],
            "feeds": [feed.status.to_dict() for feed in self.feeds],
            "stats": self.stats.to_dict(),
            "edgeHistory": list(self._edge_history),
            "config": self.config_dict(),
        }

    def history(self, event_key: str) -> list[dict]:
        return list(self._history.get(event_key, []))

    def book(self, venue: str, market_id: str) -> MarketBook | None:
        return self.books.get((venue, market_id))

    def find_opportunity(self, opportunity_id: str) -> Opportunity | None:
        return next((o for o in self.opportunities if o.id == opportunity_id), None)

    def config_dict(self) -> dict:
        s = self.settings
        return {
            "feedMode": s.feed_mode,
            "minNetEdge": s.min_net_edge,
            "maxPositionSize": s.max_position_size,
            "maxBookAge": s.max_book_age,
            "bankroll": s.bankroll,
            "kellyMultiplier": s.kelly_multiplier,
            "maxFractionPerTrade": s.max_fraction_per_trade,
            "lossFraction": s.loss_fraction,
            "slippage": self.detector.config.slippage.describe(),
            "fees": {
                venue.value: model.describe()
                for venue, model in self.detector.config.fee_models.items()
            },
            "cacheBackend": self.cache.backend if self.cache else "none",
        }


_runner: EngineRunner | None = None


def get_runner() -> EngineRunner:
    global _runner
    if _runner is None:
        _runner = EngineRunner()
    return _runner
