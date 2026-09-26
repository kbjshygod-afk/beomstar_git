"""Per-bar indicators with Pine Script v5 semantics (SPEC sections 3-4).

Pine semantics that matter here (Pine line numbers refer to minervini_swing_watch.pine):

* `ta.sma(x, n)` / `ta.highest(x, n)` / `ta.lowest(x, n)` are NaN until n bars exist,
  and (SPEC 3) NaN when any value in the window is NaN. We evaluate every window
  independently (`sliding_window_view`) instead of a running sum, so a value at date d
  does not depend on how much history precedes it and there is no accumulated
  floating-point drift.
* `x[k]` is `x.shift(k)`: NaN for the first k bars.
* Any comparison with NaN is False (numpy float semantics). Pine bools are never na,
  so `not cond` on a NaN comparison is True - we mirror that by computing the
  comparison first (-> False) and negating afterwards where Pine negates.
* `math.round` rounds ties UP: pine_round(v) = floor(v + 0.5). Python's round() is
  banker's rounding (round(182.5) == 182) and must not be used.
* `request.security(bench, "D", expr, lookahead_off)` (line 99) evaluates `expr` on
  the benchmark's OWN bars (its own 200 closes for the 200-day MA), then aligns the
  result to the chart by taking the last benchmark bar at or before each chart bar
  (gaps_off = forward fill, lookahead_off = never a later bar).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

OHLCV = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def pine_round(v):
    """Pine `math.round`: nearest integer, ties rounded up (floor(v + 0.5))."""
    if np.isscalar(v):
        return float(math.floor(float(v) + 0.5))
    return np.floor(np.asarray(v, dtype=float) + 0.5)


def pine_round_int(v) -> int:
    return int(math.floor(float(v) + 0.5))


def _window(x, n: int, how: str) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    n = int(n)
    if n < 1:
        raise ValueError("window length must be >= 1")
    out = np.full(arr.shape, np.nan)
    if arr.size >= n:
        w = sliding_window_view(arr, n)
        if how == "mean":
            # sum / n, NaN if any value in the window is NaN (Pine ta.sma)
            out[n - 1:] = w.sum(axis=1) / n
        elif how == "max":
            out[n - 1:] = w.max(axis=1)   # np.max propagates NaN
        elif how == "min":
            out[n - 1:] = w.min(axis=1)
        else:  # pragma: no cover
            raise ValueError(how)
    return out


def _series(values, like: pd.Series, name=None) -> pd.Series:
    return pd.Series(values, index=like.index, name=name)


def sma(x: pd.Series, n: int) -> pd.Series:
    """Pine ta.sma: mean of x[t-n+1..t]; NaN with < n bars or any NaN in the window."""
    return _series(_window(x.to_numpy(dtype=float), n, "mean"), x)


def highest(x: pd.Series, n: int) -> pd.Series:
    """Pine ta.highest(x, n): max of x[t-n+1..t] (includes bar t); NaN with < n bars."""
    return _series(_window(x.to_numpy(dtype=float), n, "max"), x)


def lowest(x: pd.Series, n: int) -> pd.Series:
    return _series(_window(x.to_numpy(dtype=float), n, "min"), x)


def lag(x: pd.Series, k: int) -> pd.Series:
    """Pine history reference x[k]."""
    return x.shift(int(k))


def weighted_perf_lags(n: int) -> tuple[int, int, int, int]:
    """Lags of f_weightedPerf (Pine lines 93-97).

    Pine v5 `/` on two ints returns a float (n / 4 = 91.25 for n = 365), then math.round
    rounds ties up: 365 -> (91, 183, 274, 365); 252 -> (63, 126, 189, 252).
    """
    n = int(n)
    return pine_round_int(n / 4), pine_round_int(n / 2), pine_round_int(n * 3 / 4), n


def weighted_perf(c: pd.Series, n: int) -> pd.Series:
    """IBD-style weighted 1-year performance (SPEC 4.4), same operation order as Pine."""
    q, h, t3, full = weighted_perf_lags(n)
    return (0.4 * (c / c.shift(q) - 1) + 0.2 * (c / c.shift(h) - 1)
            + 0.2 * (c / c.shift(t3) - 1) + 0.2 * (c / c.shift(full) - 1))


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine ta.tr(true): high - low when the previous close is na (first bar)."""
    prev = close.shift(1)
    full = np.maximum(high - low, np.maximum((high - prev).abs(), (low - prev).abs()))
    return full.where(prev.notna(), high - low)


