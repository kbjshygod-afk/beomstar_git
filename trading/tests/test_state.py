"""SPEC 5 state machine: hand-built bars, exact step order."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import bdays
from swing_engine.state import PositionMachine, run_state_machine


def run(rows, stop_pct=10.0, start=0):
    """rows: (open, high, low, close, exit_ma, full_signal)."""
    dates = bdays(len(rows))
    a = np.array([r[:5] for r in rows], float)
    bars = pd.DataFrame(a[:, :4], columns=["open", "high", "low", "close"], index=dates)
    ind = pd.DataFrame({"exit_ma": a[:, 4], "full_signal": [bool(r[5]) for r in rows]}, index=dates)
    states, events = run_state_machine(ind, bars, stop_pct, start=start)
    return states, [(e.bar, e.type, e.price, e.pnl_pct) for e in events]


SIG = (100, 101, 99, 100, 90, True)       # a signal bar closing at 100
FLAT = (100, 102, 98, 101, 90, False)     # quiet bar: no stop, close above exit MA


def test_gap_down_through_stop_fills_at_open():
    st, ev = run([SIG, FLAT, (85, 86, 80, 84, 90, False)])
    assert ev == [(0, "SIGNAL", 100, None), (1, "ENTRY", 100, None), (2, "STOP", 85, pytest.approx(-15.0))]
    assert math.isnan(st["entry_price"].iloc[2]) and not st["entry_pending"].iloc[2]
    assert st["stop_price"].iloc[1] == 90.0


def test_stop_on_the_entry_bar():
    st, ev = run([SIG, (100, 101, 89, 95, 80, False)])
    assert ev[1:] == [(1, "ENTRY", 100, None), (1, "STOP", 90.0, pytest.approx(-10.0))]
    assert math.isnan(st["entry_price"].iloc[1])


def test_low_equal_to_stop_triggers():
    _, ev = run([SIG, FLAT, (95, 96, 90, 94, 80, False)])
    assert ev[-1] == (2, "STOP", 90.0, pytest.approx(-10.0))


def test_exit_next_open_after_close_below_exit_ma():
    st, ev = run([SIG, FLAT, (99, 100, 94, 95, 96, False), (94, 95, 80, 90, 96, False)])
    assert ev[2] == (2, "EXIT_SIGNAL", 95, None)
    assert st["exit_pending"].iloc[2] and st["entry_price"].iloc[2] == 100
    # bar 3: exit fills at the open first; no stop check although low 80 < stop 90
    assert ev[3:] == [(3, "EXIT_MA", 94, pytest.approx(-6.0))]
    assert not st["exit_pending"].iloc[3] and math.isnan(st["entry_price"].iloc[3])


def test_exit_signal_on_the_entry_bar():
    _, ev = run([SIG, (100, 101, 95, 96, 97, False), (98, 99, 97, 98, 97, False)])
    assert [e[1] for e in ev] == ["SIGNAL", "ENTRY", "EXIT_SIGNAL", "EXIT_MA"]
    assert ev[-1] == (2, "EXIT_MA", 98, pytest.approx(-2.0))


def test_stop_has_priority_over_exit_ma():
    _, ev = run([SIG, FLAT, (95, 96, 85, 86, 97, False)])
    assert ev[-1][1] == "STOP" and len(ev) == 3


def test_resignal_same_bar_after_stop():
    st, ev = run([SIG, FLAT, (95, 96, 85, 95, 80, True), FLAT])
    assert [e[:2] for e in ev] == [(0, "SIGNAL"), (1, "ENTRY"), (2, "STOP"), (2, "SIGNAL"), (3, "ENTRY")]
    assert st["entry_pending"].iloc[2]
    assert st["entry_price"].iloc[3] == 100


def test_resignal_same_bar_after_exit_fill():
    rows = [SIG, FLAT, (99, 100, 94, 95, 96, False), (97, 103, 96, 102, 96, True), (103, 104, 102, 103, 96, False)]
    st, ev = run(rows)
    assert [e[:2] for e in ev] == [(0, "SIGNAL"), (1, "ENTRY"), (2, "EXIT_SIGNAL"),
                                   (3, "EXIT_MA"), (3, "SIGNAL"), (4, "ENTRY")]
    assert ev[4][2] == 102                                # signal price = that bar's close
    assert st["entry_price"].iloc[4] == 103 and st["stop_price"].iloc[4] == pytest.approx(92.7)


def test_no_signal_while_in_position():
    _, ev = run([SIG, FLAT, (101, 103, 100, 102, 90, True), FLAT])
    assert [e[1] for e in ev] == ["SIGNAL", "ENTRY"]


def test_no_signal_while_exit_pending():
    _, ev = run([SIG, FLAT, (99, 100, 94, 95, 96, True)])
    assert [e[1] for e in ev] == ["SIGNAL", "ENTRY", "EXIT_SIGNAL"]


def test_pending_entry_at_last_bar():
    st, ev = run([FLAT, FLAT, SIG])
    assert ev == [(2, "SIGNAL", 100, None)]
    last = st.iloc[-1]
    assert last["entry_pending"] and math.isnan(last["entry_price"]) and not last["exit_pending"]


def test_start_skips_earlier_bars():
    _, ev = run([SIG, FLAT, SIG, FLAT], start=1)
    assert [e[:2] for e in ev] == [(2, "SIGNAL"), (3, "ENTRY")]


def test_nan_exit_ma_never_exits():
    _, ev = run([SIG, (100, 101, 95, 50, float("nan"), False)])
    assert [e[1] for e in ev] == ["SIGNAL", "ENTRY"]


def test_machine_step_helpers_and_stop_pct():
    m = PositionMachine(stop_pct=7.0)
    m.arm_signal("d0", True, 50.0)
    m.fill_entry("d1", 50.0)
    assert m.in_pos and m.stop_price == pytest.approx(46.5)
    m.cancel_entry()
    assert m.in_pos                                        # cancel only clears a pending entry
