"""tools/exit_study.py: the empty rule is the engine, each exit variant does what the
pre-registration says on a hand-made bar sequence, and the verdict reads the fixed criteria."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import exit_study as E  # noqa: E402
from swing_engine.params import resolve  # noqa: E402
from swing_engine.portfolio import PortfolioConfig, simulate  # noqa: E402

STOP = 10.0


def _cfg(cost=0.0, whole=False):
    p = dict(resolve("KOSDAQ"))
    p["stop_pct"] = STOP
    return PortfolioConfig(params=p, cost_pct=cost, integer_shares=whole, initial_equity=1_000_000.0)


def _one(bars, exit_ma=0.0, signal_at=0):
    """One symbol: `bars` are (open, high, low, close) from the bar AFTER the signal bar."""
    rows = [(100.0, 100.0, 100.0, 100.0)] * (signal_at + 1) + list(bars)
    idx = pd.bdate_range("2021-01-04", periods=len(rows))
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    f["exit_ma"] = exit_ma
    f["exit_ma_20"] = exit_ma
    f["exit_ma_10"] = exit_ma
    sig = np.zeros(len(rows), bool)
    sig[signal_at] = True
    f["full_signal"] = sig
    f["rs_key"] = 90.0
    return {"A.KQ": f}


def _trade(frames, rule, **kw):
    t = E.simulate_exits(frames, _cfg(**kw), rule).trades
    assert len(t) == 1
    return t.iloc[0]


def _random_frames(seed=3, n=400, symbols=12):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    out = {}
    for k in range(symbols):
        c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, n)))
        o = c * (1 + rng.normal(0, 0.01, n))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
        f = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=idx)
        f["exit_ma"] = f["close"].rolling(50).mean()
        f["exit_ma_20"] = f["close"].rolling(20).mean()
        f["exit_ma_10"] = f["close"].rolling(10).mean()
        f["full_signal"] = rng.random(n) < 0.08
        f["rs_key"] = rng.random(n) * 100
        if k % 4 == 0:
            f = f.drop(f.index[50:60])                              # a symbol with a gap in its bars
        out[f"S{k:02d}.KQ"] = f
    return out


@pytest.mark.parametrize("whole,cost", [(True, 0.2), (False, 0.2), (True, 0.0)])
def test_empty_rule_is_the_engine(whole, cost):
    frames = _random_frames()
    cfg = _cfg(cost=cost, whole=whole)
    ok, why = E.same_as_engine(frames, cfg)
    assert ok, why
    assert len(simulate(frames, cfg).trades) > 30                    # the comparison is not empty


def test_same_as_engine_reports_a_difference():
    frames = _random_frames()
    cfg = _cfg(cost=0.2, whole=True)
    real = E.simulate_exits
    try:
        E.simulate_exits = lambda f, c, rule=E.ExitRule(): real(f, c, E.ExitRule(target_r=1.0))
        ok, why = E.same_as_engine(frames, cfg)
    finally:
        E.simulate_exits = real
    assert not ok and why


def test_full_target_fills_at_the_target_and_the_trade_is_a_win():
    bars = [(100, 105, 99, 104), (104, 121, 103, 118), (118, 130, 117, 129)]
    t = _trade(_one(bars), E.ExitRule(target_r=2.0))
    assert t.exit_type == "TARGET" and t.exit_price == pytest.approx(120.0)
    assert t.pnl_pct == pytest.approx(20.0) and t.bars_held == 2


def test_target_fills_at_the_open_when_the_open_gaps_above_it():
    bars = [(100, 105, 99, 104), (125, 127, 123, 126)]
    t = _trade(_one(bars), E.ExitRule(target_r=2.0))
    assert t.exit_type == "TARGET" and t.exit_price == pytest.approx(125.0)


def test_stop_and_target_in_one_bar_counts_as_the_stop():
    bars = [(100, 125, 89, 110)]                                     # both levels inside the entry bar
    t = _trade(_one(bars), E.ExitRule(target_r=2.0))
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(90.0)


def test_half_at_the_target_then_the_rest_follows_the_rule():
    bars = [(100, 105, 99, 104), (104, 121, 103, 118), (118, 119, 80, 85)]
    t = _trade(_one(bars), E.ExitRule(target_r=2.0, target_frac=0.5))
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(90.0)
    assert t.target_sold == pytest.approx(t.qty / 2)
    assert t.pnl_pct == pytest.approx(0.5 * 20.0 + 0.5 * -10.0)      # one trade, both sales in its result
    assert t.price_pnl_pct == pytest.approx(5.0)                     # the quantity-weighted exit, not the last sale


def test_half_at_the_target_then_the_exit_line():
    bars = [(100, 105, 99, 104), (104, 121, 103, 118), (118, 119, 112, 113), (112, 113, 111, 112)]
    f = _one(bars)
    f["A.KQ"].loc[f["A.KQ"].index[3]:, "exit_ma"] = 115.0            # the third bar closes under the line
    t = _trade(f, E.ExitRule(target_r=2.0, target_frac=0.5))
    assert t.exit_type == "EXIT_MA" and t.exit_price == pytest.approx(112.0) and t.exit_signal_date == "2021-01-07"
    assert t.pnl_pct == pytest.approx(0.5 * 20.0 + 0.5 * 12.0)


def test_a_high_equal_to_the_level_reaches_it():
    assert 100 * (1 + 1.0 * STOP / 100) > 110.0                      # the rounding the tolerance is for
    assert E.reached(110.0, 100 * (1 + 1.0 * STOP / 100)) and not E.reached(109.99, 110.0)
    t = _trade(_one([(100, 110, 99, 105), (105, 106, 89, 90)]), E.ExitRule(target_r=1.0))
    assert t.exit_type == "TARGET" and t.exit_price == pytest.approx(110.0) and t.bars_held == 1
    t = _trade(_one([(100, 110, 99, 105), (105, 106, 89, 90)]), E.ExitRule(breakeven_r=1.0))
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(100.0)


def test_combination_e8_on_separate_bars_and_in_one_bar():
    e8 = E.RULES["E8_be2R_half3R"][1]
    # +2R on bar 2, +3R on bar 3 (half sold), then a fall: the rest leaves at the entry price
    bars = [(100, 105, 99, 104), (104, 121, 103, 119), (119, 131, 118, 128), (128, 129, 95, 96)]
    t = _trade(_one(bars), e8)
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(100.0)
    assert t.target_sold == pytest.approx(t.qty / 2) and t.pnl_pct == pytest.approx(0.5 * 30.0 + 0.5 * 0.0)
    # +2R and +3R inside one bar: half is sold there, the stop moves from the next bar
    bars = [(100, 131, 99, 128), (128, 129, 95, 96)]
    t = _trade(_one(bars), e8)
    assert t.exit_price == pytest.approx(100.0) and t.pnl_pct == pytest.approx(15.0)
    # the moved stop and the +3R target in one later bar: the stop is read first
    bars = [(100, 121, 99, 119), (119, 131, 99, 125)]
    t = _trade(_one(bars), e8)
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(100.0) and t.target_sold == 0


def test_a_signal_on_the_target_bar_arms_the_next_open_like_after_a_stop():
    bars = [(100, 105, 99, 104), (104, 121, 103, 118), (119, 120, 80, 85)]
    f = _one(bars)
    f["A.KQ"].iloc[2, f["A.KQ"].columns.get_loc("full_signal")] = True          # the bar that reaches +2R
    t = E.simulate_exits(f, _cfg(), E.ExitRule(target_r=2.0)).trades
    assert list(t.exit_type) == ["TARGET", "STOP"] and list(t.entry_date) == ["2021-01-05", "2021-01-07"]
    assert t.iloc[1].entry_price == pytest.approx(119.0)
    f = _one([(100, 105, 99, 104), (104, 105, 89, 95), (96, 97, 95, 96)])
    f["A.KQ"].iloc[2, f["A.KQ"].columns.get_loc("full_signal")] = True          # the engine after a stop
    assert len(simulate(f, _cfg()).open_positions) == 1


def test_half_of_one_whole_share_sells_nothing():
    f = _one([(100, 105, 99, 104), (104, 121, 103, 118), (118, 119, 80, 85)])
    cfg = _cfg(whole=True)
    cfg.initial_equity = 1400.0                                      # 0.75% risk on a 10-point stop: one share
    t = E.simulate_exits(f, cfg, E.ExitRule(target_r=2.0, target_frac=0.5)).trades.iloc[0]
    assert t.qty == 1 and t.target_sold == 0 and t.exit_type == "STOP" and t.pnl_pct == pytest.approx(-10.0)


def test_breakeven_stop_counts_from_the_next_bar():
    same_bar = [(100, 111, 95, 96)]                                  # reaches +1R, then closes under the entry
    t = E.simulate_exits(_one(same_bar), _cfg(), E.ExitRule(breakeven_r=1.0))
    assert len(t.trades) == 0                                        # the old stop (90) held on that bar
    bars = same_bar + [(96, 99, 94, 95)]
    t = _trade(_one(bars), E.ExitRule(breakeven_r=1.0))
    assert t.exit_type == "STOP" and t.exit_price == pytest.approx(96.0)       # gap under the new stop: the open
    bars = same_bar + [(101, 102, 99, 99.5)]
    t = _trade(_one(bars), E.ExitRule(breakeven_r=1.0))
    assert t.exit_price == pytest.approx(100.0) and t.pnl_pct == pytest.approx(0.0)
    base = _trade(_one(same_bar + [(96, 99, 89, 95)]), E.ExitRule())
    assert base.exit_price == pytest.approx(90.0)                    # without the variant: the 10% stop


def test_breakeven_exit_is_a_loss_after_costs_and_a_scratch():
    bars = [(100, 111, 95, 96), (101, 102, 99, 99.5)]
    res = E.simulate_exits(_one(bars), _cfg(cost=0.2), E.ExitRule(breakeven_r=1.0))
    t = res.trades.iloc[0]
    assert t.net_pnl < 0 and abs(t.pnl_pct) < 1.0                    # not a win by the engine's definition


def test_exit_line_variant_reads_its_own_column():
    bars = [(100, 105, 99, 104), (104, 106, 103, 105), (105, 106, 104, 105), (103, 104, 102, 103)]
    f = _one(bars, exit_ma=0.0)
    f["A.KQ"]["exit_ma_20"] = 104.5                                  # the first close (104) is already under it
    t = _trade(f, E.ExitRule(exit_col="exit_ma_20"))
    assert t.exit_type == "EXIT_MA" and t.exit_signal_date == "2021-01-05" and t.exit_price == pytest.approx(104.0)
    assert len(E.simulate_exits(f, _cfg(), E.ExitRule()).trades) == 0            # the 50-day column never exits


def test_add_exit_lines_uses_the_engine_average():
    idx = pd.bdate_range("2021-01-04", periods=30)
    f = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": np.arange(30.0), "exit_ma": 0.0,
                      "full_signal": False, "rs_key": 1.0, "volume": 5.0}, index=idx)
    g = E.add_exit_lines({"A": f})["A"]
    assert list(g.columns) == E.BASE_COLS + ["exit_ma_20", "exit_ma_10"]
    assert np.isnan(g["exit_ma_10"].iloc[8]) and g["exit_ma_10"].iloc[9] == pytest.approx(4.5)
    assert g["exit_ma_20"].iloc[29] == pytest.approx(np.arange(10, 30).mean())


def test_the_ten_hypotheses_are_the_registered_ones():
    r = {k: v[1] for k, v in E.RULES.items()}
    assert list(r) == ["E0_base", "E1_target1R", "E2_target2R", "E3_target3R", "E4_half2R", "E5_half3R",
                       "E6_be1R", "E7_be2R", "E8_be2R_half3R", "E9_exit20", "E10_exit10"]
    assert r["E0_base"] == E.ExitRule()
    assert (r["E1_target1R"].target_r, r["E2_target2R"].target_r, r["E3_target3R"].target_r) == (1.0, 2.0, 3.0)
    assert all(r[k].target_frac == 1.0 for k in ("E1_target1R", "E2_target2R", "E3_target3R"))
    assert (r["E4_half2R"].target_r, r["E4_half2R"].target_frac) == (2.0, 0.5)
    assert (r["E5_half3R"].target_r, r["E5_half3R"].target_frac) == (3.0, 0.5)
    assert (r["E6_be1R"].breakeven_r, r["E7_be2R"].breakeven_r) == (1.0, 2.0)
    assert r["E8_be2R_half3R"] == E.ExitRule(target_r=3.0, target_frac=0.5, breakeven_r=2.0)
    assert (r["E9_exit20"].exit_col, r["E10_exit10"].exit_col) == ("exit_ma_20", "exit_ma_10")
    assert (E.WIN_GAIN_PP, E.WIN_AHEAD_PCT, E.CAGR_SLACK_PP, E.MDD_SLACK_PP, E.HALF_SLACK_PP, E.OTHER_SLACK_PP) == \
        (5.0, 95.0, 1.0, 3.0, 2.0, 3.0)


# ---- verdict ---------------------------------------------------------------------------------

def _row(win=26.0, cagr=10.0, h1w=25.0, h2w=27.0, h1x=7.0, h2x=8.0):
    return {"win_rate_pct": win, "cagr_pct": cagr, "h1_win_rate_pct": h1w, "h2_win_rate_pct": h2w,
            "h1_excess_pp": h1x, "h2_excess_pp": h2x}


def _pairs(key, win=(96.0, 6.0), cagr_p50=0.0, mdd_p50=0.0, cagr_p05=-2.0, modes=("priority", "drop"), n=40):
    d = {"win_rate_pct": {"n": n, "ahead_pct": win[0], "p50": win[1]}, "cagr_pct": {"n": n, "p50": cagr_p50, "p05": cagr_p05},
         "max_drawdown_pct": {"n": n, "p50": mdd_p50}}
    return {m: {"reps": 40, "diff": {key: d}} for m in modes}


K = "E2_target2R"


def _v(variant=None, pairs=None, other=None, base=None):
    rows = {E.BASE: base or _row(), K: variant or _row(win=33.0, h1w=31.0, h2w=34.0)}
    other = {E.BASE: {"cagr_pct": 12.0}, K: {"cagr_pct": 11.0}} if other is None else other
    return E.verdict(K, rows, _pairs(K) if pairs is None else pairs, other)


def test_verdict_kept_when_every_check_holds():
    v = _v()
    assert v["verdict"] == "win rate up, return kept" and all(v["checks"].values())
    assert v["return_up_as_well"] is False
    assert _v(pairs=_pairs(K, cagr_p05=0.1))["return_up_as_well"] is True


def test_verdict_boundaries_pass():
    v = _v(variant=_row(win=31.0, h1w=25.1, h2w=27.1, h1x=5.0, h2x=6.0),
           pairs=_pairs(K, win=(95.0, 5.0), cagr_p50=-1.0, mdd_p50=-3.0),
           other={E.BASE: {"cagr_pct": 12.0}, K: {"cagr_pct": 9.0}})
    assert v["verdict"] == "win rate up, return kept", v["checks"]


@pytest.mark.parametrize("kw,failed", [
    (dict(variant=_row(win=30.9, h1w=31.0, h2w=34.0)), "S1_win_rate"),
    (dict(pairs=_pairs(K, win=(94.0, 6.0))), "P1_win_paired"),
    (dict(pairs=_pairs(K, win=(100.0, 4.9))), "P1_win_paired"),
])
def test_verdict_not_raised(kw, failed):
    v = _v(**kw)
    assert v["verdict"] == "win rate not raised" and not v["checks"][failed]


@pytest.mark.parametrize("kw,failed", [
    (dict(pairs=_pairs(K, cagr_p50=-1.1)), "P2_cagr"),
    (dict(pairs=_pairs(K, mdd_p50=-3.1)), "P3_drawdown"),
    (dict(variant=_row(win=33.0, h1w=25.0, h2w=34.0)), "P4_halves"),           # first-half win rate not above
    (dict(variant=_row(win=33.0, h1w=31.0, h2w=34.0, h2x=5.9)), "P4_halves"),  # second-half excess 2.1pp under
    (dict(other={E.BASE: {"cagr_pct": 12.0}, K: {"cagr_pct": 8.9}}), "P5_other_market"),
])
def test_verdict_damaged(kw, failed):
    v = _v(**kw)
    assert v["verdict"] == "win rate up, return damaged" and not v["checks"][failed]
    assert sum(not ok for ok in v["checks"].values()) == 1


def test_verdict_needs_both_perturbations_and_the_other_market():
    v = _v(pairs=_pairs(K, modes=("priority",)))
    assert v["verdict"] == "win rate not raised" and not v["checks"]["P1_win_paired"]
    v = E.verdict(K, {E.BASE: _row(), K: _row(win=33.0, h1w=31.0, h2w=34.0)}, _pairs(K), None)
    assert v["verdict"] == "win rate up, return damaged" and not v["checks"]["P5_other_market"]


def test_verdict_needs_the_number_from_every_path():
    v = _v(pairs=_pairs(K, n=39))                                    # one path of forty without the number
    assert v["verdict"] == "win rate not raised"
    assert not any(v["checks"][k] for k in ("P1_win_paired", "P2_cagr", "P3_drawdown"))
    assert _v(pairs=_pairs(K, n=39, cagr_p05=0.1))["return_up_as_well"] is False
    p = _pairs(K)
    p["drop"]["diff"][K]["cagr_pct"]["n"] = 1
    v = _v(pairs=p)
    assert v["verdict"] == "win rate up, return damaged" and not v["checks"]["P2_cagr"] and v["checks"]["P3_drawdown"]


def test_verdict_reads_a_baseline_of_zero_as_a_number():
    v = _v(base=_row(win=0.0, h1w=0.0, h2w=0.0, h1x=0.0, h2x=0.0), variant=_row(win=5.0, h1w=4.0, h2w=6.0, h1x=-2.0, h2x=0.0),
           other={E.BASE: {"cagr_pct": 0.0}, K: {"cagr_pct": -3.0}})
    assert v["verdict"] == "win rate up, return kept", v["checks"]
    v = _v(base=_row(win=0.0), variant=_row(win=4.9, h1w=31.0, h2w=34.0))
    assert not v["checks"]["S1_win_rate"]


def test_protocol_names_every_setting_that_differs():
    import argparse
    r = E.REGISTERED
    a = argparse.Namespace(market=r["market"], other=r["other"], reps=r["reps"], drop_pct=r["drop_pct"], seed=r["seed"])
    rows = {E.BASE: {"first_date": "2016-09-26", "last_date": "2026-09-28"}}
    assert E.protocol(a, rows) == {"registered": True, "differs": [], "settings": E.protocol(a, rows)["settings"]}
    for field, value in (("reps", 1), ("other", "KOSDAQ"), ("market", "KOSPI"), ("drop_pct", 5.0), ("seed", 1)):
        b = argparse.Namespace(**{**vars(a), field: value})
        p = E.protocol(b, rows)
        assert not p["registered"] and len(p["differs"]) == 1 and p["differs"][0].startswith(field)
    p = E.protocol(a, {E.BASE: {"first_date": "2016-09-26", "last_date": "2026-09-29"}})    # one bar too many
    assert not p["registered"] and p["differs"][0].startswith("window")
    assert not E.protocol(a, {E.BASE: {}})["registered"]


def test_verdict_missing_numbers_fail_instead_of_raising():
    v = _v(variant={"win_rate_pct": None, "cagr_pct": None})
    assert v["verdict"] == "win rate not raised"
    v = _v(base={"win_rate_pct": None})
    assert v["verdict"] == "win rate not raised"


def test_paired_differences_and_tables():
    def run(mode, rep, win_gain):
        rows = {k: {"win_rate_pct": 26.0, "cagr_pct": 10.0, "max_drawdown_pct": -40.0, "profit_factor": 1.2,
                    "excess_cagr_pp": 8.0} for k in E.RULES}
        rows[K] = dict(rows[K], win_rate_pct=26.0 + win_gain, cagr_pct=9.0, profit_factor=None)
        if rep == 0:
            rows[E.BASE] = dict(rows[E.BASE], excess_cagr_pp=None)      # a path without the number
        return {"mode": mode, "rep": rep, "rows": rows}
    runs = [run(m, r, g) for m in ("priority", "drop") for r, g in enumerate((6.0, 7.0, -1.0, 8.0))]
    p = E.paired(runs)
    d = p["drop"]["diff"][K]
    assert p["drop"]["reps"] == 4 and d["win_rate_pct"]["ahead_pct"] == 75.0 and d["win_rate_pct"]["p50"] == pytest.approx(6.5)
    assert d["cagr_pct"]["p50"] == pytest.approx(-1.0) and d["profit_factor"]["n"] == 0
    assert d["win_rate_pct"]["n"] == 4 and d["excess_cagr_pp"]["n"] == 3 and p["drop"]["baseline"]["excess_cagr_pp"]["n"] == 3
    assert p["drop"]["diff"]["E1_target1R"]["win_rate_pct"]["ahead_pct"] == 0.0
    assert K in E.paired_table(p)
    text = E.table({E.BASE: {"trades": 1122, "win_rate_pct": 26.1}, K: {}})
    assert "1,122" in text and "26.1%" in text and "n/a" in text and "후반 초과" in text


def test_main_end_to_end_on_a_small_snapshot(tmp_path, capsys):
    """Loading, point-in-time preparation, the engine comparison on both markets, ten variants,
    paired paths and the output. A small snapshot is never the registered protocol."""
    import json
    from test_path_noise import _snapshot
    data = tmp_path / "data"
    data.mkdir()
    _snapshot(data)
    args = ["--data", str(data), "--out", str(tmp_path / "o"), "--other", "KOSDAQ", "--reps", "1", "--jobs", "1"]
    assert E.main(args) == 0
    out = capsys.readouterr().out
    assert out.count("empty rule vs engine: identical") == 2
    assert "Not the registered protocol" in out and "EXPLORATORY E10_exit10" in out and "VERDICT" not in out
    res = json.loads((tmp_path / "o" / "exit_study.json").read_text())
    assert list(res["rows"]) == list(E.RULES) and len(res["runs"]) == 2 and len(res["verdicts"]) == 10
    assert res["protocol"]["registered"] is False and len(res["protocol"]["differs"]) == 3      # other, reps, window
    assert res["rows"]["E0_base"]["trades"] > 5 and res["rows"]["E1_target1R"]["exit_types"].get("TARGET", 0) > 0
    assert res["other_rows"]["E0_base"]["cagr_pct"] == res["rows"]["E0_base"]["cagr_pct"]       # the second market ran
    base = res["other_rows"]["E0_base"]["cagr_pct"]
    assert all(v["checks"]["P5_other_market"] is (res["other_rows"][k]["cagr_pct"] >= base - E.OTHER_SLACK_PP - E.EPS)
               for k, v in res["verdicts"].items())                                             # P5 read from that run
    assert E.main(["--data", str(data), "--out", str(tmp_path / "n"), "--other", "", "--reps", "1", "--jobs", "1"]) == 0
    res = json.loads((tmp_path / "n" / "exit_study.json").read_text())
    assert all(v["checks"]["P5_other_market"] is False for v in res["verdicts"].values())       # no second market given
    capsys.readouterr()
    assert E.main(["--data", str(data), "--out", str(tmp_path / "c"), "--other", "KOSDAQ", "--check-only"]) == 0
    assert capsys.readouterr().out.count("identical") == 2 and not (tmp_path / "c").exists()
