# Coordination: ParsedHand JSONL Format Contract

**From:** the mbPlumber team
**To:** the mbHUD team
**Re:** the shared `ParsedHand JSONL v2` interchange format and a version-handshake request
**Status:** request for review + response (see [How to respond](#6-contact--how-to-respond))

Hi mbHUD team. mbPlumber now consumes your exported hands in production and has
started enforcing the format contract at load time. This document records
exactly what mbPlumber assumes about the format, asks you to treat the manifest
`format` field as a real version token, and lists a few documentation requests
and open questions. Nothing here requires an immediate code change on your side
— but please read section 3 (the handshake) and section 5 (open questions), and
correct anything in section 2 that is wrong.

---

## 1. Purpose & relationship

The two projects are siblings that share exactly one thing: a data format.

| | mbHUD | mbPlumber |
|---|---|---|
| Role | Lightweight **LIVE** stat tracker for ACR | Heavier **leak-triage analysis** app |
| Relationship to format | **Producer** | **Consumer** |
| Imports the other? | No | No |
| Interface | `mbhud export` → `~/PokerData/hands/*.jsonl` + `manifest.json` | reads that directory |

- **mbHUD is the producer.** Its parser (`poker_hud/hand_parser_v2.parse_hand`)
  turns raw ACR text into `ParsedHand` objects; `mbhud export`
  (`scripts/export_parsed_hands.py::run_export`) re-parses the raw histories and
  writes them out as JSON Lines to `~/PokerData/`.
- **mbPlumber is the consumer.** It never imports mbHUD code. Its *only*
  dependency on mbHUD is the `ParsedHand JSONL v2` format. It reads each record
  through `src/mbplumber/adapter/acr_jsonl.py` and maps it onto its own frozen
  internal `Hand` model.
- **The format is the contract.** Neither app reaches into the other. As long as
  the bytes in `~/PokerData/` conform to the spec at `~/PokerData/SCHEMA.md`,
  both sides are free to evolve independently.
- **mbPlumber will NOT be merged into mbHUD.** There is deliberately no
  `mbhud leaks` command. Keeping the heavy analysis app separate is what lets
  mbHUD stay lightweight and live-focused. This is an architectural decision, not
  a backlog item — please don't plan around eventually absorbing it.

---

## 2. Assumptions mbPlumber makes about the format

These are the concrete things mbPlumber relies on, derived from
`adapter/acr_jsonl.py` and `SCHEMA.md`. **If mbHUD changes any of these silently,
mbPlumber breaks or — worse — silently mis-analyzes.** Please flag any that are
inaccurate.

| # | Assumption | Why it matters / what breaks |
|---|---|---|
| 1 | **One JSON object per line.** Each `.jsonl` line is a complete, independent record; we stream line-by-line and never assume the file fits in memory. | A pretty-printed / multi-line record breaks `iter_hands`. |
| 2 | **All chip amounts are raw chips**, not normalized to BB. We divide by `metadata.big_blind` ourselves to get BB. | If amounts ever ship pre-normalized, every number in mbPlumber is off by a factor of `big_blind`. |
| 3 | **`metadata.big_blind` is present and > 0** on every record. We hard-fail a record whose `big_blind <= 0`. | It is our sole BB conversion factor; a zero/missing value voids the whole record. |
| 4 | **`metadata` shape:** `hand_id`, `hand_datetime` (format `"%Y/%m/%d %H:%M:%S UTC"`), `button_seat`, `small_blind`, `big_blind`, `players` (`{seat_str: name}`, keys are strings we `int()`), `stacks` (`{name: chips}`), `positions` (`{name: label}`). | We index `players` by string seat and look up `stacks`/`positions` by player name. A key rename or a datetime-format change breaks parsing of that field. |
| 5 | **`streets`** is a dict keyed `preflop`/`flop`/`turn`/`river`; a street is absent if not reached. Each street has `actions` (chronological) and `board_cards` (flop→3, turn→1, river→1, preflop→null). | We iterate streets in fixed order and read `board_cards` from the deepest populated street. We treat "no `flop` key" as "didn't reach flop." |
| 6 | **Action shape:** `player`, `action_type`, `amount`, `total_bet`, `is_all_in`. | We read all five per action. |
| 7 | **Raise `amount` is UNRELIABLE; we derive the increment from `total_bet`.** For a `raise`, we take `total_bet` as the player's cumulative street contribution and compute the incremental chips as `total_bet - (player's prior contribution on that street)`. We deliberately **ignore** the `amount` field on raises (it's the "raise-by" amount, net of the call and of dead blind/ante chips — not the increment we need). | If `total_bet` semantics change (e.g. it stops being cumulative, or becomes null on raises), our pot sizing and hero-invested totals go wrong **silently**. This is the single most fragile coupling — see the request in section 4 to document it. |
| 8 | For `bet` / `call` / `post_*`, **`amount` is the incremental chips** and `total_bet` is null. | We add `amount` straight into the running pot and per-street contribution. |
| 9 | **`win` and `receive` encode payouts**, carried in the action stream (not a separate ledger). `receive` = uncalled-bet return; `win` = pot award. We drop both from decision actions but use them to compute `hero_net_bb` and to record pot winners. | If payouts move out of the action stream or change type strings, hero net and pot-winner attribution break. |
| 10 | **Split pots are summed per player from `win`.** We accumulate `pot_winners[player] += win.amount` across all `win` actions, so multiple `win` rows for one player (or several players) are handled additively. | See open question in section 5 — please confirm split pots really are represented as multiple/independent `win` rows. |
| 11 | **`pot_before` is NOT in the data.** We reconstruct the running pot ourselves by walking actions + blinds, exactly as SCHEMA.md instructs. | We are not asking you to add it. Just don't start emitting a conflicting `pot_before` field expecting us to trust it. |
| 12 | **Posts are filterable.** `post_sb`/`post_bb`/`post_ante` are tagged distinctly so we can mark them `is_post` and exclude them from voluntary-decision analysis. | If posts stop being distinguishable from voluntary bets, our decision-point stats are polluted. |
| 13 | **`hero` and `hero_seat` are self-contained per record.** We read them off each record and never consult out-of-band config. We currently `int(hero_seat)` unconditionally. | See section 5: SCHEMA.md says `hero_seat` may be `null` when hero wasn't dealt in. That's a real edge we want to confirm the contract on. |
| 14 | **`metadata.positions[hero]` carries hero's position label**, which mbPlumber maps to its own position vocabulary (`features/positions.map_position`). | If the position label vocabulary changes or a position is missing for hero, mapping fails. See open question on label stability. |
| 15 | **`hole_cards`** is `{name: ["Xx","Yy"]}` for every player whose cards are known; hero's are present when hero is dealt in; villains' appear only at showdown. Cards are 2-char rank+suit. | We read hero's hole cards from here and pass all known cards through. |

> Note on strictness: `iter_hands`/`load_dir` catch per-record exceptions and
> skip bad lines with a warning, so a single malformed record won't crash a run.
> But a *systematic* format change would cause us to skip (or silently
> mis-adapt) **every** record — which is exactly what the manifest handshake in
> the next section is meant to catch loudly.

---

## 3. The manifest / version handshake — a request to mbHUD

mbPlumber now performs a **format-version handshake** before loading data
(`src/mbplumber/adapter/manifest.py`). It reads `manifest.json` one level above
the hands directory and checks the `format` field:

- `format == "ParsedHand JSONL v2"` → proceed.
- `format` present but **different** → **hard failure**
  (`UnsupportedFormatError`). We refuse to consume a format we don't recognize.
- manifest **absent**, malformed JSON, or **missing `format`** → log a warning
  and proceed (degraded, non-fatal).

**Why we did this:** it is our protection against silently consuming a changed
format. Given assumption #7 above, a schema change that we don't notice wouldn't
throw — it would just produce subtly wrong analysis. The `format` string is the
one cheap signal that lets us fail *loudly* the moment the contract moves.

**What we're asking mbHUD to do:**

1. **Treat `format` as a real version token and BUMP it on any breaking change.**
   If you change the record schema in a way that would change how a consumer must
   read it (rename/remove a field, change units, change `total_bet`/raise
   semantics, move payouts, etc.), bump the string — e.g. to
   `"ParsedHand JSONL v3"`. That trip-wire is what makes our hard-fail useful.
   Additive, backward-compatible changes (new optional field we can ignore) need
   not bump — but when in doubt, bump.
2. **Keep writing `manifest.json` on every export.** `export()` already does this
   unconditionally — please keep it that way. A missing manifest only downgrades
   us to a warning, so we lose the safety net silently.
3. **Document the format's change policy** in SCHEMA.md: state that `format` is
   the version token, that it bumps on breaking changes, and what counts as
   "breaking." That gives both teams a shared, written rule.

We are **not** asking you to add new fields or restructure anything today. We're
asking you to keep the version token honest so the handshake stays meaningful.

---

## 4. Requested changes / documentation on mbHUD's side

A concrete checklist. Priorities marked **[important]** vs *[nice-to-have]*.

| # | Request | Priority | Notes |
|---|---|---|---|
| 1 | Keep `SCHEMA.md` as the single source of truth, and version it alongside the `format` string (its header `**Version:** 2` should track the `v2`/`v3` token). | **important** | Today SCHEMA.md's version and the manifest `format` are maintained separately; keep them in lockstep. |
| 2 | Bump the `format` string on every breaking record-schema change (see section 3). | **important** | The handshake depends entirely on this. |
| 3 | Document the **"raise `amount` is unreliable — use `total_bet`"** quirk *in SCHEMA.md*. Right now this lives only as a comment in mbPlumber's adapter ("discovered against real data"). It should be part of the written contract, not folklore. | **important** | Specifically: for `raise`, `total_bet` is the cumulative street "to" amount and is the reliable field; `amount` is a "raise-by" figure that consumers should not treat as the pot increment. |
| 4 | Decide on a version token convention and stick to it: either keep the `format` string (`"ParsedHand JSONL vN"`) as *the* version token, **or** add an explicit `schema_version` integer to the manifest. Either is fine — pick one and document it. | *nice-to-have* | If you add `schema_version`, tell us and we'll read it; until then we key off `format`. |
| 5 | Confirm whether the `positions` label vocabulary is stable and enumerate the possible labels in SCHEMA.md. | *nice-to-have* | mbPlumber maps these labels; a documented, closed set lets us validate our mapping. |
| 6 | Note the `~/PokerData` default-location coupling in SCHEMA.md (both `export_parsed_hands.py` and mbPlumber default to it). If that default ever moves, it's a cross-project break. | *nice-to-have* | The exporter's `--out` and mbPlumber's data path both assume this location today. |
| 7 | Reply with any **planned** format changes so we can prepare adapters ahead of time rather than reacting to a hard-fail. | **important** | See section 6. |

---

## 5. Open questions for the mbHUD team

1. **Positions vocabulary** — Is the `metadata.positions` label set stable and
   enumerated (e.g. `BTN`, `SB`, `BB`, `UTG`, `MP`, `CO`, …)? What are the exact
   strings for 6-max vs 9-max? We map these and would like a closed set.
2. **Planned schema changes** — Are there any changes to the record schema on
   your roadmap (new fields, renames, unit changes, `total_bet` semantics)?
3. **Shared location** — Should `~/PokerData` become configurable and/or
   announced through the manifest (e.g. a canonical path field), rather than
   being a hard-coded default on both sides?
4. **`total_pot` / `rake` guarantees** — Are `total_pot` and `rake` guaranteed
   present and non-null on every record (including preflop-only / uncontested
   hands)? mbPlumber currently reconstructs pot state from actions and does not
   rely on `total_pot`, but we'd like to know if it's a dependable field.
5. **Split pots** — How exactly are split pots represented in `win` payouts? We
   sum per-player `win` amounts into `pot_winners` (assumption #10), which
   assumes each winner's share arrives as one or more `win` rows attributed to
   that player. Is that correct? Any chopped-pot rounding conventions we should
   know?
6. **`hero_seat` null case** — SCHEMA.md says `hero_seat` can be `null` when hero
   wasn't dealt in. mbPlumber currently does `int(raw["hero_seat"])`
   unconditionally, so such a record would be skipped (caught + warned) rather
   than handled. Does the export actually emit hero-absent records to
   `~/PokerData`, or are those filtered upstream? (This tells us whether we need
   to handle the null case explicitly.)

---

## 6. Contact / how to respond

Please respond by **editing this same file** — add a section below titled
`## mbHUD team response` — or by dropping a sibling doc in this repo and linking
it here. In your reply:

- **Correct any assumption in section 2 that is wrong.** Those are the ones that
  silently break us, so accuracy there matters most.
- Answer the open questions in section 5 where you can.
- Confirm you're on board with treating `format` as a real, bumped version token
  (section 3).
- List any planned format changes so we can stage adapters ahead of time.

Thanks — looking forward to keeping this contract clean on both sides.

— the mbPlumber team

---

## mbHUD team response

Thanks for the thorough writeup. We verified every assumption in section 2 against
the current parser (`poker_hud/hand_parser_v2.py`, `poker_hud/hand_structures.py`)
and against the full real export in `~/PokerData` (5,369 hands, 72 sessions). Below:
one correction that matters, confirmations, answers to all six open questions, and
our commitment on the version handshake. We also updated `SCHEMA.md` to match.

### TL;DR

- **One real mismatch:** the `positions` vocabulary is **not** `UTG/MP/CO`. It is a
  button-relative scheme: `BTN`, `SB`, `BB`, and `BTN-N`. Your `map_position` is
  almost certainly mis-mapping every non-blind/non-button seat today. Details below
  and now enumerated in `SCHEMA.md`. **This is the one to act on.**
- Everything else in section 2 is **accurate**, including the two fragile ones (#7
  raise `total_bet`, #10 split pots). We confirmed both against real data.
- We're **on board** with treating `format` as a real, bumped version token.
- **No breaking format changes are planned.** We are not changing the record schema.

### Corrections to section 2

**Assumption #14 (positions) — the label vocabulary is wrong in your mental model.**
mbHUD does not emit `UTG/MP/CO`. `calculate_position()` produces a closed,
button-relative set:

| Label | Meaning |
|---|---|
| `BTN` | button |
| `SB` | small blind (button + 1) |
| `BB` | big blind (button + 2) |
| `BTN-N` | N seats before the button; `N = 1 .. max_seats - 3` |

So the full closed set is:

- **6-max:** `BTN, SB, BB, BTN-1, BTN-2, BTN-3` (`BTN-1` = CO, `BTN-2` = HJ, `BTN-3` = UTG)
- **9-max:** `BTN, SB, BB, BTN-1, BTN-2, BTN-3, BTN-4, BTN-5, BTN-6`

Confirmed against the export — the only labels that appear are exactly
`{BTN, SB, BB, BTN-1..BTN-3}` (6-max) and `{…, BTN-4..BTN-6}` (9-max); nothing else.
The set is deterministic (pure function of seat/button/max_seats), stable, and now
enumerated in `SCHEMA.md`. We are **not** renaming these to `UTG/MP/CO` — the
button-relative scheme is the format's truth and mbHUD's own HUD depends on it.
Please update `map_position` to key off this set. (If a conventional-label field
would genuinely help, say so and we'll consider adding one *additively* — it would
be a new optional field, never a rename, so it wouldn't bump the version.)

**Everything else in section 2 is correct.** Explicit confirmations on the ones you
flagged as fragile:

- **#7 (raise `amount` unreliable, use `total_bet`) — CONFIRMED.** The parser reads
  ACR's `"raises $X to $Y"` and stores `amount = X` (the raise-by figure) and
  `total_bet = Y` (the cumulative street "to" amount). `total_bet` is the reliable
  field for a raise; `amount` is not the increment. Verified: 5,547 raise actions in
  the export, **0** with a null `total_bet`. Your read is exactly right, and this
  quirk is now written into `SCHEMA.md` (was previously only folklore).
- **#8 (bet/call `amount` incremental, `total_bet` null) — CONFIRMED.** `bet` and
  `call` actions carry the incremental chips in `amount` and leave `total_bet` null.
- **#9 (`receive`/`win` in the action stream) — CONFIRMED.** `receive` = uncalled-bet
  return (parsed from ACR's `"Uncalled bet ($X) returned to <player>"`); `win` = pot
  award (parsed from the SUMMARY `"... won $X"` lines, appended to the last street).
- **#10 (split pots = multiple independent `win` rows) — CONFIRMED.** Each SUMMARY
  win line becomes its own `win` Action. Multiple winners ⇒ multiple `win` rows, one
  per winner. Summing per player into `pot_winners` is correct. Verified: 65 hands in
  the export carry more than one `win` row.
- **#12 (posts are distinctly tagged) — CONFIRMED.** `post_sb` / `post_bb` /
  `post_ante` are separate `action_type`s; they're never conflated with `bet`.

### Answers to section 5 open questions

1. **Positions vocabulary** — Stable, closed, enumerated (see correction above and
   `SCHEMA.md`). Button-relative `BTN/SB/BB/BTN-N`, **not** `UTG/MP/CO`.
2. **Planned schema changes** — **None.** No renames, no unit changes, no
   `total_bet` semantic changes on the roadmap. If that changes we'll bump `format`
   and tell you first (section 6).
3. **Shared `~/PokerData` location** — Today it's a hard-coded default on both sides
   (`export_parsed_hands.py::DEFAULT_OUT_DIR` and your data path). We've documented
   the coupling in `SCHEMA.md` for now. Making it a manifest-announced canonical path
   is a reasonable future step; we're open to it but it's not urgent, and it would be
   additive (a new manifest field) rather than breaking.
4. **`total_pot` / `rake` guarantees** — Both are **always present and non-null**,
   including preflop-only / uncontested hands. They're parsed from the SUMMARY
   `"Total pot $X | Rake $Y"` line and default to `0.0` (not null) if absent. Verified:
   **0** null `total_pot` and **0** null `rake` across all 5,369 records. So they're
   dependable if you ever want them — though your walk-the-actions reconstruction is
   equally valid and we won't break it.
5. **Split pots** — See #10 above: one `win` row per winner, attributed to that
   player, carried in the action stream. Your additive `pot_winners` accumulation is
   correct. Rounding: amounts are taken verbatim from ACR's SUMMARY (raw chips, no
   re-rounding on our side), so chop remainders are however ACR already distributed
   them — we don't synthesize or redistribute.
6. **`hero_seat` null case** — It's a **real contract possibility** but **not
   currently exercised**. `find_hero_seat` returns `None` (→ `null`) when hero isn't
   dealt in, and the exporter *does* write those records (it does not filter
   hero-absent hands). In the current export it never triggers (0/5,369 null) only
   because `hero = config.USERNAME` and every session is hero's own play. But a
   different `--hero`, or a session containing hands where hero sat out, would emit
   `hero_seat: null`. **Recommendation: handle the null explicitly** rather than
   `int()`-ing unconditionally — the record is otherwise valid (villain-only hand),
   and your current code skips it with a warning. The contract permits null; don't
   rely on it never appearing.

### Section 3 handshake — confirmed

Yes. We treat `format` as the real version token and will **bump it on any breaking
record-schema change** (rename/remove field, unit change, `total_bet`/raise semantic
change, payout relocation). Additive optional fields will **not** bump. We keep
`SCHEMA.md`'s `**Version:**` header in lockstep with the `vN` token, and `export()`
keeps writing `manifest.json` unconditionally on every run. This policy is now
documented in `SCHEMA.md` itself so it's a written rule, not a handshake living only
in this thread.

### Section 4 checklist — status

- **#1** SCHEMA.md as single source of truth, version in lockstep — **done** (policy
  section added; header tracks the token).
- **#2** Bump `format` on breaking changes — **committed** (above).
- **#3** Document the raise-`amount`-unreliable quirk in SCHEMA.md — **done.**
- **#4** Version-token convention — we're **keeping the `format` string** (`"ParsedHand
  JSONL vN"`) as *the* token; not adding a separate `schema_version` integer. Keep
  keying off `format`.
- **#5** Enumerate positions — **done** (closed set in SCHEMA.md).
- **#6** Note the `~/PokerData` location coupling — **done.**
- **#7** Planned changes — **none** (above).

— the mbHUD team
