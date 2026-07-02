"""Module 4 — Triage Analyzer.

Scores each NodeProfile for leak likelihood using a frequency-anomaly signal
(Score A) and a realized-EV-divergence signal (Score B), combines them into a
composite, applies a priority multiplier (dataset frequency x street weight),
ranks the nodes, and emits a templated plain-English hypothesis per node.

This module depends only on the shared data contract in ``models.py`` and the
``Config`` in ``config.py``. It is tested against synthetic ``NodeProfile``
lists constructed directly.

Design decisions worth calling out
-----------------------------------
"raise possible" (Score A river-raise flag): v1 treats a raise as possible at a
node when hero is facing a bet or raise, i.e. ``node_key['action_facing']`` is
one of the BET_* / RAISE_* / DONK_BET values. (Hero cannot raise when first to
act / facing a check.)

CI gate (Score B): a node's raw divergence is only counted if at least one of
the qualifying actions (count >= ev_divergence_min_samples_per_action) has a
95% CI that excludes zero — both ``ev_ci_low`` and ``ev_ci_high`` present and
the interval not straddling 0 (``ev_ci_low > 0`` or ``ev_ci_high < 0``).

frequency_in_dataset denominator: the sum of ``total_hands`` over the nodes
actually being ranked (after the low-sample filter is applied), so frequencies
sum to 1.0 over the produced report.
"""

from __future__ import annotations

import numpy as np

from .config import Config
from .models import NodeProfile, TriageEntry

# action_facing values that mean hero is facing a bet/raise (so hero could
# raise, and "fold facing a bet" is meaningful).
_FACING_BET = {
    "BET_SMALL",
    "BET_MEDIUM",
    "BET_LARGE",
    "BET_OVERBET",
    "RAISE_SMALL",
    "RAISE_MEDIUM",
    "RAISE_LARGE",
    "RAISE_OVERBET",
    "DONK_BET",
}

# Facings where hero has the option to bet (no outstanding bet to call).
_FACING_CAN_OPEN = {"FIRST_TO_ACT", "CHECKED_TO"}


def _polarization(f: float) -> float:
    return 4.0 * f * (1.0 - f)


def _sum_freq(node: NodeProfile, prefix: str) -> float:
    return sum(
        ap.frequency for key, ap in node.action_profiles.items() if key.startswith(prefix)
    )


def _compute_score_a(node: NodeProfile, config: Config) -> tuple[float, list[str]]:
    """Return (score_a, flags).

    Base score is the mean per-action frequency anomaly (1 - polarization).
    Override flags set score_a to 1.0 and append the matching flag string.
    """
    profiles = node.action_profiles
    if profiles:
        anomalies = [1.0 - _polarization(ap.frequency) for ap in profiles.values()]
        base = sum(anomalies) / len(anomalies)
    else:
        base = 0.0

    flags: list[str] = []
    flag_cfg = config.triage.flags
    street = node.node_key.get("street")
    facing = node.node_key.get("action_facing")
    facing_bet = facing in _FACING_BET

    # River raise too rare (near-zero bluff frequency).
    if street == "RIVER" and facing_bet:
        raise_freq = _sum_freq(node, "raise_")
        if raise_freq < flag_cfg.river_raise_max_freq:
            flags.append("NEAR_ZERO_BLUFF_FREQ")

    # High fold facing a bet/raise.
    if facing_bet:
        fold_freq = profiles["fold"].frequency if "fold" in profiles else 0.0
        if fold_freq > flag_cfg.fold_to_bet_max_freq:
            flags.append("HIGH_FOLD_FREQ")

    # Never betting when hero has the option (first to act, or checked to).
    if flag_cfg.never_bet_first_to_act and facing in _FACING_CAN_OPEN:
        bet_freq = _sum_freq(node, "bet_")
        if bet_freq == 0.0:
            flags.append("NEVER_BET")

    score_a = 1.0 if flags else base
    return score_a, flags


def _raw_divergence(node: NodeProfile, config: Config) -> float:
    """Pass 1 raw EV divergence for a node, with the CI gate applied."""
    min_n = config.triage.ev_divergence_min_samples_per_action
    qualifying = [ap for ap in node.action_profiles.values() if ap.count >= min_n]
    if len(qualifying) < 2:
        return 0.0

    evs = [ap.mean_ev_bb100 for ap in qualifying]
    raw_div = max(evs) - min(evs)

    # Gate: at least one qualifying action's CI must exclude zero.
    gate = any(
        ap.ev_ci_low is not None
        and ap.ev_ci_high is not None
        and (ap.ev_ci_low > 0 or ap.ev_ci_high < 0)
        for ap in qualifying
    )
    return raw_div if gate else 0.0


