"""Async SQLAlchemy setup and ORM models.

Postgres is the production target; SQLite via aiosqlite is the zero-setup
fallback so the service starts on a clean checkout. The only schema concession
is using a portable JSON column for opportunity legs rather than JSONB.
"""

from __future__ import annotations

import time

from sqlalchemy import JSON, Boolean, Float, Index, Integer, String, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    event_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_depth: Mapped[float] = mapped_column(Float, default=0.0)
    no_depth: Mapped[float] = mapped_column(Float, default=0.0)


Index("ix_snapshot_event_ts", MarketSnapshot.event_key, MarketSnapshot.ts)


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    arb_type: Mapped[str] = mapped_column(String(32), index=True)
    event_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    gross_edge: Mapped[float] = mapped_column(Float)
    net_edge: Mapped[float] = mapped_column(Float, index=True)
    max_size: Mapped[float] = mapped_column(Float)
    capital_required: Mapped[float] = mapped_column(Float)
    expected_profit: Mapped[float] = mapped_column(Float)
    fill_probability: Mapped[float] = mapped_column(Float)
    legs: Mapped[list] = mapped_column(JSON)


class SimulatedTradeRow(Base):
    __tablename__ = "simulated_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True, default=time.time)
    opportunity_id: Mapped[str] = mapped_column(String(64), index=True)
    arb_type: Mapped[str] = mapped_column(String(32))
    size: Mapped[float] = mapped_column(Float)
    capital_deployed: Mapped[float] = mapped_column(Float)
    pnl_if_yes: Mapped[float] = mapped_column(Float)
    pnl_if_no: Mapped[float] = mapped_column(Float)
    hedged: Mapped[bool] = mapped_column(Boolean)
    realized_edge: Mapped[float] = mapped_column(Float)
    fills: Mapped[list] = mapped_column(JSON)


_settings = get_settings()
_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)
engine = create_async_engine(
    _settings.database_url, echo=False, future=True, connect_args=_connect_args
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def prune_opportunities(session: AsyncSession, keep: int) -> int:
    """Drop the oldest rows once the table exceeds `keep`.

    The table is an append-only firehose - a busy screen writes thousands of
    rows an hour - and nothing downstream reads beyond the recent window.
    """
    newest = select(OpportunityRow.id).order_by(OpportunityRow.id.desc()).limit(1)
    total = await session.scalar(newest)
    if total is None or total <= keep:
        return 0
    cutoff = total - keep
    result = await session.execute(delete(OpportunityRow).where(OpportunityRow.id <= cutoff))
    await session.commit()
    return result.rowcount or 0
