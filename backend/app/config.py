"""Runtime configuration.

Every external dependency is optional. With no environment set at all the
service runs on SQLite, an in-process cache and the synthetic feed, which is
what makes `uvicorn backend.app.main:app` work on a clean checkout.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Prediction Market Arbitrage Engine"
    environment: Literal["dev", "prod"] = "dev"

    # --- storage -----------------------------------------------------------
    #: Postgres in production; SQLite keeps the clean checkout runnable.
    database_url: str = "sqlite+aiosqlite:///./arbitrage.db"
    redis_url: str | None = None
    #: Persist snapshots and opportunities. Off for pure screening.
    persist: bool = True
    #: Seconds between writes of the current book state.
    snapshot_interval: float = 5.0
    #: Rows kept before the oldest are pruned.
    max_stored_opportunities: int = 20_000

    # --- feeds -------------------------------------------------------------
    #: "simulator" needs no credentials and produces realistic dislocations.
    feed_mode: Literal["simulator", "live"] = "simulator"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_rest_url: str = "https://clob.polymarket.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    kalshi_ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    kalshi_rest_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_api_key_id: str | None = None
    kalshi_private_key_pem: str | None = None
    #: Markets pulled per venue when discovering live markets.
    live_market_limit: int = 60

    # --- simulator ---------------------------------------------------------
    sim_events: int = 8
    sim_tick_hz: float = 4.0
    sim_seed: int = 42
    #: Per-tick probability of forcing a tradeable dislocation.
    sim_dislocation_rate: float = 0.05

    # --- engine ------------------------------------------------------------
    min_net_edge: float = 0.002
    max_position_size: float = 5_000.0
    max_book_age: float = 5.0
    latency_ms: float = 250.0
    decay_per_100ms: float = 0.08
    adverse_tick: float = 0.0
    displayed_size_credibility: float = 1.0
    bankroll: float = 10_000.0
    kelly_multiplier: float = 0.25
    max_fraction_per_trade: float = 0.20
    loss_fraction: float = 0.5
    #: Minimum seconds between full re-scans, regardless of update rate.
    scan_interval: float = 0.25
    #: Points retained per event for the divergence chart.
    history_length: int = 240

    # --- fees --------------------------------------------------------------
    kalshi_taker_rate: float = 0.07
    kalshi_maker_rate_per_contract: float = 0.0
    polymarket_taker_rate: float = 0.0
    polymarket_maker_rate: float = 0.0
    polymarket_gas_cost: float = 0.02

    # --- transport ---------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
