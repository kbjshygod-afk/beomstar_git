"""Primitive and indicator semantics (SPEC 3-4) with hand-computed expectations."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import bdays, make_bars
from swing_engine.indicators import (align_asof, compute_indicators, highest, lowest, pine_round,
                                     pine_round_int, sma, weighted_perf, weighted_perf_lags)
from swing_engine.params import resolve

nan = np.nan


def s(vals):
    return pd.Series(vals, index=bdays(len(vals)), dtype=float)


def assert_same(a, b):
    np.testing.assert_array_equal(np.asarray(a, float), np.asarray(b, float))


# --- sma / highest / lowest NaN windows --------------------------------------

def test_sma_needs_n_bars_and_nan_poisons_window():
    x = s([1, 2, nan, 4, 5, 6])
    assert_same(sma(x, 2), [nan, 1.5, nan, nan, 4.5, 5.5])
    assert_same(sma(x, 3), [nan, nan, nan, nan, nan, 5.0])
    assert_same(sma(s([1, 2]), 3), [nan, nan])          # fewer than n bars


def test_highest_lowest_nan_windows():
    x = s([3, 1, 4, 1, nan, 9, 2])
    assert_same(highest(x, 3), [nan, nan, 4, 4, nan, nan, nan])
    assert_same(lowest(x, 2), [nan, 1, 1, 1, nan, nan, 2])
    assert_same(highest(s([5, 7, 6]), 1), [5, 7, 6])


def test_sma_independent_of_history_length():
    rng = np.random.default_rng(3)
    x = s(rng.normal(100, 5, 400))
    full = sma(x, 50).iloc[-1]
    part = sma(x.iloc[-60:], 50).iloc[-1]
    assert full == part                                  # window-by-window, no running-sum drift


# --- pine_round ----------------------------------------------------------------

@pytest.mark.parametrize("v,expected", [(182.5, 183), (91.25, 91), (273.75, 274), (0.5, 1), (2.5, 3), (63.0, 63)])
def test_pine_round_ties_up(v, expected):
    assert pine_round_int(v) == expected
    assert pine_round(v) == expected
    if v == 2.5:
        assert round(v) == 2                              # Python's round would be wrong


# --- weighted performance --------------------------------------------------------

def test_weighted_perf_lags():
    assert weighted_perf_lags(252) == (63, 126, 189, 252)
    assert weighted_perf_lags(365) == (91, 183, 274, 365)


@pytest.mark.parametrize("n", [252, 365])
def test_weighted_perf_value(n):
    c = s(np.arange(1, n + 3, dtype=float))              # close = bar index + 1
    wp = weighted_perf(c, n)
    q, h, t3, full = weighted_perf_lags(n)
    t = n + 1
    ct = t + 1.0
    expected = (0.4 * (ct / (t - q + 1) - 1) + 0.2 * (ct / (t - h + 1) - 1)
                + 0.2 * (ct / (t - t3 + 1) - 1) + 0.2 * (ct / (t - full + 1) - 1))
    assert wp.iloc[t] == pytest.approx(expected, rel=1e-15)
    assert math.isnan(wp.iloc[n - 1])                     # needs close[n]
    assert not math.isnan(wp.iloc[n])


# --- pivot / volume average ---------------------------------------------------------

def _ind(df, p, bench=None):
    if bench is None:
        bench = pd.DataFrame({"close": np.full(len(df), 100.0)}, index=df.index)
    return compute_indicators(df, bench, p)


def test_pivot_excludes_today():
    p = resolve("SP500", pivot_len=2)
    df = make_bars([10, 11, 12, 20], spread=0.0)
    df["high"] = [10, 11, 12, 20]
    ind = _ind(df, p)
    assert_same(ind["pivot"], [nan, nan, 11, 12])        # bar 3: max(high[1], high[2]) = 12, not 20
    assert bool(ind["breakout"].iloc[3])                 # 20 > 12


def test_vol_avg_excludes_today():
    p = resolve("SP500", vol_len=3)
    df = make_bars([10, 10, 10, 10, 10], volume=[100, 100, 100, 300, 100])
    ind = _ind(df, p)
    assert_same(ind["vol_avg"], [nan, nan, nan, 100, 500 / 3])
    assert ind["vol_x"].iloc[3] == 3.0
    assert math.isnan(ind["vol_x"].iloc[2])


def test_vol_x_nan_when_avg_zero_or_volume_missing():
    p = resolve("SP500", vol_len=2)
    df = make_bars([1, 1, 1, 1], volume=[0, 0, 5, nan])
    ind = _ind(df, p)
    assert math.isnan(ind["vol_x"].iloc[2])              # vol_avg == 0 -> na
    assert math.isnan(ind["vol_x"].iloc[3])              # missing volume -> na
    assert not ind["vol_ok"].any()


# --- float edges ---------------------------------------------------------------------

def test_close_equal_pivot_is_not_breakout():
    p = resolve("SP500", pivot_len=2)
    df = make_bars([10, 10, 10, 12], spread=0.0)
    df["high"] = [10, 12, 11, 13]
    df.loc[df.index[3], "close"] = 12.0                   # pivot at bar 3 = max(12, 11) = 12
    ind = _ind(df, p)
    assert ind["pivot"].iloc[3] == 12.0
    assert not bool(ind["breakout"].iloc[3])


def test_vol_x_exactly_1_4_is_ok():
    p = resolve("SP500", vol_len=3)
    df = make_bars([10] * 4, volume=[100, 100, 100, 140])
    ind = _ind(df, p)
    assert ind["vol_x"].iloc[3] == 1.4
    assert bool(ind["vol_ok"].iloc[3])


def test_lo52_times_1_30_is_computed_like_pine():
    assert 3 * 1.30 > 3.9 and 3.9 / 3 >= 1.3              # the float edge exists
    p = resolve("CUSTOM", year_bars=3)
    df = make_bars([3.0, 3.5, 3.9])
    ind = _ind(df, p)
    assert ind["lo52"].iloc[2] == 3.0
    assert not bool(ind["tt6"].iloc[2])                   # 3.9 >= 3.9000000000000004 is False
    df2 = make_bars([3.0, 3.5, 3.91])
    assert bool(_ind(df2, p)["tt6"].iloc[2])


def test_hi52_and_lo52_are_close_based_and_include_today():
    p = resolve("CUSTOM", year_bars=3)
    df = make_bars([5.0, 9.0, 7.0, 8.0], spread=0.5)
    ind = _ind(df, p)
    assert_same(ind["hi52"], [nan, nan, 9, 9])
    assert_same(ind["lo52"], [nan, nan, 5, 7])


# --- regime modes -------------------------------------------------------------------

def _bench_for_regime(last_close):
    # 199 bars at 100, then one bar: b_ma200 = (199*100 + last)/200, b_ma20 = (19*100 + last)/20
    dates = bdays(200)
    closes = np.r_[np.full(199, 100.0), last_close]
    return pd.DataFrame({"close": closes}, index=dates)


@pytest.mark.parametrize("mode,last,expected", [
    ("MA200", 101.0, True), ("MA200", 100.0, False), ("MA200", 99.0, False),
    ("MA200_AND_MA20", 101.0, True), ("NONE", 50.0, True),
])
def test_regime_modes(mode, last, expected):
    bench = _bench_for_regime(last)
    df = make_bars(np.full(200, 10.0), dates=bench.index)
    ind = compute_indicators(df, bench, resolve("CUSTOM", regime_mode=mode))
    assert bool(ind["regime_on"].iloc[-1]) is expected
    assert not bool(ind["regime_on"].iloc[-2]) or mode == "NONE"   # b_ma200 NaN before bar 199


def test_regime_ma200_and_ma20_needs_both():
    # above the 200-day MA but below the 20-day MA
    dates = bdays(220)
    closes = np.r_[np.full(190, 100.0), np.full(29, 130.0), 120.0]
    bench = pd.DataFrame({"close": closes}, index=dates)
    df = make_bars(np.full(220, 10.0), dates=dates)
    a = compute_indicators(df, bench, resolve("CUSTOM", regime_mode="MA200")).iloc[-1]
    b = compute_indicators(df, bench, resolve("CUSTOM", regime_mode="MA200_AND_MA20")).iloc[-1]
    assert a["b_close"] > a["b_ma200"] and a["b_close"] < a["b_ma20"]
    assert bool(a["regime_on"]) and not bool(b["regime_on"])
    k = compute_indicators(df, bench, resolve("KOSPI")).iloc[-1]
    assert not bool(k["regime_on"])
    q = compute_indicators(df, None, resolve("KOSDAQ")).iloc[-1]
    assert bool(q["regime_on"])                          # NONE: no benchmark needed


# --- chase cap -----------------------------------------------------------------------

def test_chase_cap_off_for_crypto():
    df = make_bars([10.0] * 5 + [16.0], spread=0.0)       # +60% over the pivot
    bench = pd.DataFrame({"close": np.full(6, 1.0)}, index=df.index)
    ind_sp = compute_indicators(df, bench, resolve("SP500", pivot_len=3))
    ind_cr = compute_indicators(df, bench, resolve("CRYPTO", pivot_len=3))
    assert ind_sp["breakout_pct"].iloc[-1] == pytest.approx(60.0)
    assert bool(ind_sp["breakout"].iloc[-1])
    assert not bool(ind_sp["cap_ok"].iloc[-1])
    assert bool(ind_cr["cap_ok"].iloc[-1])
    assert resolve("CRYPTO")["cap_on"] is False and resolve("CRYPTO")["year_bars"] == 365


def test_cap_boundary_inclusive():
    df = make_bars([10.0] * 5 + [11.5], spread=0.0)
    ind = compute_indicators(df, None, resolve("SP500", pivot_len=3))
    assert ind["breakout_pct"].iloc[-1] <= 15.0 + 1e-9
    # (11.5/10 - 1)*100 in floats:
    assert bool(ind["cap_ok"].iloc[-1]) is ((11.5 / 10 - 1) * 100 <= 15.0)


# --- benchmark alignment ---------------------------------------------------------------

def test_benchmark_forward_fill_mismatched_calendar_no_lookahead():
    bench = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]},
                         index=pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-06", "2024-01-09"]))
    sym_dates = pd.date_range("2024-01-01", "2024-01-08", freq="D")   # 7-day calendar
    got = align_asof(bench, sym_dates)["close"].to_numpy()
    assert_same(got, [nan, 100, 100, 101, 101, 102, 102, 102])        # 01-09 never leaks back


def test_benchmark_ma_uses_benchmark_bars_not_symbol_bars():
    # benchmark trades every other day; its 20-day MA must use 20 benchmark bars
    bdates = pd.date_range("2024-01-01", periods=250, freq="2D")
    bench = pd.DataFrame({"close": np.arange(250, dtype=float)}, index=bdates)
    sdates = pd.date_range("2024-01-01", periods=499, freq="D")
    df = make_bars(np.full(499, 10.0), dates=sdates)
    ind = compute_indicators(df, bench, resolve("CRYPTO"))
    d = sdates[-1]                                        # = bdates[-1]
    assert ind.loc[d, "b_ma20"] == np.mean(np.arange(230, 250))
    assert ind.loc[d, "b_ma200"] == np.mean(np.arange(50, 250))
    d2 = sdates[-2]                                       # not a benchmark day -> previous bar
    assert ind.loc[d2, "b_close"] == 248.0
    assert ind.loc[d2, "b_ma20"] == np.mean(np.arange(229, 249))


def test_genuine_nan_on_benchmark_bar_is_not_filled():
    bench = pd.DataFrame({"close": [1.0, nan, 3.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    got = align_asof(bench, pd.to_datetime(["2024-01-02"]))["close"].to_numpy()
    assert math.isnan(got[0])


def test_comparisons_with_nan_are_false_and_count_as_zero():
    df = make_bars(np.linspace(10, 20, 60))
    ind = compute_indicators(df, None, resolve("SP500"))
    assert (ind["tt_count"] <= 2).all()                  # ma150/ma200/hi52 NaN, rs NaN
    assert not ind["tt8"].any()
    assert not ind["tt_pass"].any() and not ind["full_signal"].any()
    ind2 = compute_indicators(df, None, resolve("SP500", use_tt=False, regime_mode="NONE"))
    assert ind2["tt_pass"].all()


def test_rs_diff_formula(sp500):
    n = 260
    df = make_bars(100 * 1.001 ** np.arange(n))
    bench = pd.DataFrame({"close": 50 * 1.0005 ** np.arange(n)}, index=df.index)
    ind = compute_indicators(df, bench, sp500)
    c, b = df["close"], bench["close"]
    exp = (weighted_perf(c, 252) - weighted_perf(b, 252)) * 100
    assert ind["rs_diff"].iloc[-1] == exp.iloc[-1]
    assert bool(ind["tt8"].iloc[-1])
