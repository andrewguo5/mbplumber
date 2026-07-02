"""Decision-node EXPLORER: turn the pipeline output into a navigable tree.

The active node dimensions (config.active_dimensions) form an ORDERED path —
street -> in_position -> pot_type -> action_facing -> (optional dims). That
ordering is literally a decision tree: each level branches the data, and the
leaves are the fully-specified nodes the aggregator/triage already scores.

`build_tree` walks every Decision down that path, accumulating a nested tree
whose leaves carry:

  * the per-action breakdown (count / freq / mean realized EV / CI) from the
    matching NodeProfile, and
  * the individual hero decisions (hand_id, action, sizing, EV, won) so the
    user can see WHICH hands each action was taken with — the only way to eye
    the hand-selection confound that realized-EV divergence can't escape.

The tree is plain dicts/lists so it serializes straight to JSON for the HTML
explorer (report_explorer.py).
"""

from __future__ import annotations

from .aggregate import _DIMENSION_GETTERS
from .config import Config
from .features.extractor import _hero_name
from .models import Decision, Hand, NodeProfile, TriageEntry


# Dimensions whose values have a natural (non-alphabetical) order. Values not
# listed fall back to alphabetical, appended after the known ones.
_DIMENSION_ORDER: dict[str, list[str]] = {
    "street": ["PREFLOP", "FLOP", "TURN", "RIVER"],
}


def _ordered_keys(children: dict, dimension: str | None) -> list[str]:
    """Order a node's child keys: by the dimension's natural order if it has
    one (e.g. street FLOP->TURN->RIVER), else alphabetically."""
    order = _DIMENSION_ORDER.get(dimension or "")
    if not order:
        return sorted(children, key=str)
    rank = {v: i for i, v in enumerate(order)}
    return sorted(children, key=lambda k: (rank.get(k, len(order)), str(k)))


def _leaf_path(decision: Decision, dimensions: list[str]) -> tuple[str, ...]:
    return tuple(_DIMENSION_GETTERS[dim](decision) for dim in dimensions)


def _decision_row(d: Decision) -> dict:
    return {
        "hand_id": d.hand_id,
        "action": d.hero_action_taken.value,
        "sizing_pct": d.hero_action_sizing_pct,
        "ev_bb": round(d.hero_realized_ev_bb, 2),
        "all_in": d.is_all_in_decision,
    }


def _action_profile_row(ap) -> dict:
    return {
        "action": ap.action,
        "count": ap.count,
        "frequency": ap.frequency,
        "mean_ev_bb100": ap.mean_ev_bb100,
        "ev_ci_low": ap.ev_ci_low,
        "ev_ci_high": ap.ev_ci_high,
        "low_confidence": ap.low_confidence,
    }


def _hand_detail(hand: Hand) -> dict:
    """Full, JSON-serializable detail for a single hand so the explorer can let
    the user reconcile the action sequence and pots against the realized EV.

    Carries hero's hole cards, the board, hero's hand-level net, and the
    complete action log (per-street, every player) with the pot before each
    action and all-in markers — the exact inputs the EV model values a
    decision against. Posts (blinds/antes) are kept but flagged so the running
    pot reads correctly.
    """
    hero = _hero_name(hand)
    actions = [
        {
            "street": a.street.value,
            "player": a.player,
            "is_hero": a.player == hero,
            "action": a.action_type,
            "amount_bb": round(a.amount_bb, 2),
            "pot_before_bb": round(a.pot_before_bb, 2),
            "all_in": a.is_all_in,
            "is_post": a.is_post,
        }
        for a in hand.actions
    ]
    return {
        "hand_id": hand.hand_id,
        "hero": hero,
        "hero_hole_cards": list(hand.hero_hole_cards),
        "board": list(hand.board),
        "pot_type": hand.pot_type.value,
        "hero_net_bb": round(hand.hero_net_bb, 2),
        "hero_won": hand.hero_won,
        # Who took down the pot (name -> BB won); usually one, >1 for splits.
        "pot_winners": {name: round(bb, 2) for name, bb in hand.pot_winners.items()},
        "actions": actions,
    }