# ---------------------------------------------------------------------------
# bar frames
# ---------------------------------------------------------------------------

def _to_ns(idx) -> pd.DatetimeIndex:
    di = pd.DatetimeIndex(pd.to_datetime(idx))
    if di.tz is not None:
        di = di.tz_localize(None)
    return di.normalize().astype("datetime64[ns]")


def normalize_bars(df: pd.DataFrame, require_ohlc: bool = True) -> pd.DataFrame:
    """Lower-case columns, float64 values, tz-naive midnight DatetimeIndex, sorted, unique.

    Accepts either a DatetimeIndex or a 'date' column. Duplicate dates keep the last row.
    """
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    if "date" in d.columns:
        d = d.set_index("date")
    d.index = _to_ns(d.index)
    d.index.name = "date"
    cols = OHLCV if require_ohlc else ("close",)
    for c in cols:
        if c not in d.columns:
            if c == "volume":
                d[c] = np.nan
            else:
                raise ValueError(f"missing column {c!r}")
    keep = [c for c in (OHLCV if require_ohlc else ("close",)) if c in d.columns]
    d = d[keep].apply(pd.to_numeric, errors="coerce").astype("float64")
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d


def bars_from_rows(rows, require_ohlc: bool = True) -> pd.DataFrame:
    """COMPARE_API row dicts -> normalized frame. `None` values become NaN."""
    if not rows:
        cols = list(OHLCV) if require_ohlc else ["close"]
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="date"), dtype="float64")
    df = pd.DataFrame(list(rows))
    for c in df.columns:
        if c != "date":
            df[c] = pd.to_numeric(df[c], errors="coerce")   # None -> NaN
    return normalize_bars(df, require_ohlc=require_ohlc)


# ---------------------------------------------------------------------------
# benchmark (SPEC 4.1)
# ---------------------------------------------------------------------------

BENCH_COLS = ("b_close", "b_ma200", "b_ma20", "b_perf")


def benchmark_series(bench: pd.DataFrame | None, year_bars: int) -> pd.DataFrame:
    """Benchmark columns computed on the benchmark's own bars."""
    if bench is None or len(bench) == 0:
        return pd.DataFrame(columns=list(BENCH_COLS), index=pd.DatetimeIndex([], name="date"), dtype="float64")
    b = bench["close"].astype("float64")
    return pd.DataFrame({
        "b_close": b,
        "b_ma200": sma(b, 200),
        "b_ma20": sma(b, 20),
        "b_perf": weighted_perf(b, year_bars),
    }, index=bench.index)


def align_asof(frame: pd.DataFrame, dates) -> pd.DataFrame:
    """For each date d take the last row of `frame` with index <= d (no lookahead).

    Rows are copied as they are, so a genuine NaN on the matched benchmark bar stays
    NaN (this is not a column-wise ffill). Dates before the first benchmark bar -> NaN.
    """
    target = _to_ns(dates)
    src_idx = _to_ns(frame.index).to_numpy()
    vals = frame.to_numpy(dtype=float)
    pos = np.searchsorted(src_idx, target.to_numpy(), side="right") - 1
    out = np.full((len(target), vals.shape[1] if vals.ndim == 2 else 0), np.nan)
    ok = pos >= 0
    if len(src_idx) and ok.any():
        out[ok] = vals[pos[ok]]
    return pd.DataFrame(out, index=target, columns=frame.columns)


# ---------------------------------------------------------------------------
# indicators (SPEC 4.2 - 4.6)
# ---------------------------------------------------------------------------

