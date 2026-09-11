from __future__ import annotations

import pytest

from engine.models import Ladder, Level
from engine.orderbook import book_imbalance, cumulative_depth, microprice, walk_depth


def test_walk_fills_at_touch_when_size_fits_first_level():
    walk = walk_depth([Level(0.40, 100), Level(0.41, 100)], 50)
    assert walk.avg_price == pytest.approx(0.40)
    assert walk.filled == 50
    assert walk.levels_consumed == 1
    assert walk.complete


def test_walk_blends_levels_by_size():
    # 100 @ 0.40 and 100 @ 0.50 -> 150 fills at (100*0.40 + 50*0.50) / 150.
    walk = walk_depth([Level(0.40, 100), Level(0.50, 100)], 150)
    assert walk.avg_price == pytest.approx((40.0 + 25.0) / 150)
    assert walk.levels_consumed == 2
    assert walk.slippage == pytest.approx(walk.avg_price - 0.40)


def test_walk_reports_unfilled_beyond_available_depth():
    walk = walk_depth([Level(0.40, 100)], 250)
    assert walk.filled == 100
    assert walk.unfilled == pytest.approx(150)
    assert not walk.complete


def test_walk_on_empty_book_is_not_a_fill():
    walk = walk_depth([], 100)
    assert walk.filled == 0
    assert walk.unfilled == 100


def test_ladder_sorts_on_construction():
    ladder = Ladder(
        bids=[Level(0.30, 1), Level(0.45, 1), Level(0.40, 1)],
        asks=[Level(0.60, 1), Level(0.50, 1)],
    )
    assert ladder.best_bid == 0.45
    assert ladder.best_ask == 0.50
    assert ladder.spread == pytest.approx(0.05)
    assert ladder.mid == pytest.approx(0.475)


def test_mirrored_ladder_reflects_about_one_dollar():
    # A resting YES bid at 0.40 is an offer to sell NO at 0.60.
    ladder = Ladder(bids=[Level(0.40, 10)], asks=[Level(0.45, 20)])
    mirrored = ladder.mirrored()
    assert mirrored.best_ask == pytest.approx(0.60)
    assert mirrored.best_bid == pytest.approx(0.55)
    assert mirrored.asks[0].size == 10


def test_cumulative_depth_accumulates_monotonically():
    ladder = Ladder(asks=[Level(0.50, 100), Level(0.51, 200), Level(0.52, 50)])
    rows = cumulative_depth(ladder)["asks"]
    assert [row["cumulative"] for row in rows] == [100.0, 300.0, 350.0]


def test_imbalance_and_microprice_lean_toward_the_thin_side():
    ladder = Ladder(bids=[Level(0.49, 900)], asks=[Level(0.51, 100)])
    assert book_imbalance(ladder) == pytest.approx(0.8)
    # Heavy bids and a thin offer pull the fair price up toward the ask.
    assert microprice(ladder) > ladder.mid


def test_level_rejects_prices_outside_the_payout_range():
    with pytest.raises(ValueError):
        Level(1.4, 10)
    with pytest.raises(ValueError):
        Level(0.5, -1)
