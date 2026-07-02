"""Shared data contract for mbPlumber.

This module is the single source of truth for every type that crosses a module
boundary (adapter -> extractor -> aggregator -> triage). All other modules
depend only on these types, never on each other's internals.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Street(str, Enum):
    PREFLOP = "PREFLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"


class Position(str, Enum):
    UTG = "UTG"
    MP = "MP"
    CO = "CO"
    BTN = "BTN"
    SB = "SB"
    BB = "BB"


class PotType(str, Enum):
    LIMP = "LIMP"
    SRP = "SRP"
    THREE_BET = "3BP"
    FOUR_BET = "4BP"


class ActionFacing(str, Enum):
    FIRST_TO_ACT = "FIRST_TO_ACT"  # hero opens the street (no prior action) — OOP lead spot
    CHECKED_TO = "CHECKED_TO"      # action checked to hero (>=1 check before hero, no bet)
    BET_SMALL = "BET_SMALL"
    BET_MEDIUM = "BET_MEDIUM"
    BET_LARGE = "BET_LARGE"
    BET_OVERBET = "BET_OVERBET"
    RAISE_SMALL = "RAISE_SMALL"
    RAISE_MEDIUM = "RAISE_MEDIUM"
    RAISE_LARGE = "RAISE_LARGE"
    RAISE_OVERBET = "RAISE_OVERBET"
    DONK_BET = "DONK_BET"


class ActionTaken(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET_SMALL = "bet_small"
    BET_MEDIUM = "bet_medium"
    BET_LARGE = "bet_large"
    BET_OVERBET = "bet_overbet"
    RAISE_SMALL = "raise_small"
    RAISE_MEDIUM = "raise_medium"
    RAISE_LARGE = "raise_large"
    RAISE_OVERBET = "raise_overbet"


class FlopArchetype(str, Enum):
    # Stronger than one pair
    FLUSH = "FLUSH"
    STRAIGHT = "STRAIGHT"
    SET_OR_FULL_HOUSE = "SET_OR_FULL_HOUSE"
    TWO_PAIR = "TWO_PAIR"
    # One pair
    TOP_PAIR = "TOP_PAIR"
    OVERPAIR = "OVERPAIR"
    MARGINAL_PAIR = "MARGINAL_PAIR"
    # Weaker than one pair
    COMBO_DRAW = "COMBO_DRAW"
    FLUSH_DRAW = "FLUSH_DRAW"
    OESD = "OESD"
    TWO_OVERCARDS = "TWO_OVERCARDS"
    WEAK_DRAW = "WEAK_DRAW"
    AIR = "AIR"


class Color(str, Enum):
    RAINBOW = "RAINBOW"
    TWO_TONE = "TWO_TONE"
    MONOTONE = "MONOTONE"


class Connectedness(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    SEMI_CONNECTED = "SEMI_CONNECTED"
    CONNECTED = "CONNECTED"


class TopCard(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PotSizeBucket(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    DEEP = "DEEP"


class StackDepthBucket(str, Enum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    DEEP = "DEEP"
    VERY_DEEP = "VERY_DEEP"


# --------------------------------------------------------------------------- #
# Module 1 output (the adapter produces these)
# --------------------------------------------------------------------------- #
class Player(BaseModel):
    seat: int
    name: str
    stack_bb: float


class Action(BaseModel):
    street: Street
    player: str
    action_type: str  # fold | check | call | bet | raise | post
    amount_bb: float = 0.0  # incremental chips put in this action, in BB
    pot_before_bb: float = 0.0  # pot size in BB before this action
    is_all_in: bool = False
    is_post: bool = False  # blinds/antes — not a decision point


class Hand(BaseModel):
    hand_id: str
    date: datetime
    game_type: str = "NLH cash"
    big_blind: float  # in chips (e.g. dollars)
    hero_seat: int | None  # None when hero was not dealt into the hand
    button_seat: int
    players: list[Player]
    actions: list[Action]
    board: list[str] = Field(default_factory=list)  # e.g. ["Ah","Kd","2c","7s","Jh"]
    hero_hole_cards: list[str] = Field(default_factory=list)
    # Showdown hole cards for every player who revealed them, keyed by name.
    # Extension beyond the spec — feeds all-in equity computation.
    all_hole_cards: dict[str, list[str]] = Field(default_factory=dict)
    pot_type: PotType
    hero_net_bb: float
    hero_won: bool = False  # hero collected a pot ('win' payout) at the end of the hand
    # Players who collected a pot ('win' payout) at showdown/end, name -> BB won.
    # Usually one; >1 for split pots. Excludes uncalled-bet returns ('receive').
    pot_winners: dict[str, float] = Field(default_factory=dict)
    reaches_flop: bool


# --------------------------------------------------------------------------- #
# Module 2 output
# --------------------------------------------------------------------------- #
class BoardTexture(BaseModel):
    color: Color
    connectedness: Connectedness
    paired: bool
    top_card: TopCard
    kernel_score: int  # raw kernel-scan integer (extension, for tests/audit)


class Decision(BaseModel):
    hand_id: str
    street: Street
    position: Position
    in_position: bool  # True if hero is last to act on the flop (IP); else OOP
    pot_type: PotType
    action_facing: ActionFacing
    pot_size_bb: float
    stack_depth_bb: float
    pot_size_bucket: PotSizeBucket
    stack_depth_bucket: StackDepthBucket
    num_players_in_hand: int
    flop_archetype: FlopArchetype
    board_texture: BoardTexture
    hero_action_taken: ActionTaken
    hero_action_sizing_pct: float | None = None  # % of pot; None for fold/check/call
    hero_realized_ev_bb: float
    is_all_in_decision: bool = False


# --------------------------------------------------------------------------- #
# Module 3 output
# --------------------------------------------------------------------------- #
class ActionProfile(BaseModel):
    action: str
    count: int
    frequency: float  # count / total_hands at the node
    mean_ev_bb100: float  # mean realized EV in BB, scaled x100 (BB/100)
    ev_ci_low: float | None = None  # 95% bootstrap CI lower bound (BB/100)
    ev_ci_high: float | None = None
    low_confidence: bool = False  # True when n < bootstrap_min_n


class NodeProfile(BaseModel):
    node_key: dict[str, str]  # the defining dimension values
    total_hands: int
    action_profiles: dict[str, ActionProfile]
    dominant_action: str
    low_sample: bool = False  # total_hands < low_sample_threshold


# --------------------------------------------------------------------------- #
# Module 4 output
# --------------------------------------------------------------------------- #
class TriageEntry(BaseModel):
    rank: int
    node_key: dict[str, str]
    composite_score: float
    score_a: float  # frequency-anomaly component
    score_b: float  # EV-divergence component
    frequency_in_dataset: float
    street_weight: float
    total_hands: int
    flags: list[str] = Field(default_factory=list)
    action_profiles: dict[str, ActionProfile]
    hypothesis: str
