"""Venue fee models.

Fees on binary markets are not a flat basis-point charge on notional: both
venues price them off `p * (1 - p)`, which peaks at 50c and vanishes at the
tails. A 2c gross edge on a 50c contract can be entirely fee, while the same
edge on a 5c contract is nearly all profit. Nothing downstream is allowed to
see a gross number.

The published formulas change; every coefficient here is a constructor
argument so the model can be re-calibrated without touching the detector.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.models import Venue


def _round_up_cent(amount: float) -> float:
    return math.ceil(amount * 100 - 1e-9) / 100


@dataclass(frozen=True, slots=True)
class FeeModel:
    """Base model: no trading fee, optional flat per-order cost."""

    venue: Venue
    per_order_cost: float = 0.0

    def trade_fee(self, price: float, size: float, *, is_maker: bool = False) -> float:
        return self.per_order_cost if size > 0 else 0.0

    def settlement_fee(self, size: float) -> float:
        return 0.0

    def round_trip(self, price: float, size: float, *, is_maker: bool = False) -> float:
        """Total cost of entering and settling a position."""
        return self.trade_fee(price, size, is_maker=is_maker) + self.settlement_fee(size)

    def describe(self) -> dict:
        return {"venue": self.venue.value, "model": type(self).__name__}


@dataclass(frozen=True, slots=True)
class KalshiFeeModel(FeeModel):
    """Kalshi charges `ceil(rate * C * P * (1 - P))`, rounded up to the cent.

    Maker orders on most series are free; a per-contract maker rate is exposed
    for the series where that is not true. Settlement is free.
    """

    venue: Venue = Venue.KALSHI
    taker_rate: float = 0.07
    maker_rate_per_contract: float = 0.0

    def trade_fee(self, price: float, size: float, *, is_maker: bool = False) -> float:
        if size <= 0:
            return 0.0
        if is_maker:
            fee = self.maker_rate_per_contract * size
        else:
            fee = self.taker_rate * size * price * (1.0 - price)
        return _round_up_cent(fee) + self.per_order_cost

    def describe(self) -> dict:
        return {
            "venue": self.venue.value,
            "model": "KalshiFeeModel",
            "formula": "ceil(rate * C * P * (1-P)) to the cent",
            "takerRate": self.taker_rate,
            "makerRatePerContract": self.maker_rate_per_contract,
        }


@dataclass(frozen=True, slots=True)
class PolymarketFeeModel(FeeModel):
    """Polymarket's CLOB has historically charged no maker or taker fee.

    What it does charge is gas and relay cost per order, which is a fixed
    dollar amount and therefore dominates small clips: a $0.02 per-order cost
    on a 10-contract fill is 20 bps of a 1c edge. Markets that do enable a
    trading fee use `rate * min(p, 1-p) * shares`, which is symmetric around
    50c like Kalshi's but linear in the tail distance rather than quadratic.
    """

    venue: Venue = Venue.POLYMARKET
    taker_rate: float = 0.0
    maker_rate: float = 0.0
    gas_cost_per_order: float = 0.02

    def trade_fee(self, price: float, size: float, *, is_maker: bool = False) -> float:
        if size <= 0:
            return 0.0
        rate = self.maker_rate if is_maker else self.taker_rate
        fee = rate * min(price, 1.0 - price) * size
        return fee + self.gas_cost_per_order + self.per_order_cost

    def describe(self) -> dict:
        return {
            "venue": self.venue.value,
            "model": "PolymarketFeeModel",
            "formula": "rate * min(p, 1-p) * shares + gas",
            "takerRate": self.taker_rate,
            "makerRate": self.maker_rate,
            "gasCostPerOrder": self.gas_cost_per_order,
        }


_DEFAULTS: dict[Venue, FeeModel] = {
    Venue.KALSHI: KalshiFeeModel(),
    Venue.POLYMARKET: PolymarketFeeModel(),
}


def fee_model_for(venue: Venue) -> FeeModel:
    return _DEFAULTS.get(venue, FeeModel(venue=venue))


def set_fee_model(venue: Venue, model: FeeModel) -> None:
    """Re-calibrate a venue at runtime (used by the settings endpoint)."""
    _DEFAULTS[venue] = model


def effective_fee_bps(model: FeeModel, price: float, size: float) -> float:
    """Fee as basis points of the contract's $1 payout, for comparison."""
    if size <= 0:
        return 0.0
    return (model.trade_fee(price, size) / size) * 10_000