def _hypothesis(node: NodeProfile, flags: list[str], score_b: float, raw_div: float) -> str:
    nk = node.node_key
    facing = nk.get("action_facing", "")
    # Prefer the 6-way seat name if present; otherwise describe IP/OOP.
    if nk.get("position"):
        position = nk["position"]
    elif "in_position" in nk:
        position = "in position" if nk["in_position"] == "IP" else "out of position"
    else:
        position = ""
    street = nk.get("street", "")
    pot_type = nk.get("pot_type", "")
    profiles = node.action_profiles
    total = node.total_hands

    # Natural-language phrase for the spot, since FIRST_TO_ACT / CHECKED_TO are
    # not things you "face".
    if facing == "FIRST_TO_ACT":
        facing_phrase = "first to act"
    elif facing == "CHECKED_TO":
        facing_phrase = "checked to"
    else:
        facing_phrase = f"facing {facing}"

    sentences: list[str] = []

    if "HIGH_FOLD_FREQ" in flags:
        fold_freq = profiles["fold"].frequency if "fold" in profiles else 0.0
        sentences.append(
            f"You fold to {facing} {fold_freq:.0%} of the time from {position} "
            f"({street}, {pot_type}). This is likely too high; consider whether your "
            f"continuing range is wide enough."
        )

    if "NEAR_ZERO_BLUFF_FREQ" in flags:
        raise_freq = _sum_freq(node, "raise_")
        sentences.append(
            f"You almost never raise the river facing {facing} from {position} "
            f"(raise freq {raise_freq:.0%}, n={total}). This spot warrants solver review."
        )

    if "NEVER_BET" in flags:
        spot = "checked to" if nk.get("action_facing") == "CHECKED_TO" else "first to act"
        sentences.append(
            f"You never bet when {spot} on the {street} from {position} "
            f"({pot_type}, n={total}). Check the right betting frequency in a solver."
        )

    # EV-divergence-driven hypothesis (no override flag but meaningful gap).
    if not flags and score_b > 0.0 and raw_div > 0.0:
        # Identify best/worst action among those carrying the divergence.
        items = list(profiles.items())
        best = max(items, key=lambda kv: kv[1].mean_ev_bb100)
        worst = min(items, key=lambda kv: kv[1].mean_ev_bb100)
        sentences.append(
            f"{worst[0]} returns {worst[1].mean_ev_bb100:.0f} BB/100 vs {best[0]} at "
            f"{best[1].mean_ev_bb100:.0f} BB/100 ({street}, {position}, {facing_phrase}). "
            f"The EV gap suggests a leak in this spot."
        )

    if not sentences:
        sentences.append(
            f"No strong leak signal at this node ({street}, {position}, {pot_type}, "
            f"{facing_phrase}, n={total})."
        )

    return " ".join(sentences)


def triage(nodes: list[NodeProfile], config: Config) -> list[TriageEntry]:
    """Score, rank, and produce a triage report from a list of NodeProfiles."""
    tri = config.triage

    # Low-sample filtering decides which nodes get ranked.
    if tri.include_low_sample:
        ranked_nodes = list(nodes)
    else:
        ranked_nodes = [n for n in nodes if not n.low_sample]

    if not ranked_nodes:
        return []

    # Score A and raw divergence (Pass 1) per node.
    score_a_list: list[float] = []
    flags_list: list[list[str]] = []
    raw_divs: list[float] = []
    for node in ranked_nodes:
        sa, flags = _compute_score_a(node, config)
        score_a_list.append(sa)
        flags_list.append(flags)
        raw_divs.append(_raw_divergence(node, config))

    # Normalization ceiling: pctile of nonzero raw divergences.
    nonzero = [d for d in raw_divs if d > 0.0]
    if nonzero:
        ceiling = float(np.percentile(nonzero, tri.ev_divergence_pctile))
    else:
        ceiling = 0.0

    # Pass 2: Score B.
    if ceiling > 0.0:
        score_b_list = [min(d / ceiling, 1.0) for d in raw_divs]
    else:
        score_b_list = [0.0 for _ in raw_divs]

    w_a = tri.score_weights.get("a", 0.5)
    w_b = tri.score_weights.get("b", 0.5)

    total_hands_sum = sum(n.total_hands for n in ranked_nodes)

    # Build entries with the ranking value, then sort.
    scratch = []
    for node, sa, sb, flags, raw_div in zip(
        ranked_nodes, score_a_list, score_b_list, flags_list, raw_divs
    ):
        composite = w_a * sa + w_b * sb
        freq = node.total_hands / total_hands_sum if total_hands_sum > 0 else 0.0
        street_weight = tri.street_weights.get(node.node_key.get("street", ""), 1.0)
        rank_value = composite * freq * street_weight
        hypothesis = _hypothesis(node, flags, sb, raw_div)
        scratch.append(
            {
                "node": node,
                "composite": composite,
                "score_a": sa,
                "score_b": sb,
                "freq": freq,
                "street_weight": street_weight,
                "flags": flags,
                "hypothesis": hypothesis,
                "rank_value": rank_value,
            }
        )

    # Primary sort tier: flagged nodes first (when enabled), then by the spec's
    # composite x frequency x street value within each tier.
    def _sort_key(d):
        tier = 1 if (tri.prioritize_flagged and d["flags"]) else 0
        return (tier, d["rank_value"])

    scratch.sort(key=_sort_key, reverse=True)

    entries: list[TriageEntry] = []
    for i, d in enumerate(scratch, start=1):
        node = d["node"]
        entries.append(
            TriageEntry(
                rank=i,
                node_key=node.node_key,
                composite_score=d["composite"],
                score_a=d["score_a"],
                score_b=d["score_b"],
                frequency_in_dataset=d["freq"],
                street_weight=d["street_weight"],
                total_hands=node.total_hands,
                flags=d["flags"],
                action_profiles=node.action_profiles,
                hypothesis=d["hypothesis"],
            )
        )
    return entries
