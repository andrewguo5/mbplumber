"""Card parsing and a pure-Python 7-card hand evaluator.

Leaf utility with no mbPlumber dependencies. Used by equity computation and
(rank helpers) by the flop-archetype/texture classifiers.

Cards are strings like "Ah", "Td", "2c": a rank char then a suit char.
Ranks map to ints 2..14 (T=10, J=11, Q=12, K=13, A=14).
"""

from __future__ import annotations

from itertools import combinations

RANK_CHARS = "23456789TJQKA"
RANK_VALUE = {ch: i for i, ch in enumerate(RANK_CHARS, start=2)}  # '2'->2 ... 'A'->14
VALUE_RANK = {v: ch for ch, v in RANK_VALUE.items()}
SUITS = "cdhs"

# Hand category ranks (higher is better)
HIGH_CARD = 0
PAIR = 1
TWO_PAIR = 2
TRIPS = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
QUADS = 7
STRAIGHT_FLUSH = 8


def parse_card(card: str) -> tuple[int, str]:
    """('Ah') -> (14, 'h'). Case-insensitive on rank, lower-cases suit."""
    card = card.strip()
    rank = RANK_VALUE[card[0].upper()]
    suit = card[1].lower()
    return rank, suit


def full_deck() -> list[str]:
    return [ch + s for ch in RANK_CHARS for s in SUITS]


def remaining_deck(known: list[str]) -> list[str]:
    """All cards not in `known` (case-insensitive), in canonical form."""
    used = set()
    for c in known:
        r, s = parse_card(c)
        used.add(VALUE_RANK[r] + s)
    return [c for c in full_deck() if c not in used]


def _straight_high(values: set[int]) -> int:
    """Return the high card of the best straight in `values`, or 0 if none.
    Handles the wheel (A-2-3-4-5) via a ghost ace at value 1."""
    vals = set(values)
    if 14 in vals:
        vals.add(1)  # ace plays low for the wheel
    best = 0
    for high in range(14, 4, -1):
        if all(high - i in vals for i in range(5)):
            best = high
            break
    return best


def evaluate7(cards: list[str]) -> tuple[int, ...]:
    """Evaluate the best 5-card hand out of 5..7 cards.

    Returns a comparable tuple: (category, tiebreaker ranks...). Larger is
    better, and tuples are directly comparable for the same number of cards.
    """
    parsed = [parse_card(c) for c in cards]
    best: tuple[int, ...] | None = None
    for combo in combinations(parsed, 5):
        score = _evaluate5(combo)
        if best is None or score > best:
            best = score
    assert best is not None
    return best


def _evaluate5(cards: tuple[tuple[int, str], ...]) -> tuple[int, ...]:
    values = sorted((v for v, _ in cards), reverse=True)
    suits = [s for _, s in cards]
    is_flush = len(set(suits)) == 1

    value_set = set(values)
    straight_high = _straight_high(value_set) if len(value_set) == 5 else 0

    # counts: value -> frequency, ordered by (count desc, value desc)
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    count_shape = tuple(c for _, c in by_count)
    ordered_vals = tuple(v for v, _ in by_count)

    if is_flush and straight_high:
        return (STRAIGHT_FLUSH, straight_high)
    if count_shape == (4, 1):
        return (QUADS, *ordered_vals)
    if count_shape == (3, 2):
        return (FULL_HOUSE, *ordered_vals)
    if is_flush:
        return (FLUSH, *values)
    if straight_high:
        return (STRAIGHT, straight_high)
    if count_shape == (3, 1, 1):
        return (TRIPS, *ordered_vals)
    if count_shape == (2, 2, 1):
        return (TWO_PAIR, *ordered_vals)
    if count_shape == (2, 1, 1, 1):
        return (PAIR, *ordered_vals)
    return (HIGH_CARD, *values)
