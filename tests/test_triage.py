"""Tests for Module 4 — Triage Analyzer.

All tests construct synthetic NodeProfile objects directly; no dependency on
the adapter/extractor/aggregator.
"""

from __future__ import annotations

import pytest

from mbplumber.config import Config
from mbplumber.models import ActionProfile, NodeProfile
from mbplumber.triage import triage


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def ap(
    action: str,
    count: int,
    frequency: float,
    mean_ev: float = 0.0,
    ci_low: float | None = None,
    ci_high: float | None = None,
) -> ActionProfile:
    return ActionProfile(
        action=action,
        count=count,
        frequency=frequency,
        mean_ev_bb100=mean_ev,
        ev_ci_low=ci_low,
        ev_ci_high=ci_high,
    )


def node(
    *,
    street="FLOP",
    position="BTN",
    pot_type="SRP",
    action_facing="FIRST_TO_ACT",
    total_hands=100,
    profiles: dict[str, ActionProfile],
    dominant="check",
    low_sample=False,
) -> NodeProfile:
    return NodeProfile(
        node_key={
            "street": street,
            "position": position,
            "pot_type": pot_type,
            "action_facing": action_facing,
        },
        total_hands=total_hands,
        action_profiles=profiles,
        dominant_action=dominant,
        low_sample=low_sample,
    )


def find(entries, **node_key_match):
    for e in entries:
        if all(e.node_key.get(k) == v for k, v in node_key_match.items()):
            return e
    raise AssertionError(f"no entry matching {node_key_match}")


# --------------------------------------------------------------------------- #
# Score A — polarization math
# --------------------------------------------------------------------------- #
def test_polarization_fully_polarized_high_anomaly():
    # Single action at freq 1.0 -> polarization 0 -> anomaly 1.0.
    # action_facing chosen so no override flag fires (BET_SMALL but freq high
    # on "call" so HIGH_FOLD does not fire; raise possible but it's FLOP).
    n = node(
        street="FLOP",
        action_facing="BET_SMALL",
        profiles={"call": ap("call", 100, 1.0)},
        dominant="call",
    )
    out = triage([n], Config())
    e = out[0]
    assert e.flags == []
    assert e.score_a == pytest.approx(1.0)


def test_polarization_balanced_zero_anomaly():
    # Two actions each at freq 0.5 -> polarization 1 -> anomaly 0 each -> base 0.
    n = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        profiles={
            "check": ap("check", 50, 0.5),
            "bet_medium": ap("bet_medium", 50, 0.5),
        },
        dominant="check",
    )
    out = triage([n], Config())
    e = out[0]
    assert e.flags == []
    assert e.score_a == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Score A — override flags
# --------------------------------------------------------------------------- #
def test_flag_near_zero_bluff_freq():
    # RIVER, facing a bet, raise freq 0 -> NEAR_ZERO_BLUFF_FREQ, score_a=1.0.
    n = node(
        street="RIVER",
        action_facing="BET_LARGE",
        total_hands=34,
        profiles={
            "fold": ap("fold", 20, 0.59),
            "call": ap("call", 14, 0.41),
        },
        dominant="fold",
    )
    out = triage([n], Config())
    e = out[0]
    assert "NEAR_ZERO_BLUFF_FREQ" in e.flags
    assert e.score_a == pytest.approx(1.0)


def test_flag_high_fold_freq():
    # Facing a bet, fold freq 0.8 > 0.75 -> HIGH_FOLD_FREQ.
    n = node(
        street="TURN",
        action_facing="BET_MEDIUM",
        profiles={
            "fold": ap("fold", 80, 0.8),
            "call": ap("call", 20, 0.2),
        },
        dominant="fold",
    )
    out = triage([n], Config())
    e = out[0]
    assert "HIGH_FOLD_FREQ" in e.flags
    assert e.score_a == pytest.approx(1.0)


def test_flag_high_fold_not_fired_below_threshold():
    n = node(
        street="TURN",
        action_facing="BET_MEDIUM",
        profiles={
            "fold": ap("fold", 70, 0.70),
            "call": ap("call", 30, 0.30),
        },
        dominant="fold",
    )
    out = triage([n], Config())
    assert out[0].flags == []


def test_flag_never_bet():
    # First to act (FIRST_TO_ACT), bet freq 0 -> NEVER_BET.
    n = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        profiles={"check": ap("check", 100, 1.0)},
        dominant="check",
    )
    out = triage([n], Config())
    e = out[0]
    assert "NEVER_BET" in e.flags
    assert e.score_a == pytest.approx(1.0)


