"""Tests for ACR position-label mapping (Unit A)."""

from __future__ import annotations

import pytest

from mbplumber.features.positions import map_position
from mbplumber.models import Position


@pytest.mark.parametrize(
    "label,expected",
    [
        ("SB", Position.SB),
        ("BB", Position.BB),
        ("BTN", Position.BTN),
        ("BTN-1", Position.CO),
        ("BTN-2", Position.MP),
        ("BTN-3", Position.UTG),
        # Deeper offsets (full-ring) collapse to UTG.
        ("BTN-4", Position.UTG),
        ("BTN-5", Position.UTG),
        ("BTN-6", Position.UTG),
    ],
)
def test_map_position_known_labels(label, expected):
    assert map_position(label) == expected


def test_map_position_is_case_and_whitespace_insensitive():
    assert map_position(" btn-1 ") == Position.CO
    assert map_position("sb") == Position.SB


@pytest.mark.parametrize("bad", ["", "UTG", "BTN-7", "EP", "CO", "X", "BTN-"])
def test_map_position_unknown_raises_value_error(bad):
    with pytest.raises(ValueError):
        map_position(bad)


def test_map_position_non_string_raises():
    with pytest.raises(ValueError):
        map_position(None)  # type: ignore[arg-type]


def test_every_mapped_value_is_a_position_enum():
    for label in ["SB", "BB", "BTN", "BTN-1", "BTN-2", "BTN-3", "BTN-4", "BTN-5", "BTN-6"]:
        assert isinstance(map_position(label), Position)


# The button-relative position vocabulary is a closed set, confirmed by the
# mbHUD team in COORDINATION_mbHUD.md (2026-07-02): calculate_position() emits
# exactly BTN, SB, BB, and BTN-N with N = 1 .. max_seats - 3. For 9-max that is
# BTN-1..BTN-6; nothing else appears in the export. This test pins that contract
# so a future vocabulary change (on either side) fails loudly instead of
# silently mis-bucketing seats.
MBHUD_POSITION_VOCABULARY = frozenset(
    {"BTN", "SB", "BB", "BTN-1", "BTN-2", "BTN-3", "BTN-4", "BTN-5", "BTN-6"}
)


def test_mbhud_enumerated_vocabulary_is_fully_mapped():
    """Every label mbHUD can emit maps to a Position without error."""
    for label in MBHUD_POSITION_VOCABULARY:
        assert isinstance(map_position(label), Position)


def test_labels_outside_the_enumerated_vocabulary_are_rejected():
    """Labels outside mbHUD's closed set — including UTG/MP/CO — must raise.

    mbHUD explicitly does NOT emit conventional labels (UTG/MP/CO); accepting
    them would mask a vocabulary drift, so the mapper rejects them.
    """
    for conventional in ["UTG", "MP", "CO", "HJ", "LJ"]:
        assert conventional not in MBHUD_POSITION_VOCABULARY
        with pytest.raises(ValueError):
            map_position(conventional)
    # One seat deeper than any real 9-max table is likewise out of contract.
    with pytest.raises(ValueError):
        map_position("BTN-7")
