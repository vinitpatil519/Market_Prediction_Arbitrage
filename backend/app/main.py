"""FastAPI application entry point.

Run from the repository root so that both `engine` and `backend` are importable:

    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.db import dispose_db, init_db
from backend.app.routers import config as config_router
from backend.app.routers import markets, opportunities, simulate, ws
from backend.app.services.engine_runner import get_runner

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    runner = get_runner()
    await runner.start()
    try:
        yield
    finally:
        await runner.stop()
        await dispose_db()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Detects same-venue and cross-venue mispricing on binary prediction "
        "markets, prices it net of venue fees and depth-walked slippage, and "
        "sizes it with risk-adjusted Kelly."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(markets.router)
app.include_router(opportunities.router)
app.include_router(simulate.router)
app.include_router(config_router.router)
app.include_router(ws.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    runner = get_runner()
    return {
        "status": "ok",
        "ts": time.time(),
        "feedMode": settings.feed_mode,
        "markets": len(runner.books),
        "liveOpportunities": len(runner.opportunities),
        "feeds": [feed.status.to_dict() for feed in runner.feeds],
    }


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "stream": "/ws/stream",
        "endpoints": [
            "/api/markets",
            "/api/markets/{venue}/{market_id}/book",
            "/api/divergence",
            "/api/opportunities",
            "/api/opportunities/summary",
            "/api/opportunities/history",
            "/api/simulate/execute",
            "/api/simulate/kelly",
            "/api/simulate/montecarlo",
            "/api/config",
        ],
    }
