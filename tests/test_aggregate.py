"""Tests for Module 3 — Node Aggregator (aggregate.py)."""

from __future__ import annotations

import math

from mbplumber.aggregate import aggregate
from mbplumber.config import AggregationConfig, Config
from mbplumber.models import (
    ActionFacing,
    ActionTaken,
    BoardTexture,
    Color,
    Connectedness,
    Decision,
    FlopArchetype,
    Position,
    PotSizeBucket,
    PotType,
    StackDepthBucket,
    Street,
    TopCard,
)


def make_decision(
    *,
    action: ActionTaken = ActionTaken.BET_SMALL,
    ev_bb: float = 1.0,
    street: Street = Street.FLOP,
    position: Position = Position.BTN,
    in_position: bool = True,
    pot_type: PotType = PotType.SRP,
    action_facing: ActionFacing = ActionFacing.FIRST_TO_ACT,
    flop_archetype: FlopArchetype = FlopArchetype.TOP_PAIR,
    hand_id: str = "h",
) -> Decision:
    """Construct a valid Decision with simple defaults; override per test."""
    return Decision(
        hand_id=hand_id,
        street=street,
        position=position,
        in_position=in_position,
        pot_type=pot_type,
        action_facing=action_facing,
        pot_size_bb=10.0,
        stack_depth_bb=100.0,
        pot_size_bucket=PotSizeBucket.MEDIUM,
        stack_depth_bucket=StackDepthBucket.DEEP,
        num_players_in_hand=2,
        flop_archetype=flop_archetype,
        board_texture=BoardTexture(
            color=Color.RAINBOW,
            connectedness=Connectedness.DISCONNECTED,
            paired=False,
            top_card=TopCard.HIGH,
            kernel_score=0,
        ),
        hero_action_taken=action,
        hero_realized_ev_bb=ev_bb,
    )


def test_frequencies_sum_to_one():
    decisions = (
        [make_decision(action=ActionTaken.BET_SMALL) for _ in range(7)]
        + [make_decision(action=ActionTaken.CHECK) for _ in range(3)]
    )
    profiles = aggregate(decisions, Config())
    assert len(profiles) == 1
    node = profiles[0]
    total_freq = sum(ap.frequency for ap in node.action_profiles.values())
    assert math.isclose(total_freq, 1.0, abs_tol=1e-9)
    assert node.total_hands == 10


def test_mean_ev_scaling():
    decisions = [make_decision(ev_bb=-0.42) for _ in range(5)]
    profiles = aggregate(decisions, Config())
    ap = profiles[0].action_profiles[ActionTaken.BET_SMALL.value]
    assert math.isclose(ap.mean_ev_bb100, -42.0, abs_tol=1e-9)


def test_ci_none_below_min_n():
    # 9 < bootstrap_min_n (default 10) -> no CI, low_confidence.
    decisions = [make_decision(ev_bb=2.0) for _ in range(9)]
    profiles = aggregate(decisions, Config())
    ap = profiles[0].action_profiles[ActionTaken.BET_SMALL.value]
    assert ap.count == 9
    assert ap.ev_ci_low is None
    assert ap.ev_ci_high is None
    assert ap.low_confidence is True


def test_ci_present_and_brackets_mean_above_min_n():
    # 30 >= bootstrap_min_n -> CI present, brackets mean, not low_confidence.
    evs = [float(i % 5) for i in range(30)]  # spread so CI is non-degenerate
    decisions = [make_decision(ev_bb=ev) for ev in evs]
    profiles = aggregate(decisions, Config())
    ap = profiles[0].action_profiles[ActionTaken.BET_SMALL.value]
    assert ap.count == 30
    assert ap.low_confidence is False
    assert ap.ev_ci_low is not None
    assert ap.ev_ci_high is not None
    assert ap.ev_ci_low <= ap.mean_ev_bb100 <= ap.ev_ci_high


