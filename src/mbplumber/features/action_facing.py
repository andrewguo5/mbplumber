"""Action-facing and action-taken classification for a postflop street.

Pure functions operating on synthetic or real Action lists so they can be unit
tested in isolation. The extractor walks each street with `StreetWalker` and, at
each hero decision, reads off:

  * action_facing  (ActionFacing): what hero must respond to right now.
  * hero_action_taken (ActionTaken): what hero did.
  * hero_action_sizing_pct (float | None): hero's bet/raise as % of the pot at
    the moment hero acts (None for fold/check/call).

Sizing buckets share one pot-fraction thresholding rule (left-open, right-closed
on the upper edge): <=0.33 SMALL, <=0.67 MEDIUM, <=1.0 LARGE, >1.0 OVERBET.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Action, ActionFacing, ActionTaken, Street


def size_bucket(fraction: float) -> str:
    """Map a pot fraction to one of small/medium/large/overbet."""
    if fraction <= 0.33:
        return "small"
    elif fraction <= 0.67:
        return "medium"
    elif fraction <= 1.0:
        return "large"
    return "overbet"


_BET_FACING = {
    "small": ActionFacing.BET_SMALL,
    "medium": ActionFacing.BET_MEDIUM,
    "large": ActionFacing.BET_LARGE,
    "overbet": ActionFacing.BET_OVERBET,
}
_RAISE_FACING = {
    "small": ActionFacing.RAISE_SMALL,
    "medium": ActionFacing.RAISE_MEDIUM,
    "large": ActionFacing.RAISE_LARGE,
    "overbet": ActionFacing.RAISE_OVERBET,
}
_BET_TAKEN = {
    "small": ActionTaken.BET_SMALL,
    "medium": ActionTaken.BET_MEDIUM,
    "large": ActionTaken.BET_LARGE,
    "overbet": ActionTaken.BET_OVERBET,
}
_RAISE_TAKEN = {
    "small": ActionTaken.RAISE_SMALL,
    "medium": ActionTaken.RAISE_MEDIUM,
    "large": ActionTaken.RAISE_LARGE,
    "overbet": ActionTaken.RAISE_OVERBET,
}


@dataclass
class FacingResult:
    action_facing: ActionFacing
    hero_action_taken: ActionTaken
    hero_action_sizing_pct: float | None


def classify_facing(
    *,
    facing_kind: str,
    sizing_fraction: float,
    is_donk: bool,
) -> ActionFacing:
    """What hero faces. `facing_kind` is "first_to_act", "checked_to", "bet",
    or "raise".

    `sizing_fraction` = bet/pot_before_bet for a bet, raise_increment/pot_before_raise
    for a raise. DONK_BET overrides any bet bucket when is_donk is True.
    """
    if facing_kind == "first_to_act":
        return ActionFacing.FIRST_TO_ACT
    if facing_kind == "checked_to":
        return ActionFacing.CHECKED_TO
    if facing_kind == "bet":
        if is_donk:
            return ActionFacing.DONK_BET
        return _BET_FACING[size_bucket(sizing_fraction)]
    # raise
    return _RAISE_FACING[size_bucket(sizing_fraction)]


def classify_taken(
    *,
    action_type: str,
    pot_before: float,
    amount: float,
    is_raise: bool,
) -> tuple[ActionTaken, float | None]:
    """What hero did + sizing %.

    For a bet, sizing % = amount / pot_before. For a raise, sizing % = the raise
    increment (amount, i.e. the additional chips beyond the call) / pot_before.
    The caller passes `amount` already as the relevant chips for the % numerator.
    """
    if action_type == "fold":
        return ActionTaken.FOLD, None
    if action_type == "check":
        return ActionTaken.CHECK, None
    if action_type == "call":
        return ActionTaken.CALL, None
    frac = amount / pot_before if pot_before > 0 else 0.0
    bucket = size_bucket(frac)
    pct = frac * 100.0
    if is_raise:
        return _RAISE_TAKEN[bucket], pct
    return _BET_TAKEN[bucket], pct


@dataclass
class StreetWalker:
    """Walks one street's actions, tracking the outstanding bet hero faces.

    Bookkeeping per street:
      * current_bet: the highest committed amount any player has matched this
        street (0 if everyone has checked so far).
      * num_bets: count of bet/raise actions this street (0 -> a fresh bet is a
        BET, >=1 -> the next aggressive action is a RAISE).
      * last_raise_pot_before: pot_before of the most recent aggressive action,
        used as the denominator for the next raise's sizing.
    """

    pre_aggressor: str | None  # preflop aggressor name (None in limped pots)
    street: Street

    def hero_decision(
        self,
        *,
        actions_before: list[Action],
        hero_action: Action,
        pot_before_hero: float,
    ) -> FacingResult:
        """Classify a single hero decision given the street actions that
        preceded it (non-post) and hero's own action.

        actions_before: the non-post actions on this street strictly before
        hero's action (in order).
        pot_before_hero: pot size in BB right before hero acts.
        """
        # Reconstruct the bet hero is facing from actions_before.
        current_bet = 0.0
        num_aggr = 0  # number of bet/raise actions so far this street
        prev_aggr_level = 0.0  # the committed level BEFORE the latest aggression
        last_aggr_pot_before = 0.0
        last_aggressor: str | None = None
        for a in actions_before:
            if a.action_type in ("bet", "raise"):
                prev_aggr_level = current_bet
                last_aggr_pot_before = a.pot_before_bb
                # For a bet, amount_bb is the level. For a raise, amount_bb is
                # the incremental chips, so the new level is prev + increment.
                if a.action_type == "bet":
                    current_bet = a.amount_bb
                else:
                    current_bet = current_bet + a.amount_bb
                num_aggr += 1
                last_aggressor = a.player
            # checks/calls/folds do not change the level (call matches it)

        # What does hero face?
        if current_bet <= 0:
            # No outstanding bet. If anyone checked before hero this street,
            # the action was checked TO hero (hero acts behind); otherwise hero
            # is FIRST to act and is opening the street.
            checked_before = any(a.action_type == "check" for a in actions_before)
            facing = classify_facing(
                facing_kind="checked_to" if checked_before else "first_to_act",
                sizing_fraction=0.0,
                is_donk=False,
            )
        elif num_aggr == 1:
            # facing a bet
            frac = current_bet / last_aggr_pot_before if last_aggr_pot_before > 0 else 0.0
            is_donk = (
                self.street == Street.FLOP
                and self.pre_aggressor is not None
                and last_aggressor is not None
                and last_aggressor != self.pre_aggressor
            )
            facing = classify_facing(
                facing_kind="bet", sizing_fraction=frac, is_donk=is_donk
            )
        else:
            # facing a raise; increment = current_bet - prev_aggr_level
            increment = current_bet - prev_aggr_level
            frac = increment / last_aggr_pot_before if last_aggr_pot_before > 0 else 0.0
            facing = classify_facing(
                facing_kind="raise", sizing_fraction=frac, is_donk=False
            )

        # What did hero do?
        atype = hero_action.action_type
        is_raise_action = atype == "raise"
        if atype == "raise":
            numerator = hero_action.amount_bb  # incremental raise chips
        elif atype == "bet":
            numerator = hero_action.amount_bb
        else:
            numerator = 0.0
        taken, pct = classify_taken(
            action_type=atype,
            pot_before=pot_before_hero,
            amount=numerator,
            is_raise=is_raise_action,
        )
        return FacingResult(
            action_facing=facing,
            hero_action_taken=taken,
            hero_action_sizing_pct=pct,
        )