def compute_indicators(sym: pd.DataFrame, bench: pd.DataFrame | None, p: dict,
                       tt8_override: pd.Series | None = None) -> pd.DataFrame:
    """All per-bar columns for one symbol.

    `sym` must be normalized (see normalize_bars); `bench` needs a 'close' column.
    `tt8_override` (portfolio percentile mode, SPEC 8.2) replaces tt8.
    """
    c, h, l, v = sym["close"], sym["high"], sym["low"], sym["volume"]
    yb = int(p["year_bars"])
    out = pd.DataFrame(index=sym.index)

    # --- 4.1 benchmark on its own bars, then aligned with no lookahead
    bser = benchmark_series(bench, yb)
    out[list(BENCH_COLS)] = align_asof(bser, sym.index).to_numpy()

    # --- 4.2 regime
    mode = p["regime_mode"]
    if mode == "NONE":
        regime = pd.Series(True, index=sym.index)
    elif mode == "MA200_AND_MA20":
        regime = (out["b_close"] > out["b_ma200"]) & (out["b_close"] > out["b_ma20"])
    elif mode == "MA200":
        regime = out["b_close"] > out["b_ma200"]
    else:
        raise ValueError(f"unknown regime_mode {mode!r}")
    out["regime_on"] = regime.astype(bool)

    # --- 4.3 trend template
    out["ma50"] = ma50 = sma(c, 50)
    out["ma150"] = ma150 = sma(c, 150)
    out["ma200"] = ma200 = sma(c, 200)
    out["exit_ma"] = sma(c, int(p["exit_ma_len"]))
    out["hi52"] = hi52 = highest(c, yb)      # close-based, includes bar t (SPEC 9 #4)
    out["lo52"] = lo52 = lowest(c, yb)
    out["wp"] = wp = weighted_perf(c, yb)
    out["rs_diff"] = rs_diff = (wp - out["b_perf"]) * 100

    out["tt1"] = (c > ma150) & (c > ma200)
    out["tt2"] = ma150 > ma200
    out["tt3"] = ma200 > ma200.shift(int(p["ma200_rise_bars"]))
    out["tt4"] = (ma50 > ma150) & (ma50 > ma200)
    out["tt5"] = c > ma50
    # Keep Pine's exact float expression: close >= lo52 * 1.30 (not close / lo52 >= 1.3).
    # e.g. lo52 = 3, close = 3.9: 3 * 1.30 = 3.9000000000000004 > 3.9 -> False.
    out["tt6"] = c >= lo52 * 1.30
    out["tt7"] = c >= hi52 * 0.75
    out["tt8_proxy"] = rs_diff >= float(p["rs_min_diff"])

    # --- 4.5 trigger, volume, chase cap
    # pivot = ta.highest(high[1], pivot_len): the previous pivot_len highs, bar t excluded.
    # high[1] is NaN on bar 0, so the first valid pivot is at bar pivot_len.
    out["pivot"] = pivot = highest(h.shift(1), int(p["pivot_len"]))
    # vol_avg = ta.sma(volume, vol_len)[1]: previous vol_len volumes, bar t excluded.
    out["vol_avg"] = vol_avg = sma(v, int(p["vol_len"])).shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["vol_x"] = np.where(vol_avg > 0, v / vol_avg, np.nan)   # NaN vol_avg -> NaN
    out["breakout_pct"] = breakout_pct = (c / pivot - 1) * 100
    out["to_pivot_pct"] = (pivot / c - 1) * 100
    out["breakout"] = c > pivot                          # close == pivot is NOT a breakout
    out["vol_ok"] = out["vol_x"] >= float(p["vol_mult"])  # exactly 1.4x passes
    if p["cap_on"]:
        out["cap_ok"] = breakout_pct <= float(p["max_breakout_pct"])
    else:
        out["cap_ok"] = True
    if p["use_value_filter"]:
        out["liquidity_ok"] = (c * v) >= float(p["min_trading_value"])
    else:
        out["liquidity_ok"] = True

    # --- 4.6 display-only
    tr = true_range(h, l, c)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["contraction"] = sma(tr, 10) / sma(tr, 40)
        out["dry_up"] = sma(v, 10) / sma(v, 50)
    out["from_high52"] = (c / hi52 - 1) * 100

    return finalize_signals(out, p, tt8_override)


def finalize_signals(out: pd.DataFrame, p: dict, tt8_override: pd.Series | None = None) -> pd.DataFrame:
    """tt8 -> tt_count -> tt_pass -> candidate -> full_signal (can be re-run with another tt8)."""
    if tt8_override is None:
        out["tt8"] = out["tt8_proxy"].astype(bool)
    else:
        out["tt8"] = pd.Series(tt8_override, index=out.index).fillna(False).astype(bool)
    tts = [f"tt{i}" for i in range(1, 9)]
    for k in tts:
        out[k] = out[k].fillna(False).astype(bool)
    out["tt_count"] = out[tts].sum(axis=1).astype(int)
    out["tt_pass"] = (out["tt_count"] == 8) if p["use_tt"] else True
    out["tt_pass"] = out["tt_pass"].astype(bool)
    for k in ("breakout", "vol_ok", "cap_ok", "liquidity_ok", "regime_on"):
        out[k] = out[k].fillna(False).astype(bool)
    out["candidate"] = out["tt_pass"] & out["liquidity_ok"]
    out["full_signal"] = (out["breakout"] & out["vol_ok"] & out["cap_ok"]
                          & out["candidate"] & out["regime_on"])
    return out