def test_determinism():
    evs = [float(i % 7) - 3.0 for i in range(40)]
    decisions = [make_decision(ev_bb=ev) for ev in evs]
    config = Config()
    p1 = aggregate(decisions, config)
    p2 = aggregate(decisions, config)
    ap1 = p1[0].action_profiles[ActionTaken.BET_SMALL.value]
    ap2 = p2[0].action_profiles[ActionTaken.BET_SMALL.value]
    assert ap1.ev_ci_low == ap2.ev_ci_low
    assert ap1.ev_ci_high == ap2.ev_ci_high


def test_low_sample_flag_at_threshold():
    # Default low_sample_threshold = 15. 14 -> True, 15 -> False.
    fourteen = [make_decision() for _ in range(14)]
    fifteen = [make_decision() for _ in range(15)]
    assert aggregate(fourteen, Config())[0].low_sample is True
    assert aggregate(fifteen, Config())[0].low_sample is False


def test_node_key_default_dimensions():
    profiles = aggregate([make_decision()], Config())
    key = profiles[0].node_key
    assert set(key.keys()) == {"street", "in_position", "pot_type", "action_facing"}
    assert key == {
        "street": "FLOP",
        "in_position": "IP",
        "pot_type": "SRP",
        "action_facing": "FIRST_TO_ACT",
    }


def test_position_optional_dimension():
    # The 6-way seat name is available as an opt-in dimension.
    config = Config(optional_dimensions={"position": True})
    key = aggregate([make_decision()], config)[0].node_key
    assert key["position"] == "BTN"
    assert key["in_position"] == "IP"


def test_in_position_splits_nodes():
    decisions = [
        make_decision(in_position=True),
        make_decision(in_position=True),
        make_decision(in_position=False),
    ]
    profiles = aggregate(decisions, Config())
    assert len(profiles) == 2
    assert {n.node_key["in_position"] for n in profiles} == {"IP", "OOP"}


def test_optional_dimension_splits_nodes():
    config = Config(optional_dimensions={"flop_archetype": True})
    decisions = [
        make_decision(flop_archetype=FlopArchetype.TOP_PAIR),
        make_decision(flop_archetype=FlopArchetype.TOP_PAIR),
        make_decision(flop_archetype=FlopArchetype.AIR),
    ]
    profiles = aggregate(decisions, config)
    # Two distinct flop_archetype values -> two nodes.
    assert len(profiles) == 2
    for node in profiles:
        assert "flop_archetype" in node.node_key
    archetypes = {node.node_key["flop_archetype"] for node in profiles}
    assert archetypes == {"TOP_PAIR", "AIR"}


def test_dominant_action():
    decisions = (
        [make_decision(action=ActionTaken.BET_SMALL) for _ in range(6)]
        + [make_decision(action=ActionTaken.CHECK) for _ in range(2)]
        + [make_decision(action=ActionTaken.CALL) for _ in range(2)]
    )
    profiles = aggregate(decisions, Config())
    assert profiles[0].dominant_action == ActionTaken.BET_SMALL.value


def test_dominant_action_tie_break_lexicographic():
    # Equal counts (5 each) for "call" and "check" -> lexicographically smallest.
    decisions = (
        [make_decision(action=ActionTaken.CHECK) for _ in range(5)]
        + [make_decision(action=ActionTaken.CALL) for _ in range(5)]
    )
    profiles = aggregate(decisions, Config())
    # "call" < "check" lexicographically.
    assert profiles[0].dominant_action == "call"


def test_custom_bootstrap_min_n():
    config = Config(aggregation=AggregationConfig(bootstrap_min_n=5))
    decisions = [make_decision(ev_bb=float(i)) for i in range(6)]
    profiles = aggregate(decisions, config)
    ap = profiles[0].action_profiles[ActionTaken.BET_SMALL.value]
    assert ap.low_confidence is False
    assert ap.ev_ci_low is not None
