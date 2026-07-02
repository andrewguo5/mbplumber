"""Board texture computation from the three flop cards only.

The texture is computed once from the flop and carried forward unchanged to all
later streets (the spec treats turn/river completion via the street dimension,
not by recomputing texture).

The headline piece is the connectedness *kernel scan*: a sliding 5-wide window
that measures how densely the distinct flop values cluster into straight-making
ranges. Its integer score is exposed on BoardTexture.kernel_score for auditing.
"""

from __future__ import annotations

from ..cards import parse_card
from ..models import BoardTexture, Color, Connectedness, TopCard

# Window score table: how many distinct values fall inside a 5-wide window.
# 0 or 1 -> 0 pts, 2 -> 1 pt, 3 (or more, though 3 is the max with 3 flop
# cards) -> 3 pts. Capping at 3 keeps the wheel ghost-ace case well defined.
_WINDOW_SCORE = {0: 0, 1: 0, 2: 1, 3: 3}


def _kernel_score(values: set[int]) -> int:
    """Slide a 5-wide window [W, W+4] across W=1..10 and sum window scores.

    `values` must be the DISTINCT flop values, already including the ghost ace
    (value 1) when an Ace is present.
    """
    score = 0
    for w in range(1, 11):
        count = sum(1 for v in values if w <= v <= w + 4)
        score += _WINDOW_SCORE.get(count, 3)
    return score


def board_texture(flop_cards: list[str]) -> BoardTexture:
    """Compute the 4-dimension board texture from exactly the 3 flop cards."""
    if len(flop_cards) < 3:
        raise ValueError("board_texture requires at least 3 flop cards")
    flop = flop_cards[:3]
    parsed = [parse_card(c) for c in flop]
    ranks = [r for r, _ in parsed]
    suits = [s for _, s in parsed]

    # --- color ---
    n_suits = len(set(suits))
    if n_suits == 3:
        color = Color.RAINBOW
    elif n_suits == 2:
        color = Color.TWO_TONE
    else:
        color = Color.MONOTONE

    # --- paired (any two share a rank; trips also paired) ---
    paired = len(set(ranks)) < 3

    # --- top card ---
    top = max(ranks)
    if top >= 12:  # A, K, Q
        top_card = TopCard.HIGH
    elif top >= 8:  # J, T, 9, 8
        top_card = TopCard.MEDIUM
    else:  # 7 and below
        top_card = TopCard.LOW

    # --- connectedness kernel scan (distinct values, wheel ghost ace) ---
    distinct = set(ranks)
    if 14 in distinct:
        distinct = distinct | {1}
    score = _kernel_score(distinct)
    if score <= 2:
        connectedness = Connectedness.DISCONNECTED
    elif score <= 6:
        connectedness = Connectedness.SEMI_CONNECTED
    else:
        connectedness = Connectedness.CONNECTED

    return BoardTexture(
        color=color,
        connectedness=connectedness,
        paired=paired,
        top_card=top_card,
        kernel_score=score,
    )
