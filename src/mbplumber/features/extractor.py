"""Module 2 entry point: turn a Hand into a list of postflop hero Decisions.

`extract(hand, config, hero_position)` walks FLOP/TURN/RIVER actions and emits
one Decision per genuine hero decision (posts excluded).

POSITION DEPENDENCY (documented): the Hand does not carry hero's position. To
avoid coupling Module 2 to the positions module / adapter, hero's Position is
passed in as a parameter. The pipeline supplies it from the adapter; unit tests
pass a Position directly. We deliberately do NOT import mbplumber.features.positions.
"""

from __future__ import annotations

from ..config import Config
from ..models import (
    Action,
    BoardTexture,
    Decision,
    FlopArchetype,
    Hand,
    Position,
    PotSizeBucket,
    StackDepthBucket,
    Street,
)
from .action_facing import StreetWalker
from .archetype import flop_archetype
from .ev import allin_equity, decision_ev
from .texture import board_texture

_POSTFLOP_STREETS = [Street.FLOP, Street.TURN, Street.RIVER]


def pot_size_bucket(pot_bb: float) -> PotSizeBucket:
    """Left-closed bucketing: 5 -> SMALL, 15 -> MEDIUM, 40 -> LARGE, 100 -> DEEP."""
    if pot_bb < 5:
        return PotSizeBucket.MICRO
    elif pot_bb < 15:
        return PotSizeBucket.SMALL
    elif pot_bb < 40:
        return PotSizeBucket.MEDIUM
    elif pot_bb <= 100:
        return PotSizeBucket.LARGE
    return PotSizeBucket.DEEP


def stack_depth_bucket(stack_bb: float) -> StackDepthBucket:
    """Left-closed: 20 -> MEDIUM, 50 -> DEEP, 100 -> VERY_DEEP (boundary up)."""
    if stack_bb < 20:
        return StackDepthBucket.SHORT
    elif stack_bb < 50:
        return StackDepthBucket.MEDIUM
    elif stack_bb <= 100:
        return StackDepthBucket.DEEP
    return StackDepthBucket.VERY_DEEP


def _hero_name(hand: Hand) -> str | None:
    for p in hand.players:
        if p.seat == hand.hero_seat:
            return p.name
    return None


def _preflop_aggressor(hand: Hand) -> str | None:
    """Last preflop bettor/raiser (None in a purely limped pot)."""
    aggressor: str | None = None
    for a in hand.actions:
        if a.street != Street.PREFLOP:
            continue
        if a.action_type in ("bet", "raise") and not a.is_post:
            aggressor = a.player
    return aggressor


def _hero_is_ip(hand: Hand, hero: str, in_hand: set[str]) -> bool:
    """True if hero is in position (last to act) on the flop.

    Postflop, action runs clockwise starting from the first live seat left of
    the button; the button (or the closest live seat before it) acts last. So
    among players still in the hand, the IP player is the one whose seat is
    last in that clockwise-from-button order. Hero is IP iff hero is that
    player. Seat-based so it is independent of who checked or folded mid-flop.
    """
    seats = {p.name: p.seat for p in hand.players}
    contenders = [p for p in in_hand if p in seats]
    if hero not in contenders:
        return False
    if len(contenders) <= 1:
        # Hero is the only one to the flop (e.g. blinds walked) -> treat as IP.
        return True

    # Postflop the button acts last and action proceeds clockwise from the seat
    # after the button. Going *counter-clockwise* from the button (button,
    # button-1, ...), the first contender we hit is the latest to act = IP.
    button = hand.button_seat
    occupied = sorted(p.seat for p in hand.players)
    n = len(occupied)
    # Map each seat to its index in clockwise seating order for stepping.
    order = {seat: i for i, seat in enumerate(occupied)}
    # Start at the button's position (or, if the button seat is empty, the
    # nearest occupied seat at/just before it) and step backwards to find the
    # first still-in player.
    start = max((i for s, i in order.items() if s <= button), default=n - 1)
    for step in range(n):
        seat = occupied[(start - step) % n]
        name = next((nm for nm, se in seats.items() if se == seat), None)
        if name in contenders:
            return name == hero
    return False


