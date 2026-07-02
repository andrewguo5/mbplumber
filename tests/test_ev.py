"""Tests for the per-decision realized-EV model (mbplumber.features.ev)."""

import pytest

from mbplumber.features.ev import decision_ev


def ev(**kw):
    base = dict(
        pot_before_bb=10.0,
        hero_commit_bb=0.0,
        villain_response_bb=0.0,
        is_fold=False,
        hero_won=False,
    )
    base.update(kw)
    return decision_ev(**base)


def test_fold_is_zero():
    assert ev(is_fold=True, hero_won=False) == 0.0
    # Even a (nonsensical) folded-and-won is 0: a folding hero never wins.
    assert ev(is_fold=True, hero_won=True) == 0.0


def test_check_win_is_pot_before():
    assert ev(hero_commit_bb=0.0, hero_won=True) == 10.0


def test_check_lose_is_zero():
    assert ev(hero_commit_bb=0.0, hero_won=False) == 0.0


def test_call_win_is_pot_before():
    # Calling 7 into a pot of 10 and winning: collect pot, call nets out -> +P.
    assert ev(hero_commit_bb=7.0, hero_won=True) == 10.0


def test_call_lose_is_negative_call():
    assert ev(hero_commit_bb=7.0, hero_won=False) == -7.0


def test_bet_fold_is_pot_before_not_inflated():
    # Bet 7, villain folds (no response), hero wins the pre-existing pot.
    # MUST equal a check-win (+P), so inducing a fold does not inflate EV.
    bet_fold = ev(hero_commit_bb=7.0, villain_response_bb=0.0, hero_won=True)
    check_win = ev(hero_commit_bb=0.0, hero_won=True)
    assert bet_fold == check_win == 10.0


def test_bet_called_win_adds_extraction():
    # Bet 7, called 7, win: pot plus the matched chips.
    assert ev(hero_commit_bb=7.0, villain_response_bb=7.0, hero_won=True) == 17.0


def test_bet_called_lose_is_negative_bet():
    assert ev(hero_commit_bb=7.0, villain_response_bb=7.0, hero_won=False) == -7.0


def test_allin_equity_blends_win_and_lose():
    # eq=0.4 on bet 7 called 7: 0.4*(10+7) + 0.6*(-7) = 6.8 - 4.2 = 2.6
    val = ev(
        hero_commit_bb=7.0,
        villain_response_bb=7.0,
        hero_won=False,
        equity_override=0.4,
    )
    assert val == pytest.approx(2.6)


def test_allin_equity_clamped():
    # Out-of-range equity is clamped to [0,1].
    assert ev(hero_commit_bb=7.0, villain_response_bb=7.0, equity_override=2.0) == 17.0
    assert ev(hero_commit_bb=7.0, villain_response_bb=7.0, equity_override=-1.0) == -7.0
