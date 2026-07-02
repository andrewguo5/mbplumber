# mbPlumber — Engineering Specification

## Overview

This document is the authoritative specification for mbPlumber. It is intended for engineers implementing the system and should be read in full before beginning any work.

---

## Background and Motivation

A poker "leak" is a decision node in which a player's strategy is suboptimal, resulting in a negative expected value (EV) contribution over a large sample. Leaks manifest in three forms:

- **Frequency leaks** — the player takes an action too often or too rarely relative to a correct strategy
- **Selection leaks** — the player takes the right action but with the wrong hands
- **Sizing leaks** — the player takes the right action with the right hands but at the wrong sizing

The fundamental challenge in identifying leaks from hand history data alone is that **realized EV is confounded by hand selection into a spot**. A spot may look profitable simply because the player only arrives there with strong hands. Conversely, a sizing or bluff-frequency leak is invisible in realized EV because the counterfactual actions (larger sizing, bluff raises) never occurred.

This system therefore does **not** attempt to benchmark the player against a solver or GTO solution. Instead, it triages candidate leak spots using two signals that are internally observable:

1. **Frequency anomalies** — action frequencies that are extreme (near 0% or 100%) or that violate basic strategic constraints
2. **Realized EV divergence across actions** — within a given decision node, one action yields significantly worse realized EV than alternatives, suggesting the player is taking that action too often with the wrong hands or at the wrong frequency

The output of the system is a **ranked list of candidate leak nodes** with enough context for the player to take a specific spot to a solver for targeted study. The system does the triage; the solver does the confirmation.

---

## Glossary

- **Hand**: A single dealt round of Texas Hold'em
- **Street**: One of four phases — Preflop, Flop, Turn, River
- **Position**: The player's seat relative to the dealer button — UTG, MP, CO, BTN, SB, BB (configurable)
- **Action facing**: The action the player must respond to — e.g. check, bet (with sizing bucket), raise (with sizing bucket), 3bet, etc.
- **Decision node**: A unique combination of (Street, Position, Action Facing, [configurable additional dimensions]) that defines a spot in the game tree
- **Action taken**: The player's response at a decision node — fold, check, call, bet (size bucket), raise (size bucket)
- **Realized EV**: The player's net chip outcome for the hand, expressed in big blinds, attributed to decisions made at that node. Approximated as hand outcome in BB adjusted for all-in equity where applicable
- **BB/100**: Big blinds won per 100 hands — the standard unit of poker win rate
- **Sizing bucket**: A discretized category for bet or raise sizes expressed as a fraction of the pot (e.g. small ≤33%, medium 33–67%, large 67–100%, overbet >100%)
- **Sample CI**: Bootstrap 95% confidence interval on mean realized EV for a node
- **Flop archetype**: The hand strength category assigned on the flop and carried forward unchanged through all subsequent streets, regardless of how the board runs out
- **Pot type**: The preflop action that determined the pot going to the flop — SRP, 3BP, 4BP, or Limp

---

## System Architecture

The system is composed of four independent modules that form a pipeline:

```
[Module 1: Parser] → [Module 2: Feature Extractor] → [Module 3: Node Aggregator] → [Module 4: Triage Analyzer]
```

Each module has a defined input and output format. Modules 1 and 2 are tightly coupled (format-specific); Modules 3 and 4 are format-agnostic and reusable across hand history sources.

---

## Module 1 — Hand History Parser

### Responsibility

Parse raw hand history files into a structured, normalized intermediate representation. One record per hand.

### Scope

This system focuses exclusively on **postflop play**. Hands that do not reach the flop (e.g. preflop folds, preflop all-ins with no runout) are parsed but filtered out before feature extraction. They do not appear in any decision node output.

### Input

Raw hand history text files. The parser must be written for a specific format. Supported formats should be implemented as interchangeable parser backends:

- PokerStars (`.txt`)
- GGPoker (`.txt`)
- 888poker (`.txt`)