def extract(hand: Hand, config: Config, hero_position: Position) -> list[Decision]:
    if not hand.reaches_flop:
        return []

    hero = _hero_name(hand)
    if hero is None:
        return []

    flop_cards = hand.board[:3]
    if len(flop_cards) < 3:
        return []

    # Hand invariants (computed once, carried to every decision).
    archetype: FlopArchetype = flop_archetype(hand.hero_hole_cards, flop_cards)
    texture: BoardTexture = board_texture(flop_cards)
    is_all_in_decision = any(
        a.is_all_in for a in hand.actions if a.player == hero and not a.is_post
    )
    # Per-decision EV (see ev.py) needs whether hero won the pot, and — for
    # all-in pots — hero's equity at the all-in point to blend win/lose.
    hero_won = hand.hero_won
    hero_equity = allin_equity(hand, hero) if is_all_in_decision else None
    pre_aggressor = _preflop_aggressor(hand)

    # Per-player total chips invested across the whole hand (running), used for
    # remaining stacks and effective stack depth.
    invested: dict[str, float] = {p.name: 0.0 for p in hand.players}
    stack0 = {p.name: p.stack_bb for p in hand.players}
    # folded / still-in tracking across streets.
    folded: set[str] = set()
    # players who reached the flop = everyone who did not fold preflop.
    for a in hand.actions:
        if a.street == Street.PREFLOP:
            invested[a.player] = invested.get(a.player, 0.0) + a.amount_bb
            if a.action_type == "fold":
                folded.add(a.player)

    # A player who reached the flop must actually have a postflop presence:
    # either they take a postflop action, or they are hero. Some preflop
    # folders (e.g. a blind that folds) are not emitted as an explicit `fold`
    # action, so the `folded` set alone leaves "phantom" contenders in the
    # hand. Including them corrupts the IP/OOP seat order (a phantom seated
    # after hero steals the last-to-act slot, flipping hero IP -> OOP) and
    # inflates `num_players_in_hand`. Intersect with players seen postflop.
    reached_flop = {
        a.player for a in hand.actions if a.street != Street.PREFLOP and not a.is_post
    }
    reached_flop.add(hero)
    in_hand = ({p.name for p in hand.players} - folded) & reached_flop

    # In position (IP) = hero is the last player to act on the flop among those
    # who reached it. The flop action sequence is in positional order (OOP acts
    # first, button-most last), so the IP player is the last DISTINCT actor on
    # the flop who did not fold preflop. Hero is IP iff that player is hero.
    hero_in_position = _hero_is_ip(hand, hero, in_hand)

    decisions: list[Decision] = []

    for street in _POSTFLOP_STREETS:
        street_actions = [a for a in hand.actions if a.street == street]
        if not street_actions:
            continue
        walker = StreetWalker(pre_aggressor=pre_aggressor, street=street)
        prior_non_post: list[Action] = []
        for idx, a in enumerate(street_actions):
            if a.is_post:
                invested[a.player] = invested.get(a.player, 0.0) + a.amount_bb
                continue

            if a.player == hero:
                pot_before = a.pot_before_bb
                result = walker.hero_decision(
                    actions_before=list(prior_non_post),
                    hero_action=a,
                    pot_before_hero=pot_before,
                )
                # Chips villains commit in DIRECT response to hero's AGGRESSION
                # on this street: scan forward until action would return to hero
                # or the street ends. This is the "M" that a bet/raise induced.
                # Only bets/raises induce M — a check/call induces nothing, so it
                # never accrues later villain chips (those aren't won by virtue of
                # checking/calling).
                villain_response = 0.0
                if a.action_type in ("bet", "raise"):
                    for b in street_actions[idx + 1 :]:
                        if b.is_post:
                            continue
                        if b.player == hero:
                            break
                        villain_response += b.amount_bb

                hero_commit = a.amount_bb
                is_fold = a.action_type == "fold"
                realized_ev = decision_ev(
                    pot_before_bb=pot_before,
                    hero_commit_bb=hero_commit,
                    villain_response_bb=villain_response,
                    is_fold=is_fold,
                    hero_won=hero_won,
                    equity_override=hero_equity,
                )
                # effective stack = min(hero remaining, max remaining among
                # villains still in the hand at this point).
                hero_remaining = stack0[hero] - invested.get(hero, 0.0)
                villain_remainings = [
                    stack0[p] - invested.get(p, 0.0)
                    for p in in_hand
                    if p != hero
                ]
                if villain_remainings:
                    eff_stack = min(hero_remaining, max(villain_remainings))
                else:
                    eff_stack = hero_remaining
                eff_stack = max(eff_stack, 0.0)

                decisions.append(
                    Decision(
                        hand_id=hand.hand_id,
                        street=street,
                        position=hero_position,
                        in_position=hero_in_position,
                        pot_type=hand.pot_type,
                        action_facing=result.action_facing,
                        pot_size_bb=pot_before,
                        stack_depth_bb=eff_stack,
                        pot_size_bucket=pot_size_bucket(pot_before),
                        stack_depth_bucket=stack_depth_bucket(eff_stack),
                        num_players_in_hand=len(in_hand),
                        flop_archetype=archetype,
                        board_texture=texture,
                        hero_action_taken=result.hero_action_taken,
                        hero_action_sizing_pct=result.hero_action_sizing_pct,
                        hero_realized_ev_bb=realized_ev,
                        is_all_in_decision=is_all_in_decision,
                    )
                )

            # update bookkeeping after the action
            invested[a.player] = invested.get(a.player, 0.0) + a.amount_bb
            if a.action_type == "fold":
                folded.add(a.player)
                in_hand.discard(a.player)
            prior_non_post.append(a)

    return decisions
