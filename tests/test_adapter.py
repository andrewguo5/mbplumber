"""Tests for the ACR ParsedHand JSONL v2 adapter (Unit A).

Validation anchors verified against a real 5369-hand export (an ``mbhud export``
of the maintainer's history). Point ``MBPLUMBER_TEST_HANDS`` at your own export
to run these; otherwise they skip cleanly. Anchors:

* parsed == 5369, parse_failures == 0
* reaches_flop == True for exactly 2866 hands
* exactly 386 actions across all hands have is_all_in == True
* pot_type distribution: SRP 3324, LIMP 1220, 3BP 694, 4BP 131
* hand 2661500157: hero is all-in with QQ and loses, hero_net_bb == -92.0
* hand 2658681643: hero wins the blinds uncontested, hero_net_bb == +0.5

Note on the raise `amount` field: it does NOT equal the incremental chips
the player added (verified -- 103 raises mismatch, all caused by dead
ante/blind chips and the "raise-by" convention). The adapter therefore
derives the increment from `total_bet` minus the player's own prior
street contribution.
"""

from __future__ import annotations

import copy
import os
from collections import Counter
from pathlib import Path

import pytest

from mbplumber.adapter.acr_jsonl import adapt_hand, iter_hands, load_dir
from mbplumber.models import Hand, PotType, Street

# The dataset-anchored assertions below need a real export. Set
# MBPLUMBER_TEST_HANDS to your export's hands/ directory to run them; with no
# such env var they fall back to mbHUD's default export location and, if that
# is absent too, skip cleanly (see the `loaded` fixture). No path is hardcoded.
HANDS_DIR = Path(
    os.environ.get(
        "MBPLUMBER_TEST_HANDS", str(Path.home() / "PokerData" / "hands")
    )
)
HERO = "aampersands"

# Anchor hand ids discovered with a one-off scan against the real data.
QQ_ALLIN_LOSS_HAND = "2661500157"
UNCONTESTED_WIN_HAND = "2658681643"


# --------------------------------------------------------------------------- #
# Dataset-level fixtures (loaded once, shared across tests)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def loaded():
    if not HANDS_DIR.is_dir():
        pytest.skip(f"dataset not available at {HANDS_DIR}")
    hands, stats = load_dir(HANDS_DIR)
    return hands, stats


@pytest.fixture(scope="module")
def by_id(loaded):
    hands, _ = loaded
    return {h.hand_id: h for h in hands}


# --------------------------------------------------------------------------- #
# Dataset-wide validation anchors
# --------------------------------------------------------------------------- #
def test_load_counts(loaded):
    _, stats = loaded
    assert stats["total_lines"] == 5369
    assert stats["parsed"] == 5369
    assert stats["parse_failures"] == 0


def test_reaches_flop_count(loaded):
    hands, _ = loaded
    assert sum(1 for h in hands if h.reaches_flop) == 2866


def test_all_in_action_count(loaded):
    hands, _ = loaded
    n = sum(1 for h in hands for a in h.actions if a.is_all_in)
    assert n == 386


def test_pot_type_distribution(loaded):
    hands, _ = loaded
    counts = Counter(h.pot_type for h in hands)
    assert counts[PotType.SRP] == 3324
    assert counts[PotType.LIMP] == 1220
    assert counts[PotType.THREE_BET] == 694
    assert counts[PotType.FOUR_BET] == 131
    # all hands classified
    assert sum(counts.values()) == 5369


# --------------------------------------------------------------------------- #
# hero_net_bb anchors
# --------------------------------------------------------------------------- #
def test_qq_allin_loss_net(by_id):
    h = by_id[QQ_ALLIN_LOSS_HAND]
    # hero holds QQ
    ranks = sorted(c[0] for c in h.hero_hole_cards)
    assert ranks == ["Q", "Q"]
    # hero went all-in
    assert any(a.player == HERO and a.is_all_in for a in h.actions)
    # and lost ~92 BB
    assert h.hero_net_bb == pytest.approx(-92.0, abs=1.0)


def test_uncontested_win_net(by_id):
    # Hero posts the BB (0.1), both opponents fold, hero wins 0.15.
    # net = (0.15 - 0.10) / 0.10 = +0.5 BB.
    h = by_id[UNCONTESTED_WIN_HAND]
    assert h.hero_net_bb == pytest.approx(0.5, abs=1e-6)
    assert not h.reaches_flop
    assert h.pot_type == PotType.LIMP


