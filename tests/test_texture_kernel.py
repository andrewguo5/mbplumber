"""Lock the kernel-scan reference scores and the texture dimensions."""

import pytest

from mbplumber.features.texture import board_texture
from mbplumber.models import Color, Connectedness, TopCard

# (flop string, expected kernel score). Suits chosen rainbow unless paired.
_REFERENCE = [
    ("K82", 0),
    ("A82", 1),
    ("A72", 1),
    ("J73", 2),
    ("T92", 4),
    ("T84", 4),
    ("A54", 6),
    ("KQJ", 7),
    ("T76", 7),
    ("Q98", 7),
    ("J98", 9),
    ("QJT", 10),
    ("567", 11),
]

_SUITS = ["h", "d", "c"]


def _flop(s: str) -> list[str]:
    return [r + _SUITS[i] for i, r in enumerate(s)]


@pytest.mark.parametrize("flop_str,expected", _REFERENCE)
def test_kernel_score_reference(flop_str, expected):
    tex = board_texture(_flop(flop_str))
    assert tex.kernel_score == expected, f"{flop_str}: {tex.kernel_score} != {expected}"


@pytest.mark.parametrize(
    "flop_str,expected",
    [
        ("K82", Connectedness.DISCONNECTED),
        ("A72", Connectedness.DISCONNECTED),
        ("T92", Connectedness.SEMI_CONNECTED),
        ("A54", Connectedness.SEMI_CONNECTED),
        ("T76", Connectedness.CONNECTED),
        ("567", Connectedness.CONNECTED),
    ],
)
def test_connectedness_buckets(flop_str, expected):
    assert board_texture(_flop(flop_str)).connectedness == expected


def test_color():
    assert board_texture(["Ah", "Kd", "2c"]).color == Color.RAINBOW
    assert board_texture(["Ah", "Kh", "2c"]).color == Color.TWO_TONE
    assert board_texture(["Ah", "Kh", "2h"]).color == Color.MONOTONE


def test_paired():
    assert board_texture(["Ah", "Ad", "2c"]).paired is True
    assert board_texture(["Ah", "Ad", "As"]).paired is True  # trips
    assert board_texture(["Ah", "Kd", "2c"]).paired is False


def test_top_card():
    assert board_texture(["Ah", "Kd", "2c"]).top_card == TopCard.HIGH
    assert board_texture(["Qh", "Kd", "2c"]).top_card == TopCard.HIGH
    assert board_texture(["Jh", "Td", "2c"]).top_card == TopCard.MEDIUM
    assert board_texture(["8h", "5d", "2c"]).top_card == TopCard.MEDIUM
    assert board_texture(["7h", "5d", "2c"]).top_card == TopCard.LOW


def test_paired_board_no_double_count():
    # 882: distinct values {8,2}. Windows containing both: none within 5 (8-2=6).
    tex = board_texture(["8h", "8d", "2c"])
    assert tex.kernel_score == 0
    assert tex.paired is True
