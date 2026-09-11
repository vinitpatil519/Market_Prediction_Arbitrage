"""Market, book and divergence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.services.engine_runner import get_runner
from engine.orderbook import book_imbalance, cumulative_depth, microprice
from engine.slippage import SlippageModel

router = APIRouter(prefix="/api", tags=["markets"])


@router.get("/markets")
async def list_markets(venue: str | None = None, event_key: str | None = None) -> dict:
    runner = get_runner()
    books = list(runner.books.values())
    if venue:
        books = [b for b in books if b.venue.value == venue]
    if event_key:
        books = [b for b in books if b.event_key == event_key]
    return {
        "count": len(books),
        "markets": [
            {
                **book.to_dict(),
                "yesBid": book.yes.best_bid,
                "yesAsk": book.yes.best_ask,
                "noBid": book.no.best_bid,
                "noAsk": book.no.best_ask,
                "yesSpread": book.yes.spread,
                "imbalance": round(book_imbalance(book.yes), 4),
                "microprice": microprice(book.yes),
                "age": round(book.age, 2),
                "crossed": book.is_crossed,
            }
            for book in books
        ],
    }


@router.get("/markets/{venue}/{market_id}/book")
async def get_book(
    venue: str,
    market_id: str,
    levels: int = Query(default=15, ge=1, le=50),
) -> dict:
    runner = get_runner()
    book = runner.book(venue, market_id)
    if book is None:
        raise HTTPException(status_code=404, detail="book not found")

    slippage: SlippageModel = runner.detector.config.slippage
    return {
        "venue": book.venue.value,
        "marketId": book.market_id,
        "eventKey": book.event_key,
        "title": book.title,
        "ts": book.ts,
        "age": round(book.age, 2),
        "yes": {
            **cumulative_depth(book.yes, levels),
            "bestBid": book.yes.best_bid,
            "bestAsk": book.yes.best_ask,
            "mid": book.yes.mid,
            "spread": book.yes.spread,
        },
        "no": {
            **cumulative_depth(book.no, levels),
            "bestBid": book.no.best_bid,
            "bestAsk": book.no.best_ask,
            "mid": book.no.mid,
            "spread": book.no.spread,
        },
        # The cost of size is the whole game, so the book endpoint ships the
        # curve rather than making the client re-walk the ladder.
        "costCurve": {
            "yesBuy": slippage.cost_curve(book.yes.asks, buying=True),
            "noBuy": slippage.cost_curve(book.no.asks, buying=True),
        },
    }


@router.get("/divergence")
async def divergence() -> dict:
    runner = get_runner()
    return {"rows": runner.divergence, "ts": runner.stats.to_dict()}


@router.get("/events/{event_key}/history")
async def event_history(event_key: str) -> dict:
    runner = get_runner()
    return {"eventKey": event_key, "points": runner.history(event_key)}


@router.get("/feeds")
async def feeds() -> dict:
    runner = get_runner()
    return {
        "mode": runner.settings.feed_mode,
        "feeds": [feed.status.to_dict() for feed in runner.feeds],
    }
