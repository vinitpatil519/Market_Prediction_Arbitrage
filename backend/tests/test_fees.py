from __future__ import annotations

import pytest

from engine.fees import KalshiFeeModel, PolymarketFeeModel, effective_fee_bps, fee_model_for
from engine.models import Venue


def test_kalshi_fee_follows_the_published_formula():
    model = KalshiFeeModel()
    # 0.07 * 100 * 0.50 * 0.50 = 1.75
    assert model.trade_fee(0.50, 100) == pytest.approx(1.75)
    # 0.07 * 100 * 0.10 * 0.90 = 0.63
    assert model.trade_fee(0.10, 100) == pytest.approx(0.63)


def test_kalshi_fee_rounds_up_to_the_cent():
    model = KalshiFeeModel()
    # 0.07 * 1 * 0.5 * 0.5 = 0.0175, which is billed as 2c not 1.75c.
    assert model.trade_fee(0.50, 1) == pytest.approx(0.02)


def test_kalshi_fee_peaks_at_a_coin_flip():
    model = KalshiFeeModel()
    at_the_money = model.trade_fee(0.50, 1_000)
    in_the_tail = model.trade_fee(0.05, 1_000)
    assert at_the_money > in_the_tail
    # This ratio is why profitable cross-venue arbitrage lives in the tails:
    # the same clip costs roughly 5x more to trade at 50c.
    assert at_the_money / in_the_tail > 4


def test_kalshi_maker_orders_are_free_by_default():
    assert KalshiFeeModel().trade_fee(0.50, 100, is_maker=True) == pytest.approx(0.0)


def test_polymarket_charges_gas_not_notional_by_default():
    model = PolymarketFeeModel(gas_cost_per_order=0.02)
    assert model.trade_fee(0.50, 10) == pytest.approx(0.02)
    assert model.trade_fee(0.50, 10_000) == pytest.approx(0.02)


def test_polymarket_fixed_cost_dominates_small_clips():
    model = PolymarketFeeModel(gas_cost_per_order=0.02)
    # 20 bps of the payout on a 10-lot, 0.02 bps on a 10,000-lot.
    assert effective_fee_bps(model, 0.5, 10) == pytest.approx(20.0)
    assert effective_fee_bps(model, 0.5, 10_000) == pytest.approx(0.02)


def test_polymarket_optional_rate_is_symmetric_around_fifty_cents():
    model = PolymarketFeeModel(taker_rate=0.02, gas_cost_per_order=0.0)
    assert model.trade_fee(0.30, 100) == pytest.approx(model.trade_fee(0.70, 100))


def test_default_registry_maps_each_venue():
    assert isinstance(fee_model_for(Venue.KALSHI), KalshiFeeModel)
    assert isinstance(fee_model_for(Venue.POLYMARKET), PolymarketFeeModel)


def test_zero_size_is_free():
    assert KalshiFeeModel().trade_fee(0.5, 0) == 0.0
    assert PolymarketFeeModel().trade_fee(0.5, 0) == 0.0