def test_multiple_flags_compose():
    # RIVER facing a bet, raise freq 0 AND fold freq 0.8.
    n = node(
        street="RIVER",
        action_facing="BET_LARGE",
        profiles={
            "fold": ap("fold", 80, 0.8),
            "call": ap("call", 20, 0.2),
        },
        dominant="fold",
    )
    out = triage([n], Config())
    e = out[0]
    assert "NEAR_ZERO_BLUFF_FREQ" in e.flags
    assert "HIGH_FOLD_FREQ" in e.flags
    assert e.score_a == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Score B — EV divergence, normalization, gate
# --------------------------------------------------------------------------- #
def test_score_b_gate_blocks_ci_including_zero():
    # Large raw divergence but all CIs include zero -> score_b 0.
    # Use FLOP/FIRST_TO_ACT with a non-zero bet so NEVER_BET doesn't fire and confound.
    gated = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        position="SB",
        profiles={
            "check": ap("check", 50, 0.5, mean_ev=-50, ci_low=-120, ci_high=20),
            "bet_medium": ap("bet_medium", 50, 0.5, mean_ev=50, ci_low=-30, ci_high=130),
        },
        dominant="check",
    )
    # A second node provides a valid (gated-pass) divergence so a ceiling exists.
    valid = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        position="CO",
        profiles={
            "check": ap("check", 50, 0.5, mean_ev=-40, ci_low=-70, ci_high=-10),
            "bet_medium": ap("bet_medium", 50, 0.5, mean_ev=40, ci_low=10, ci_high=70),
        },
        dominant="check",
    )
    out = triage([gated, valid], Config())
    g = find(out, position="SB")
    v = find(out, position="CO")
    assert g.score_b == pytest.approx(0.0)
    assert v.score_b > 0.0


def test_score_b_requires_two_qualifying_actions():
    # Only one action meets min samples -> raw_div 0 -> score_b 0.
    n = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        profiles={
            "check": ap("check", 50, 0.5, mean_ev=-40, ci_low=-70, ci_high=-10),
            "bet_medium": ap("bet_medium", 5, 0.5, mean_ev=60, ci_low=20, ci_high=100),
        },
        dominant="check",
    )
    out = triage([n], Config())
    assert out[0].score_b == pytest.approx(0.0)


def test_score_b_caps_at_one_at_ceiling():
    # Three nodes; node with the largest divergence sits at/above 95th pctile
    # ceiling and must cap at 1.0.
    def ev_node(pos, lo_ev, hi_ev):
        return node(
            street="FLOP",
            action_facing="FIRST_TO_ACT",
            position=pos,
            profiles={
                "check": ap("check", 50, 0.5, mean_ev=lo_ev, ci_low=lo_ev - 20, ci_high=lo_ev + 5),
                "bet_medium": ap("bet_medium", 50, 0.5, mean_ev=hi_ev, ci_low=hi_ev - 5, ci_high=hi_ev + 20),
            },
            dominant="check",
        )

    n_small = ev_node("UTG", -10, 10)   # raw_div 20
    n_mid = ev_node("MP", -30, 30)      # raw_div 60
    n_big = ev_node("CO", -100, 100)    # raw_div 200 (largest)
    out = triage([n_small, n_mid, n_big], Config())
    big = find(out, position="CO")
    assert big.score_b == pytest.approx(1.0)
    # Smaller divergences strictly below 1.0.
    assert find(out, position="UTG").score_b < 1.0


def test_score_b_zero_when_no_divergence_anywhere():
    n = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        profiles={
            "check": ap("check", 50, 0.5, mean_ev=10, ci_low=5, ci_high=15),
            "bet_medium": ap("bet_medium", 50, 0.5, mean_ev=10, ci_low=5, ci_high=15),
        },
        dominant="check",
    )
    out = triage([n], Config())
    assert out[0].score_b == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_ranking_respects_street_weight():
    # Two nodes, identical composite & frequency, different street weight.
    # RIVER (1.5) should outrank FLOP (1.1).
    flop = node(
        street="FLOP",
        action_facing="BET_MEDIUM",
        position="BTN",
        total_hands=100,
        profiles={"fold": ap("fold", 80, 0.8), "call": ap("call", 20, 0.2)},
        dominant="fold",
    )
    river = node(
        street="RIVER",
        action_facing="BET_MEDIUM",
        position="BB",
        total_hands=100,
        profiles={"fold": ap("fold", 80, 0.8), "call": ap("call", 20, 0.2)},
        dominant="fold",
    )
    out = triage([flop, river], Config())
    assert out[0].node_key["street"] == "RIVER"
    assert out[0].rank == 1
    assert out[1].rank == 2


