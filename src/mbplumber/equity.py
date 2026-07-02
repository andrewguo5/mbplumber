"""Equity of hero vs a field of villain hands.

Hero-vs-field: each villain is an independent contestant and hero must beat all
of them to win the pot outright. On a tie hero takes 1/k of the pot for a k-way
tie that includes hero. Side pots are ignored (spec: hero-vs-field).

Runouts are enumerated exactly when the number of completions is small
(flop/turn/river all-ins: at most C(45,2) ~= 990). For early all-ins where the
remaining board is large (e.g. a preflop all-in needs 5 cards, ~1.4M
completions), exact enumeration is prohibitively slow, so we fall back to
deterministic Monte Carlo sampling. The crossover threshold and sample size are
module constants; sampling is seeded so results are reproducible.
"""

from __future__ import annotations

import math
import random
from itertools import combinations

from .cards import evaluate7, remaining_deck

# Above this many exact completions, switch to Monte Carlo sampling.
EXACT_MAX_RUNOUTS = 20_000
# Number of Monte Carlo samples when enumeration is too large.
MC_SAMPLES = 10_000
# Fixed seed so equity (and thus EV) is reproducible run to run.
MC_SEED = 1234


def _count_combinations(n: int, k: int) -> int:
    return math.comb(n, k)


def _hero_share(hero_score, villain_scores) -> float:
    best_villain = max(villain_scores)
    if hero_score > best_villain:
        return 1.0
    if hero_score < best_villain:
        return 0.0
    tied = 1 + sum(1 for s in villain_scores if s == hero_score)
    return 1.0 / tied


def equity(hero: list[str], villains: list[list[str]], board: list[str]) -> float:
    """Hero's equity vs one or more villains.

    board may have 3, 4, or 5 cards. Completes the board to 5 cards (exactly or
    by sampling), scores hero vs each villain, and averages hero's share.
    """
    if not villains:
        return 1.0
    known = list(hero)
    for v in villains:
        known += v
    known += board
    deck = remaining_deck(known)
    needed = 5 - len(board)

    if needed <= 0:
        # Board already complete: single deterministic showdown.
        hero_score = evaluate7(hero + board)
        villain_scores = [evaluate7(v + board) for v in villains]
        return _hero_share(hero_score, villain_scores)

    n_runouts = _count_combinations(len(deck), needed)

    if n_runouts <= EXACT_MAX_RUNOUTS:
        total = 0.0
        for extra in combinations(deck, needed):
            full_board = board + list(extra)
            hero_score = evaluate7(hero + full_board)
            villain_scores = [evaluate7(v + full_board) for v in villains]
            total += _hero_share(hero_score, villain_scores)
        return total / n_runouts

    # Monte Carlo: sample `needed` distinct cards from the deck, repeatedly.
    rng = random.Random(MC_SEED)
    total = 0.0
    for _ in range(MC_SAMPLES):
        extra = rng.sample(deck, needed)
        full_board = board + extra
        hero_score = evaluate7(hero + full_board)
        villain_scores = [evaluate7(v + full_board) for v in villains]
        total += _hero_share(hero_score, villain_scores)
    return total / MC_SAMPLES
