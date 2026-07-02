"""Equity enumeration sanity checks."""

from mbplumber.equity import equity


def test_aa_vs_kk_preflop():
    eq = equity(["Ah", "As"], [["Kh", "Ks"]], [])
    assert 0.80 <= eq <= 0.84


def test_set_vs_flush_draw_flop():
    # Hero flopped a set of 8s; villain has a nut flush draw (no pair).
    # Hero should be a clear favorite.
    eq = equity(["8c", "8d"], [["Ah", "Kh"]], ["8h", "2h", "5s"])
    assert eq > 0.6


def test_dead_heat_split_both_play_board():
    # Both players hold cards that cannot improve over a board that already makes
    # the nuts for both: board is a royal-ish straight; both play the board.
    # Use a board with a made straight A-K-Q-J-T; each holds two low offsuit
    # blockers that never beat the board -> exact split.
    eq = equity(["2c", "3c"], [["2d", "3d"]], ["Th", "Jh", "Qs", "Kc", "Ad"])
    assert abs(eq - 0.5) < 1e-9


def test_three_way_field():
    # Hero vs two villains, full board: deterministic.
    # Board makes hero a flush; villains do not have it.
    eq = equity(
        ["Ah", "Qh"],
        [["Kd", "Kc"], ["7s", "2d"]],
        ["2h", "5h", "9h", "Td", "3c"],
    )
    assert eq == 1.0
