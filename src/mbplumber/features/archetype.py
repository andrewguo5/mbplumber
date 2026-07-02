"""Flop archetype classification from hero's 2 hole cards + the 3 flop cards.

Strict priority, first match wins: made hands beat draws, and the draw-only
categories (COMBO_DRAW / FLUSH_DRAW / OESD / WEAK_DRAW / TWO_OVERCARDS) are only
ever reached when hero has no pair or better.

Edge-case decisions (documented for the caller):
  * SET_OR_FULL_HOUSE covers any hero holding of trips-or-better made with the
    flop (pocket pair hitting a set, or hero pairing a board pair into a boat).
    We detect it as "hero has 3+ of some rank across hole+flop", which on a
    3-card flop also catches the rare quads case.
  * TWO_PAIR requires BOTH hole cards to pair the board (per spec), which is the
    only way to flop two pair with two hole cards consumed.
  * TOP_PAIR is pairing the single highest flop card. If the flop's top rank is
    paired on board, "top pair" is governed by SET_OR_FULL_HOUSE / TWO_PAIR
    first; a lone hole card matching a non-top board card is MARGINAL_PAIR.
  * OVERPAIR is a pocket pair strictly higher than every flop card. A pocket
    pair lower than the top flop card (an underpair) is MARGINAL_PAIR.
  * OESD vs gutshot is decided by counting how many of the 4 ranks needed to
    complete each candidate straight window are present; an open-ender has two
    distinct completing ranks, a gutshot one. Wheel handled via ghost ace.
  * WEAK_DRAW = gutshot OR a backdoor (3-to-flush, or 3 distinct values inside
    one straight window) and nothing stronger, with no pair.
  * TWO_OVERCARDS requires no pair AND no qualifying draw (no FD/OESD/gutshot/
    backdoor) — both hole cards over the board.
"""

from __future__ import annotations

from itertools import combinations

from ..cards import parse_card
from ..models import FlopArchetype


def _ranks_suits(cards: list[str]) -> tuple[list[int], list[str]]:
    parsed = [parse_card(c) for c in cards]
    return [r for r, _ in parsed], [s for _, s in parsed]


def _has_straight(values: set[int]) -> bool:
    """Is there a 5-card straight using these distinct values (wheel aware)?"""
    vals = set(values)
    if 14 in vals:
        vals.add(1)
    for high in range(14, 4, -1):
        if all(high - i in vals for i in range(5)):
            return True
    return False


def _completing_ranks(present_distinct: set[int]) -> set[int]:
    """Distinct card ranks that would complete a 5-card straight given the
    DISTINCT values hero currently holds (ghost ace already folded in).

    A rank r "completes" if adding r yields some 5-consecutive run. We map a
    completing ghost-ace (value 1) back to the Ace so it counts as one real card.
    """
    completing: set[int] = set()
    for r in range(1, 15):  # candidate completing rank (1 = ghost ace)
        if r in present_distinct:
            continue
        test = present_distinct | {r}
        for high in range(5, 15):
            if all(high - i in test for i in range(5)):
                completing.add(14 if r == 1 else r)
                break
    return completing


def _straight_draw_kind(hole_vals: list[int], board_vals: list[int]) -> str:
    """Classify the best straight draw using hole+board distinct values.

    Returns one of: "oesd", "gutshot", "backdoor", "none". A qualifying draw
    must involve at least one hole card.

    * Four cards toward a straight with TWO distinct completing ranks -> OESD.
    * Four cards toward a straight with ONE completing rank -> gutshot.
    * Three distinct values inside a single 5-wide window (a backdoor straight
      seed) -> backdoor.
    """
    work = set(hole_vals) | set(board_vals)
    if 14 in work:
        work.add(1)
    hole_set = set(hole_vals)
    if 14 in hole_set:
        hole_set = hole_set | {1}

    best = "none"
    # Consider every contiguous 4-subset hero can hold toward a straight: look at
    # each 5-wide window, the present values inside it.
    for high in range(5, 15):
        window = set(range(high - 4, high + 1))
        present = work & window
        if not (present & hole_set):
            continue
        n = len(present)
        if n == 4:
            comp = _completing_ranks(present)
            if len(comp) >= 2:
                return "oesd"
            elif len(comp) == 1:
                best = _stronger(best, "gutshot")
        elif n == 3:
            best = _stronger(best, "backdoor")
    return best


def _stronger(a: str, b: str) -> str:
    order = {"none": 0, "backdoor": 1, "gutshot": 2, "oesd": 3}
    return a if order[a] >= order[b] else b