# --------------------------------------------------------------------------- #
# Per-hand structural correctness (unit-level, no dataset dependency)
# --------------------------------------------------------------------------- #
RAW_SRP_HAND = {
    "metadata": {
        "hand_id": "2658681752",
        "hand_datetime": "2026/01/30 16:36:11 UTC",
        "table_name": "South Beloit",
        "max_seats": 6,
        "button_seat": 6,
        "small_blind": 0.05,
        "big_blind": 0.1,
        "players": {"2": "aampersands", "4": "alwayswnuts", "6": "Fise"},
        "stacks": {"aampersands": 10.05, "alwayswnuts": 10.0, "Fise": 17.53},
        "positions": {"aampersands": "BB", "alwayswnuts": "BTN-2", "Fise": "BTN"},
    },
    "streets": {
        "preflop": {
            "name": "preflop",
            "actions": [
                {"player": "aampersands", "action_type": "post_sb", "amount": 0.05, "total_bet": None, "is_all_in": False},
                {"player": "alwayswnuts", "action_type": "post_bb", "amount": 0.1, "total_bet": None, "is_all_in": False},
                {"player": "Fise", "action_type": "raise", "amount": 0.3, "total_bet": 0.3, "is_all_in": False},
                {"player": "aampersands", "action_type": "raise", "amount": 0.65, "total_bet": 0.7, "is_all_in": False},
                {"player": "alwayswnuts", "action_type": "fold", "amount": None, "total_bet": None, "is_all_in": False},
                {"player": "Fise", "action_type": "call", "amount": 0.4, "total_bet": None, "is_all_in": False},
            ],
            "board_cards": None,
        },
        "flop": {
            "name": "flop",
            "actions": [
                {"player": "aampersands", "action_type": "check", "amount": None, "total_bet": None, "is_all_in": False},
                {"player": "Fise", "action_type": "bet", "amount": 0.71, "total_bet": None, "is_all_in": False},
                {"player": "aampersands", "action_type": "call", "amount": 0.71, "total_bet": None, "is_all_in": False},
            ],
            "board_cards": ["9c", "9d", "Jh"],
        },
        "turn": {
            "name": "turn",
            "actions": [
                {"player": "aampersands", "action_type": "check", "amount": None, "total_bet": None, "is_all_in": False},
                {"player": "Fise", "action_type": "check", "amount": None, "total_bet": None, "is_all_in": False},
            ],
            "board_cards": ["9c", "9d", "Jh", "5s"],
        },
        "river": {
            "name": "river",
            "actions": [
                {"player": "aampersands", "action_type": "bet", "amount": 1.46, "total_bet": None, "is_all_in": False},
                {"player": "Fise", "action_type": "fold", "amount": None, "total_bet": None, "is_all_in": False},
                {"player": "aampersands", "action_type": "receive", "amount": 1.46, "total_bet": None, "is_all_in": False},
                {"player": "aampersands", "action_type": "win", "amount": 2.78, "total_bet": None, "is_all_in": False},
            ],
            "board_cards": ["9c", "9d", "Jh", "5s", "8d"],
        },
    },
    "hole_cards": {"aampersands": ["Td", "Js"]},
    "total_pot": 2.78,
    "rake": 0.1,
    "hero": "aampersands",
    "hero_seat": 2,
}


def test_adapt_hand_basic_fields():
    h = adapt_hand(RAW_SRP_HAND)
    assert isinstance(h, Hand)
    assert h.hand_id == "2658681752"
    assert h.big_blind == 0.1
    assert h.hero_seat == 2
    assert h.button_seat == 6
    assert h.date.year == 2026 and h.date.hour == 16 and h.date.minute == 36
    # players sorted by seat, stacks normalized to BB
    assert [p.seat for p in h.players] == [2, 4, 6]
    assert h.players[0].name == "aampersands"
    assert h.players[0].stack_bb == pytest.approx(100.5)


def test_adapt_hand_payouts_dropped_from_actions():
    h = adapt_hand(RAW_SRP_HAND)
    assert all(a.action_type in {"fold", "check", "call", "bet", "raise", "post"} for a in h.actions)
    assert not any(a.action_type in {"win", "receive"} for a in h.actions)


def test_adapt_hand_posts_flagged_and_normalized():
    h = adapt_hand(RAW_SRP_HAND)
    posts = [a for a in h.actions if a.is_post]
    assert len(posts) == 2
    assert all(a.action_type == "post" for a in posts)
    # SB post = 0.05 chips = 0.5 BB
    assert posts[0].amount_bb == pytest.approx(0.5)


def test_adapt_hand_raise_increment_from_total_bet():
    h = adapt_hand(RAW_SRP_HAND)
    pre = [a for a in h.actions if a.street == Street.PREFLOP]
    # Fise raises to 0.3 (prior 0) -> increment 0.3 chips = 3 BB
    fise_raise = next(a for a in pre if a.player == "Fise" and a.action_type == "raise")
    assert fise_raise.amount_bb == pytest.approx(3.0)
    # Hero (posted SB 0.05) raises to total 0.7 -> increment 0.65 chips = 6.5 BB
    hero_raise = next(a for a in pre if a.player == "aampersands" and a.action_type == "raise")
    assert hero_raise.amount_bb == pytest.approx(6.5)


