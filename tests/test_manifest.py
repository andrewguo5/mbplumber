"""Tests for the format-version handshake (adapter.manifest).

The handshake reads ``manifest.json`` sitting one level above the hands
directory and hard-fails only on a genuine format mismatch. Absent,
malformed, or ``format``-less manifests degrade to a warning-and-proceed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbplumber.adapter.manifest import (
    EXPECTED_FORMAT,
    UnsupportedFormatError,
    check_format,
)


def _make_dataset(root: Path, manifest: dict | None) -> Path:
    """Build a ``root/hands/`` layout, optionally writing ``root/manifest.json``.

    Returns the hands directory to point :func:`check_format` at.
    """
    hands_dir = root / "hands"
    hands_dir.mkdir()
    if manifest is not None:
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return hands_dir


def test_matching_manifest_passes(tmp_path):
    hands_dir = _make_dataset(tmp_path, {"format": EXPECTED_FORMAT})
    # No exception is a pass.
    check_format(hands_dir)


def test_mismatched_format_raises(tmp_path):
    hands_dir = _make_dataset(tmp_path, {"format": "ParsedHand JSONL v1"})
    with pytest.raises(UnsupportedFormatError) as exc_info:
        check_format(hands_dir)
    message = str(exc_info.value)
    assert "ParsedHand JSONL v1" in message  # found format named
    assert EXPECTED_FORMAT in message  # expected format named


def test_absent_manifest_does_not_raise(tmp_path):
    hands_dir = _make_dataset(tmp_path, manifest=None)
    check_format(hands_dir)  # warns and proceeds


def test_manifest_missing_format_key_does_not_raise(tmp_path):
    hands_dir = _make_dataset(tmp_path, {"version": 2})
    check_format(hands_dir)  # warns and proceeds


def test_single_file_resolves_grandparent_manifest(tmp_path):
    hands_dir = _make_dataset(tmp_path, {"format": EXPECTED_FORMAT})
    hand_file = hands_dir / "x.jsonl"
    hand_file.write_text("", encoding="utf-8")
    check_format(hand_file)  # manifest is the file's grandparent


def test_malformed_manifest_json_does_not_raise(tmp_path):
    hands_dir = tmp_path / "hands"
    hands_dir.mkdir()
    (tmp_path / "manifest.json").write_text("{not valid json", encoding="utf-8")
    check_format(hands_dir)  # warns and proceeds
