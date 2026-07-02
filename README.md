# mbPlumber

mbPlumber is an independent **consumer** of the **ParsedHand JSONL v2** standard
produced by mbHUD. It never imports mbHUD code — it depends only on the format
(the contract, documented in `~/PokerData/SCHEMA.md`), of which mbHUD is one
producer and mbPlumber is one consumer.

It triages a player's hand history into a ranked list of candidate "leak" spots
for solver study, using two internally-observable signals per decision node:
**frequency anomalies** and **realized-EV divergence**. It does *not* benchmark
against GTO — it does the triage; the solver does the confirmation.

See `mbplumber_spec.md` for the full specification.

## Status

- **Input**: ACR (Americas Cardroom) hand histories in the standardized
  `ParsedHand JSONL v2` format (`../PokerData/`). This JSONL *is* Module-1
  (parser) output, so an **adapter** maps it to the spec's `Hand` schema and
  Modules 2–4 + a CLI run on top.
- Implemented: adapter, Module 2 (feature extractor), Module 3 (node
  aggregator), Module 4 (triage analyzer), a `rich` CLI summary, an HTML triage
  report, and an HTML **decision-node tree explorer**.
- 151 tests pass.

## Install & run

```bash
pip install -e .            # or: pip install pydantic numpy scipy pyyaml rich pytest
python -m mbplumber.cli --data ../PokerData/hands --config config/default.yaml --top 25
```

Useful flags:
- `--html report.html` — write the ranked HTML triage report.
- `--explorer explorer.html` — write the **decision-node tree explorer**: a
  two-pane page that lets you walk the decision tree (street › IP/OOP › pot type
  › action facing › …, following the active node dimensions) and, at any leaf,
  see the per-action EV breakdown *and* the individual hands behind each action.
  Click an action row to expand which hands you took it with — the direct way to
  judge whether an EV gap is a real leak or just hand selection.
- `--dimensions street,position,pot_type,action_facing` — override the node key
  (coarser keys pool more hands per node; finer keys split samples thinner). The
  explorer tree re-shapes itself to whatever dimensions are active.
- `--include-low-sample` — rank nodes below the sample threshold too.
- `-v` — log adapt/extract warnings.

Run the tests:

```bash
PYTHONPATH=src python -m pytest -q
```

## Architecture

```
ACR JSONL ─[adapter]─► Hand ─[extractor]─► Decision ─[aggregator]─► NodeProfile ─[triage]─► TriageEntry ─► CLI / HTML report
                                              │
                                              └─[explorer.build_tree]─► decision tree ─► HTML explorer
```

`src/mbplumber/models.py` is the shared, frozen type contract every module depends on.

## Notes / known limitations

- **Position is IP/OOP by default, not 6-way seat names.** The default node key
  uses `in_position` (IP = hero is last to act on the flop). The 6-way
  `position` is an optional toggle (`optional_dimensions.position: true`).
- **The "no-bet" facing is split** into `FIRST_TO_ACT` (hero opens the street —
  the OOP lead spot) and `CHECKED_TO` (action checked to hero). There is no
  generic "CHECK" facing; you can't "face a check" while first to act.
- **Per-decision EV.** Each decision is valued by its realized result vs folding
  (=0), counting the pre-existing pot consistently: check-win = +P, bet-called-
  win = +P + matched, bet-called-lose = −bet, bet-fold = +P (not inflated),
  fold/check-lose = 0; all-ins blend by equity. Folds are exactly 0, checks
  never negative. The "matched" term (M) accrues **only to bets/raises** — a
  check/call induces nothing, so a won check is valued at +P alone (it does not
  pick up villain chips that arrive after the check).
- **EV-divergence (Score B) is confounded by hand selection.** Comparing
  realized EV *across actions* at a node favors actions hero takes with stronger
  hands (the spec's intro warns realized EV can't escape this). **Trust the
  rule-based flags (Score A) over the EV-divergence hypotheses.**
- **Flag prioritization**: by default, nodes that fire a rule-based flag
  (`HIGH_FOLD_FREQ`, `NEAR_ZERO_BLUFF_FREQ`, `NEVER_BET`) are ranked above
  unflagged high-volume nodes. Set `triage.prioritize_flagged: false` for pure
  spec ordering.
- **Granularity vs sample size**: at the default 4-dimension node key, most
  flagged leaks fall below the 15-hand low-sample threshold and are filtered
  out. Coarser keys (drop `pot_type`, or merge sizing) surface more, at the cost
  of mixing distinct spots. This is the spec's intended configurability knob.
- **All-in equity**: exact runout enumeration for flop/turn/river all-ins;
  deterministic Monte Carlo (10k samples) for early all-ins where exact
  enumeration is prohibitive. Multiway side pots ignored (hero-vs-field).
```
