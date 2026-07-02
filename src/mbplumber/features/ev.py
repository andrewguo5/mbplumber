"""Per-decision realized EV attribution (in BB).

Each postflop hero decision is valued by the chips it realizes relative to
giving up (folding = 0), counting the pre-existing pot consistently so no
branch is inflated. With:

  P  = pot before hero's action (the pre-existing pot)
  B  = chips hero commits at this decision (bet/raise/call amount; 0 for check)
  M  = chips villains commit in direct response to hero's aggressive action on
       this street (what a bet/raise induced and got matched)
  won = did hero take the pot down at the end of the hand

the value of the decision is:

  fold                      -> 0
  check, won                -> +P            (checked through, won the pot)
  check, lost               ->  0
  call B, won               -> +P            (collect the pot; the call nets out)
  call B, lost              -> -B
  bet/raise B, villain folds -> +P           (won the pre-existing pot)
  bet/raise B, called, won  -> +P + M        (pot plus the extra value extracted)
  bet/raise B, called, lost -> -B

A single closed form produces every row:

  EV = (+P + M)   if won
       (-B)       if lost
  with check/fold contributing B = 0 (so a lost check/fold is 0), and a
  fold short-circuited to 0 (a folding hero never wins).

"Each decision uses its own pot-before" (per design): P is the pot at the
moment of THIS decision, so the same chips may appear in several decisions'
P across streets. That double-counting is intentional and consistent.

All-in handling: when the chips go in all-in and the hand is a genuine
contest (>=1 villain revealed hole cards), `won` is replaced by hero's
*equity* at the all-in point, so a coin-flip cooler is valued by its equity
rather than the lucky/unlucky runout. The win branch is then scaled by equity
and the lose branch by (1 - equity).
"""

from __future__ import annotations

from ..equity import equity
from ..models import Hand, Street

_STREET_BOARD_LEN = {
    Street.PREFLOP: 0,
    Street.FLOP: 3,
    Street.TURN: 4,
    Street.RIVER: 5,
}


def decision_ev(
    *,
    pot_before_bb: float,
    hero_commit_bb: float,
    villain_response_bb: float,
    is_fold: bool,
    hero_won: bool,
    equity_override: float | None = None,
) -> float:
    """Realized EV (BB) of a single hero decision; see module docstring.

    pot_before_bb:      P, pot before hero acts.
    hero_commit_bb:     B, chips hero puts in at this decision (0 for check/fold).
    villain_response_bb: M, chips villains matched against hero's aggression
                        on this street after hero's action.
    is_fold:            hero folded (always 0).
    hero_won:           did hero take the pot down.
    equity_override:    if set (all-in), use this in place of the 0/1 win
                        outcome to blend the win/lose branches.
    """
    if is_fold:
        return 0.0

    win_value = pot_before_bb + villain_response_bb
    lose_value = -hero_commit_bb

    if equity_override is not None:
        eq = max(0.0, min(1.0, equity_override))
        return eq * win_value + (1.0 - eq) * lose_value

    return win_value if hero_won else lose_value


def allin_equity(hand: Hand, hero: str) -> float | None:
    """Hero's equity at the point chips went all-in, or None if not applicable.

    Returns None when hero was not all-in or there is no genuine contest
    (no other player revealed hole cards), in which case the caller should use
    the realized win/lose outcome instead.
    """
    hero_all_in = any(
        a.is_all_in for a in hand.actions if a.player == hero and not a.is_post
    )
    if not hero_all_in or not hand.hero_hole_cards:
        return None

    villain_holes = [
        cards for name, cards in hand.all_hole_cards.items() if name != hero and cards
    ]
    if not villain_holes:
        return None

    allin_street: Street | None = next(
        (a.street for a in hand.actions if a.is_all_in), None
    )
    if allin_street is None:
        return None

    board_len = _STREET_BOARD_LEN[allin_street]
    board_at_allin = hand.board[:board_len]
    if len(board_at_allin) < board_len:
        return None

    return equity(hand.hero_hole_cards, villain_holes, board_at_allin)