def test_ranking_respects_frequency_in_dataset():
    # Same street & composite; the node with more hands ranks higher.
    big = node(
        street="FLOP",
        action_facing="BET_MEDIUM",
        position="BTN",
        total_hands=300,
        profiles={"fold": ap("fold", 240, 0.8), "call": ap("call", 60, 0.2)},
        dominant="fold",
    )
    small = node(
        street="FLOP",
        action_facing="BET_MEDIUM",
        position="CO",
        total_hands=50,
        profiles={"fold": ap("fold", 40, 0.8), "call": ap("call", 10, 0.2)},
        dominant="fold",
    )
    out = triage([big, small], Config())
    assert out[0].node_key["position"] == "BTN"
    # frequency_in_dataset sums to ~1 over ranked nodes.
    assert sum(e.frequency_in_dataset for e in out) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Low-sample handling
# --------------------------------------------------------------------------- #
def test_low_sample_excluded_by_default():
    keep = node(
        position="BTN",
        profiles={"check": ap("check", 100, 1.0)},
        low_sample=False,
    )
    drop = node(
        position="CO",
        total_hands=5,
        profiles={"check": ap("check", 5, 1.0)},
        low_sample=True,
    )
    out = triage([keep, drop], Config())
    positions = {e.node_key["position"] for e in out}
    assert positions == {"BTN"}


def test_low_sample_included_when_configured():
    cfg = Config()
    cfg.triage.include_low_sample = True
    keep = node(
        position="BTN",
        profiles={"check": ap("check", 100, 1.0)},
        low_sample=False,
    )
    low = node(
        position="CO",
        total_hands=5,
        profiles={"check": ap("check", 5, 1.0)},
        low_sample=True,
    )
    out = triage([keep, low], cfg)
    positions = {e.node_key["position"] for e in out}
    assert positions == {"BTN", "CO"}


def test_empty_input_returns_empty():
    assert triage([], Config()) == []


# --------------------------------------------------------------------------- #
# Hypothesis text
# --------------------------------------------------------------------------- #
def test_hypothesis_high_fold():
    n = node(
        street="RIVER",
        action_facing="BET_LARGE",
        position="BB",
        profiles={"fold": ap("fold", 81, 0.81), "call": ap("call", 19, 0.19)},
        dominant="fold",
    )
    out = triage([n], Config())
    h = out[0].hypothesis
    assert "fold to BET_LARGE" in h
    assert "81%" in h
    assert "BB" in h


def test_hypothesis_near_zero_bluff():
    n = node(
        street="RIVER",
        action_facing="BET_LARGE",
        position="BTN",
        total_hands=34,
        profiles={"fold": ap("fold", 20, 0.59), "call": ap("call", 14, 0.41)},
        dominant="fold",
    )
    out = triage([n], Config())
    h = out[0].hypothesis
    assert "almost never raise the river" in h
    assert "n=34" in h
    assert "solver review" in h


def test_hypothesis_never_bet():
    n = node(
        street="FLOP",
        action_facing="FIRST_TO_ACT",
        position="SB",
        total_hands=60,
        profiles={"check": ap("check", 60, 1.0)},
        dominant="check",
    )
    out = triage([n], Config())
    h = out[0].hypothesis
    assert "never bet when first to act" in h
    assert "FLOP" in h
    assert "n=60" in h


def test_hypothesis_ev_divergence_driven():
    # No override flag, but a meaningful EV gap -> EV-divergence hypothesis.
    n = node(
        street="FLOP",
        action_facing="BET_LARGE",
        position="CO",
        profiles={
            "fold": ap("fold", 41, 0.59, mean_ev=-8, ci_low=-15, ci_high=-1),
            "call": ap("call", 28, 0.41, mean_ev=-42, ci_low=-60, ci_high=-24),
        },
        dominant="fold",
    )
    out = triage([n], Config())
    e = out[0]
    assert e.flags == []
    assert e.score_b > 0.0
    h = e.hypothesis
    assert "BB/100" in h
    assert "EV gap" in h
    assert "call" in h and "fold" in h
