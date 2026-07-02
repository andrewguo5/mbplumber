"""Module 3 — Node Aggregator.

Groups Decision records by node key (the active node dimensions from config),
and for each node computes an ActionProfile per distinct hero action, including
a bootstrap confidence interval on realized EV.

Determinism / seeding approach
------------------------------
A single ``numpy.random.default_rng`` Generator is created ONCE per
``aggregate()`` call, seeded from ``config.aggregation.rng_seed``. All bootstrap
resampling for every node and every action draws from that one Generator in a
fixed, deterministic order: nodes are processed in sorted node-key order and,
within a node, actions are processed in sorted action-string order. Because the
Generator advances deterministically and the iteration order is stable, two
runs on the same input produce byte-identical CI bounds.

Tie-break for dominant_action
------------------------------
The dominant action is the action with the highest frequency. Ties are broken
deterministically by: highest count first (equivalent to highest frequency
since total_hands is shared), then the lexicographically smallest action string.
"""

from __future__ import annotations

import numpy as np

from .config import Config
from .models import ActionProfile, Decision, NodeProfile

# Maps each active-dimension name to a function extracting its string value
# from a Decision. Kept module-level so the contract is explicit and testable.
_DIMENSION_GETTERS = {
    "street": lambda d: d.street.value,
    "position": lambda d: d.position.value,
    "in_position": lambda d: "IP" if d.in_position else "OOP",
    "pot_type": lambda d: d.pot_type.value,
    "action_facing": lambda d: d.action_facing.value,
    "pot_size_bucket": lambda d: d.pot_size_bucket.value,
    "stack_depth_bucket": lambda d: d.stack_depth_bucket.value,
    "flop_archetype": lambda d: d.flop_archetype.value,
    "board_color": lambda d: d.board_texture.color.value,
    "board_connectedness": lambda d: d.board_texture.connectedness.value,
    "board_paired": lambda d: str(d.board_texture.paired),
    "board_top_card": lambda d: d.board_texture.top_card.value,
    "num_players_in_hand": lambda d: str(d.num_players_in_hand),
}


def _node_key(decision: Decision, dimensions: list[str]) -> dict[str, str]:
    """Build the node-key dict for a decision over the active dimensions."""
    return {dim: _DIMENSION_GETTERS[dim](decision) for dim in dimensions}


def aggregate(decisions: list[Decision], config: Config) -> list[NodeProfile]:
    """Aggregate Decision records into NodeProfiles.

    See module docstring for seeding and tie-break semantics.
    """
    agg = config.aggregation
    dimensions = config.active_dimensions()

    # One Generator per call -> reproducible across runs.
    rng = np.random.default_rng(agg.rng_seed)

    # Group decisions by the ordered tuple of dimension values.
    groups: dict[tuple[str, ...], list[Decision]] = {}
    for decision in decisions:
        key = tuple(_DIMENSION_GETTERS[dim](decision) for dim in dimensions)
        groups.setdefault(key, []).append(decision)

    profiles: list[NodeProfile] = []

    # Sorted node order makes RNG consumption deterministic.
    for key in sorted(groups.keys()):
        node_decisions = groups[key]
        total_hands = len(node_decisions)
        node_key = dict(zip(dimensions, key))

        # Bucket EVs (in BB) by action string.
        evs_by_action: dict[str, list[float]] = {}
        for d in node_decisions:
            evs_by_action.setdefault(d.hero_action_taken.value, []).append(
                d.hero_realized_ev_bb
            )

        action_profiles: dict[str, ActionProfile] = {}
        # Sorted action order -> deterministic RNG consumption within a node.
        for action in sorted(evs_by_action.keys()):
            evs = np.asarray(evs_by_action[action], dtype=float)
            count = len(evs)
            frequency = count / total_hands
            mean_ev_bb100 = float(evs.mean()) * 100.0

            if count >= agg.bootstrap_min_n:
                # Resample WITH REPLACEMENT, take the mean of each resample.
                resample_idx = rng.integers(
                    0, count, size=(agg.bootstrap_resamples, count)
                )
                resample_means = evs[resample_idx].mean(axis=1)
                ci_low = float(np.percentile(resample_means, 2.5)) * 100.0
                ci_high = float(np.percentile(resample_means, 97.5)) * 100.0
                low_confidence = False
            else:
                ci_low = None
                ci_high = None
                low_confidence = True

            action_profiles[action] = ActionProfile(
                action=action,
                count=count,
                frequency=frequency,
                mean_ev_bb100=mean_ev_bb100,
                ev_ci_low=ci_low,
                ev_ci_high=ci_high,
                low_confidence=low_confidence,
            )

        # dominant_action: highest count, then lexicographically smallest action.
        dominant_action = min(
            action_profiles.values(),
            key=lambda ap: (-ap.count, ap.action),
        ).action

        profiles.append(
            NodeProfile(
                node_key=node_key,
                total_hands=total_hands,
                action_profiles=action_profiles,
                dominant_action=dominant_action,
                low_sample=total_hands < agg.low_sample_threshold,
            )
        )

    return profiles
