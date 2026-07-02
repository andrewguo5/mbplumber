# mbPlumber — Issue Tracker

Lightweight backlog for known bugs and follow-ups. Not a git repo, so this file
is the tracker. Newest issues on top. Mark resolved ones `[x]` with a date.

---

## Open

_(none)_

---

## Resolved

### [x] #4 — mbHUD coordination reply reconciled (position vocab all-clear) — 2026-07-02
- **Component:** `src/mbplumber/features/positions.py` + `tests/test_positions.py`
  + `COORDINATION_mbHUD.md`.
- **Context:** mbHUD replied in `COORDINATION_mbHUD.md` (`## mbHUD team response`).
  Their one flagged mismatch: the `positions` vocabulary is button-relative
  (`BTN, SB, BB, BTN-N`, `N = 1 .. max_seats-3`), **not** `UTG/MP/CO`, and they
  warned `map_position` was "almost certainly mis-mapping every non-blind seat."
- **Finding:** **No bug.** `positions.py` already keys off exactly the
  button-relative labels; assumption #14's `UTG/MP/CO` phrasing was our *mental
  model* in the doc, not the code. Verified against the real export — the only
  labels present are `{BTN, SB, BB, BTN-1..BTN-6}`, all correctly mapped.
- **Action taken:** Added a closed-set contract test
  (`test_mbhud_enumerated_vocabulary_is_fully_mapped` +
  `test_labels_outside_the_enumerated_vocabulary_are_rejected`) pinning mbHUD's
  enumerated vocabulary so a future drift on either side fails loudly. All other
  section-2 assumptions were CONFIRMED by mbHUD (incl. #7 `total_bet`, #10 split
  pots); the `format` handshake holds (`ParsedHand JSONL v2`, SCHEMA v2) and
  mbHUD committed to bumping `format` on breaking changes with **none planned**.
- **Severity:** contract reconciliation — no code defect; net all-clear.
- **Found:** 2026-07-02, on reading mbHUD's coordination reply.

### [x] #3 — Adapter crashes on schema-legal `hero_seat: null` — 2026-07-02
- **Component:** `src/mbplumber/adapter/acr_jsonl.py` (`adapt_hand`) +
  `models.py` (`Hand.hero_seat`) + `pipeline.py` (`build_decisions`).
- **Symptom:** A record with `hero_seat: null` (hero not dealt in — allowed by
  `~/PokerData/SCHEMA.md`) raised `TypeError` in `int(None)`; the pipeline caught
  it and *silently skipped* the hand as a "parse failure".
- **Cause:** `hero_seat=int(raw["hero_seat"])` assumed a non-null value, and
  `Hand.hero_seat` was typed `int`.
- **Fix:** `Hand.hero_seat` widened to `int | None`; adapter casts via a new
  `_opt_int` helper that preserves `None`; `build_decisions` now skips
  hero-absent hands **explicitly**, counted under a new `no_hero` stat (before
  the flop check), instead of via a swallowed exception.
- **Guard:** `tests/test_adapter.py::test_adapt_hand_null_hero_seat_becomes_none`
  (adapter) and `::test_pipeline_skips_hero_absent_hand` (pipeline skip + stat).
- **Severity:** was latent robustness — no current data hit it
  (`hands_with_hero == total_hands`), but a future export could.
- **Found:** 2026-07-02, by the mbHUD coordination-doc pass.

### [x] #2 — IP/OOP misclassified by phantom preflop-folders — 2026-06-24
- **Component:** `src/mbplumber/features/extractor.py` (`in_hand` construction →
  `_hero_is_ip`)
- **Symptom:** Found via the explorer: hands in **RIVER / OOP / CHECKED_TO**
  (an impossible heads-up combo) where the per-hand drill-down clearly shows
  hero acting in position. 36 RIVER decisions affected; 188/1318 hands (14%)
  carried a phantom contender.
- **Cause:** `in_hand` (the flop contender set used to compute hero's IP/OOP)
  was built as `players − {explicit preflop folds}`. Some preflop folders —
  e.g. a blind that folds — emit **no `fold` action**, so they stayed in the
  set as "phantom" contenders. A phantom seated after hero in the postflop
  act-order stole the last-to-act slot, flipping hero **IP → OOP**.
  `action_facing` is computed live per street and correctly read CHECKED_TO,
  producing the contradiction. (Also inflated `num_players_in_hand`.)
- **Fix:** Intersect `in_hand` with players who actually reached the flop —
  i.e. took any postflop non-post action, plus hero:
  `in_hand = (players − folded) & reached_flop`. Verified this drops **zero**
  legitimate contenders (no pot-winner who reached showdown is ever excluded).
  Moved 43 decisions OOP→IP; 208 OOP+CHECKED_TO remain and are the *legit*
  "IP-side player folded on a later street" pattern (IP is a flop-level
  property by design, facing is per-street), confirmed phantom-free.
- **Guard:** `tests/test_extractor_ip.py::test_phantom_preflop_folder_does_not_
  flip_hero_to_oop` (confirmed to fail if the fix is reverted).
- **Severity:** data-correctness (mislabeled IP/OOP on ~14% of hands).

### [x] #1 — Explorer: action label disappears when toggling the per-hand breakdown — 2026-06-24
- **Component:** `src/mbplumber/report_explorer.py` (detail-pane action rows)
- **Symptom:** In the decision-node explorer, clicking an action row to
  expand/collapse its individual-hand breakdown causes the action label (e.g.
  `call`, `bet_large`) to vanish — only the caret remains.
- **Cause:** The action cell renders as a single text node `"▸ <action>"`. The
  toggle handler does `tr.querySelector('td').firstChild.textContent = '▸ '`,
  which overwrites that whole text node, dropping the action name with it.
- **Fix sketch:** Don't rewrite the cell's text node. Either (a) wrap the caret
  in its own `<span class="acaret">` and toggle only that span's text, leaving
  a separate label node intact, or (b) toggle a CSS class on the row and render
  the caret via `::before`. Option (a) is the smaller change.
- **Severity:** cosmetic (no data wrong; expand/collapse still works).
