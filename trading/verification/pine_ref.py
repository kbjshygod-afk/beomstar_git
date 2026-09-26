#!/usr/bin/env python3
"""
Independent pure-Python reference of the Pine v5 indicator
`minervini_swing_watch.pine` ("Minervini Swing Watch", MSW).

Standard library only (no pandas, no numpy). Written blind to trading/swing_engine
and trading/tests. Ground truth is the Pine source; SPEC.md is secondary.

Emulation approach (literal, bar by bar):
  * The script body is executed once per bar t = 0..N-1, appending to full history
    arrays, exactly as Pine's runtime does. `x[k]` reads the array at t-k (na if < 0).
  * na is Python None. Arithmetic with na gives na; every comparison with na is False
    (Pine v5 semantics). Division by zero gives na (assumption, see REPORT at bottom).
  * ta.sma / ta.highest / ta.lowest are recomputed naively over each window.
    SMA uses math.fsum(window) / length (correctly rounded sum, one division).
  * Default na handling inside ta.* windows = propagation (SPEC section 3): any na in
    the window, or fewer than `length` bars, gives na. Pass params["ta_skip_na"]=True
    (or set TA_SKIP_NA) for the alternative reading of the Pine reference manual
    ("na values in the source series are ignored"); see the report for details.
  * request.security(..., lookahead_off): the benchmark context runs its own bar loop
    over bench_rows (close, sma200, sma20, weighted perf on the benchmark's own bars);
    each symbol bar then takes the latest benchmark bar with date <= symbol date, else na.
  * Every bar is a confirmed historical bar (barstate.isconfirmed is true).
  * var state (entryPending, exitPending, entryPrice, stopPrice) persists across bars;
    the state-machine block runs in the exact Pine order.

Public API (see COMPARE_API.md):  compute(symbol_rows, bench_rows, params) -> dict
"""

import math
from bisect import bisect_right

TA_SKIP_NA = False  # default: SPEC section 3 na propagation inside ta.* windows

# =============================================================================
# Pine primitives
# =============================================================================


def is_na(x):
    return x is None


def pine_round(v):
    """math.round(): nearest integer, ties rounding up (floor(v + 0.5))."""
    if v is None:
        return None
    return int(math.floor(v + 0.5))


def _f(x):
    """Input value -> float or na. NaN floats are treated as na."""
    if x is None:
        return None
    x = float(x)
    if x != x:  # NaN
        return None
    return x


def add(a, b):
    return None if a is None or b is None else a + b


def sub(a, b):
    return None if a is None or b is None else a - b


def mul(a, b):
    return None if a is None or b is None else a * b


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def gt(a, b):
    return a is not None and b is not None and a > b


def ge(a, b):
    return a is not None and b is not None and a >= b


def lt(a, b):
    return a is not None and b is not None and a < b


def le(a, b):
    return a is not None and b is not None and a <= b


def pmin(a, b):
    """math.min: na if any argument is na."""
    return None if a is None or b is None else min(a, b)


def pmax(a, b):
    return None if a is None or b is None else max(a, b)


def pabs(a):
    return None if a is None else abs(a)


def hist(series, t, k):
    """series[k] evaluated on bar t: value at bar t-k, na when t-k < 0."""
    if k is None:
        return None
    i = t - k
    if i < 0 or i > t:
        return None
    return series[i]


def ta_sma(src, t, length, skip_na=False):
    """ta.sma(src, length) on bar t, recomputed naively from the history array."""
    if skip_na:
        vals = []
        i = t
        while i >= 0 and len(vals) < length:
            if src[i] is not None:
                vals.append(src[i])
            i -= 1
        if len(vals) < length:
            return None
        return math.fsum(vals) / length
    start = t - length + 1
    if start < 0:
        return None
    window = src[start:t + 1]
    for v in window:
        if v is None:
            return None
    return math.fsum(window) / length


def _ta_extreme(src, t, length, skip_na, fn):
    start = t - length + 1
    if start < 0:
        return None  # fewer than `length` bars of history
    window = src[start:t + 1]
    if skip_na:
        vals = [v for v in window if v is not None]
        return fn(vals) if vals else None
    for v in window:
        if v is None:
            return None
    return fn(window)


def ta_highest(src, t, length, skip_na=False):
    return _ta_extreme(src, t, length, skip_na, max)


def ta_lowest(src, t, length, skip_na=False):
    return _ta_extreme(src, t, length, skip_na, min)


def ta_tr_true(high, low, close, t):
    """ta.tr(true): high-low when close[1] is na, else the usual true range."""
    h, l = high[t], low[t]
    pc = hist(close, t, 1)
    if pc is None:
        return sub(h, l)
    return pmax(pmax(sub(h, l), pabs(sub(h, pc))), pabs(sub(l, pc)))


