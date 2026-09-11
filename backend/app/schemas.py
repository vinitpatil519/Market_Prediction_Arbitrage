"""Request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    opportunity_id: str = Field(alias="opportunityId")
    size: float | None = Field(default=None, gt=0)
    #: Leg indices forced to miss, for stress-testing the unhedged case.
    drop_legs: list[int] = Field(default_factory=list, alias="dropLegs")
    persist: bool = True

    model_config = {"populate_by_name": True}


class KellyRequest(BaseModel):
    opportunity_id: str = Field(alias="opportunityId")
    bankroll: float = Field(default=10_000.0, gt=0)
    kelly_multiplier: float | None = Field(default=None, gt=0, le=1, alias="kellyMultiplier")
    loss_fraction: float | None = Field(default=None, gt=0, le=1, alias="lossFraction")
    max_fraction_per_trade: float | None = Field(
        default=None, gt=0, le=1, alias="maxFractionPerTrade"
    )

    model_config = {"populate_by_name": True}


class MonteCarloRequest(BaseModel):
    bankroll: float = Field(default=10_000.0, gt=0)
    trades: int = Field(default=250, ge=1, le=5_000)
    paths: int = Field(default=500, ge=10, le=5_000)
    net_edge: float = Field(default=0.015, gt=0, lt=1, alias="netEdge")
    cost_per_pair: float = Field(default=0.985, gt=0, lt=1, alias="costPerPair")
    fill_probability: float = Field(default=0.985, gt=0, le=1, alias="fillProbability")
    loss_fraction: float = Field(default=0.5, gt=0, le=1, alias="lossFraction")
    kelly_multiplier: float = Field(default=0.25, gt=0, le=1, alias="kellyMultiplier")
    max_fraction_per_trade: float = Field(
        default=0.20, gt=0, le=1, alias="maxFractionPerTrade"
    )
    seed: int | None = 7

    model_config = {"populate_by_name": True}


class ConfigUpdate(BaseModel):
    """Every field is optional; only what is sent is applied."""

    min_net_edge: float | None = Field(default=None, ge=0, lt=1, alias="minNetEdge")
    max_position_size: float | None = Field(default=None, gt=0, alias="maxPositionSize")
    max_book_age: float | None = Field(default=None, gt=0, alias="maxBookAge")
    latency_ms: float | None = Field(default=None, ge=0, alias="latencyMs")
    decay_per_100ms: float | None = Field(default=None, ge=0, le=1, alias="decayPer100ms")
    adverse_tick: float | None = Field(default=None, ge=0, lt=0.5, alias="adverseTick")
    displayed_size_credibility: float | None = Field(
        default=None, gt=0, le=1, alias="displayedSizeCredibility"
    )
    bankroll: float | None = Field(default=None, gt=0)
    kelly_multiplier: float | None = Field(default=None, gt=0, le=1, alias="kellyMultiplier")
    max_fraction_per_trade: float | None = Field(
        default=None, gt=0, le=1, alias="maxFractionPerTrade"
    )
    loss_fraction: float | None = Field(default=None, gt=0, le=1, alias="lossFraction")
    kalshi_taker_rate: float | None = Field(default=None, ge=0, le=1, alias="kalshiTakerRate")
    polymarket_taker_rate: float | None = Field(
        default=None, ge=0, le=1, alias="polymarketTakerRate"
    )
    polymarket_gas_cost: float | None = Field(default=None, ge=0, alias="polymarketGasCost")

    model_config = {"populate_by_name": True}
