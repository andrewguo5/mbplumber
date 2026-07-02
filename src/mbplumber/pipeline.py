"""End-to-end pipeline: adapt -> extract -> aggregate -> triage.

Ties the four units together. Hero position is not stored on the Hand model,
so this layer reads each hand's ACR position label from the raw record and
maps it via features.positions.map_position before calling the extractor.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .adapter.acr_jsonl import adapt_hand
from .adapter.manifest import check_format
from .aggregate import aggregate
from .config import Config
from .features.extractor import extract
from .features.positions import map_position
from .models import Decision, Hand, NodeProfile, Position, TriageEntry

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    triage: list[TriageEntry]
    nodes: list[NodeProfile]
    decisions: list[Decision]
    # Full hand detail keyed by hand_id (cards, board, net, action log) so the
    # explorer can expand a hand and let the user reconcile its actions and pot
    # against the realized EV shown for the decision. One entry per hand that
    # produced a decision; a hand appears once here even if it spans streets.
    hands: dict[str, Hand] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def _hero_position(raw: dict, hand: Hand) -> Position | None:
    """Map hero's ACR position label to a spec Position, or None if absent."""
    hero = raw.get("hero")
    label = raw.get("metadata", {}).get("positions", {}).get(hero)
    if label is None:
        return None
    try:
        return map_position(label)
    except ValueError:
        logger.warning("hand %s: unknown position label %r", hand.hand_id, label)
        return None


def iter_raw(path: str | Path):
    """Yield (lineno, raw_dict) for every JSON line under `path`.

    `path` may be a single .jsonl file or a directory of them.
    """
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield f.name, lineno, json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("%s:%d: invalid JSON, skipping", f.name, lineno)


def build_decisions(
    path: str | Path, config: Config
) -> tuple[list[Decision], dict[str, Hand], dict]:
    """Adapt + extract every hand under `path` into a flat list of Decisions.

    Also returns the `Hand` objects that produced at least one decision, keyed
    by hand_id, so downstream consumers (the explorer) can show full hand
    detail without re-parsing.
    """
    decisions: list[Decision] = []
    hands: dict[str, Hand] = {}
    stats = {
        "total_lines": 0,
        "parsed": 0,
        "parse_failures": 0,
        "no_hero": 0,
        "reached_flop": 0,
        "no_position": 0,
        "all_in_decisions": 0,
    }
    for _fname, _lineno, raw in iter_raw(path):
        stats["total_lines"] += 1
        try:
            hand = adapt_hand(raw)
        except Exception as exc:  # noqa: BLE001 - robustness per spec
            stats["parse_failures"] += 1
            logger.warning("adapt failed on %s:%d: %s", _fname, _lineno, exc)
            continue
        stats["parsed"] += 1
        if hand.hero_seat is None:
            # Hero was not dealt into this hand (schema-legal null hero_seat);
            # it can yield no hero decisions, so skip it explicitly.
            stats["no_hero"] += 1
            continue
        if not hand.reaches_flop:
            continue
        stats["reached_flop"] += 1
        pos = _hero_position(raw, hand)
        if pos is None:
            stats["no_position"] += 1
            continue
        hand_decisions = extract(hand, config, pos)
        for d in hand_decisions:
            if d.is_all_in_decision:
                stats["all_in_decisions"] += 1
        if hand_decisions:
            hands[hand.hand_id] = hand
        decisions.extend(hand_decisions)
    stats["decisions"] = len(decisions)
    return decisions, hands, stats


def run(path: str | Path, config: Config) -> PipelineResult:
    """Full pipeline: produce a ranked triage report for the hands under `path`."""
    check_format(path)  # fail fast on a mismatched dataset format
    decisions, hands, stats = build_decisions(path, config)
    nodes = aggregate(decisions, config)
    entries = triage_nodes(nodes, config)
    stats["nodes"] = len(nodes)
    stats["ranked_entries"] = len(entries)
    return PipelineResult(
        triage=entries, nodes=nodes, decisions=decisions, hands=hands, stats=stats
    )


def triage_nodes(nodes: list[NodeProfile], config: Config) -> list[TriageEntry]:
    # thin indirection so callers can import a single name
    from .triage import triage

    return triage(nodes, config)
