"""Kelly sizing for arbitrage with execution risk.

A textbook arbitrage has no downside, so Kelly says bet everything. That is
wrong here, and the reason is worth stating: the trade is only riskless if
*both* legs fill and the two venues resolve the same event the same way. In
practice one leg gets picked off, or Kalshi settles on the AP call while
Polymarket settles on the UMA oracle, and you are left holding a naked
directional position.

So the bet is modelled as: win with probability `p` and earn the net edge,
lose with probability `1 - p` and give up `loss_fraction` of the stake. That
is the generalised Kelly problem

    f* = (p * b - q * a) / (a * b)

with `b` the profit per dollar staked on a win and `a` the loss per dollar
staked on a loss. When a -> 0 this correctly diverges, which is why
`loss_fraction` is never allowed to be zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.models import Opportunity

MIN_LOSS_FRACTION = 1e-4


def kelly_fraction(win_prob: float, win_payoff: float, loss_fraction: float = 1.0) -> float:
    """Optimal fraction of bankroll to stake. Clipped to [0, 1]."""
    p = min(1.0, max(0.0, win_prob))
    q = 1.0 - p
    b = max(1e-9, win_payoff)
    a = max(MIN_LOSS_FRACTION, loss_fraction)
    f = (p * b - q * a) / (a * b)
    return min(1.0, max(0.0, f))


def expected_log_growth(
    f: float, win_prob: float, win_payoff: float, loss_fraction: float
) -> float:
    """Expected log-wealth growth per bet at stake fraction `f`."""
    p = min(1.0, max(0.0, win_prob))
    q = 1.0 - p
    a = max(MIN_LOSS_FRACTION, loss_fraction)
    if f * a >= 1.0:
        return float("-inf")
    growth = p * math.log(1.0 + f * win_payoff)
    if q > 0:
        growth += q * math.log(1.0 - f * a)
    return growth


@dataclass(frozen=True, slots=True)
class KellyResult:
    full_fraction: float
    #: `full_fraction` after the fractional-Kelly multiplier and caps.
    applied_fraction: float
    stake: float
    contracts: float
    win_payoff: float
    win_prob: float
    loss_fraction: float
    expected_value: float
    expected_log_growth: float
    #: Which constraint set the size: "kelly", "depth", "cap", "risk" or "none".
    binding_constraint: str

    def to_dict(self) -> dict:
        return {
            "fullFraction": round(self.full_fraction, 6),
            "appliedFraction": round(self.applied_fraction, 6),
            "stake": round(self.stake, 2),
            "contracts": round(self.contracts, 2),
            "winPayoff": round(self.win_payoff, 6),
            "winProb": round(self.win_prob, 6),
            "lossFraction": round(self.loss_fraction, 6),
            "expectedValue": round(self.expected_value, 4),
            "expectedLogGrowth": round(self.expected_log_growth, 8),
            "bindingConstraint": self.binding_constraint,
        }


@dataclass(frozen=True, slots=True)
class KellySizer:
    """Turns a priced opportunity into a dollar stake."""

    #: Fractional Kelly. Full Kelly is correct only if `win_prob` is exact,
    #: and it never is, so a quarter is the desk default.
    kelly_multiplier: float = 0.25
    #: Hard ceiling on bankroll committed to any one opportunity.
    max_fraction_per_trade: float = 0.20
    #: Expected fraction of the stake lost when the hedge breaks. A broken
    #: basket is not a total loss: you are left holding one naked leg that is
    #: still worth roughly its market price, so the damage is about half the
    #: committed capital rather than all of it. Set to 1.0 to size as if every
    #: break were a wipeout.
    loss_fraction: float = 0.5

    def size(self, opportunity: Opportunity, bankroll: float) -> KellyResult:
        cost_per_pair = self._cost_per_pair(opportunity)
        if bankroll <= 0 or cost_per_pair <= 0 or opportunity.max_size <= 0:
            return self._empty(opportunity)

        # Profit per dollar staked: the pair costs `cost_per_pair` and returns
        # $1.00 at settlement, so the payoff ratio is the net edge over cost.
        win_payoff = max(0.0, (1.0 - cost_per_pair) / cost_per_pair)
        if win_payoff <= 0:
            return self._empty(opportunity)

        full = kelly_fraction(opportunity.fill_probability, win_payoff, self.loss_fraction)
        if full <= 0:
            # The edge does not cover the expected cost of a broken hedge.
            # Screening it is correct; trading it is not.
            return self._empty(opportunity, constraint="risk")

        applied = full * self.kelly_multiplier
        constraint = "kelly"

        if applied > self.max_fraction_per_trade:
            applied = self.max_fraction_per_trade
            constraint = "cap"
        if applied <= 0:
            return self._empty(opportunity)

        stake = applied * bankroll
        contracts = stake / cost_per_pair

        # Never size past the liquidity that produced the edge in the first
        # place: beyond `max_size` the next contract is priced at a loss.
        if contracts > opportunity.max_size:
            contracts = opportunity.max_size
            stake = contracts * cost_per_pair
            applied = stake / bankroll
            constraint = "depth"

        p = opportunity.fill_probability
        ev = p * stake * win_payoff - (1.0 - p) * stake * self.loss_fraction
        return KellyResult(
            full_fraction=full,
            applied_fraction=applied,
            stake=stake,
            contracts=contracts,
            win_payoff=win_payoff,
            win_prob=p,
            loss_fraction=self.loss_fraction,
            expected_value=ev,
            expected_log_growth=expected_log_growth(applied, p, win_payoff, self.loss_fraction),
            binding_constraint=constraint,
        )

    def allocate(
        self, opportunities: list[Opportunity], bankroll: float
    ) -> list[tuple[Opportunity, KellyResult]]:
        """Size a book of simultaneous opportunities against one bankroll.

        Opportunities are taken best-edge-first and each is sized against the
        capital still unspent, so the total never exceeds the bankroll even
        when ten screens light up at once.
        """
        ranked = sorted(opportunities, key=lambda o: o.net_edge, reverse=True)
        remaining = bankroll
        out: list[tuple[Opportunity, KellyResult]] = []
        for opportunity in ranked:
            if remaining <= 0:
                out.append((opportunity, self._empty(opportunity)))
                continue
            result = self.size(opportunity, remaining)
            remaining -= result.stake
            out.append((opportunity, result))
        return out

    @staticmethod
    def _cost_per_pair(opportunity: Opportunity) -> float:
        total = sum(leg.cash_out for leg in opportunity.legs)
        size = max(leg.size for leg in opportunity.legs) if opportunity.legs else 0.0
        return total / size if size > 0 else 0.0

    def _empty(self, opportunity: Opportunity, constraint: str = "none") -> KellyResult:
        return KellyResult(
            full_fraction=0.0,
            applied_fraction=0.0,
            stake=0.0,
            contracts=0.0,
            win_payoff=0.0,
            win_prob=opportunity.fill_probability,
            loss_fraction=self.loss_fraction,
            expected_value=0.0,
            expected_log_growth=0.0,
            binding_constraint=constraint,
        )
