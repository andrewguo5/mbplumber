# Playtester Guide — mbHUD + mbPlumber

Thanks for testing! This walks you through the **full flow**: track your poker
sessions with **mbHUD**, then see your likely leaks on the **mbPlumber** screen.

## The two tools

- **mbHUD** — watches your Americas Cardroom (ACR) play and tracks live stats. It
  can also *export* your parsed hands to a shared folder.
- **mbPlumber** — reads that export and shows you a **ranked list of your likely
  leaks** plus a **navigable decision-tree explorer**. This is the screen we most
  want your feedback on.

They connect through one shared folder (`~/PokerData/`). Once both are installed,
the handoff is automatic — you don't wire anything up.

```
   You play on ACR
        │
        ▼
  ┌──────────┐  mbhud export   ┌──────────────┐   mbplumber   ┌──────────────────┐
  │  mbHUD    │ ──────────────▶ │  ~/PokerData/ │ ────────────▶ │  mbPlumber screen │
  │ (tracker) │  JSONL + manifest│  (shared)    │   reads it    │ (report + explorer)│
  └──────────┘                 └──────────────┘               └──────────────────┘
```

**Requirements:** Python 3.11+ · Americas Cardroom client with hand-history
saving enabled.

---

## Part A — One-time setup

**1. Install both tools.**

```bash
# mbHUD (the tracker)
pip3 install https://github.com/andrewguo5/mbHUD/releases/download/v0.4.0/mbhud-0.4.0-py3-none-any.whl

# mbPlumber (the leak screen)
pip3 install https://github.com/andrewguo5/mbplumber/releases/download/v0.1.0/mbplumber-0.1.0-py3-none-any.whl
```

Check both installed:

```bash
mbhud --help
mbplumber --help
```

> If a command isn't found, your Python `Scripts`/`bin` folder likely isn't on
> your PATH. See mbHUD's README troubleshooting section.

**2. Configure mbHUD** (asks for your ACR username + hand-history folder, then
processes your existing hands):

```bash
mbhud init
```

---

## Part B — Play & track (each session)

**3. Start the live HUD, then go play on ACR:**

```bash
mbhud start          # flushes, then watches ACR and updates stats live
```

- Join a table on ACR. Stats update **after each completed hand** (there's always
  a 1-hand delay).
- When you're done, **stop the tracker** (Ctrl-C), then save what it saw:

```bash
mbhud flush          # persists the hands from your live session
```

> ⚠️ Don't skip this flush. The live tracker holds new hands in memory; without
> the flush they won't reach the mbPlumber screen.

---

## Part C — See the mbPlumber screen (the payoff)

**4. Export your hands for mbPlumber:**

```bash
mbhud export         # writes ~/PokerData/hands/*.jsonl + manifest.json
```

**5. Run mbPlumber.** No paths needed — it defaults to mbHUD's export location:

```bash
mbplumber --top 25 --html report.html --explorer explorer.html
```

**6. Open the two views:**

```bash
open report.html      # ranked triage table — your top candidate leaks
open explorer.html    # navigable decision-tree explorer
```

- **`report.html`** — a ranked list of the decision spots most worth studying,
  each with flags and a short reason.
- **`explorer.html`** — the deep view. A collapsible tree
  (street › in-position/out-of-position › pot type › action faced); **every node
  shows its mean realized EV in BB**, so you scan for the red numbers. Click a
  leaf → per-action EV table → click an action → the individual hands you took it
  in → click a hand → **full hand detail** (your hole cards, the board, every
  player's action per street, and who won the pot). Lets you reconcile the EV
  against real hands by eye.

---

## The order matters

If the mbPlumber screen looks empty or stale, it's almost always the sequence.
The pipeline is:

```
mbhud start → (play) → Ctrl-C → mbhud flush → mbhud export → mbplumber
```
