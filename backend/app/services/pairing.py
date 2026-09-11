"""Cross-venue event matching.

Cross-venue arbitrage is only an arbitrage if the two contracts settle on the
same fact. The venues share no identifiers, so the only link is the question
text - and a false positive here is the single most expensive bug in the
system: matching "Fed cuts in March" against "Fed cuts in June" produces a
screen that shows a 30c edge and loses the whole stake.

The matcher is therefore deliberately conservative:

* Numbers and years are treated as hard constraints, not weights. "above 3.0%"
  and "above 4.0%" can never match regardless of how similar the prose is.
* Comparison direction (above/below, over/under) is a hard constraint too.
* Only the remaining prose is scored, by token overlap, and it has to clear a
  high threshold.

Anything that does not clear the bar keeps its venue-local event key and is
screened for same-venue arbitrage only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.models import Venue
from engine.normalizer import MarketRef, Normalizer

STOPWORDS = {
    "a", "an", "the", "will", "be", "is", "are", "to", "of", "in", "on", "at",
    "for", "by", "this", "that", "it", "its", "and", "or", "do", "does", "did",
    "there", "their", "what", "when", "who", "market", "contract", "yes", "no",
}

ABOVE = {"above", "over", "higher", "exceed", "exceeds", "greater", "more", "up"}
BELOW = {"below", "under", "lower", "less", "fewer", "down", "beneath"}

MATCH_THRESHOLD = 0.55


@dataclass(frozen=True, slots=True)
class _Signature:
    ref: MarketRef
    tokens: frozenset[str]
    numbers: frozenset[float]
    direction: str  # "above", "below" or "none"


def build_signature(ref: MarketRef) -> _Signature:
    text = ref.title.lower()
    numbers = frozenset(_extract_numbers(text))
    words = set(re.findall(r"[a-z]+", text))
    direction = "above" if words & ABOVE else ("below" if words & BELOW else "none")
    tokens = frozenset(word for word in words if word not in STOPWORDS and len(word) > 2)
    return _Signature(ref=ref, tokens=tokens, numbers=numbers, direction=direction)


def similarity(left: _Signature, right: _Signature) -> float:
    """Jaccard over prose, gated by hard numeric and directional constraints."""
    if left.numbers != right.numbers:
        return 0.0
    if "none" not in (left.direction, right.direction) and left.direction != right.direction:
        return 0.0
    if not left.tokens or not right.tokens:
        return 0.0
    intersection = len(left.tokens & right.tokens)
    union = len(left.tokens | right.tokens)
    return intersection / union if union else 0.0


def pair_markets(normalizer: Normalizer, threshold: float = MATCH_THRESHOLD) -> list[dict]:
    """Rewrite event keys so matched markets share one key. Returns the log."""
    by_venue: dict[Venue, list[_Signature]] = {}
    for ref in normalizer.markets:
        by_venue.setdefault(ref.venue, []).append(build_signature(ref))

    if len(by_venue) < 2:
        return []

    (venue_a, left), (venue_b, right) = list(by_venue.items())[:2]
    used: set[str] = set()
    matches: list[dict] = []

    for source in left:
        best: _Signature | None = None
        best_score = threshold
        for candidate in right:
            if candidate.ref.market_id in used:
                continue
            score = similarity(source, candidate)
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            continue

        used.add(best.ref.market_id)
        event_key = f"pair:{source.ref.market_id[:16]}"
        normalizer.register(_rekey(source.ref, event_key))
        normalizer.register(_rekey(best.ref, event_key))
        matches.append(
            {
                "eventKey": event_key,
                "score": round(best_score, 3),
                venue_a.value: source.ref.title,
                venue_b.value: best.ref.title,
            }
        )

    return matches


def _rekey(ref: MarketRef, event_key: str) -> MarketRef:
    return MarketRef(
        venue=ref.venue,
        market_id=ref.market_id,
        event_key=event_key,
        title=ref.title,
        token_ids=ref.token_ids,
    )


def _extract_numbers(text: str) -> list[float]:
    """Numbers that change the contract's meaning: thresholds, years, counts.

    Formatting is stripped ($100,000 and 100000 are the same number) but the
    value itself is never rounded away.
    """
    out: list[float] = []
    for raw in re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?[kmb]?", text):
        cleaned = raw.replace("$", "").replace(",", "").replace("%", "")
        multiplier = 1.0
        if cleaned and cleaned[-1] in "kmb":
            multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}[cleaned[-1]]
            cleaned = cleaned[:-1]
        try:
            out.append(float(cleaned) * multiplier)
        except ValueError:
            continue
    return out
