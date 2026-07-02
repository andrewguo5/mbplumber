# Distribution Guide for mbPlumber

mbPlumber is a poker leak-triage analysis tool. It is an independent **consumer**
of the **ParsedHand JSONL v2** format produced by [mbHUD](../mbHUD)'s
`mbhud export`; it never imports mbHUD code. See `README.md` for what it does and
`mbplumber_spec.md` for the full spec.

---

## Building the package

From the repo root:

```bash
python3 -m build
```

This creates:
- `dist/mbplumber-<version>-py3-none-any.whl` (wheel — the artifact to share)
- `dist/mbplumber-<version>.tar.gz` (source distribution — optional)

`build` is available as a dev extra: `pip install -e '.[dev]'`.

The wheel is **self-contained**: all default configuration lives in the pydantic
model (`mbplumber/config.py`), so a fresh install runs with zero config files.
`config/default.yaml` in the repo is a reference example, not required at runtime.

---

## Installing

From the wheel (what you give to others):

```bash
pip install mbplumber-<version>-py3-none-any.whl
```

For local development (editable):

```bash
pip install -e '.[dev]'
```

**Requirements:** Python 3.11+.

---

## Running

The install provides an `mbplumber` console command:

```bash
# Explicit data path:
mbplumber --data ~/PokerData/hands --top 25 --explorer explorer.html

# Zero-arg: falls back through MBPLUMBER_DATA env var -> config -> ~/PokerData/hands
mbplumber --top 25
```

### Data source resolution

mbPlumber finds its hand data in this order (highest priority first):

1. `--data <path>` CLI flag
2. `MBPLUMBER_DATA` environment variable
3. `input.data_source` in a `--config` YAML
4. `~/PokerData/hands` (mbHUD's default export location)

So once mbHUD has exported to its default location, `mbplumber` runs with no
arguments.

---

## The mbHUD relationship

mbPlumber and mbHUD are **separate apps** joined only by the ParsedHand JSONL v2
format. mbHUD stays a lightweight live stat tracker and emits the format via
`mbhud export`; mbPlumber consumes it. mbPlumber validates the format version it
reads from `manifest.json` and refuses to run on an unrecognized version — see
`COORDINATION_mbHUD.md` for the format contract and coordination notes.

---

## Releasing

To cut a release:

1. Bump `version` in `pyproject.toml`.
2. `python3 -m build`
3. Verify the wheel installs and runs in a clean environment:
   ```bash
   python3 -m venv /tmp/mbp-verify
   /tmp/mbp-verify/bin/pip install dist/mbplumber-<version>-py3-none-any.whl
   /tmp/mbp-verify/bin/mbplumber --data ~/PokerData/hands --top 3
   ```
4. Attach the wheel to a GitHub release (mirrors mbHUD's distribution flow), or
   share the wheel file directly.
