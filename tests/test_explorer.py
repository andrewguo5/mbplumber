"""Tests for the decision-node explorer tree builder (explorer.build_tree)."""

import pathlib

import pytest

from mbplumber.config import load_config
from mbplumber.explorer import build_tree
from mbplumber.pipeline import run


@pytest.fixture(scope="module")
def _result():
    cfg = load_config()
    res = run(pathlib.Path("../PokerData/hands"), cfg)
    return res, cfg


def test_tree_partitions_all_decisions(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg)
    # Root count == total decisions; every decision lands in exactly one leaf.
    assert tree["root"]["count"] == len(res.decisions)

    def leaf_count(node):
        if not node["children"]:
            return node["count"] if node["leaf"] else 0
        return sum(leaf_count(c) for c in node["children"])

    assert leaf_count(tree["root"]) == len(res.decisions)


def test_tree_path_follows_active_dimensions(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg)
    assert tree["dimensions"] == cfg.active_dimensions()

    # Walk to any leaf; the dimension at each depth matches the ordered path.
    dims = tree["dimensions"]
    node = tree["root"]
    depth = 0
    while node["children"]:
        node = node["children"][0]
        assert node["dimension"] == dims[depth]
        depth += 1
    assert node["leaf"] is not None
    # Leaf key has exactly the active dimensions.
    assert list(node["leaf"]["node_key"].keys()) == dims


def test_every_node_has_aggregate_ev(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg)

    def check(node):
        assert "mean_ev_bb" in node and "mean_ev_bb100" in node
        # BB/100 is exactly 100x BB.
        assert abs(node["mean_ev_bb100"] - 100 * node["mean_ev_bb"]) < 1e-6
        for c in node["children"]:
            check(c)

    check(tree["root"])
    # Root aggregate == overall mean realized EV (BB) across all decisions.
    overall = sum(d.hero_realized_ev_bb for d in res.decisions) / len(res.decisions)
    assert abs(tree["root"]["mean_ev_bb"] - overall) < 1e-6


def test_streets_ordered_flop_turn_river(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg)
    # Only meaningful when street is the first dimension (it is by default).
    assert tree["dimensions"][0] == "street"
    labels = [c["label"] for c in tree["root"]["children"]]
    order = {s: i for i, s in enumerate(["PREFLOP", "FLOP", "TURN", "RIVER"])}
    assert labels == sorted(labels, key=lambda s: order[s])


def test_leaf_carries_per_hand_decisions_and_profiles(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg)

    def first_leaf(node):
        if not node["children"]:
            return node if node["leaf"] else None
        for c in node["children"]:
            r = first_leaf(c)
            if r:
                return r
        return None

    leaf = first_leaf(tree["root"])["leaf"]
    # Individual hand rows are present and counts reconcile with action profiles.
    assert leaf["decisions"], "leaf should list the individual decisions"
    prof_total = sum(p["count"] for p in leaf["action_profiles"])
    assert prof_total == len(leaf["decisions"])
    for r in leaf["decisions"]:
        assert {"hand_id", "action", "ev_bb"} <= r.keys()


def _all_leaves(node):
    if node["leaf"]:
        yield node["leaf"]
    for c in node["children"]:
        yield from _all_leaves(c)


def test_tree_embeds_full_hand_detail(_result):
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg, res.hands)
    hands = tree["hands"]
    assert hands, "tree should embed per-hand detail"

    # Every decision's hand has detail (it produced that decision).
    decided_ids = {d.hand_id for d in res.decisions}
    assert decided_ids <= set(hands), "every decided hand must have detail"

    # A detail entry carries cards, board, net, won, and a full action log.
    sample = hands[next(iter(hands))]
    assert {"hero", "hero_hole_cards", "board", "hero_net_bb",
            "hero_won", "actions"} <= sample.keys()
    assert sample["actions"], "action log must be non-empty"
    for a in sample["actions"]:
        assert {"street", "player", "is_hero", "action",
                "amount_bb", "pot_before_bb", "all_in", "is_post"} <= a.keys()


def test_hand_detail_reconciles_check_win_ev(_result):
    """A hero check-win decision's EV (BB) must equal the pot before that
    check in the embedded action log — the user reconciles by eye on this."""
    res, cfg = _result
    tree = build_tree(res.decisions, res.nodes, res.triage, cfg, res.hands)
    hands = tree["hands"]

    checked = False
    for leaf in _all_leaves(tree["root"]):
        for r in leaf["decisions"]:
            if r["action"] != "check" or r["ev_bb"] <= 0:
                continue
            h = hands.get(r["hand_id"])
            if not h or not h["hero_won"]:
                continue
            hero_checks = [
                a for a in h["actions"] if a["is_hero"] and a["action"] == "check"
            ]
            # Reconcile when the hand has a single hero check (unambiguous P).
            if len(hero_checks) == 1:
                assert abs(hero_checks[0]["pot_before_bb"] - r["ev_bb"]) < 0.05
                checked = True
    assert checked, "expected at least one reconcilable hero check-win"