def build_tree(
    decisions: list[Decision],
    nodes: list[NodeProfile],
    triage: list[TriageEntry],
    config: Config,
    hands: dict[str, Hand] | None = None,
) -> dict:
    """Build a nested tree of decision nodes for the HTML explorer.

    Returns a dict:
      {
        "dimensions": [...ordered dimension names...],
        "root": <node>,
        "hands": { hand_id: <hand detail>, ... },  # full log+cards per hand
      }
    where each <node> is:
      {
        "label": str,            # the dimension VALUE at this branch ("" at root)
        "dimension": str|None,   # the dimension whose value `label` is
        "count": int,            # decisions under this subtree
        "children": [<node>...], # present on internal nodes
        "leaf": {...}|None,      # present on leaves (a fully-specified node)
      }
    A leaf carries the per-action profiles, the individual decision rows, and
    the triage flags/score for that node.
    """
    dimensions = config.active_dimensions()

    # Index aggregator + triage output by the leaf path for O(1) leaf decoration.
    nodes_by_path: dict[tuple[str, ...], NodeProfile] = {
        tuple(n.node_key.get(dim, "") for dim in dimensions): n for n in nodes
    }
    triage_by_path: dict[tuple[str, ...], TriageEntry] = {
        tuple(t.node_key.get(dim, "") for dim in dimensions): t for t in triage
    }

    # Group decisions by full leaf path.
    decisions_by_path: dict[tuple[str, ...], list[Decision]] = {}
    for d in decisions:
        decisions_by_path.setdefault(_leaf_path(d, dimensions), []).append(d)

    root: dict = {
        "label": "", "dimension": None, "count": 0, "ev_sum": 0.0,
        "children": {}, "leaf": None,
    }

    for path, ds in decisions_by_path.items():
        ev_sum = sum(d.hero_realized_ev_bb for d in ds)
        cursor = root
        cursor["count"] += len(ds)
        cursor["ev_sum"] += ev_sum
        for depth, value in enumerate(path):
            children = cursor["children"]
            if value not in children:
                children[value] = {
                    "label": value,
                    "dimension": dimensions[depth],
                    "count": 0,
                    "ev_sum": 0.0,
                    "children": {},
                    "leaf": None,
                }
            cursor = children[value]
            cursor["count"] += len(ds)
            cursor["ev_sum"] += ev_sum

        node = nodes_by_path.get(path)
        entry = triage_by_path.get(path)
        cursor["leaf"] = {
            "node_key": dict(zip(dimensions, path)),
            "total_hands": node.total_hands if node else len(ds),
            "low_sample": node.low_sample if node else None,
            "dominant_action": node.dominant_action if node else None,
            "action_profiles": (
                [_action_profile_row(ap) for ap in node.action_profiles.values()]
                if node
                else []
            ),
            "decisions": sorted(
                (_decision_row(d) for d in ds),
                key=lambda r: (r["action"], r["ev_bb"]),
            ),
            "flags": entry.flags if entry else [],
            "composite_score": entry.composite_score if entry else None,
            "score_a": entry.score_a if entry else None,
            "score_b": entry.score_b if entry else None,
            "hypothesis": entry.hypothesis if entry else None,
        }

    # Convert children dicts -> ordered lists, and roll up an aggregate EV at
    # every level so leaks are scannable without opening each leaf.
    def _finalize(node: dict, depth: int) -> dict:
        n = node["count"]
        node["mean_ev_bb"] = node["ev_sum"] / n if n else 0.0
        node["mean_ev_bb100"] = 100.0 * node["mean_ev_bb"]
        children = node.pop("children")
        dim = dimensions[depth] if depth < len(dimensions) else None
        node["children"] = [
            _finalize(children[k], depth + 1) for k in _ordered_keys(children, dim)
        ]
        return node

    _finalize(root, 0)

    # Embed full hand detail ONCE per hand (a hand spans multiple decision
    # nodes across streets); per-hand rows reference these by hand_id so the
    # payload stays small. Only hands that actually produced a decision in this
    # run are included.
    seen_ids = {d.hand_id for d in decisions}
    hands = hands or {}
    hands_detail = {
        hid: _hand_detail(hands[hid]) for hid in seen_ids if hid in hands
    }

    return {"dimensions": dimensions, "root": root, "hands": hands_detail}