Each format has its own parser class implementing a common interface. New formats are added by implementing the interface — no changes to downstream modules.

### Output

A list of structured Hand objects. Each Hand contains:

```
Hand
├── hand_id: str
├── date: datetime
├── game_type: str              # e.g. "NLH cash"
├── big_blind: float            # in chips
├── hero_seat: int
├── button_seat: int
├── players: List[Player]
│   ├── seat: int
│   ├── stack: float            # in BB
│   └── name: str
├── actions: List[Action]       # ordered chronologically
│   ├── street: str             # PREFLOP | FLOP | TURN | RIVER
│   ├── player: str
│   ├── action_type: str        # fold | check | call | bet | raise | post
│   ├── amount: float           # in BB, 0 if fold/check
│   └── pot_before: float       # pot size in BB before this action
├── board: List[str]            # e.g. ["Ah", "Kd", "2c", "7s", "Jh"]
├── hero_hole_cards: List[str]  # e.g. ["As", "Kh"]
├── pot_type: str               # LIMP | SRP | 3BP | 4BP (see Pot Type below)
└── hero_net_bb: float          # hero's net chip change for the hand in BB
```

### Notes

- All chip amounts must be normalized to BB units during parsing
- Posts (blinds, antes) are recorded as actions but flagged separately — they are not decision points
- If hero is not present in a hand, skip it
- If the hand does not reach the flop, parse it but mark `reaches_flop: false` — Module 2 will filter these out
- Parser must be robust to malformed or incomplete hand histories — log and skip, do not crash

---

## Module 2 — Feature Extractor

### Responsibility

Walk through each hand's action sequence and emit one record per **postflop** decision point faced by the hero. A decision point is any moment where hero must act on the flop, turn, or river (excluding posting blinds and preflop decisions).

### Input

List of Hand objects from Module 1. Hands with `reaches_flop: false` are skipped entirely.

### Output

A list of Decision records. Each Decision contains:

```
Decision
├── hand_id: str
├── street: str                 # FLOP | TURN | RIVER
├── position: str               # UTG | MP | CO | BTN | SB | BB
├── pot_type: str               # LIMP | SRP | 3BP | 4BP
├── action_facing: str          # see Action Facing Taxonomy below
├── pot_size_bb: float          # pot size in BB at time of decision
├── stack_depth_bb: float       # hero's effective stack in BB
├── pot_size_bucket: str        # see bucketing below
├── stack_depth_bucket: str     # see bucketing below
├── num_players_in_hand: int    # players still in the hand
├── flop_archetype: str         # see Flop Archetype Taxonomy below
├── board_texture: BoardTexture # see Board Texture below (computed from flop cards only)
├── hero_action_taken: str      # fold | check | call | bet_small | bet_medium | bet_large | bet_overbet | raise_small | ...
├── hero_action_sizing_pct: float  # sizing as % of pot, null if fold/check/call
└── hero_realized_ev_bb: float  # net BB outcome of the hand attributed to this decision
```

### Pot Type

Determined from preflop action sequence:

```
LIMP:  one or more players limped, no raise before flop
SRP:   single raised pot (one raise preflop, called)
3BP:   3bet pot (one reraise preflop, called)
4BP:   4bet pot (two reraises preflop, called)
```

### Action Facing Taxonomy

Postflop actions facing hero must be bucketed consistently. Sizing buckets are expressed as a percentage of the pot at the time of the bet or raise.

```
Postflop:
  - CHECK (option to check)
  - BET_SMALL (bet ≤33% pot)
  - BET_MEDIUM (bet 33–67% pot)
  - BET_LARGE (bet 67–100% pot)
  - BET_OVERBET (bet >100% pot)
  - RAISE_SMALL (raise ≤33% of pot)
  - RAISE_MEDIUM (raise 33–67% of pot)
  - RAISE_LARGE (raise 67–100% of pot)
  - RAISE_OVERBET (raise >100% of pot)
  - DONK_BET (bet into preflop aggressor — any sizing, flagged separately)
```

