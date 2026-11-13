"""tools/path_noise.py: the perturbations leave the rules' signals alone, both presets meet the
same random numbers, and the reading rule is the one fixed before the first run."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import path_noise as P  # noqa: E402


def _frames(n=200, symbols=("A.KQ", "B.KQ", "C.KQ"), signal_every=3):
    idx = pd.bdate_range("2020-01-01", periods=n)
    out = {}
    for k, s in enumerate(symbols):
        sig = np.zeros(n, bool)
        sig[k::signal_every] = True
        out[s] = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "exit_ma": 9.5,
                               "full_signal": sig, "rs_key": np.linspace(50, 99, n)}, index=idx)
    return out


def test_priority_changes_only_the_fill_order_key():
    f = _frames()
    g = P.perturb(f, "priority", rep=0)
    for s in f:
        assert g[s]["full_signal"].equals(f[s]["full_signal"])
        assert not np.allclose(g[s]["rs_key"], f[s]["rs_key"])
        assert g[s]["rs_key"].between(0, 100).all()
        assert g[s][["open", "high", "low", "close", "exit_ma"]].equals(f[s][["open", "high", "low", "close", "exit_ma"]])
    assert f["A.KQ"]["rs_key"].iloc[0] == 50.0                       # the input is not modified


def test_drop_only_removes_signals_and_about_the_asked_share():
    f = _frames(n=3000, signal_every=1)                             # every bar is a signal
    g = P.perturb(f, "drop", rep=1, drop_pct=10.0)
    for s in f:
        kept = g[s]["full_signal"].to_numpy()
        assert not (kept & ~f[s]["full_signal"].to_numpy()).any()   # never adds a signal
        assert 0.07 < 1 - kept.mean() < 0.13
        assert g[s]["rs_key"].equals(f[s]["rs_key"])


def test_same_repetition_gives_both_presets_the_same_luck():
    a = _frames(signal_every=1)
    b = {s: x.copy() for s, x in a.items()}
    for s in b:                                                     # preset B: a subset of A's signals
        b[s].loc[b[s].index[::2], "full_signal"] = False
    for mode in P.MODES:
        ga, gb = P.perturb(a, mode, rep=5), P.perturb(b, mode, rep=5)
        for s in a:
            if mode == "priority":
                assert ga[s]["rs_key"].equals(gb[s]["rs_key"])
            else:                                                   # a signal dropped in A is dropped in B too
                dropped_a = a[s]["full_signal"].to_numpy() & ~ga[s]["full_signal"].to_numpy()
                assert not (gb[s]["full_signal"].to_numpy() & dropped_a).any()
    assert not P.perturb(a, "priority", rep=5)["A.KQ"]["rs_key"].equals(P.perturb(a, "priority", rep=6)["A.KQ"]["rs_key"])
    assert not P.perturb(a, "priority", rep=5)["A.KQ"]["rs_key"].equals(P.perturb(a, "priority", rep=5)["B.KQ"]["rs_key"])


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError):
        P.perturb(_frames(), "shuffle", rep=0)


def _rows(diffs_by_mode):
    rows = []
    for mode, diffs in diffs_by_mode.items():
        for i, d in enumerate(diffs):
            a = {k: 10.0 for k in P.METRICS}
            b = {k: 10.0 + d for k in P.METRICS}
            rows.append({"mode": mode, "rep": i, "a": a, "b": b})
    return rows


RULE = {"a": {k: 10.0 for k in P.METRICS}, "b": {k: 12.0 for k in P.METRICS}}


def test_verdict_needs_the_5th_percentile_above_zero_in_both_perturbations():
    both = P.summarize_runs(_rows({"priority": np.linspace(0.5, 4, 40), "drop": np.linspace(0.2, 3, 40)}), RULE)
    assert P.verdict(both)["verdict"] == "outside the noise"
    assert both["priority"]["metrics"]["cagr_pct"]["b_ahead_pct"] == 100.0
    one = P.summarize_runs(_rows({"priority": np.linspace(0.5, 4, 40), "drop": np.linspace(-1, 3, 40)}), RULE)
    v = P.verdict(one)
    assert v["verdict"] == "inside the noise" and v["cagr_diff_p05"]["drop"] < 0 < v["cagr_diff_p05"]["priority"]
    # a positive median is not enough
    assert one["drop"]["metrics"]["cagr_pct"]["b_minus_a"]["p50"] > 0


def test_verdict_is_incomplete_when_a_perturbation_is_missing():
    only = P.summarize_runs(_rows({"priority": np.linspace(0.5, 4, 40)}), RULE)
    assert P.verdict(only)["verdict"] == "incomplete"


def test_dist_ignores_missing_values_and_pairs_stay_aligned():
    assert P.dist([None, float("nan")]) == {"n": 0}
    d = P.dist([1.0, None, 3.0])
    assert d["n"] == 2 and d["min"] == 1.0 and d["max"] == 3.0
    rows = [{"mode": "priority", "rep": 0, "a": {"cagr_pct": 1.0}, "b": {"cagr_pct": None}},
            {"mode": "priority", "rep": 1, "a": {"cagr_pct": 2.0}, "b": {"cagr_pct": 5.0}}]
    s = P.summarize_runs(rows, {"a": {}, "b": {}})
    assert s["priority"]["metrics"]["cagr_pct"]["b_minus_a"] == P.dist([3.0])   # the unpaired run is left out


def test_priority_decides_who_is_filled_when_cash_runs_out():
    """Through the real simulator: two same-day signals, cash for one. The filled symbol follows
    the fill-order key, so replacing the key changes the path and nothing else."""
    from swing_engine.params import resolve
    from swing_engine.portfolio import PortfolioConfig, simulate
    idx = pd.bdate_range("2020-01-01", periods=30)
    def frame(rs):
        sig = np.zeros(30, bool)
        sig[5] = True
        return pd.DataFrame({"open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "exit_ma": 1.0,
                             "full_signal": sig, "rs_key": rs}, index=idx)
    f = {"A.KQ": frame(90.0), "B.KQ": frame(80.0)}
    # 10% stop and 10% risk: each position wants all the equity, so only the first candidate is filled
    cfg = PortfolioConfig(params=resolve("CUSTOM", stop_pct=10.0), initial_equity=1000.0, risk_pct=10.0, cost_pct=0.0)
    assert [p["symbol"] for p in simulate(f, cfg).open_positions] == ["A.KQ"]
    f["A.KQ"]["rs_key"], f["B.KQ"]["rs_key"] = 10.0, 80.0
    assert [p["symbol"] for p in simulate(f, cfg).open_positions] == ["B.KQ"]
