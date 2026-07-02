"""Format-version handshake against the upstream dataset manifest.

mbPlumber consumes hands in the "ParsedHand JSONL v2" standard produced by
mbHUD. One level above the hands directory sits ``manifest.json``, whose
``format`` field declares the standard the data was written in. This module
validates that field so a mismatched exporter fails the run fast rather than
silently mis-parsing.

Failure policy:

* Format mismatch (manifest present, ``format`` != :data:`EXPECTED_FORMAT`):
  raise :class:`UnsupportedFormatError` -- a hard failure.
* Absent manifest, malformed manifest JSON, or missing ``format`` key: log a
  warning and proceed. These are degraded but non-fatal conditions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EXPECTED_FORMAT = "ParsedHand JSONL v2"

_MANIFEST_NAME = "manifest.json"


class UnsupportedFormatError(Exception):
    """Raised when the dataset manifest declares an unsupported format."""


def _manifest_path(data_path: Path) -> Path:
    """Resolve the manifest sitting one level above the hands directory.

    For a hands directory ``.../PokerData/hands`` the manifest is
    ``.../PokerData/manifest.json``; for a single file
    ``.../PokerData/hands/x.jsonl`` it is the same path (the file's
    grandparent).
    """
    hands_dir = data_path if data_path.is_dir() else data_path.parent
    return hands_dir.parent / _MANIFEST_NAME


def check_format(data_path: str | Path) -> None:
    """Validate the dataset's declared format against :data:`EXPECTED_FORMAT`.

    Raises :class:`UnsupportedFormatError` on a genuine format mismatch. An
    absent, malformed, or ``format``-less manifest is logged as a warning and
    tolerated, so this never crashes on a merely missing handshake.
    """
    manifest_path = _manifest_path(Path(data_path))

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "no manifest at %s; skipping format handshake", manifest_path
        )
        return

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("malformed manifest %s, proceeding (%s)", manifest_path, exc)
        return

    found_format = manifest.get("format")
    if found_format is None:
        logger.warning(
            "manifest %s has no 'format' key; skipping handshake", manifest_path
        )
        return

    if found_format != EXPECTED_FORMAT:
        raise UnsupportedFormatError(
            f"unsupported dataset format {found_format!r}; "
            f"expected {EXPECTED_FORMAT!r} (manifest: {manifest_path})"
        )
