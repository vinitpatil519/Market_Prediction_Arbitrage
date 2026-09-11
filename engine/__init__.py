"""Venue-agnostic quant core for binary prediction-market arbitrage.

The engine package has no web, database or network dependencies: it takes
normalized order books in and returns priced, sized, fee-adjusted trade
opportunities. Everything in `backend/` is a transport layer around this.
"""

from engine.arbitrage import ArbitrageDetector, DetectorConfig
from engine.execution import ExecutionSimulator, SimulatedFill, SimulatedTrade
from engine.fees import FeeModel, KalshiFeeModel, PolymarketFeeModel, fee_model_for
from engine.kelly import KellyResult, KellySizer, kelly_fraction
from engine.models import (
    ArbType,
    Ladder,
    Level,
    MarketBook,
    Opportunity,
    OpportunityLeg,
    Side,
    Venue,
)
from engine.normalizer import Normalizer
from engine.orderbook import DepthWalk, walk_depth
from engine.slippage import SlippageModel

__all__ = [
    "ArbType",
    "ArbitrageDetector",
    "DepthWalk",
    "DetectorConfig",
    "ExecutionSimulator",
    "FeeModel",
    "KalshiFeeModel",
    "KellyResult",
    "KellySizer",
    "Ladder",
    "Level",
    "MarketBook",
    "Normalizer",
    "Opportunity",
    "OpportunityLeg",
    "PolymarketFeeModel",
    "Side",
    "SimulatedFill",
    "SimulatedTrade",
    "SlippageModel",
    "Venue",
    "fee_model_for",
    "kelly_fraction",
    "walk_depth",
]