def f_weighted_perf(close, t, n):
    """
    f_weightedPerf(n) =>
        q = math.round(n / 4); h = math.round(n / 2); t = math.round(n * 3 / 4)
        0.4*(close/close[q]-1) + 0.2*(close/close[h]-1) + 0.2*(close/close[t]-1) + 0.2*(close/close[n]-1)
    n (yearBars) derives from inputs, so it is not 'const int' and `/` is float division
    in Pine v5 (365/2 = 182.5 -> 183).
    """
    q = pine_round(n / 4)
    h = pine_round(n / 2)
    t3 = pine_round(n * 3 / 4)
    c = close[t]
    a = sub(div(c, hist(close, t, q)), 1)
    b = sub(div(c, hist(close, t, h)), 1)
    d = sub(div(c, hist(close, t, t3)), 1)
    e = sub(div(c, hist(close, t, n)), 1)
    return add(add(add(mul(0.4, a), mul(0.2, b)), mul(0.2, d)), mul(0.2, e))


def weighted_perf_lags(n):
    return (pine_round(n / 4), pine_round(n / 2), pine_round(n * 3 / 4), n)


def fmt_pct(x):
    """f_pct(x) = na(x) ? "-" : str.tostring(x, "+#.#;-#.#") + "%"   (SPEC section 6 rule)."""
    if x is None:
        return "-"
    k = pine_round(abs(x) * 10)  # tenths, ties up
    s = str(k // 10) if k % 10 == 0 else "%d.%d" % (k // 10, k % 10)
    return ("+" if x >= 0 else "-") + s + "%"


# =============================================================================
# request.security: benchmark context
# =============================================================================


def _bench_context(bench_rows, year_bars, skip_na):
    """Run [close, ta.sma(close,200), ta.sma(close,20), f_weightedPerf(yearBars)] on the
    benchmark's own bars. Returns (dates, [(bClose, bMa200, bMa20, bPerf), ...])."""
    dates = []
    close = []
    out = []
    for t, r in enumerate(bench_rows):
        dates.append(str(r["date"]))
        close.append(_f(r["close"]))
        b_ma200 = ta_sma(close, t, 200, skip_na)
        b_ma20 = ta_sma(close, t, 20, skip_na)
        b_perf = f_weighted_perf(close, t, year_bars)
        out.append((close[t], b_ma200, b_ma20, b_perf))
    for i in range(1, len(dates)):
        if not dates[i - 1] < dates[i]:
            raise ValueError("bench_rows must be ascending with unique dates")
    return dates, out


def _security_lookup(b_dates, b_vals, date):
    """lookahead_off on confirmed history: latest benchmark bar with date <= symbol date."""
    j = bisect_right(b_dates, date) - 1
    if j < 0:
        return (None, None, None, None)
    return b_vals[j]


# =============================================================================
# Indicator
# =============================================================================

_REGIMES = ("MA200", "MA200_AND_MA20", "NONE")


def compute(symbol_rows, bench_rows, params):
    p = params
    stop_pct = float(p["stop_pct"])
    cap_on = bool(p["cap_on"])
    year_bars = int(p["year_bars"])
    regime_mode = p["regime_mode"]
    pivot_len = int(p["pivot_len"])
    vol_len = int(p["vol_len"])
    vol_mult = float(p["vol_mult"])
    max_breakout_pct = float(p["max_breakout_pct"])
    use_tt = bool(p["use_tt"])
    ma200_rise_bars = int(p["ma200_rise_bars"])
    rs_min_diff = float(p["rs_min_diff"])
    exit_ma_len = int(p["exit_ma_len"])
    use_value_filter = bool(p["use_value_filter"])
    min_trading_value = float(p["min_trading_value"])
    skip_na = bool(p.get("ta_skip_na", TA_SKIP_NA))
    if regime_mode not in _REGIMES:
        raise ValueError("unknown regime_mode %r" % (regime_mode,))

    b_dates, b_vals = _bench_context(bench_rows, year_bars, skip_na)

    # ----- history arrays (one slot per bar, appended as the script runs) -----
    open_, high, low, close, volume, dates = [], [], [], [], [], []
    high_1 = []           # the series `high[1]`
    ma50_s, ma150_s, ma200_s, exit_ma_s = [], [], [], []
    hi52_s, lo52_s = [], []
    vol_sma_s = []        # ta.sma(volume, volLen)

    # ----- var state -----
    entry_pending = False
    exit_pending = False
    entry_price = None
    stop_price = None

    bars = []
    events = []
    last = None  # values needed for statusTxt on the last bar

    for t, r in enumerate(symbol_rows):
        d = str(r["date"])
        if dates and not dates[-1] < d:
            raise ValueError("symbol_rows must be ascending with unique dates")
        dates.append(d)
        open_.append(_f(r["open"]))
        high.append(_f(r["high"]))
        low.append(_f(r["low"]))
        close.append(_f(r["close"]))
        volume.append(_f(r.get("volume")))
        o, h, l, c, v = open_[t], high[t], low[t], close[t], volume[t]

        # [bClose, bMa200, bMa20, bPerf] = request.security(...)
        b_close, b_ma200, b_ma20, b_perf = _security_lookup(b_dates, b_vals, d)

        # ----- 3-1 regime -----
        if regime_mode == "NONE":
            regime_on = True
        elif regime_mode == "MA200_AND_MA20":
            regime_on = gt(b_close, b_ma200) and gt(b_close, b_ma20)
        else:
            regime_on = gt(b_close, b_ma200)

        # ----- 3-2 trend template -----
        ma50_s.append(ta_sma(close, t, 50, skip_na))
        ma150_s.append(ta_sma(close, t, 150, skip_na))
        ma200_s.append(ta_sma(close, t, 200, skip_na))
        exit_ma_s.append(ta_sma(close, t, exit_ma_len, skip_na))
        hi52_s.append(ta_highest(close, t, year_bars, skip_na))
        lo52_s.append(ta_lowest(close, t, year_bars, skip_na))
        ma50, ma150, ma200, exit_ma = ma50_s[t], ma150_s[t], ma200_s[t], exit_ma_s[t]
        hi52, lo52 = hi52_s[t], lo52_s[t]
        rs_diff = mul(sub(f_weighted_perf(close, t, year_bars), b_perf), 100)

        tt1 = gt(c, ma150) and gt(c, ma200)
        tt2 = gt(ma150, ma200)
        tt3 = gt(ma200, hist(ma200_s, t, ma200_rise_bars))
        tt4 = gt(ma50, ma150) and gt(ma50, ma200)
        tt5 = gt(c, ma50)
        tt6 = ge(c, mul(lo52, 1.30))
        tt7 = ge(c, mul(hi52, 0.75))
        tt8 = ge(rs_diff, rs_min_diff)
        tt = [tt1, tt2, tt3, tt4, tt5, tt6, tt7, tt8]
        tt_count = sum(1 if x else 0 for x in tt)
        tt_pass = (not use_tt) or tt_count == 8

        # ----- 3-3 trigger / volume / chase cap -----
        high_1.append(hist(high, t, 1))
        pivot = ta_highest(high_1, t, pivot_len, skip_na)
        vol_sma_s.append(ta_sma(volume, t, vol_len, skip_na))
        vol_avg = hist(vol_sma_s, t, 1)
        vol_x = div(v, vol_avg) if gt(vol_avg, 0) else None
        breakout_pct = mul(sub(div(c, pivot), 1), 100)
        to_pivot_pct = mul(sub(div(pivot, c), 1), 100)

        breakout = gt(c, pivot)
        vol_ok = ge(vol_x, vol_mult)
        cap_ok = (not cap_on) or le(breakout_pct, max_breakout_pct)

        liquidity_ok = (not use_value_filter) or ge(mul(c, v), min_trading_value)
        candidate = tt_pass and liquidity_ok
        full_signal = breakout and vol_ok and cap_ok and candidate and regime_on

        # ----- 3-5 position tracking (barstate.isconfirmed is always true here) -----
        signal = False
        if exit_pending:
            exit_pending = False
            exit_pnl = mul(sub(div(o, entry_price), 1), 100)
            events.append({"date": d, "type": "EXIT_MA", "price": o, "pnl_pct": exit_pnl})
            entry_price = None
            stop_price = None
        if entry_pending:
            entry_pending = False
            entry_price = o
            stop_price = mul(o, 1 - stop_pct / 100)
            events.append({"date": d, "type": "ENTRY", "price": o, "pnl_pct": None})
        if not is_na(entry_price):
            if le(l, stop_price):
                fill = pmin(o, stop_price)
                stop_pnl = mul(sub(div(fill, entry_price), 1), 100)
                events.append({"date": d, "type": "STOP", "price": fill, "pnl_pct": stop_pnl})
                entry_price = None
                stop_price = None
            elif lt(c, exit_ma):
                exit_pending = True
                events.append({"date": d, "type": "EXIT_SIGNAL", "price": c, "pnl_pct": None})
        if is_na(entry_price):
            signal = full_signal
            entry_pending = signal
            if signal:
                events.append({"date": d, "type": "SIGNAL", "price": c, "pnl_pct": None})

        bars.append({
            "date": d,
            "ma50": ma50, "ma150": ma150, "ma200": ma200, "exit_ma": exit_ma,
            "hi52": hi52, "lo52": lo52, "rs_diff": rs_diff,
            "tt": tt, "tt_count": tt_count, "tt_pass": tt_pass,
            "pivot": pivot, "vol_x": vol_x,
            "breakout": breakout, "vol_ok": vol_ok, "cap_ok": cap_ok, "regime_on": regime_on,
            "candidate": candidate, "full_signal": full_signal,
            "entry_price": entry_price, "stop_price": stop_price,
            "entry_pending": entry_pending, "exit_pending": exit_pending,
        })
        last = dict(in_pos=not is_na(entry_price), entry_pending=entry_pending,
                    tt_pass=tt_pass, tt_count=tt_count, liquidity_ok=liquidity_ok,
                    regime_on=regime_on, breakout=breakout, cap_ok=cap_ok, vol_ok=vol_ok,
                    breakout_pct=breakout_pct, to_pivot_pct=to_pivot_pct)

    status = _status_txt(last, exit_ma_len) if last is not None else ""
    return {"bars": bars, "events": events, "status": status}


def _status_txt(s, exit_ma_len):
    exit_ma_name = str(exit_ma_len) + "일선"
    if s["in_pos"]:
        return "보유 중 — " + exit_ma_name + " 종가 이탈 시 청산"
    if s["entry_pending"]:
        return "신호 확정 → 다음 시가 진입"
    if not s["tt_pass"]:
        return "후보 아님 (트렌드 템플릿 " + str(s["tt_count"]) + "/8)"
    if not s["liquidity_ok"]:
        return "후보 아님 (거래대금 부족)"
    if not s["regime_on"]:
        return "레짐 OFF — 신규 진입 금지"
    if s["breakout"] and not s["cap_ok"]:
        return "추격 제외 (돌파폭 " + fmt_pct(s["breakout_pct"]) + ")"
    if s["breakout"] and not s["vol_ok"]:
        return "돌파 · 거래량 부족"
    if le(s["to_pivot_pct"], 1):
        return "1순위 · 임박 (피벗 1% 이내)"
    if le(s["to_pivot_pct"], 3):
        return "2순위 · 근접 (피벗 3% 이내)"
    return "3순위 · 관찰"


def display_only(symbol_rows, params):
    """Display-only table values (section 3-4): contraction, dryUp, fromHigh52. Not part
    of the comparison output; kept for completeness of the emulation (ta.tr(true))."""
    skip_na = bool(params.get("ta_skip_na", TA_SKIP_NA))
    year_bars = int(params["year_bars"])
    high, low, close, volume, tr = [], [], [], [], []
    out = []
    for t, r in enumerate(symbol_rows):
        high.append(_f(r["high"]))
        low.append(_f(r["low"]))
        close.append(_f(r["close"]))
        volume.append(_f(r.get("volume")))
        tr.append(ta_tr_true(high, low, close, t))
        contraction = div(ta_sma(tr, t, 10, skip_na), ta_sma(tr, t, 40, skip_na))
        dry_up = div(ta_sma(volume, t, 10, skip_na), ta_sma(volume, t, 50, skip_na))
        hi52 = ta_highest(close, t, year_bars, skip_na)
        from_high52 = mul(sub(div(close[t], hi52), 1), 100)
        out.append({"date": str(r["date"]), "tr": tr[t], "contraction": contraction,
                    "dry_up": dry_up, "from_high52": from_high52})
    return out


# =============================================================================
# Self-test (synthetic data, hand-derived expectations)
# =============================================================================

if __name__ == "__main__":
    import datetime as _dt
    import time as _time

    _checks = [0]

    def check(cond, msg):
        _checks[0] += 1
        if not cond:
            raise AssertionError(msg)

    def close_to(a, b, tol=1e-9):
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))

    # ---------------- T1: primitives ----------------
    check(pine_round(182.5) == 183 and pine_round(91.25) == 91 and pine_round(273.75) == 274, "round")
    check(pine_round(2.5) == 3 and pine_round(-2.5) == -2 and pine_round(0.49) == 0, "round ties up")
    check(weighted_perf_lags(252) == (63, 126, 189, 252), "lags 252")
    check(weighted_perf_lags(365) == (91, 183, 274, 365), "lags 365")
    check(weighted_perf_lags(250) == (63, 125, 188, 250), "lags 250 (62.5->63, 187.5->188)")
    check(fmt_pct(16.04) == "+16%" and fmt_pct(16.25) == "+16.3%", "fmt_pct SPEC examples")
    check(fmt_pct(-3.14) == "-3.1%" and fmt_pct(0.0) == "+0%" and fmt_pct(None) == "-", "fmt_pct misc")
    check(fmt_pct(16.8316831683) == "+16.8%" and fmt_pct(9.96) == "+10%", "fmt_pct rounding")
    s = [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0, 8.0]
    check(ta_sma(s, 1, 3) is None and ta_sma(s, 2, 3) == 2.0, "sma warmup")
    check(ta_sma(s, 3, 3) is None and ta_sma(s, 5, 3) is None and ta_sma(s, 6, 3) == 6.0, "sma na propagation")
    check(ta_sma(s, 4, 3, True) == (2 + 3 + 5) / 3 and ta_sma(s, 2, 3, True) == 2.0, "sma skip-na")
    check(ta_highest(s, 2, 3) == 3.0 and ta_highest(s, 1, 3) is None and ta_highest(s, 4, 3) is None, "highest")
    check(ta_highest(s, 4, 3, True) == 5.0 and ta_lowest(s, 6, 3) == 5.0, "highest skip / lowest")
    check(hist(s, 2, 3) is None and hist(s, 5, 2) is None and hist(s, 5, 1) == 5.0, "history ref")
    check(not gt(None, 1) and not ge(1, None) and not lt(None, None) and not le(None, 0), "na compare false")
    check(ta_tr_true([10.0, 12.0], [9.0, 11.5], [9.5, 12.0], 0) == 1.0, "tr first bar = high-low")
    check(ta_tr_true([10.0, 12.0], [9.0, 11.5], [9.5, 12.0], 1) == 2.5, "tr uses prev close")

    # ---------------- T2: hand-built state-machine scenario ----------------
    def mkrows(ohlcv, start="2024-01-01"):
        d0 = _dt.date.fromisoformat(start)
        return [{"date": (d0 + _dt.timedelta(days=i)).isoformat(), "open": o, "high": h,
                 "low": l, "close": c, "volume": v} for i, (o, h, l, c, v) in enumerate(ohlcv)]

    P_SMALL = dict(stop_pct=10.0, cap_on=True, year_bars=252, regime_mode="NONE", pivot_len=5,
                   vol_len=10, vol_mult=1.4, max_breakout_pct=15.0, use_tt=False,
                   ma200_rise_bars=22, rs_min_diff=0.0, exit_ma_len=5, use_value_filter=False,
                   min_trading_value=3e9)
    base = [(100.0, 101.0, 99.0, 100.0, 1000.0)] * 10
    tail = [
        (100.0, 104.0, 100.0, 103.0, 2000.0),   # 10 signal
        (104.0, 106.0, 102.0, 105.0, 1500.0),   # 11 entry @104, stop 93.6
        (105.0, 105.5, 98.5, 99.0, 1200.0),     # 12 close < sma5 101.4 -> exit signal
        (98.0, 109.0, 97.5, 108.0, 2000.0),     # 13 exit @98, then new signal (pivot 106)
        (110.0, 115.0, 98.0, 112.0, 3000.0),    # 14 entry @110, stop on entry bar, re-signal
        (111.0, 113.0, 108.0, 112.0, 1000.0),   # 15 entry @111, stop 99.9
        (95.0, 97.0, 94.0, 96.0, 1000.0),       # 16 gap below stop -> fill at open 95
        (96.0, 100.0, 95.0, 99.0, 1000.0),      # 17 flat, 3rd priority
    ]
    rows = mkrows(base + tail)
    dts = [r["date"] for r in rows]
    res = compute(rows, [], P_SMALL)
    ev = [(e["date"], e["type"], e["price"], e["pnl_pct"]) for e in res["events"]]
    exp = [
        (dts[10], "SIGNAL", 103.0, None),
        (dts[11], "ENTRY", 104.0, None),
        (dts[12], "EXIT_SIGNAL", 99.0, None),
        (dts[13], "EXIT_MA", 98.0, (98.0 / 104.0 - 1) * 100),
        (dts[13], "SIGNAL", 108.0, None),
        (dts[14], "ENTRY", 110.0, None),
        (dts[14], "STOP", 99.0, -10.0),
        (dts[14], "SIGNAL", 112.0, None),
        (dts[15], "ENTRY", 111.0, None),
        (dts[16], "STOP", 95.0, (95.0 / 111.0 - 1) * 100),
    ]
    check(len(ev) == len(exp), "event count %d vs %d: %r" % (len(ev), len(exp), ev))
    for got, want in zip(ev, exp):
        check(got[0] == want[0] and got[1] == want[1], "event id %r vs %r" % (got, want))
        check(close_to(got[2], want[2]) and close_to(got[3], want[3]), "event nums %r vs %r" % (got, want))
    b = res["bars"]
    check(b[9]["pivot"] == 101.0 and b[4]["pivot"] is None and b[5]["pivot"] == 101.0, "pivot warmup")
    check(b[9]["vol_x"] is None and b[10]["vol_x"] == 2.0, "vol_x warmup / value")
    check(close_to(b[11]["vol_x"], 1500 / 1100) and not b[11]["vol_ok"] and b[11]["breakout"], "vol_x bar 11")
    check(close_to(b[13]["vol_x"], 2000 / 1170) and b[13]["pivot"] == 106.0, "bar 13 pivot/vol")
    check(close_to(b[12]["exit_ma"], 101.4) and b[3]["exit_ma"] is None, "exit_ma")
    check(b[10]["entry_pending"] and b[10]["entry_price"] is None, "bar 10 state")
    check(b[11]["entry_price"] == 104.0 and close_to(b[11]["stop_price"], 93.6), "bar 11 state")
    check(b[12]["exit_pending"] and b[12]["entry_price"] == 104.0, "bar 12 state")
    check(not b[13]["exit_pending"] and b[13]["entry_pending"] and b[13]["entry_price"] is None, "bar 13 state")
    check(b[14]["entry_price"] is None and b[14]["stop_price"] is None and b[14]["entry_pending"], "bar 14 state")
    check(b[15]["entry_price"] == 111.0 and close_to(b[15]["stop_price"], 99.9), "bar 15 state")
    check(b[16]["entry_price"] is None and not b[16]["entry_pending"], "bar 16 state")
    check(b[10]["tt_count"] == 0 and b[10]["tt"] == [False] * 8 and b[10]["tt_pass"], "use_tt off")
    check(b[10]["regime_on"] and b[10]["rs_diff"] is None and b[10]["ma50"] is None, "NONE regime, na")
    check(res["status"] == "3순위 · 관찰", "status end: %s" % res["status"])
    check(compute(rows[:11], [], P_SMALL)["status"] == "신호 확정 → 다음 시가 진입", "status pending")
    check(compute(rows[:12], [], P_SMALL)["status"] == "보유 중 — 5일선 종가 이탈 시 청산", "status in pos")
    r13 = compute(rows[:13], [], P_SMALL)
    check(r13["status"] == "보유 중 — 5일선 종가 이탈 시 청산" and r13["bars"][-1]["exit_pending"], "in pos + exit pending")
    check(compute(rows[:17], [], P_SMALL)["status"] == "3순위 · 관찰", "status after gap stop")

    # ---------------- T3: status priority variants on bar 10 ----------------
    def variant(bar10, **over):
        pp = dict(P_SMALL)
        pp.update(over.pop("params", {}))
        return compute(mkrows(base + [bar10]), over.pop("bench", []), pp)

    r = variant((100.0, 119.0, 100.0, 118.0, 2000.0))
    check(r["status"] == "추격 제외 (돌파폭 +16.8%)" and not r["bars"][-1]["cap_ok"], "chase: " + r["status"])
    r = variant((100.0, 119.0, 100.0, 118.0, 2000.0), params={"cap_on": False})
    check(r["status"] == "신호 확정 → 다음 시가 진입", "cap off -> signal")
    r = variant((100.0, 104.0, 100.0, 103.0, 1200.0))
    check(r["status"] == "돌파 · 거래량 부족" and close_to(r["bars"][-1]["vol_x"], 1.2), "low vol")
    r = variant((100.0, 101.0, 99.0, 100.5, 2000.0))
    check(r["status"] == "1순위 · 임박 (피벗 1% 이내)", "near 1%")
    r = variant((100.0, 101.0, 98.0, 99.0, 2000.0))
    check(r["status"] == "2순위 · 근접 (피벗 3% 이내)", "near 3%")
    r = variant((100.0, 101.0, 96.0, 97.0, 2000.0))
    check(r["status"] == "3순위 · 관찰", "watch")
    r = variant((100.0, 104.0, 100.0, 103.0, 2000.0), params={"regime_mode": "MA200"},
                bench=[{"date": x["date"], "close": 1.0} for x in mkrows(base)])
    check(r["status"] == "레짐 OFF — 신규 진입 금지" and not r["bars"][-1]["regime_on"], "regime off")
    r = variant((100.0, 119.0, 100.0, 118.0, 2000.0), params={"regime_mode": "MA200"})
    check(r["status"] == "레짐 OFF — 신규 진입 금지", "regime off outranks chase (no bench)")
    r = variant((100.0, 104.0, 100.0, 103.0, 2000.0), params={"use_tt": True})
    check(r["status"] == "후보 아님 (트렌드 템플릿 0/8)", "tt fail: " + r["status"])
    r = variant((100.0, 104.0, 100.0, 103.0, 2000.0), params={"use_value_filter": True, "min_trading_value": 1e9})
    check(r["status"] == "후보 아님 (거래대금 부족)", "liquidity")
    r = variant((100.0, 104.0, 100.0, 103.0, 2000.0), params={"use_value_filter": True, "min_trading_value": 206000.0})
    check(r["status"] == "신호 확정 → 다음 시가 진입", "liquidity boundary (>=)")
    r = variant((100.0, 104.0, 100.0, 103.0, None))
    check(r["bars"][-1]["vol_x"] is None and r["status"] == "돌파 · 거래량 부족", "missing volume today")

    # ---------------- T4: analytic 300-bar series + 7-day benchmark with a gap ----------------
    def weekdays(start, n):
        d = _dt.date.fromisoformat(start)
        out = []
        while len(out) < n:
            if d.weekday() < 5:
                out.append(d.isoformat())
            d += _dt.timedelta(days=1)
        return out

    N = 300
    sdates = weekdays("2020-01-01", N)
    closes = [50.0 + 0.2 * t for t in range(N)]
    srows = []
    for t in range(N):
        o = closes[t - 1] if t > 0 else 50.0
        vol = 2000.0 if t == 270 else (None if t == 100 else 1000.0)
        srows.append({"date": sdates[t], "open": o, "high": closes[t] + 0.05,
                      "low": min(o, closes[t]) - 0.1, "close": closes[t], "volume": vol})
    skipped = "2021-01-15"  # a Friday that the benchmark lacks (holiday) -> use Thursday's bar
    check(skipped in sdates, "test setup: skipped date is a symbol date")
    bdates = []
    d = _dt.date(2019, 1, 1)
    while d <= _dt.date(2021, 6, 1):
        if d.isoformat() != skipped:
            bdates.append(d.isoformat())
        d += _dt.timedelta(days=1)
    bcl = [1000.0 + 0.5 * k for k in range(len(bdates))]
    brows = [{"date": x, "close": y} for x, y in zip(bdates, bcl)]
    P252 = dict(P_SMALL, year_bars=252, regime_mode="MA200", pivot_len=20, vol_len=50, use_tt=True,
                exit_ma_len=50)

    def wp_closed(cs, i, lags):
        if i - lags[3] < 0:
            return None
        return (0.4 * (cs[i] / cs[i - lags[0]] - 1) + 0.2 * (cs[i] / cs[i - lags[1]] - 1)
                + 0.2 * (cs[i] / cs[i - lags[2]] - 1) + 0.2 * (cs[i] / cs[i - lags[3]] - 1))

    t0 = _time.time()
    res = compute(srows, brows, P252)
    t_elapsed = _time.time() - t0
    b = res["bars"]
    lags = (63, 126, 189, 252)
    for t in range(N):
        j = -1
        for k, bd in enumerate(bdates):  # independent linear scan for the aligned bench bar
            if bd <= sdates[t]:
                j = k
        bperf = wp_closed(bcl, j, lags)
        sperf = wp_closed(closes, t, lags)
        want_rs = None if (bperf is None or sperf is None) else (sperf - bperf) * 100
        check(close_to(b[t]["rs_diff"], want_rs), "rs_diff t=%d" % t)
        for n, key in ((50, "ma50"), (150, "ma150"), (200, "ma200")):
            want = 50.0 + 0.2 * (t - (n - 1) / 2) if t >= n - 1 else None
            check(close_to(b[t][key], want), "%s t=%d" % (key, t))
        check(close_to(b[t]["hi52"], closes[t] if t >= 251 else None), "hi52 t=%d" % t)
        check(close_to(b[t]["lo52"], closes[t - 251] if t >= 251 else None), "lo52 t=%d" % t)
        check(close_to(b[t]["pivot"], closes[t - 1] + 0.05 if t >= 20 else None), "pivot t=%d" % t)
        want_vx = None if (t < 50 or 100 <= t <= 150) else (2.0 if t == 270 else 1000.0 / (1020.0 if 271 <= t <= 320 else 1000.0))
        check(close_to(b[t]["vol_x"], want_vx), "vol_x t=%d got %r want %r" % (t, b[t]["vol_x"], want_vx))
        want_cnt = (8 if t >= 252 else 7 if t >= 251 else
                    sum([t >= 199, t >= 199, t >= 221, t >= 199, t >= 49, False, False, False]))
        check(b[t]["tt_count"] == want_cnt, "tt_count t=%d got %d want %d" % (t, b[t]["tt_count"], want_cnt))
        check(b[t]["regime_on"], "regime on t=%d" % t)
    ji = sdates.index(skipped)
    check(ji >= 252 and close_to(b[ji]["rs_diff"], (wp_closed(closes, ji, lags) - wp_closed(bcl, bdates.index("2021-01-14"), lags)) * 100),
          "holiday forward fill")
    evs = [(e["date"], e["type"]) for e in res["events"]]
    check(evs == [(sdates[270], "SIGNAL"), (sdates[271], "ENTRY")], "T4 events %r" % evs)
    check(res["events"][1]["price"] == closes[270], "T4 entry at next open")
    check(res["status"] == "보유 중 — 50일선 종가 이탈 시 청산", "T4 status " + res["status"])
    r2 = compute(srows, brows, dict(P252, regime_mode="MA200_AND_MA20"))
    check([(e["date"], e["type"]) for e in r2["events"]] == evs, "MA200_AND_MA20 same")
    brows_dn = [{"date": x, "close": 3000.0 - 0.5 * k} for k, x in enumerate(bdates)]
    r3 = compute(srows, brows_dn, P252)
    check(r3["events"] == [] and r3["status"] == "레짐 OFF — 신규 진입 금지", "falling bench -> regime off")
    r4 = compute(srows, [x for x in brows if x["date"] >= "2020-03-01"], dict(P252, regime_mode="NONE"))
    check(r4["bars"][0]["rs_diff"] is None and r4["bars"][0]["regime_on"], "no bench bar yet -> na")
    # skip-na mode: the missing volume at t=100 is ignored instead of poisoning 51 bars
    r5 = compute(srows, brows, dict(P252, ta_skip_na=True))
    check(r5["bars"][100]["vol_x"] is None and r5["bars"][101]["vol_x"] == 1.0, "skip-na vol_x")
    check([(e["date"], e["type"]) for e in r5["events"]] == evs, "skip-na events same here")

    # ---------------- T5: year_bars=365 rounding (183 not 182) ----------------
    M = 400
    cdates = [(_dt.date(2023, 1, 1) + _dt.timedelta(days=i)).isoformat() for i in range(M)]
    bc = [100.0 * 1.001 ** k for k in range(M)]
    crows = [{"date": x, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1.0} for x in cdates]
    P365 = dict(P252, year_bars=365, cap_on=False)
    r = compute(crows, [{"date": x, "close": y} for x, y in zip(cdates, bc)], P365)
    lg = (91, 183, 274, 365)
    for t in (364, 365, 399):
        want = None if t < 365 else -wp_closed(bc, t, lg) * 100
        check(close_to(r["bars"][t]["rs_diff"], want), "365 rs t=%d" % t)
    wrong = -wp_closed(bc, 399, (91, 182, 273, 365)) * 100
    check(not close_to(r["bars"][399]["rs_diff"], wrong, 1e-12), "365 lags distinguishable")

    # ---------------- T7: exact-equality boundaries ----------------
    bo = (103.0 / 101.0 - 1) * 100  # breakout_pct exactly equal to the cap -> allowed (<=)
    r = variant((100.0, 104.0, 100.0, 103.0, 2000.0), params={"max_breakout_pct": bo})
    check(r["bars"][-1]["cap_ok"] and r["status"] == "신호 확정 → 다음 시가 진입", "cap boundary <=")
    r = variant((100.0, 104.0, 100.0, 103.0, 1400.0))  # vol_x == 1.4 exactly -> ok (>=)
    check(r["bars"][-1]["vol_x"] == 1.4 and r["bars"][-1]["vol_ok"], "vol boundary >=")
    r = variant((100.0, 101.0, 99.0, 101.0, 2000.0))  # close == pivot -> no breakout (>)
    check(not r["bars"][-1]["breakout"] and r["status"] == "1순위 · 임박 (피벗 1% 이내)", "breakout strict >")
    # close == exit MA exactly (sma5 of 100,100,103,105,102 = 102) -> no exit signal (<)
    rb = mkrows(base + [tail[0], tail[1], (105.0, 106.0, 101.0, 102.0, 1000.0)])
    r = compute(rb, [], P_SMALL)
    check(r["bars"][-1]["exit_ma"] == 102.0 and not r["bars"][-1]["exit_pending"], "exit boundary <")
    # low == stop exactly (100 * 0.9 == 90.0) -> stop (<=), fill at stop
    rb = mkrows(base + [tail[0], (100.0, 101.0, 90.0, 100.5, 1000.0)])
    r = compute(rb, [], P_SMALL)
    check(r["bars"][-1]["entry_price"] is None and r["events"][-1]["type"] == "STOP"
          and r["events"][-1]["price"] == 90.0, "stop boundary <=")

    # ---------------- T6: display-only ----------------
    disp = display_only(rows, P_SMALL)
    check(disp[0]["tr"] == 2.0 and disp[10]["tr"] == 4.0 and disp[9]["contraction"] is None, "display")

    # ---------------- timing on a long series ----------------
    L = 2500
    ldates = weekdays("2016-01-01", L)
    lrows = [{"date": ldates[i], "open": 100 + math.sin(i / 7), "high": 101 + math.sin(i / 7),
              "low": 99 + math.sin(i / 7), "close": 100 + math.sin(i / 5), "volume": 1000.0 + i} for i in range(L)]
    t0 = _time.time()
    compute(lrows, [{"date": x["date"], "close": x["close"]} for x in lrows], P252)
    t_long = _time.time() - t0

    print("SELFTEST PASS: %d checks (300-bar run %.2fs, 2500-bar run %.2fs)" % (_checks[0], t_elapsed, t_long))