def test_adapt_hand_pot_accumulator_chronological():
    h = adapt_hand(RAW_SRP_HAND)
    # First action (SB post) sees an empty pot.
    assert h.actions[0].pot_before_bb == pytest.approx(0.0)
    # Second action (BB post) sees the SB already in: 0.5 BB.
    assert h.actions[1].pot_before_bb == pytest.approx(0.5)
    # Third action (Fise raise) sees SB+BB = 1.5 BB.
    assert h.actions[2].pot_before_bb == pytest.approx(1.5)


def test_adapt_hand_board_and_reaches_flop():
    h = adapt_hand(RAW_SRP_HAND)
    assert h.reaches_flop is True
    # Deepest street is the river -> full 5-card board.
    assert h.board == ["9c", "9d", "Jh", "5s", "8d"]


def test_adapt_hand_pot_type_srp():
    # Two preflop raises -> 3BP.
    h = adapt_hand(RAW_SRP_HAND)
    assert h.pot_type == PotType.THREE_BET


def test_adapt_hand_hole_cards():
    h = adapt_hand(RAW_SRP_HAND)
    assert h.hero_hole_cards == ["Td", "Js"]
    assert h.all_hole_cards == {"aampersands": ["Td", "Js"]}


def test_adapt_hand_hero_net():
    # Hero invested: SB 0.05 + raise increment 0.65 + flop call 0.71 + river bet 1.46
    #              = 2.87 chips.
    # Hero payout: receive 1.46 + win 2.78 = 4.24 chips.
    # net = (4.24 - 2.87) / 0.1 = 13.7 BB.
    h = adapt_hand(RAW_SRP_HAND)
    assert h.hero_net_bb == pytest.approx(13.7, abs=1e-6)


# --------------------------------------------------------------------------- #
# Robustness: bad lines are skipped, never crash
# --------------------------------------------------------------------------- #
def test_iter_hands_skips_bad_lines(tmp_path):
    good = (
        '{"metadata": {"hand_id": "1", "hand_datetime": "2026/01/30 16:35:59 UTC", '
        '"table_name": "T", "max_seats": 6, "button_seat": 4, "small_blind": 0.05, '
        '"big_blind": 0.1, "players": {"2": "aampersands"}, '
        '"stacks": {"aampersands": 10.0}, "positions": {"aampersands": "BB"}}, '
        '"streets": {"preflop": {"name": "preflop", "actions": [], "board_cards": null}}, '
        '"hole_cards": {"aampersands": ["As", "Kd"]}, "total_pot": 0.0, "rake": 0.0, '
        '"hero": "aampersands", "hero_seat": 2}'
    )
    p = tmp_path / "mixed.jsonl"
    p.write_text(
        good + "\n"
        + "this is not json\n"
        + "\n"  # blank line ignored
        + '{"metadata": {"oops": true}}\n'  # valid json, bad schema
        + good + "\n"
    )
    hands = list(iter_hands(p))
    assert len(hands) == 2
    assert all(h.hand_id == "1" for h in hands)


def test_load_dir_counts_failures(tmp_path):
    (tmp_path / "a.jsonl").write_text("not json\n{}\n")
    hands, stats = load_dir(tmp_path)
    assert stats["total_lines"] == 2
    assert stats["parsed"] == 0
    assert stats["parse_failures"] == 2


def test_adapt_hand_null_hero_seat_becomes_none():
    """Schema-legal `hero_seat: null` (hero not dealt in) must adapt to None,
    not crash on int(None). Regression guard for issue #3."""
    raw = copy.deepcopy(RAW_SRP_HAND)
    raw["hero_seat"] = None
    h = adapt_hand(raw)
    assert h.hero_seat is None


def test_pipeline_skips_hero_absent_hand(tmp_path):
    """A hero-absent hand yields no hero decisions and is skipped explicitly,
    counted under the `no_hero` stat rather than raising. Regression for #3."""
    import json

    from mbplumber.config import Config
    from mbplumber.pipeline import build_decisions

    raw = copy.deepcopy(RAW_SRP_HAND)
    raw["hero_seat"] = None
    (tmp_path / "s.jsonl").write_text(json.dumps(raw) + "\n", encoding="utf-8")

    decisions, hands, stats = build_decisions(tmp_path, Config())
    assert stats["parsed"] == 1
    assert stats["no_hero"] == 1
    assert stats["reached_flop"] == 0  # skipped before the flop check
    assert decisions == []
    assert hands == {}
