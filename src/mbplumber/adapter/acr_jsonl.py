"""ACR ParsedHand JSONL v2 adapter (Unit A of mbPlumber).

Reads the pre-parsed ACR hand-history JSONL produced by the upstream
exporter and maps each line onto the frozen :class:`mbplumber.models.Hand`
contract. This module owns format-specific concerns only; it never touches
downstream modules.

Input format (one JSON object per line)::

    {
      "metadata": {"hand_id", "hand_datetime", "table_name", "max_seats",
                   "button_seat", "small_blind", "big_blind",
                   "players": {seat_str: name}, "stacks": {name: chips},
                   "positions": {name: acr_label}},
      "streets": {"preflop": {...}, "flop": {...}, "turn": {...}, "river": {...}},
      "hole_cards": {name: ["Td","Js"], ...},
      "total_pot", "rake", "hero", "hero_seat"
    }

Each action::

    {"player", "action_type", "amount", "total_bet", "is_all_in"}

Key semantics discovered against real data:

* For ``bet`` / ``call`` / ``post_*``: ``amount`` is the incremental chips
  for that action; ``total_bet`` is null.
* For ``raise``: ``total_bet`` is the player's CUMULATIVE wagered chips on
  that street. The incremental chips added are ``total_bet`` minus the
  player's own prior contribution on that street. The provided ``amount``
  field is NOT this increment -- it is the "raise-by" amount (total_bet
  minus the current bet-to-call and minus dead ante/blind chips), so it is
  ignored for raises in favor of the computed increment.
* ``win`` / ``receive`` are payouts (uncalled-bet return = ``receive``; pot
  award = ``win``). They are dropped from ``Hand.actions`` but used to
  compute ``hero_net_bb``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from mbplumber.features.positions import map_position  # noqa: F401  (kept available)
from mbplumber.models import Action, Hand, Player, PotType, Street

logger = logging.getLogger(__name__)

# Street ordering used to flatten actions chronologically.
_STREET_ORDER: list[tuple[str, Street]] = [
    ("preflop", Street.PREFLOP),
    ("flop", Street.FLOP),
    ("turn", Street.TURN),
    ("river", Street.RIVER),
]

# action_type values that move chips into the pot (a "wager").
_POST_TYPES = {"post_sb", "post_bb", "post_ante"}
_WAGER_TYPES = {"bet", "call"} | _POST_TYPES  # raise handled separately
_PAYOUT_TYPES = {"win", "receive"}

_DATE_FORMAT = "%Y/%m/%d %H:%M:%S UTC"


def _parse_date(raw_dt: str) -> datetime:
    """Parse '2026/01/30 16:35:59 UTC' into a datetime."""
    return datetime.strptime(raw_dt, _DATE_FORMAT)


def _opt_int(value: object) -> int | None:
    """Cast to int, preserving None. The schema allows a null hero_seat (hero
    was not dealt in); such hands carry no hero decisions and are skipped
    downstream, so the adapter represents the absence rather than crashing."""
    return None if value is None else int(value)


def _normalize_action_type(action_type: str) -> str:
    """Normalize an ACR action_type to the contract vocabulary.

    Returns one of: fold | check | call | bet | raise | post.
    """
    if action_type in _POST_TYPES:
        return "post"
    return action_type


def _deepest_board(streets: dict) -> list[str]:
    """Board cards from the deepest populated street (river > turn > flop)."""
    for name in ("river", "turn", "flop"):
        sd = streets.get(name)
        if sd:
            cards = sd.get("board_cards")
            if cards:
                return list(cards)
    return []


def _pot_type(preflop_actions: list[dict]) -> PotType:
    """Classify pot type from the count of preflop raises."""
    n_raises = sum(1 for a in preflop_actions if a.get("action_type") == "raise")
    if n_raises == 0:
        return PotType.LIMP
    if n_raises == 1:
        return PotType.SRP
    if n_raises == 2:
        return PotType.THREE_BET
    return PotType.FOUR_BET  # 4+ bet cases all bucket here


def adapt_hand(raw: dict) -> Hand:
    """Map one ParsedHand JSONL v2 dict to a :class:`Hand`.

    Raises on malformed input; callers that need resilience should use
    :func:`iter_hands`, which catches and skips bad records.
    """
    md = raw["metadata"]
    bb = float(md["big_blind"])
    if bb <= 0:
        raise ValueError(f"non-positive big_blind: {bb!r}")
    hero = raw["hero"]
    streets = raw["streets"]

    # --- players -----------------------------------------------------------
    stacks = md["stacks"]
    players: list[Player] = []
    for seat_str, name in md["players"].items():
        chips = float(stacks.get(name, 0.0))
        players.append(Player(seat=int(seat_str), name=name, stack_bb=chips / bb))
    players.sort(key=lambda p: p.seat)

    # --- actions + running pot + hero net ----------------------------------
    actions: list[Action] = []
    pot_bb = 0.0  # running pot in BB
    hero_payout = 0.0  # chips paid out to hero (win + receive)
    hero_invested = 0.0  # chips hero put in (posts + bets + calls + raise increments)
    hero_won = False  # hero collected a pot via a 'win' payout
    pot_winners: dict[str, float] = {}  # player -> chips won via 'win' payouts

    for street_name, street_enum in _STREET_ORDER:
        sdata = streets.get(street_name)
        if not sdata:
            continue
        # Per-street cumulative contribution by player, to derive raise increments.
        prior_contrib: dict[str, float] = {}
        for a in sdata.get("actions", []):
            at = a["action_type"]
            player = a["player"]

            if at in _PAYOUT_TYPES:
                # Not a decision: drop from actions, but use for hero net and
                # to record who took down the pot ('win' only, not 'receive').
                if at == "win":
                    pot_winners[player] = (
                        pot_winners.get(player, 0.0) + float(a.get("amount") or 0.0) / bb
                    )
                if player == hero:
                    hero_payout += float(a.get("amount") or 0.0)
                    if at == "win":
                        hero_won = True
                continue

            # Determine incremental chips for this action.
            if at == "raise":
                total_bet = float(a["total_bet"])
                increment = total_bet - prior_contrib.get(player, 0.0)
                prior_contrib[player] = total_bet
                amount_chips = increment
            elif at in _WAGER_TYPES:
                amount_chips = float(a.get("amount") or 0.0)
                prior_contrib[player] = prior_contrib.get(player, 0.0) + amount_chips
            else:
                # fold / check: no chips
                amount_chips = 0.0

            amount_bb = amount_chips / bb

            actions.append(
                Action(
                    street=street_enum,
                    player=player,
                    action_type=_normalize_action_type(at),
                    amount_bb=amount_bb,
                    pot_before_bb=pot_bb,
                    is_all_in=bool(a.get("is_all_in", False)),
                    is_post=at in _POST_TYPES,
                )
            )

            # Update the pot AFTER recording pot_before for this action.
            if amount_chips:
                pot_bb += amount_bb
                if player == hero:
                    hero_invested += amount_chips

    hero_net_bb = (hero_payout - hero_invested) / bb

    # --- board / flop reach ------------------------------------------------
    board = _deepest_board(streets)
    flop = streets.get("flop")
    reaches_flop = bool(flop and flop.get("board_cards"))

    # --- hole cards --------------------------------------------------------
    all_hole_cards = {
        name: list(cards) for name, cards in (raw.get("hole_cards") or {}).items()
    }
    hero_hole_cards = list(all_hole_cards.get(hero, []))

    return Hand(
        hand_id=str(md["hand_id"]),
        date=_parse_date(md["hand_datetime"]),
        big_blind=bb,
        hero_seat=_opt_int(raw.get("hero_seat")),
        button_seat=int(md["button_seat"]),
        players=players,
        actions=actions,
        board=board,
        hero_hole_cards=hero_hole_cards,
        all_hole_cards=all_hole_cards,
        pot_type=_pot_type(streets["preflop"]["actions"]),
        hero_net_bb=hero_net_bb,
        hero_won=hero_won,
        pot_winners=pot_winners,
        reaches_flop=reaches_flop,
    )


def iter_hands(path: str | Path) -> Iterator[Hand]:
    """Yield :class:`Hand` objects from a .jsonl file, one per line.

    Malformed lines (bad JSON or that fail adaptation) are logged as a
    warning and skipped -- this never raises on bad input.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("%s:%d: bad JSON, skipping (%s)", path.name, lineno, exc)
                continue
            try:
                yield adapt_hand(raw)
            except Exception as exc:  # noqa: BLE001 - robustness is required
                logger.warning(
                    "%s:%d: failed to adapt hand, skipping (%s)", path.name, lineno, exc
                )
                continue


def load_dir(path: str | Path) -> tuple[list[Hand], dict]:
    """Load all ``*.jsonl`` files in a directory.

    Returns ``(hands, stats)`` where ``stats`` contains ``total_lines``,
    ``parsed`` and ``parse_failures``.
    """
    path = Path(path)
    hands: list[Hand] = []
    total_lines = 0
    parse_failures = 0

    for fp in sorted(path.glob("*.jsonl")):
        with fp.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    raw = json.loads(line)
                    hands.append(adapt_hand(raw))
                except Exception as exc:  # noqa: BLE001
                    parse_failures += 1
                    logger.warning(
                        "%s:%d: skipping bad line (%s)", fp.name, lineno, exc
                    )

    stats = {
        "total_lines": total_lines,
        "parsed": len(hands),
        "parse_failures": parse_failures,
    }
    return hands, stats
