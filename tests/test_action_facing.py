"""Action-facing / action-taken classification, including sizing boundaries."""

from mbplumber.features.action_facing import (
    StreetWalker,
    classify_taken,
    size_bucket,
)
from mbplumber.models import Action, ActionFacing, ActionTaken, Street


def _a(player, action_type, amount=0.0, pot_before=0.0, all_in=False):
    return Action(
        street=Street.FLOP,
        player=player,
        action_type=action_type,
        amount_bb=amount,
        pot_before_bb=pot_before,
        is_all_in=all_in,
    )


def test_size_bucket_boundaries():
    assert size_bucket(0.33) == "small"
    assert size_bucket(0.331) == "medium"
    assert size_bucket(0.67) == "medium"
    assert size_bucket(0.671) == "large"
    assert size_bucket(1.0) == "large"
    assert size_bucket(1.01) == "overbet"


def test_facing_first_to_act():
    # Hero opens the street with nobody having acted -> FIRST_TO_ACT, not a
    # "facing a check" spot.
    w = StreetWalker(pre_aggressor="X", street=Street.FLOP)
    res = w.hero_decision(
        actions_before=[],
        hero_action=_a("Hero", "check"),
        pot_before_hero=10.0,
    )
    assert res.action_facing == ActionFacing.FIRST_TO_ACT
    assert res.hero_action_taken == ActionTaken.CHECK
    assert res.hero_action_sizing_pct is None


def test_facing_checked_to():
    # A villain checks before hero (no bet) -> action is CHECKED_TO hero.
    w = StreetWalker(pre_aggressor="X", street=Street.FLOP)
    res = w.hero_decision(
        actions_before=[_a("V", "check")],
        hero_action=_a("Hero", "check"),
        pot_before_hero=10.0,
    )
    assert res.action_facing == ActionFacing.CHECKED_TO
    assert res.hero_action_taken == ActionTaken.CHECK


def test_facing_bet_at_33pct():
    # villain (PFR) bets 3.3 into pot of 10 -> 33% -> BET_SMALL (not a donk)
    w = StreetWalker(pre_aggressor="V", street=Street.FLOP)
    bet = _a("V", "bet", amount=3.3, pot_before=10.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "call"),
        pot_before_hero=13.3,
    )
    assert res.action_facing == ActionFacing.BET_SMALL
    assert res.hero_action_taken == ActionTaken.CALL


def test_facing_bet_at_67pct():
    # V IS the preflop aggressor (c-bets), so this is an ordinary bet by sizing.
    w = StreetWalker(pre_aggressor="V", street=Street.FLOP)
    bet = _a("V", "bet", amount=6.7, pot_before=10.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "fold"),
        pot_before_hero=16.7,
    )
    assert res.action_facing == ActionFacing.BET_MEDIUM


def test_facing_bet_at_100pct():
    w = StreetWalker(pre_aggressor="V", street=Street.FLOP)
    bet = _a("V", "bet", amount=10.0, pot_before=10.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "fold"),
        pot_before_hero=20.0,
    )
    assert res.action_facing == ActionFacing.BET_LARGE


def test_facing_overbet():
    w = StreetWalker(pre_aggressor="V", street=Street.FLOP)
    bet = _a("V", "bet", amount=15.0, pot_before=10.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "fold"),
        pot_before_hero=25.0,
    )
    assert res.action_facing == ActionFacing.BET_OVERBET


def test_donk_bet_on_flop():
    # V is NOT preflop aggressor and leads into the PFR on the flop -> DONK_BET
    w = StreetWalker(pre_aggressor="Hero", street=Street.FLOP)
    bet = _a("V", "bet", amount=2.0, pot_before=10.0)  # small sizing but donk
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "call"),
        pot_before_hero=12.0,
    )
    assert res.action_facing == ActionFacing.DONK_BET


def test_limped_pot_lead_is_not_donk():
    w = StreetWalker(pre_aggressor=None, street=Street.FLOP)
    bet = _a("V", "bet", amount=5.0, pot_before=10.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=_a("Hero", "call"),
        pot_before_hero=15.0,
    )
    assert res.action_facing == ActionFacing.BET_MEDIUM  # 50% pot


def test_facing_raise():
    # V1 bets 5 into 10, V2 raises +10 (increment 10), pot before raise = 15
    w = StreetWalker(pre_aggressor="Hero", street=Street.FLOP)
    bet = _a("V1", "bet", amount=5.0, pot_before=10.0)
    raise_ = _a("V2", "raise", amount=10.0, pot_before=20.0)
    res = w.hero_decision(
        actions_before=[bet, raise_],
        hero_action=_a("Hero", "fold"),
        pot_before_hero=30.0,
    )
    # increment 10 / pot_before_raise 20 = 50% -> RAISE_MEDIUM
    assert res.action_facing == ActionFacing.RAISE_MEDIUM


def test_hero_bet_sizing_pct():
    taken, pct = classify_taken(
        action_type="bet", pot_before=10.0, amount=5.0, is_raise=False
    )
    assert taken == ActionTaken.BET_MEDIUM
    assert pct == 50.0


def test_hero_raise_taken():
    # V is the PFR c-betting; hero raise-raises. Ordinary bet faced, not a donk.
    w = StreetWalker(pre_aggressor="V", street=Street.FLOP)
    bet = _a("V", "bet", amount=5.0, pot_before=10.0)
    hero_raise = _a("Hero", "raise", amount=15.0, pot_before=20.0)
    res = w.hero_decision(
        actions_before=[bet],
        hero_action=hero_raise,
        pot_before_hero=20.0,
    )
    # facing the bet 5/10 = 50% medium
    assert res.action_facing == ActionFacing.BET_MEDIUM
    # hero raises increment 15 / pot 20 = 75% -> raise_large
    assert res.hero_action_taken == ActionTaken.RAISE_LARGE
    assert res.hero_action_sizing_pct == 75.0


def test_multi_action_street():
    # V1 checks, V2 (the PFR) bets, hero faces the bet (not the check).
    w = StreetWalker(pre_aggressor="V2", street=Street.FLOP)
    check = _a("V1", "check", pot_before=10.0)
    bet = _a("V2", "bet", amount=3.0, pot_before=10.0)  # 30% small
    res = w.hero_decision(
        actions_before=[check, bet],
        hero_action=_a("Hero", "call"),
        pot_before_hero=13.0,
    )
    assert res.action_facing == ActionFacing.BET_SMALL
