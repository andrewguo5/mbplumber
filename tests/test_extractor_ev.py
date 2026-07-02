"""Tests for per-decision EV attribution at the EXTRACTOR call-site.

The closed-form in ev.py is tested in isolation by test_ev.py. These tests guard
the attribution logic in extractor.extract — specifically that the "M" term
(chips villains commit in response to hero's aggression) accrues ONLY to hero
bets/raises, never to checks or calls. A won check must be valued at pot_before
alone; the villains piling money in AFTER hero checks is not won by virtue of
the check. See the 2026-06-23 fix.
"""

from datetime import datetime

from mbplumber.config import load_config
from mbplumber.features.extractor import extract
from mbplumber.models import Action, Hand, Player, Position, PotType, Street


def _post(name, amt, pot):
    return Action(
        street=Street.PREFLOP, player=name, action_type="post",
        amount_bb=amt, pot_before_bb=pot, is_post=True,
    )


def _hand(actions, *, hero_won):
    """3-way SRP that reaches the flop; hero='hero' on the button (IP)."""
    return Hand(
        hand_id="ev",
        date=datetime(2026, 1, 1),
        big_blind=1.0,
        hero_seat=4,
        button_seat=4,
        players=[
            Player(seat=1, name="sb", stack_bb=100.0),
            Player(seat=2, name="bb", stack_bb=100.0),
            Player(seat=4, name="hero", stack_bb=100.0),
        ],
        actions=actions,
        board=["2c", "7d", "Kh", "9s", "Js"],
        hero_hole_cards=["As", "Ad"],
        pot_type=PotType.SRP,
        hero_net_bb=0.0,
        hero_won=hero_won,
        reaches_flop=True,
    )


def _hero_decisions(hand):
    cfg = load_config()
    return [d for d in extract(hand, cfg, Position.BTN)]


def test_won_check_does_not_absorb_later_villain_chips():
    # Preflop everyone limps to a 3 BB pot; flop = hero checks, then villains bet
    # and call AFTER hero. Those later chips must NOT inflate the won check.
    actions = [
        _post("sb", 0.5, 0.0),
        _post("bb", 1.0, 0.5),
        Action(street=Street.PREFLOP, player="hero", action_type="call", amount_bb=1.0, pot_before_bb=1.5),
        Action(street=Street.PREFLOP, player="sb", action_type="call", amount_bb=0.5, pot_before_bb=2.5),
        Action(street=Street.PREFLOP, player="bb", action_type="check", amount_bb=0.0, pot_before_bb=3.0),
        # Flop, pot = 3.0. Hero (IP, last preflop actor folds none) checks FIRST here
        # to construct the leak: villains then pour money in behind the check.
        Action(street=Street.FLOP, player="hero", action_type="check", amount_bb=0.0, pot_before_bb=3.0),
        Action(street=Street.FLOP, player="sb", action_type="bet", amount_bb=2.0, pot_before_bb=3.0),
        Action(street=Street.FLOP, player="bb", action_type="call", amount_bb=2.0, pot_before_bb=5.0),
    ]
    hero_checks = [d for d in _hero_decisions(_hand(actions, hero_won=True))
                   if d.street == Street.FLOP]
    assert hero_checks, "expected a flop hero decision"
    # Won check is valued at pot_before (3.0) ONLY — the 4.0 of villain chips that
    # arrived after the check are not attributed to it.
    assert hero_checks[0].hero_realized_ev_bb == 3.0


def test_won_bet_still_adds_villain_match():
    # Same shape, but hero BETS the flop and a villain calls. The call IS induced
    # by hero's aggression, so it accrues: EV = pot_before + matched call.
    actions = [
        _post("sb", 0.5, 0.0),
        _post("bb", 1.0, 0.5),
        Action(street=Street.PREFLOP, player="hero", action_type="call", amount_bb=1.0, pot_before_bb=1.5),
        Action(street=Street.PREFLOP, player="sb", action_type="call", amount_bb=0.5, pot_before_bb=2.5),
        Action(street=Street.PREFLOP, player="bb", action_type="check", amount_bb=0.0, pot_before_bb=3.0),
        Action(street=Street.FLOP, player="hero", action_type="bet", amount_bb=2.0, pot_before_bb=3.0),
        Action(street=Street.FLOP, player="sb", action_type="call", amount_bb=2.0, pot_before_bb=5.0),
        Action(street=Street.FLOP, player="bb", action_type="fold", amount_bb=0.0, pot_before_bb=7.0),
    ]
    hero_bets = [d for d in _hero_decisions(_hand(actions, hero_won=True))
                 if d.street == Street.FLOP]
    assert hero_bets, "expected a flop hero decision"
    # pot_before (3.0) + induced call (2.0) = 5.0.
    assert hero_bets[0].hero_realized_ev_bb == 5.0