def _flush_state(hole_suits: list[str], board_suits: list[str]) -> str:
    """Return "flush", "flush_draw", "backdoor", or "none" for hero+board."""
    # only suits hero contributes to matter
    for suit in set(hole_suits):
        total = hole_suits.count(suit) + board_suits.count(suit)
        if total >= 5:
            return "flush"
    for suit in set(hole_suits):
        total = hole_suits.count(suit) + board_suits.count(suit)
        if total == 4:
            return "flush_draw"
    for suit in set(hole_suits):
        total = hole_suits.count(suit) + board_suits.count(suit)
        if total == 3:
            return "backdoor"
    return "none"


def flop_archetype(hero_hole: list[str], flop_cards: list[str]) -> FlopArchetype:
    """Classify hero's flop holding into one FlopArchetype (strict priority)."""
    flop = flop_cards[:3]
    hole_vals, hole_suits = _ranks_suits(hero_hole)
    board_vals, board_suits = _ranks_suits(flop)
    five = hero_hole + flop
    all_vals = set(hole_vals) | set(board_vals)

    flush = _flush_state(hole_suits, board_suits)

    # 1 FLUSH
    if flush == "flush":
        return FlopArchetype.FLUSH

    # 2 STRAIGHT (must use a hole card -> require straight across 5 cards that
    # is not purely on the board)
    if _has_straight(all_vals) and not _has_straight(set(board_vals)):
        return FlopArchetype.STRAIGHT
    # also straight that exists on board only does not count for hero archetype
    if _has_straight(all_vals) and _has_straight(set(board_vals)):
        # board straight; hero archetype depends on pairs etc. fall through
        pass

    # rank multiplicity across hole+board
    counts: dict[int, int] = {}
    for v in hole_vals + board_vals:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())

    # 3 SET_OR_FULL_HOUSE: hero has 3+ of a kind across hole+flop, and hero
    # contributes to it (pocket pair making a set, or pairing a board pair).
    for v, c in counts.items():
        if c >= 3 and v in hole_vals:
            return FlopArchetype.SET_OR_FULL_HOUSE

    top_board = max(board_vals)

    # Determine which hole cards pair the board.
    paired_board_ranks = [v for v in hole_vals if v in board_vals]
    distinct_paired = set(paired_board_ranks)
    is_pocket_pair = len(hole_vals) == 2 and hole_vals[0] == hole_vals[1]

    # 4 TWO_PAIR: both hole cards pair the board (two distinct ranks).
    if len(distinct_paired) >= 2:
        return FlopArchetype.TWO_PAIR

    has_pair = bool(distinct_paired) or is_pocket_pair

    # 5 TOP_PAIR: hero pairs the highest flop card (one hole card == top board).
    if top_board in distinct_paired:
        return FlopArchetype.TOP_PAIR

    # 6 OVERPAIR: pocket pair higher than all flop cards.
    if is_pocket_pair and hole_vals[0] > top_board:
        return FlopArchetype.OVERPAIR

    # 7 MARGINAL_PAIR: pairs a non-top board card, or underpair pocket pair.
    if distinct_paired:  # pairs some non-top board card
        return FlopArchetype.MARGINAL_PAIR
    if is_pocket_pair and hole_vals[0] < top_board:
        return FlopArchetype.MARGINAL_PAIR
    if is_pocket_pair:  # equal would have been caught by set/top; safety
        return FlopArchetype.MARGINAL_PAIR

    # No pair: draw / overcard analysis.
    sd = _straight_draw_kind(hole_vals, board_vals)
    fd = flush == "flush_draw"
    bd_flush = flush == "backdoor"

    # 8 COMBO_DRAW: flush draw AND oesd, no pair.
    if fd and sd == "oesd":
        return FlopArchetype.COMBO_DRAW
    # 9 FLUSH_DRAW
    if fd:
        return FlopArchetype.FLUSH_DRAW
    # 10 OESD
    if sd == "oesd":
        return FlopArchetype.OESD

    # 11 TWO_OVERCARDS: both hole cards over the board, no pair, no qualifying draw.
    both_over = (
        len(hole_vals) == 2
        and min(hole_vals) > top_board
        and sd in ("none",)
        and not bd_flush
    )
    if both_over:
        return FlopArchetype.TWO_OVERCARDS

    # 12 WEAK_DRAW: gutshot or backdoor (flush/straight) only, no pair.
    if sd in ("gutshot", "backdoor") or bd_flush:
        return FlopArchetype.WEAK_DRAW

    # 13 AIR
    return FlopArchetype.AIR
