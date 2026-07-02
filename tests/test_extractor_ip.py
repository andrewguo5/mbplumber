"""Tests for in-position (IP) detection: hero is IP iff hero acts last on the
flop among players still in the hand."""

from datetime import datetime

from mbplumber.config import Config
from mbplumber.features.extractor import _hero_is_ip, extract
from mbplumber.models import (
    Action,
    ActionFacing,
    Hand,
    Player,
    PotType,
    Position,
    Street,
)


def _hand(*, button_seat, seats, in_hand, hero_seat):
    """Minimal Hand for IP testing. `seats` maps name->seat."""
    players = [Player(seat=s, name=n, stack_bb=100.0) for n, s in seats.items()]
    return Hand(
        hand_id="h",
        date=datetime(2026, 1, 1),
        big_blind=1.0,
        hero_seat=hero_seat,
        button_seat=button_seat,
        players=players,
        actions=[],
        board=["2c", "7d", "Kh"],
        hero_hole_cards=["As", "Ad"],
        pot_type=PotType.SRP,
        hero_net_bb=0.0,
        reaches_flop=True,
    )


def _ip(button_seat, seats, in_hand, hero_name):
    hero_seat = seats[hero_name]
    h = _hand(button_seat=button_seat, seats=seats, in_hand=in_hand, hero_seat=hero_seat)
    return _hero_is_ip(h, hero_name, set(in_hand))


def test_heads_up_button_is_ip():
    # Button (seat 4) vs BB (seat 6). Button acts last postflop -> IP.
    seats = {"btn": 4, "bb": 6}
    assert _ip(4, seats, ["btn", "bb"], "btn") is True
    assert _ip(4, seats, ["btn", "bb"], "bb") is False


def test_three_way_button_is_ip():
    seats = {"sb": 1, "bb": 2, "btn": 4}
    assert _ip(4, seats, ["sb", "bb", "btn"], "btn") is True
    assert _ip(4, seats, ["sb", "bb", "btn"], "sb") is False
    assert _ip(4, seats, ["sb", "bb", "btn"], "bb") is False


def test_button_folded_preflop_next_seat_is_ip():
    # Button folded preflop; only SB and BB see the flop. BB acts last -> IP.
    seats = {"sb": 1, "bb": 2, "btn": 4}
    assert _ip(4, seats, ["sb", "bb"], "bb") is True
    assert _ip(4, seats, ["sb", "bb"], "sb") is False


def test_co_is_ip_when_button_out():
    # 6-max, button seat 6 folded; CO (seat 5) is now last to act -> IP.
    seats = {"utg": 1, "co": 5, "btn": 6, "bb": 3}
    assert _ip(6, seats, ["utg", "bb", "co"], "co") is True
    assert _ip(6, seats, ["utg", "bb", "co"], "utg") is False


def test_lone_player_is_ip():
    seats = {"hero": 2, "x": 4}
    assert _ip(4, seats, ["hero"], "hero") is True


def test_extract_sets_in_position_on_decisions():
    # Full extract: hero on the button checks the flop -> IP decision emitted.
    seats = {"hero": 4, "vil": 6}
    h = _hand(button_seat=4, seats=seats, in_hand=["hero", "vil"], hero_seat=4)
    h.actions = [
        Action(street=Street.FLOP, player="vil", action_type="check", amount_bb=0.0,
               pot_before_bb=4.0),
        Action(street=Street.FLOP, player="hero", action_type="check", amount_bb=0.0,
               pot_before_bb=4.0),
    ]
    decs = extract(h, Config(), Position.BTN)
    assert decs
    assert all(d.in_position is True for d in decs)


def test_phantom_preflop_folder_does_not_flip_hero_to_oop():
    # Regression: a player who folds preflop WITHOUT an emitted `fold` action
    # (e.g. a blind that folds) used to remain a "phantom" contender. If that
    # phantom sits after hero in the postflop order it stole the last-to-act
    # slot, flipping hero IP -> OOP and producing the impossible (OOP,
    # CHECKED_TO) heads-up combo. `phantom` (seat 3, between button-4 and
    # hero-2 in the act-last walk) never acts and has no fold action; hero
    # (seat 2) is heads-up vs `vil` (seat 6) postflop. Postflop the button acts
    # last, so walking back from seat 4 the order is 3, 2, ... -> a counted
    # phantom at seat 3 acts after hero and steals IP. With the fix hero is
    # correctly IP, and a check to hero classifies as CHECKED_TO.
    seats = {"hero": 2, "phantom": 3, "vil": 6}
    h = _hand(button_seat=4, seats=seats, in_hand=["hero", "vil"], hero_seat=2)
    h.actions = [
        # preflop: phantom (seat 3) silently folds — no action emitted for it.
        Action(street=Street.PREFLOP, player="hero", action_type="raise",
               amount_bb=3.0, pot_before_bb=1.5),
        Action(street=Street.PREFLOP, player="vil", action_type="call",
               amount_bb=2.0, pot_before_bb=4.5),
        # flop heads-up: vil checks, hero (acting last = IP) checks behind.
        Action(street=Street.FLOP, player="vil", action_type="check",
               amount_bb=0.0, pot_before_bb=6.5),
        Action(street=Street.FLOP, player="hero", action_type="check",
               amount_bb=0.0, pot_before_bb=6.5),
    ]
    decs = extract(h, Config(), Position.SB)
    assert decs
    assert all(d.in_position is True for d in decs)
    # the flop decision: vil checked to hero -> CHECKED_TO, and IP (not OOP).
    flop = [d for d in decs if d.street == Street.FLOP][0]
    assert flop.in_position is True
    assert flop.action_facing == ActionFacing.CHECKED_TO