### Pot Size Buckets

```
MICRO:   <5 BB
SMALL:   5–15 BB
MEDIUM:  15–40 BB
LARGE:   40–100 BB
DEEP:    >100 BB
```

### Stack Depth Buckets

```
SHORT:     <20 BB effective
MEDIUM:    20–50 BB effective
DEEP:      50–100 BB effective
VERY_DEEP: >100 BB effective
```

### Flop Archetype Taxonomy

The flop archetype is assigned once on the flop based on hero's hole cards and the flop board cards. It is **carried forward unchanged** to all turn and river decisions in the same hand. This anchors the hand category to the decision context at the point the hand was defined, not the current board state.

If a draw completes on the turn or river (e.g. a flush draw becomes a flush), the archetype remains the flop archetype — the completing street is captured by board texture and street dimensions.

Archetypes are organized into three broad tiers:

**Stronger than one pair**
1. `FLUSH` — flopped flush (hero holds two cards of the same suit, three of that suit on flop)
2. `STRAIGHT` — flopped straight
3. `SET_OR_FULL_HOUSE` — flopped set or full house (hero holds a pocket pair matching one board card, or the board trips hero's pair)
4. `TWO_PAIR` — both hole cards pair the board (note: two pair + draw combos are impossible since both hole cards are consumed making the two pair)

**One pair**
5. `TOP_PAIR` — hero pairs the highest board card
6. `OVERPAIR` — hero holds a pocket pair higher than all board cards
7. `MARGINAL_PAIR` — hero pairs a non-top board card, or holds a pocket pair lower than the top board card (includes underpairs to the board)

**Weaker than one pair**
8. `COMBO_DRAW` — flush draw + open-ended straight draw, no pair
9. `FLUSH_DRAW` — flush draw only, no pair
10. `OESD` — open-ended straight draw only, no pair
11. `TWO_OVERCARDS` — both hole cards are higher than all board cards, no draw
12. `WEAK_DRAW` — gutshot or backdoor draws only, no pair
13. `AIR` — no pair, no meaningful draw

**Priority ordering for overlapping categories**: stronger made hand always takes precedence over draws. Within made hands, use the highest applicable category. A hand that qualifies as both TOP_PAIR and FLUSH_DRAW is classified as TOP_PAIR — draw information is captured by board texture. The exception is COMBO_DRAW, FLUSH_DRAW, OESD, and WEAK_DRAW, which are only assigned when hero has no pair.

### Board Texture

Board texture is computed from the **three flop cards only** and does not change on later streets. It has four independent dimensions:

```
BoardTexture
├── color: RAINBOW | TWO_TONE | MONOTONE
├── connectedness: DISCONNECTED | SEMI_CONNECTED | CONNECTED
├── paired: bool
└── top_card: HIGH | MEDIUM | LOW
```

#### Color

Determined by the number of suits represented on the flop:

- `RAINBOW`: three different suits
- `TWO_TONE`: two cards of the same suit, one different
- `MONOTONE`: all three cards of the same suit

#### Connectedness

Connectedness is computed using a **kernel scan** that measures how densely the board cards cluster within straight-making windows.

Algorithm:
1. Extract the distinct card values from the flop (ignoring duplicates on paired boards)
2. If an Ace is present, add a ghost Ace with value 1 to capture wheel draws (A-2-3-4-5)
3. For each window W from 1 to 10 (window covers [W, W+4], reflecting the 5-card straight):
   - Count how many distinct board card values fall within [W, W+4]
   - Score the window: 0 cards → 0 pts, 1 card → 0 pts, 2 cards → 1 pt, 3 cards → 3 pts
4. Sum scores across all windows

This scoring reflects that two cards in a window share one straight connection, while three cards share multiple connections and score disproportionately more. The integral over all windows naturally weights central card values more than edge values, since middle cards appear in more windows.

Bucket thresholds (validated against canonical boards):
- `DISCONNECTED`: score 0–2 (e.g. K82, A72)
- `SEMI_CONNECTED`: score 3–6 (e.g. T92, T84, A54)
- `CONNECTED`: score ≥ 7 (e.g. T76, KQJ, 567)

**Important**: on paired boards, use only the distinct card values in the kernel scan. Do not double-count the paired card.

Reference scores for canonical boards:
```
K82:  0  → DISCONNECTED
A82:  1  → DISCONNECTED
A72:  1  → DISCONNECTED
J73:  2  → DISCONNECTED
T92:  4  → SEMI_CONNECTED
T84:  4  → SEMI_CONNECTED
A54:  6  → SEMI_CONNECTED
KQJ:  7  → CONNECTED
T76:  7  → CONNECTED
Q98:  7  → CONNECTED
J98:  9  → CONNECTED
QJT: 10  → CONNECTED
567: 11  → CONNECTED
```

#### Paired

A boolean flag. `true` if any two board cards share the same rank (includes trips boards, which are also treated as paired). `false` otherwise.

#### Top Card

Categorized by the highest-ranking card on the flop:

- `HIGH`: top card is A, K, or Q
- `MEDIUM`: top card is J, T, 9, or 8
- `LOW`: top card is 7 or below

### Realized EV Attribution

Attribute the full hand net outcome (in BB) to every postflop decision in that hand. This is a known approximation — it introduces noise but no systematic bias across a large sample.

For all-in situations, use equity-adjusted EV: `EV = (equity × pot) - amount_invested` rather than raw chip outcome, to reduce variance from runout luck.

### Configuration

The set of dimensions used to define a decision node must be configurable. The default set is:

```
[street, position, pot_type, action_facing]
```

Additional dimensions (pot_size_bucket, stack_depth_bucket, flop_archetype, board texture fields, num_players) can be toggled on or off via a config file. This allows the user to control granularity — more dimensions means finer nodes but smaller samples per node.

---

## Module 3 — Node Aggregator

### Responsibility

Group Decision records by node key, and for each node compute the full statistical profile across all actions taken.

### Input

List of Decision records from Module 2, plus the active dimension config.

### Output

A list of NodeProfile objects:

```
NodeProfile
├── node_key: dict              # the defining dimension values
├── total_hands: int            # total decisions at this node
├── action_profiles: dict[str, ActionProfile]
│   └── ActionProfile
│       ├── action: str
│       ├── count: int
│       ├── frequency: float    # count / total_hands
│       ├── mean_ev_bb100: float
│       ├── ev_ci_low: float    # 95% bootstrap CI lower bound
│       └── ev_ci_high: float   # 95% bootstrap CI upper bound
└── dominant_action: str        # action with highest frequency
```

### Bootstrap CI Implementation

For each action profile with n ≥ 10 samples:
- Resample with replacement 1000 times
- Compute mean EV for each resample
- CI bounds are the 2.5th and 97.5th percentiles

For n < 10, set CI to null and flag as low-confidence.

### Minimum Sample Threshold

Node profiles with `total_hands < 15` are retained in output but flagged as `low_sample: true`. They are excluded from triage ranking by default but can be included via config.

---

## Module 4 — Triage Analyzer

### Responsibility

Score each NodeProfile for leak likelihood using frequency anomaly detection and realized EV divergence signals. Produce a ranked triage report.

### Input

List of NodeProfile objects from Module 3.

### Scoring

Each node receives two independent scores, then a composite.

**Score A — Frequency Anomaly Score**

For each action in the node, compute a polarization penalty:

```
polarization(f) = 4 * f * (1 - f)
```

This is 0 when f=0 or f=1 (fully polarized) and 1 when f=0.5 (balanced). Invert it: `anomaly = 1 - polarization`. Average across all actions.

Additionally apply rule-based flags that override the score to maximum:
- River raise frequency < 5% (likely never bluffing)
- Fold frequency > 75% facing any postflop bet
- Bet frequency = 0% when first to act on any postflop street (never betting)

These thresholds are configurable.

**Score B — EV Divergence Score**

For nodes with ≥ 2 actions each having ≥ 15 samples:

```
ev_divergence = max(mean_ev per action) - min(mean_ev per action)
```

Normalized to a 0–1 scale using the 95th percentile EV divergence across all nodes as the ceiling.

Only count this score if the CI of at least one action excludes zero (i.e. the EV difference is statistically meaningful).

**Composite Score**

```
composite = 0.5 * score_A + 0.5 * score_B
```

Weights are configurable. Users who want to prioritize frequency anomalies over EV signals can adjust.

**Priority Multiplier**

Multiply composite score by:
- `frequency_in_dataset`: fraction of all decisions that occur at this node (higher frequency = higher priority)
- `street_weight`: River=1.5, Turn=1.3, Flop=1.1

**Final rank**: sort by `composite × frequency_in_dataset × street_weight` descending.

### Output — Triage Report

A structured report containing, for each node ranked by score:

```
Triage Entry
├── rank: int
├── node_key: dict
├── composite_score: float
├── frequency_in_dataset: float
├── total_hands: int
├── flags: List[str]           # e.g. ["NEAR_ZERO_BLUFF_FREQ", "HIGH_FOLD_FREQ"]
├── action_profiles: ...       # full action breakdown with EV and CI
└── hypothesis: str            # auto-generated plain English summary
```

The `hypothesis` field is a templated string generated from the flags and action profiles. Examples:

- "You fold to river bets 81% of the time from BB. This is likely too high. Consider whether your calling range is wide enough."
- "You never raise the river from BTN after calling a flop and turn bet. Bluff raise frequency is 0% (n=34). This spot warrants solver review."
- "Calling facing a flop BET_LARGE from OOP returns -42 BB/100 vs folding at -8 BB/100 (n=28 calls, n=41 folds). The EV gap suggests over-calling in this spot."

---

## Module 5 — Report Output (Stretch Goal)

A thin output layer that renders the triage report in human-readable formats:

- **CLI summary**: top N nodes printed to stdout with color coding
- **CSV export**: full NodeProfile data for external analysis
- **HTML report**: sortable table of triage entries with expandable action breakdowns

This module is low priority. Implement after Modules 1–4 are validated.

---

## Implementation Plan and Parallelism

### Phase 1 — Foundation (Sequential, ~1 week)

These must be done in order as each feeds the next.

**Step 1.1 — Define data models** *(1 engineer, 1–2 days)*
Define all dataclasses/Pydantic models: Hand, Action, Decision, NodeProfile, ActionProfile, Triage Entry. No logic — just schemas. This unblocks all parallel work in Phase 2. Write JSON serialization for each model so modules can be tested independently.

**Step 1.2 — Write test fixtures** *(1 engineer, 1–2 days, can start in parallel with 1.1)*
Create a small set of manually crafted hand histories (10–20 hands) in each supported format with known properties — e.g. a hand where hero folds river, a hand where hero makes a large river raise. These are used to validate all downstream modules. Ground truth Decision and NodeProfile outputs should be hand-computed for these fixtures. Fixtures must cover a range of flop archetypes, board textures, and pot types.

---

### Phase 2 — Core Modules (Parallel after Phase 1)

**Step 2.1 — Module 1: Parser backends** *(1 engineer per format)*
Each format parser is independent. Implement PokerStars first as the reference implementation. GGPoker and 888poker parsers can be implemented in parallel once the Hand schema is defined. Each parser must pass all fixture tests.

**Step 2.2 — Module 2: Feature Extractor** *(1 engineer)*
Implement the action-by-action walker and all feature computation: position detection, pot type detection, action facing taxonomy, flop archetype classification, board texture computation (color, connectedness via kernel scan, paired flag, top card category). This is the most logic-dense module. Validate against fixtures. Pay particular attention to the flop archetype priority ordering and the kernel scan edge cases (paired boards, wheel draws).

**Step 2.3 — Module 3: Node Aggregator** *(1 engineer)*
Implement grouping logic, ActionProfile computation, and bootstrap CI. This module only depends on the Decision schema, not on Modules 1 or 2, so it can be built and tested against synthetic Decision data in parallel.

**Step 2.4 — Configuration system** *(0.5 engineer)*
Implement the config file schema (YAML or JSON) that controls active node dimensions, minimum sample thresholds, scoring weights, and rule-based flag thresholds. Wire config into Modules 2, 3, and 4.

---

### Phase 3 — Triage and Integration (Sequential after Phase 2)

**Step 3.1 — Module 4: Triage Analyzer** *(1 engineer, 2–3 days)*
Implement scoring, ranking, flag detection, and hypothesis template generation. Requires NodeProfile output from Module 3.

**Step 3.2 — End-to-end integration** *(1 engineer, 1–2 days)*
Wire all modules into a single pipeline: `parse → extract → aggregate → triage → report`. Run against a real hand history dataset (several hundred hands minimum). Validate that output is sensible and nodes are correctly ranked.

**Step 3.3 — Validation pass** *(all engineers, 1 day)*
Manually inspect the top 10 triage entries against the raw hand histories. Confirm that flagged nodes correspond to real behavioral patterns. Adjust scoring weights and thresholds if output is miscalibrated.

---

### Phase 4 — Output and Hardening (Parallel)

**Step 4.1 — CLI and CSV output** *(0.5 engineer)*
**Step 4.2 — HTML report** *(0.5 engineer)*
**Step 4.3 — Parser robustness** *(0.5 engineer)* — edge cases, malformed histories, tournament vs cash game handling
**Step 4.4 — Performance** *(0.5 engineer)* — ensure pipeline handles 10,000+ hands without significant latency

---

## Parallelism Summary

```
Phase 1:  [1.1 Data Models] → [1.2 Fixtures]  (1.2 can start in parallel)
               ↓
Phase 2:  [2.1 Parsers] [2.2 Extractor] [2.3 Aggregator] [2.4 Config]  (all parallel)
               ↓
Phase 3:  [3.1 Triage] → [3.2 Integration] → [3.3 Validation]  (sequential)
               ↓
Phase 4:  [4.1 CLI] [4.2 HTML] [4.3 Robustness] [4.4 Performance]  (all parallel)
```

The critical path is: **1.1 → 2.2 → 3.1 → 3.2 → 3.3**.

---

## Technology Recommendations

- **Language**: Python 3.11+
- **Data models**: Pydantic v2
- **Data manipulation**: pandas for aggregation in Module 3
- **Statistics**: numpy + scipy for bootstrap CI
- **Config**: YAML via PyYAML or TOML via tomllib
- **Testing**: pytest with parametrized fixture tests
- **Output**: rich (CLI), pandas (CSV), Jinja2 (HTML)

---

## What This System Does Not Do

To be explicit about scope:

- It does **not** analyze preflop decisions — all analysis is postflop only
- It does **not** tell the player the correct action. It flags spots for review.
- It does **not** benchmark against GTO or solver output.
- It does **not** analyze villain tendencies or exploit reads.
- It does **not** account for game dynamics, reads, or live tells.
- It does **not** handle tournament ICM adjustments (cash game only in v1).

These are all valid future directions but are out of scope for v1.

---

## Success Criteria

The system is considered successful if:

1. Given a hand history of ≥ 500 hands, it produces a ranked triage list within 30 seconds
2. The top 5 ranked nodes, when manually inspected, each correspond to a real and identifiable behavioral pattern in the player's game
3. The hypothesis text for each flagged node is accurate and actionable
4. A player can take the node definition directly to a solver and run a meaningful study session

---

*End of specification.*
