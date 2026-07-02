"""One case per archetype plus the priority/edge cases called out in the spec."""

from mbplumber.features.archetype import flop_archetype
from mbplumber.models import FlopArchetype as FA


def test_flush():
    assert flop_archetype(["Ah", "Kh"], ["2h", "7h", "9h"]) == FA.FLUSH


def test_flush_monotone_two_suited():
    # monotone flop, hero holds two of that suit -> FLUSH
    assert flop_archetype(["Ah", "Th"], ["2h", "7h", "9h"]) == FA.FLUSH


def test_straight():
    # hero 6-7, flop 5-8-9 -> 5,6,7,8,9
    assert flop_archetype(["6c", "7d"], ["5h", "8s", "9c"]) == FA.STRAIGHT


def test_wheel_straight():
    assert flop_archetype(["Ac", "2d"], ["3h", "4s", "5c"]) == FA.STRAIGHT


def test_set():
    assert flop_archetype(["8c", "8d"], ["8h", "2s", "Kc"]) == FA.SET_OR_FULL_HOUSE


def test_set_beats_two_pair_priority():
    # pocket pair sets; not two pair
    assert flop_archetype(["9c", "9d"], ["9h", "Ks", "2c"]) == FA.SET_OR_FULL_HOUSE


def test_two_pair():
    assert flop_archetype(["Kc", "7d"], ["Kh", "7s", "2c"]) == FA.TWO_PAIR


def test_top_pair():
    assert flop_archetype(["Kc", "5d"], ["Kh", "8s", "2c"]) == FA.TOP_PAIR


def test_top_pair_beats_flush_draw_priority():
    # pairs top card AND has a flush draw -> TOP_PAIR
    assert flop_archetype(["Kh", "5h"], ["Kd", "8h", "2h"]) == FA.TOP_PAIR


def test_overpair():
    assert flop_archetype(["Ac", "Ad"], ["Kh", "8s", "2c"]) == FA.OVERPAIR


def test_underpair_is_marginal():
    # pocket pair lower than the top board card -> MARGINAL_PAIR
    assert flop_archetype(["7c", "7d"], ["Kh", "8s", "2c"]) == FA.MARGINAL_PAIR


def test_marginal_pair_non_top():
    # pairs the non-top board card
    assert flop_archetype(["8c", "5d"], ["Kh", "8s", "2c"]) == FA.MARGINAL_PAIR


def test_combo_draw():
    # flush draw + OESD, no pair: hero 9h Th, flop 8h 7c 2h
    # spades? use hearts FD with 7-8-9-T oesd
    assert flop_archetype(["9h", "Th"], ["8h", "7c", "2h"]) == FA.COMBO_DRAW


def test_flush_draw():
    assert flop_archetype(["Ah", "5h"], ["Kh", "8h", "2c"]) == FA.FLUSH_DRAW


def test_oesd():
    # 6-7 with 8-9 on board, no flush draw, no pair
    assert flop_archetype(["6c", "7d"], ["8h", "9s", "2c"]) == FA.OESD


def test_two_overcards():
    # both hole cards over the board, no pair, no draw (no backdoor wheel/flush)
    assert flop_archetype(["Kc", "Qd"], ["7h", "4s", "2c"]) == FA.TWO_OVERCARDS


def test_gutshot_is_weak_draw():
    # 6-7, flop 9-T-2: need 8 only (gutshot)
    assert flop_archetype(["6c", "7d"], ["9h", "Ts", "2c"]) == FA.WEAK_DRAW


def test_backdoor_is_weak_draw():
    # backdoor flush only (3 to a flush), no pair, no straight draw
    res = flop_archetype(["Ah", "2h"], ["Kh", "9s", "5c"])
    assert res == FA.WEAK_DRAW


def test_air():
    assert flop_archetype(["7c", "2d"], ["Kh", "9s", "4c"]) == FA.AIR
