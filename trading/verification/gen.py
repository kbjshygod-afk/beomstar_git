#!/usr/bin/env python3
"""Deterministic, seeded synthetic datasets for cross-checking the swing engine
(trading/swing_engine/compare_api.py) against the Pine reference (ref/pine_ref.py).

Writes  <this dir>/data/ds_NNN.json  and  <this dir>/data/manifest.json.
Each dataset file: {"id", "preset", "variant", "params", "symbol_rows", "bench_rows", "meta"}.

* Parameters are resolved here from the SPEC section 2 tables (written from the spec,
  not imported from either implementation).
* Base series: phase-driven price paths (advances, bases with volume dry-up,
  volume-spike breakouts, pullbacks, one-day shocks, declines, rallies), market tick
  rounding, integer volumes for stocks, benchmark on its own calendar.
* Edge cases are injected at chosen bars.  Placement uses a small numpy "oracle"
  written in this file (a third, placement-only reading of SPEC 4-5).  The oracle's
  output is never compared; it only decides where an injection lands and checks
  that the injection had the intended effect (otherwise the bar is restored).
  Every injection modifies only bars >= its target bar, and injections are applied
  in increasing bar order, so earlier injections stay valid.

Run:  python gen.py            (same bytes every run: seeds are fixed)
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import os
import random
import sys

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
MASTER_SEED = 20260925

# ---------------------------------------------------------------------------
# SPEC section 2 (typed in from the spec tables)
# ---------------------------------------------------------------------------
DEFAULTS = dict(pivot_len=20, vol_len=50, vol_mult=1.4, max_breakout_pct=15.0, use_tt=True,
                ma200_rise_bars=22, rs_min_diff=0.0, exit_ma_len=50, use_value_filter=False,
                min_trading_value=3e9)
PRESETS = {
    "SP500": dict(stop_pct=10.0, cap_on=True, year_bars=252, regime_mode="MA200"),
    "NDX100": dict(stop_pct=7.0, cap_on=True, year_bars=252, regime_mode="MA200"),
    "KOSPI": dict(stop_pct=7.0, cap_on=True, year_bars=252, regime_mode="MA200_AND_MA20"),
    "KOSDAQ": dict(stop_pct=10.0, cap_on=True, year_bars=252, regime_mode="NONE"),
    "CRYPTO": dict(stop_pct=10.0, cap_on=False, year_bars=365, regime_mode="MA200"),
}
PRESET_ORDER = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO"]
KEYS = ("stop_pct", "cap_on", "year_bars", "regime_mode", "pivot_len", "vol_len", "vol_mult",
        "max_breakout_pct", "use_tt", "ma200_rise_bars", "rs_min_diff", "exit_ma_len",
        "use_value_filter", "min_trading_value")


def resolve(preset, **over):
    p = dict(DEFAULTS)
    p.update(PRESETS[preset])
    p.update(over)
    return {k: p[k] for k in KEYS}


# ---------------------------------------------------------------------------
# placement oracle (numpy; SPEC 4-5)
# ---------------------------------------------------------------------------

def _roll(x, k, how):
    out = np.full(x.shape[0], np.nan)
    if x.shape[0] >= k:
        w = sliding_window_view(x, k)
        out[k - 1:] = getattr(w, how)(axis=1)
    return out


def _shift(x, k):
    out = np.full(x.shape[0], np.nan)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


def _pr(v):
    return int(math.floor(v + 0.5))


def _wperf(x, n):
    q, h, t3 = _pr(n / 4), _pr(n / 2), _pr(n * 3 / 4)
    return (0.4 * (x / _shift(x, q) - 1) + 0.2 * (x / _shift(x, h) - 1)
            + 0.2 * (x / _shift(x, t3) - 1) + 0.2 * (x / _shift(x, n) - 1))


class Oracle:
    pass


def oracle(D, B, p):
    o = np.asarray(D["open"], float)
    h = np.asarray(D["high"], float)
    l = np.asarray(D["low"], float)
    c = np.asarray(D["close"], float)
    v = np.array([np.nan if x is None else x for x in D["volume"]], float)
    n = len(c)
    yb = p["year_bars"]
    R = Oracle()
    with np.errstate(all="ignore"):
        al = np.full((n, 4), np.nan)
        if B["date"]:
            bc = np.asarray(B["close"], float)
            cols = np.column_stack([bc, _roll(bc, 200, "mean"), _roll(bc, 20, "mean"), _wperf(bc, yb)])
            pos = np.searchsorted(np.array(B["date"]), np.array(D["date"]), side="right") - 1
            ok = pos >= 0
            al[ok] = cols[pos[ok]]
        b_close, b_ma200, b_ma20, b_perf = al.T
        mode = p["regime_mode"]
        if mode == "NONE":
            regime = np.ones(n, bool)
        elif mode == "MA200_AND_MA20":
            regime = (b_close > b_ma200) & (b_close > b_ma20)
        else:
            regime = b_close > b_ma200
        ma50, ma150, ma200 = _roll(c, 50, "mean"), _roll(c, 150, "mean"), _roll(c, 200, "mean")
        exit_ma = _roll(c, p["exit_ma_len"], "mean")
        hi52, lo52 = _roll(c, yb, "max"), _roll(c, yb, "min")
        rs = (_wperf(c, yb) - b_perf) * 100
        tt = [(c > ma150) & (c > ma200), ma150 > ma200, ma200 > _shift(ma200, p["ma200_rise_bars"]),
              (ma50 > ma150) & (ma50 > ma200), c > ma50, c >= lo52 * 1.30, c >= hi52 * 0.75,
              rs >= p["rs_min_diff"]]
        cnt = sum(x.astype(int) for x in tt)
        tt_pass = (cnt == 8) if p["use_tt"] else np.ones(n, bool)
        pivot = _roll(_shift(h, 1), p["pivot_len"], "max")
        vol_avg = _shift(_roll(v, p["vol_len"], "mean"), 1)
        vol_x = np.where(vol_avg > 0, v / vol_avg, np.nan)
        bo = (c / pivot - 1) * 100
        breakout = c > pivot
        vol_ok = vol_x >= p["vol_mult"]
        cap_ok = (bo <= p["max_breakout_pct"]) if p["cap_on"] else np.ones(n, bool)
        liq = (c * v >= p["min_trading_value"]) if p["use_value_filter"] else np.ones(n, bool)
        cand = tt_pass & liq
        full = breakout & vol_ok & cap_ok & cand & regime
    R.__dict__.update(o=o, h=h, l=l, c=c, v=v, n=n, regime=regime, exit_ma=exit_ma, hi52=hi52,
                      lo52=lo52, tt_pass=tt_pass, pivot=pivot, vol_avg=vol_avg, vol_x=vol_x, bo=bo,
                      breakout=breakout, vol_ok=vol_ok, cap_ok=cap_ok, cand=cand, full=full, cnt=cnt)
    # state machine (SPEC 5)
    s = p["stop_pct"]
    enp = exp_ = False
    ep = sp = math.nan
    R.pre_enp = np.zeros(n, bool)
    R.pre_exp = np.zeros(n, bool)
    R.pos_ep = np.full(n, np.nan)     # position subject to step 3 (after steps 1-2)
    R.pos_sp = np.full(n, np.nan)
    R.entry_bar = np.zeros(n, bool)
    R.post_ep = np.full(n, np.nan)
    R.post_sp = np.full(n, np.nan)
    R.post_enp = np.zeros(n, bool)
    R.post_exp = np.zeros(n, bool)
    ev = []
    for t in range(n):
        R.pre_enp[t], R.pre_exp[t] = enp, exp_
        if exp_:
            exp_ = False
            ev.append((t, "EXIT_MA", o[t]))
            ep = sp = math.nan
        if enp:
            enp = False
            ep = float(o[t])
            sp = ep * (1 - s / 100)
            ev.append((t, "ENTRY", ep))
            R.entry_bar[t] = True
        R.pos_ep[t], R.pos_sp[t] = ep, sp
        if not math.isnan(ep):
            if l[t] <= sp:
                ev.append((t, "STOP", min(o[t], sp)))
                ep = sp = math.nan
            elif c[t] < exit_ma[t]:
                exp_ = True
                ev.append((t, "EXIT_SIGNAL", c[t]))
        if math.isnan(ep):
            enp = bool(full[t])
            if enp:
                ev.append((t, "SIGNAL", c[t]))
        R.post_ep[t], R.post_sp[t], R.post_enp[t], R.post_exp[t] = ep, sp, enp, exp_
    R.events = ev
    R.at = {}
    for t, typ, pr in ev:
        R.at.setdefault(t, []).append((typ, pr))
    return R


def has(R, t, typ):
    return any(x[0] == typ for x in R.at.get(t, []))


def price_of(R, t, typ):
    for x in R.at.get(t, []):
        if x[0] == typ:
            return x[1]
    return None


# ---------------------------------------------------------------------------
# calendars
# ---------------------------------------------------------------------------

def stock_master(rng, start, n):
    d = start
    out = []
    while len(out) < n:
        if d.weekday() < 5 and rng.random() > 9 / 261:   # ~9 market holidays a year
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def daily_master(start, n):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def all_days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def drop_random(rng, dates, frac, blocks, keep_first=True):
    """Remove about `frac` of dates at random plus `blocks` contiguous runs of 3-15."""
    n = len(dates)
    kill = [False] * n
    for i in range(n):
        if rng.random() < frac:
            kill[i] = True
    for _ in range(blocks):
        a = rng.randrange(0, max(1, n - 20))
        for i in range(a, min(n, a + rng.randint(3, 15))):
            kill[i] = True
    if keep_first and n:
        kill[0] = False
    return [d for d, k in zip(dates, kill) if not k]


def build_calendars(rng, preset, n, cal):
    """Returns (symbol_dates, bench_dates, note)."""
    crypto = preset == "CRYPTO"
    pre = rng.randint(250, 700)          # benchmark history before the symbol's first bar
    start = dt.date(2008, 1, 1) + dt.timedelta(days=rng.randrange(0, 365 * 8))
    total = pre + n + 200
    master = daily_master(start, total) if crypto else stock_master(rng, start, total)
    sym = master[pre:pre + n]
    bench = master[:pre + n]
    if cal == "same":
        bench = list(sym)
    elif cal == "long_history":
        pass
    elif cal == "bench_later":
        k = rng.choice([1, 2, 5, rng.randint(10, 60), rng.randint(60, 260), rng.randint(260, 420)])
        bench = master[pre + min(k, n - 5):pre + n]
    elif cal == "bench_missing":
        bench = drop_random(rng, master[:pre + n], rng.uniform(0.02, 0.08), rng.randint(1, 3))
    elif cal == "bench_extra":
        # the symbol lacks days the benchmark has (halts / symbol-only holidays)
        pool = master[pre:pre + n + 150]
        sym = drop_random(rng, pool, rng.uniform(0.02, 0.06), rng.randint(1, 3))[:n]
        if len(sym) < n:
            sym = pool[:n]
        bench = master[:master.index(sym[-1]) + 1 + rng.randint(0, 10)]
    elif cal == "bench_7day":
        if crypto:        # crypto symbol on 7 days, benchmark only on weekdays
            bench = [d for d in master[:pre + n] if dt.date.fromisoformat(d).weekday() < 5]
        else:             # stock symbol on weekdays, benchmark trades every calendar day
            bench = all_days_between(master[0], master[pre + n - 1])
    elif cal == "bench_ends_early":
        bench = master[:pre + n - rng.randint(1, 40)]
    elif cal == "bench_mixed":
        k = rng.randint(1, 300)
        base = master[pre + k:pre + n + 10]
        base = drop_random(rng, base, rng.uniform(0.01, 0.05), rng.randint(0, 2))
        extra = [d for d in all_days_between(base[0], base[-1]) if rng.random() < 0.03]
        bench = sorted(set(base) | set(extra))
    elif cal == "bench_short":
        m = rng.randint(30, 250)               # fewer bars than year_bars: b_perf is na
        bench = master[pre + n - m:pre + n]
    elif cal in ("no_bench", "self"):
        bench = [] if cal == "no_bench" else list(sym)
    else:
        raise ValueError(cal)
    sym = sorted(set(sym))[:n]
    bench = sorted(set(bench))
    return sym, bench


# ---------------------------------------------------------------------------
# price paths
# ---------------------------------------------------------------------------

def kr_tick(p):
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return t
    return 1000


def make_rounder(market):
    if market in ("KOSPI", "KOSDAQ"):
        def r(x):
            t = kr_tick(x)
            return float(max(t, round(x / t) * t))
    elif market == "CRYPTO":
        def r(x):
            dec = 2 if x >= 1000 else 4 if x >= 1 else 6
            return float(max(10 ** -dec, round(x, dec)))
    else:
        def r(x):
            dec = 2 if x >= 1 else 4
            return float(max(10 ** -dec, round(x, dec)))
    return r


TRANS = {
    "leader": {
        "start": [("rally", 5), ("advance", 3), ("base", 2)],
        "advance": [("pullback50", 5), ("base", 2), ("shock", 1.5), ("advance", 0.5)],
        "base": [("breakout", 8), ("pullback", 1), ("base", 1)],
        "breakout": [("advance", 6), ("shock", 1.5), ("pullback50", 1.5), ("failed", 1.5)],
        "failed": [("base", 5), ("pullback50", 2)],
        "pullback": [("base", 5), ("rally", 3), ("decline", 0.5)],
        "pullback50": [("base", 7), ("rally", 1), ("decline", 0.3)],
        "shock": [("base", 4), ("rally", 3), ("decline", 0.5)],
        "decline": [("base", 4), ("rally", 5)],
        "rally": [("base", 6), ("advance", 3)],
        "chop": [("base", 5), ("rally", 3)],
    },
    "cyclical": {
        "start": [("rally", 4), ("base", 3), ("decline", 2)],
        "advance": [("base", 4), ("pullback", 2), ("shock", 1), ("decline", 1)],
        "base": [("breakout", 6), ("pullback", 2), ("decline", 1)],
        "breakout": [("advance", 4), ("shock", 1.5), ("pullback", 1), ("pullback50", 1), ("failed", 1.5)],
        "failed": [("base", 3), ("decline", 2)],
        "pullback": [("base", 4), ("rally", 2), ("decline", 2)],
        "pullback50": [("base", 4), ("rally", 2), ("decline", 1)],
        "shock": [("base", 3), ("rally", 2), ("decline", 2)],
        "decline": [("base", 3), ("rally", 4), ("chop", 1)],
        "rally": [("base", 5), ("advance", 2)],
        "chop": [("base", 3), ("rally", 2), ("decline", 1)],
    },
    "choppy": {
        "start": [("chop", 5), ("base", 3)],
        "advance": [("base", 5), ("chop", 3)],
        "base": [("breakout", 5), ("chop", 3), ("pullback", 2)],
        "breakout": [("chop", 3), ("failed", 3), ("advance", 2), ("shock", 1)],
        "failed": [("chop", 3), ("base", 2)],
        "pullback": [("chop", 3), ("rally", 2)],
        "shock": [("chop", 3), ("rally", 2)],
        "decline": [("chop", 3), ("rally", 3)],
        "rally": [("base", 3), ("chop", 2)],
        "chop": [("base", 4), ("chop", 2), ("rally", 2), ("decline", 1)],
    },
    "bear": {
        "start": [("decline", 5), ("chop", 2)],
        "advance": [("base", 3), ("decline", 3)],
        "base": [("breakout", 3), ("decline", 3), ("pullback", 2)],
        "breakout": [("failed", 3), ("advance", 2), ("shock", 1)],
        "failed": [("decline", 3), ("base", 1)],
        "pullback": [("decline", 3), ("base", 2)],
        "shock": [("decline", 2), ("base", 2)],
        "decline": [("base", 3), ("rally", 2), ("decline", 2)],
        "rally": [("base", 3), ("decline", 2)],
        "chop": [("decline", 2), ("base", 2)],
    },
}


def wchoice(rng, items):
    tot = sum(w for _, w in items)
    x = rng.random() * tot
    for it, w in items:
        x -= w
        if x <= 0:
            return it
    return items[-1][0]


def gen_symbol(rng, n, market, style, int_volume):
    rnd = make_rounder(market)
    if market in ("KOSPI", "KOSDAQ"):
        p0 = rng.choice([rng.uniform(1500, 9000), rng.uniform(9000, 80000), rng.uniform(80000, 600000)])
        v0 = rng.uniform(3e4, 3e6)
    elif market == "CRYPTO":
        p0 = rng.choice([rng.uniform(0.02, 0.9), rng.uniform(1, 90), rng.uniform(100, 5000), rng.uniform(5000, 60000)])
        v0 = rng.uniform(1e3, 5e7) / max(1.0, p0 ** 0.5)
    else:
        p0 = rng.choice([rng.uniform(0.5, 9), rng.uniform(10, 150), rng.uniform(150, 900)])
        v0 = rng.uniform(1e5, 3e7)
    sig = rng.uniform(0.010, 0.024) * (1.6 if market == "CRYPTO" else 1.0)
    O, H, L, C, VM = [], [], [], [], []
    prev = p0

    def bar(close, vm, opn=None, wick=None):
        nonlocal prev
        w = sig * 0.45 if wick is None else wick
        if opn is None:
            opn = prev * math.exp(rng.gauss(0, sig * 0.35))
        close = max(close, 1e-6)
        o_, c_ = rnd(opn), rnd(close)
        hi = rnd(max(o_, c_) * (1 + abs(rng.gauss(0, w))))
        lo = rnd(min(o_, c_) * (1 - abs(rng.gauss(0, w))))
        hi = max(hi, o_, c_)
        lo = min(lo, o_, c_)
        O.append(o_); H.append(hi); L.append(lo); C.append(c_); VM.append(vm)
        prev = c_

    phase = wchoice(rng, TRANS[style]["start"])
    while len(C) < n:
        if phase == "advance":
            mu = rng.uniform(0.005, 0.012)
            for _ in range(rng.randint(6, 22)):
                vm = rng.uniform(1.5, 3.0) if rng.random() < 0.25 else rng.uniform(0.9, 1.4)
                bar(prev * math.exp(mu + rng.gauss(0, sig)), vm)
        elif phase == "rally":
            mu = rng.uniform(0.004, 0.010)
            for _ in range(rng.randint(15, 60)):
                vm = rng.uniform(1.5, 3.0) if rng.random() < 0.15 else rng.uniform(0.9, 1.3)
                bar(prev * math.exp(mu + rng.gauss(0, sig)), vm)
        elif phase == "base":
            k = rng.randint(8, 24)
            depth = rng.uniform(0.03, 0.10)
            center = prev
            x = 0.0
            for j in range(k):
                s = sig * (1.0 - 0.65 * j / k)
                x = 0.55 * x + rng.gauss(0, s)
                x = min(max(x, -depth), depth * 0.25)
                bar(center * math.exp(x - depth * 0.15), rng.uniform(0.4, 0.85), wick=s * 0.5)
        elif phase == "breakout":
            look = H[-20:] if H else [prev]
            piv = max(look)
            u = rng.random()
            if u < 0.72:
                b = rng.uniform(0.002, 0.07)
            elif u < 0.80:
                b = rng.uniform(0.07, 0.149)
            else:
                b = rng.uniform(0.151, 0.32)       # chase zone
            vm = rng.uniform(1.5, 4.5) if rng.random() < 0.82 else rng.uniform(0.8, 1.39)
            opn = prev * math.exp(rng.gauss(0.004, sig * 0.4))
            bar(piv * (1 + b), vm, opn=opn)
        elif phase == "failed":
            for _ in range(rng.randint(3, 10)):
                bar(prev * math.exp(rng.uniform(-0.03, -0.004) + rng.gauss(0, sig * 0.5)), rng.uniform(1.0, 1.6))
        elif phase == "pullback":
            mu = rng.uniform(-0.022, -0.006)
            for _ in range(rng.randint(3, 14)):
                bar(prev * math.exp(mu + rng.gauss(0, sig * 0.7)), rng.uniform(1.0, 1.6))
        elif phase == "pullback50":
            # drop until the close is below the running 50-bar mean (forces 50DMA exits)
            mu = rng.uniform(-0.025, -0.008)
            tgt = rng.uniform(0.975, 0.997)
            for _ in range(rng.randint(12, 20)):
                m50 = sum(C[-49:]) / len(C[-49:]) if C else prev
                bar(prev * math.exp(mu + rng.gauss(0, sig * 0.5)), rng.uniform(1.0, 1.6))
                if C[-1] < m50 * tgt:
                    break
        elif phase == "shock":
            r = rng.uniform(-0.18, -0.07)
            opn = prev * (1 + r * rng.uniform(0.0, 1.0))
            bar(prev * (1 + r), rng.uniform(1.8, 3.5), opn=opn)
        elif phase == "decline":
            mu = rng.uniform(-0.007, -0.0015)
            for _ in range(rng.randint(25, 110)):
                bar(prev * math.exp(mu + rng.gauss(0, sig)), rng.uniform(0.8, 1.3))
        elif phase == "chop":
            for _ in range(rng.randint(15, 50)):
                bar(prev * math.exp(rng.gauss(0, sig * 1.3)), rng.uniform(0.7, 1.3))
        phase = wchoice(rng, TRANS[style][phase])
    O, H, L, C, VM = O[:n], H[:n], L[:n], C[:n], VM[:n]
    vols = []
    level = v0
    for i in range(n):
        level *= math.exp(rng.gauss(0, 0.01))
        x = level * VM[i] * math.exp(rng.gauss(0, 0.22))
        if int_volume:
            x = float(max(1, int(round(x))))
            if market in ("SP500", "NDX100") and x > 1e4 and rng.random() < 0.5:
                x = float(max(100, int(round(x / 100)) * 100))
        else:
            x = float(round(x, 3))
        vols.append(x)
    return {"open": O, "high": H, "low": L, "close": C, "volume": vols}


def gen_bench(rng, m, market, flat=False, flat_int=True):
    lvl = rng.uniform(800, 5000)
    flat_at = rng.randrange(0, max(1, m - 260)) if flat and m > 300 else -1
    flat_len = rng.randint(205, 260)
    sig = rng.uniform(0.006, 0.012) * (2.0 if market == "CRYPTO" else 1.0)
    out = []
    bull = rng.random() < 0.85
    left = rng.randint(80, 450)
    mu = rng.uniform(0.0006, 0.0015)
    for _ in range(m):
        if left == 0:
            bull = not bull if rng.random() < 0.8 else bull
            left = rng.randint(120, 600) if bull else rng.randint(20, 110)
            mu = rng.uniform(0.0006, 0.0015) if bull else rng.uniform(-0.0025, -0.0006)
        left -= 1
        if 0 <= flat_at <= len(out) < flat_at + flat_len:
            if len(out) == flat_at and flat_int:
                lvl = float(round(lvl))        # integer level: every mean method is exact
            out.append(lvl)
            continue
        lvl *= math.exp(mu + rng.gauss(0, sig))
        out.append(float(round(lvl, 2)))
    return out


# ---------------------------------------------------------------------------
# injections
# ---------------------------------------------------------------------------

def fix_bar(D, t):
    o, c = D["open"][t], D["close"][t]
    if D["high"][t] < max(o, c):
        D["high"][t] = max(o, c)
    if D["low"][t] > min(o, c):
        D["low"][t] = min(o, c)


def is_int_vol(x):
    return x is not None and float(x).is_integer()


def spike_volume(D, R, t, rng, mult):
    va = R.vol_avg[t]
    x = va * mult
    if D.get("_intvol", True):
        x = float(math.ceil(x))
    return float(x)


def ulp_scan(p, target_fn, want):
    """Search c near p*(1+want/100) (by ulps) for (c/p-1)*100 satisfying target_fn."""
    c0 = p * (1 + want / 100)
    best = None
    for direction in (math.inf, -math.inf):
        c = c0
        for _ in range(400):
            v = (c / p - 1) * 100
            if target_fn(v):
                return c, v
            c = math.nextafter(c, direction)
    return best


def c_for_bo15(p, above):
    """Largest c with (c/p-1)*100 <= 15 (below) or smallest c with it > 15 (above)."""
    c = p * 1.15
    v = (c / p - 1) * 100
    if above:
        while v <= 15.0:
            c = math.nextafter(c, math.inf); v = (c / p - 1) * 100
        while True:
            c2 = math.nextafter(c, -math.inf); v2 = (c2 / p - 1) * 100
            if v2 > 15.0:
                c, v = c2, v2
            else:
                return c, v
    else:
        while v > 15.0:
            c = math.nextafter(c, -math.inf); v = (c / p - 1) * 100
        while True:
            c2 = math.nextafter(c, math.inf); v2 = (c2 / p - 1) * 100
            if v2 <= 15.0:
                c, v = c2, v2
            else:
                return c, v


def fmt_tie_c(p, rng):
    """c with breakout_pct x in (15.5, 35) such that float(abs(x)*10) ends exactly in .5."""
    for _ in range(60):
        tenths = rng.randint(156, 349)
        want = (tenths + 0.5) / 10
        r = ulp_scan(p, lambda v: (abs(v) * 10) % 1 == 0.5, want)
        if r:
            return r
    return None


class Ctx:
    def __init__(self, D, B, p, rng, preset):
        self.D, self.B, self.p, self.rng, self.preset = D, B, p, rng, preset
        self.R = oracle(D, B, p)
        self.log = []

    def attempt(self, name, cands, modify, verify, tries=10):
        cands = list(cands)
        self.rng.shuffle(cands)
        for t in cands[:tries]:
            snap = copy.deepcopy(self.D)
            info = modify(t)
            if info is None:
                self.D.clear(); self.D.update(snap)
                continue
            R2 = oracle(self.D, self.B, self.p)
            if verify(R2, t, info):
                self.R = R2
                self.log.append({"scenario": name, "bar": t, "date": self.D["date"][t], **(info or {})})
                return t
            self.D.clear(); self.D.update(snap)
        self.log.append({"scenario": name, "bar": None, "failed": True})
        return None


def mid_scenarios(ctx):
    D, p, rng = ctx.D, ctx.p, ctx.rng
    s = p["stop_pct"]
    intv = D.get("_intvol", True)

    def in_pos(R, t):
        return not math.isnan(R.pos_ep[t])

    def rng_c(a, b):
        return a + (b - a) * rng.random()

    S = {}

    # --- gap-down open below the stop while holding (not the entry bar)
    def gap_stop(lo, hi):
        R = ctx.R
        cands = [t for t in range(lo, hi) if in_pos(R, t) and not R.entry_bar[t]]

        def mod(t):
            sp = ctx.R.pos_sp[t]
            o = sp * rng_c(0.85, 0.995)
            D["open"][t] = o
            D["low"][t] = o * rng_c(0.96, 1.0)
            D["close"][t] = rng_c(D["low"][t], o * 1.04)
            D["high"][t] = max(o, D["close"][t]) * (1 + rng_c(0, 0.01))
            return {"open": o, "stop": sp}
        return ctx.attempt("gap_stop", cands, mod,
                           lambda R2, t, i: price_of(R2, t, "STOP") == i["open"] and i["open"] < i["stop"])
    S["gap_stop"] = gap_stop

    # --- gap-down open below the stop while an exit is pending (exit fills first)
    def gap_exit(lo, hi):
        R = ctx.R
        cands = [t for t in range(lo, hi) if t > 0 and R.pre_exp[t]]

        def mod(t):
            sp = ctx.R.post_sp[t - 1]
            o = sp * rng_c(0.85, 0.995)
            D["open"][t] = o
            D["low"][t] = o * rng_c(0.96, 1.0)
            D["close"][t] = rng_c(D["low"][t], o * 1.04)
            D["high"][t] = max(o, D["close"][t]) * (1 + rng_c(0, 0.01))
            return {"open": o, "stop": sp}
        return ctx.attempt("gap_exit", cands, mod,
                           lambda R2, t, i: price_of(R2, t, "EXIT_MA") == i["open"] and not has(R2, t, "STOP"))
    S["gap_exit"] = gap_exit

    # --- stop on the entry bar
    def stop_entry_bar(lo, hi):
        R = ctx.R
        cands = [t for t in range(lo, hi) if R.entry_bar[t]]

        def mod(t):
            o = D["open"][t]
            sp = o * (1 - s / 100)
            D["low"][t] = sp * rng_c(0.93, 0.999)
            D["close"][t] = rng_c(D["low"][t], max(o, sp) * 1.02)
            fix_bar(D, t)
            return {"stop": sp}
        return ctx.attempt("stop_entry_bar", cands, mod,
                           lambda R2, t, i: has(R2, t, "ENTRY") and has(R2, t, "STOP"))
    S["stop_entry_bar"] = stop_entry_bar

    # --- low exactly equal to the stop (half on entry bars)
    def low_eq_stop(lo, hi, above=False):
        R = ctx.R
        entry_first = rng.random() < 0.5
        cands = [t for t in range(lo, hi) if in_pos(R, t) and D["open"][t] > R.pos_sp[t]
                 and (R.entry_bar[t] == entry_first or rng.random() < 0.3)]
        name = "low_above_stop" if above else "low_eq_stop"

        def mod(t):
            sp = float(ctx.R.pos_sp[t])
            low = math.nextafter(sp, math.inf) if above else sp
            D["low"][t] = low
            if D["close"][t] < low:
                D["close"][t] = low * rng_c(1.0, 1.03)
            fix_bar(D, t)
            D["low"][t] = low
            return {"stop": sp, "low": low}

        def ver(R2, t, i):
            if above:
                return in_pos(R2, t) and not has(R2, t, "STOP") and R2.l[t] == i["low"]
            return price_of(R2, t, "STOP") == i["stop"] and R2.l[t] == i["stop"]
        return ctx.attempt(name, cands, mod, ver)
    S["low_eq_stop"] = low_eq_stop
    S["low_above_stop"] = lambda lo, hi: low_eq_stop(lo, hi, above=True)

    # --- close clearly below the exit MA, then exit at the next open
    def exit_below_ma(lo, hi):
        R = ctx.R
        L = p["exit_ma_len"]
        cands = [t for t in range(max(lo, L), min(hi, R.n - 1)) if in_pos(R, t) and not R.pre_exp[t]]

        def mod(t):
            m = sum(D["close"][t - L + 1:t]) / (L - 1)
            nc = m * rng_c(0.95, 0.99)
            sp = ctx.R.pos_sp[t]
            low = min(D["open"][t], nc) * rng_c(0.993, 1.0)
            if not low > sp * 1.0005:
                return None
            D["close"][t] = nc
            D["low"][t] = low
            fix_bar(D, t)
            return {"close": nc}
        return ctx.attempt("exit_below_ma", cands, mod,
                           lambda R2, t, i: has(R2, t, "EXIT_SIGNAL") and has(R2, t + 1, "EXIT_MA")
                           and price_of(R2, t + 1, "EXIT_MA") == R2.o[t + 1])
    S["exit_below_ma"] = exit_below_ma

    # --- new signal on the same bar as a stop (entry_only: on the entry bar)
    def signal_on_stop(lo, hi, entry_only=False):
        R = ctx.R
        cands = [t for t in range(lo, hi) if in_pos(R, t) and (R.entry_bar[t] or not entry_only)
                 and R.vol_avg[t] > 0 and R.pivot[t] == R.pivot[t] and R.cand[t] and R.regime[t]]
        name = "signal_on_entry_stop" if entry_only else "signal_on_stop"

        def mod(t):
            sp = ctx.R.pos_sp[t]
            D["low"][t] = min(sp * rng_c(0.95, 0.999), D["open"][t])
            D["close"][t] = float(ctx.R.pivot[t]) * (1 + rng_c(0.003, 0.05))
            D["high"][t] = max(D["open"][t], D["close"][t]) * (1 + rng_c(0, 0.01))
            D["volume"][t] = spike_volume(D, ctx.R, t, rng, rng_c(1.6, 3.5))
            return {}
        return ctx.attempt(name, cands, mod,
                           lambda R2, t, i: has(R2, t, "STOP") and has(R2, t, "SIGNAL")
                           and (has(R2, t, "ENTRY") or not entry_only), tries=14)
    S["signal_on_stop"] = signal_on_stop
    S["signal_on_entry_stop"] = lambda lo, hi: signal_on_stop(lo, hi, entry_only=True)

    # --- new signal on the same bar as an exit fill
    def signal_on_exit(lo, hi):
        R = ctx.R
        cands = [t for t in range(lo, hi) if R.pre_exp[t] and R.vol_avg[t] > 0 and R.pivot[t] == R.pivot[t]]

        def mod(t):
            D["close"][t] = float(ctx.R.pivot[t]) * (1 + rng_c(0.003, 0.05))
            D["high"][t] = max(D["open"][t], D["close"][t]) * (1 + rng_c(0, 0.01))
            D["low"][t] = min(D["low"][t], D["open"][t], D["close"][t])
            D["volume"][t] = spike_volume(D, ctx.R, t, rng, rng_c(1.6, 3.5))
            return {}
        return ctx.attempt("signal_on_exit", cands, mod,
                           lambda R2, t, i: has(R2, t, "EXIT_MA") and has(R2, t, "SIGNAL"), tries=20)
    S["signal_on_exit"] = signal_on_exit

    def signal_bars(lo, hi):
        R = ctx.R
        return [t for t in range(lo, hi) if has(R, t, "SIGNAL")]

    # --- close exactly equal to the pivot on a would-be signal bar
    def close_eq_pivot(lo, hi, ulp_above=False):
        name = "close_above_pivot_ulp" if ulp_above else "close_eq_pivot"

        def mod(t):
            pv = float(ctx.R.pivot[t])
            nc = math.nextafter(pv, math.inf) if ulp_above else pv
            D["close"][t] = nc
            fix_bar(D, t)
            return {"pivot": pv, "close": nc}

        def ver(R2, t, i):
            if ulp_above:
                return has(R2, t, "SIGNAL") and R2.c[t] > R2.pivot[t]
            return (not has(R2, t, "SIGNAL")) and R2.c[t] == R2.pivot[t] and R2.cand[t] and R2.regime[t]
        return ctx.attempt(name, signal_bars(lo, hi), mod, ver)
    S["close_eq_pivot"] = close_eq_pivot
    S["close_above_pivot_ulp"] = lambda lo, hi: close_eq_pivot(lo, hi, ulp_above=True)

    # --- vol_x exactly 1.4 (and one share below)
    def vol_eq(lo, hi, below=False):
        L = p["vol_len"]
        name = "vol_below_1_4" if below else "vol_eq_1_4"
        cands = [t for t in signal_bars(lo, hi)
                 if t > L + 1 and all(is_int_vol(x) for x in D["volume"][t - L:t])]

        def mod(t):
            M = 5 * L
            S_ = sum(D["volume"][t - L:t])
            D["volume"][t - 1] = D["volume"][t - 1] + (M - S_ % M) % M
            S2 = sum(D["volume"][t - L:t])
            assert S2 % M == 0
            v = 7 * S2 / (5 * L)
            D["volume"][t] = float(v - 1) if below else float(v)
            return {"vol_sum": S2}

        def ver(R2, t, i):
            if below:
                return (not has(R2, t, "SIGNAL")) and R2.vol_x[t] < 1.4 and R2.breakout[t]
            return has(R2, t, "SIGNAL") and R2.vol_x[t] == 1.4
        return ctx.attempt(name, cands, mod, ver)
    S["vol_eq_1_4"] = vol_eq
    S["vol_below_1_4"] = lambda lo, hi: vol_eq(lo, hi, below=True)

    # --- breakout_pct at the representable neighbours of 15.0
    def bo15(lo, hi, above=False):
        name = "bo15_above" if above else "bo15_below"

        def mod(t):
            pv = float(ctx.R.pivot[t])
            c, v = c_for_bo15(pv, above)
            D["close"][t] = c
            fix_bar(D, t)
            return {"breakout_pct": v}

        def ver(R2, t, i):
            if above and p["cap_on"]:
                return (not has(R2, t, "SIGNAL")) and not R2.cap_ok[t]
            return has(R2, t, "SIGNAL")
        return ctx.attempt(name, signal_bars(lo, hi), mod, ver)
    S["bo15_below"] = bo15
    S["bo15_above"] = lambda lo, hi: bo15(lo, hi, above=True)

    # --- close exactly lo52*1.30 / hi52*0.75 (float arithmetic)
    def band_eq(lo, hi, which):
        yb = p["year_bars"]
        name = "lo52_eq" if which == "lo" else "hi52_eq"
        C = D["close"]
        scored = []
        for t in range(max(lo, yb), hi):
            win = C[t - yb + 1:t]
            tgt = (min(win) * 1.30) if which == "lo" else (max(win) * 0.75)
            if which == "lo" and not tgt > min(win):
                continue
            if which == "hi" and not tgt < max(win):
                continue
            scored.append((abs(tgt / C[t] - 1), t))
        scored.sort()
        cands = [t for d, t in scored[:12] if d < 0.35]

        def mod(t):
            win = D["close"][t - yb + 1:t]
            ref = min(win) if which == "lo" else max(win)
            tgt = ref * 1.30 if which == "lo" else ref * 0.75
            D["close"][t] = tgt
            fix_bar(D, t)
            return {"ref": ref, "close": tgt}

        def ver(R2, t, i):
            if which == "lo":
                return R2.lo52[t] == i["ref"] and R2.c[t] == R2.lo52[t] * 1.30
            return R2.hi52[t] == i["ref"] and R2.c[t] == R2.hi52[t] * 0.75
        return ctx.attempt(name, cands, mod, ver)
    S["lo52_eq"] = lambda lo, hi: band_eq(lo, hi, "lo")
    S["hi52_eq"] = lambda lo, hi: band_eq(lo, hi, "hi")

    # --- zero / missing volume on a would-be signal bar
    def vol_kill(lo, hi, how):
        name = "zero_vol_breakout" if how == "zero" else "nan_vol_breakout"

        def mod(t):
            D["volume"][t] = 0.0 if how == "zero" else None
            return {}
        return ctx.attempt(name, signal_bars(lo, hi), mod,
                           lambda R2, t, i: not has(R2, t, "SIGNAL") and R2.breakout[t])
    S["zero_vol_breakout"] = lambda lo, hi: vol_kill(lo, hi, "zero")
    S["nan_vol_breakout"] = lambda lo, hi: vol_kill(lo, hi, "nan")
    return S


MID = ["gap_stop", "gap_exit", "stop_entry_bar", "low_eq_stop", "low_above_stop", "exit_below_ma",
       "signal_on_stop", "signal_on_entry_stop", "signal_on_exit", "close_eq_pivot",
       "close_above_pivot_ulp", "vol_eq_1_4", "vol_below_1_4", "bo15_below", "bo15_above",
       "lo52_eq", "hi52_eq", "zero_vol_breakout", "nan_vol_breakout"]
END = ["end_signal_last", "end_exit_pending", "end_in_position", "end_close_eq_pivot", "end_chase",
       "end_chase_fmt_tie", "end_low_vol", "end_regime_off", "end_not_tt", "end_near", "end_none"]


def end_scenario(ctx, name, lo):
    D, p, rng = ctx.D, ctx.p, ctx.rng
    lo = max(lo, 299)
    R = ctx.R
    n = R.n
    if name == "end_none" or lo >= n:
        return None
    if name in ("end_chase", "end_chase_fmt_tie") and not p["cap_on"]:
        name = "end_low_vol"

    def truncate(t):
        for k in ("date", "open", "high", "low", "close", "volume"):
            D[k] = D[k][:t + 1]
        ctx.R = oracle(D, ctx.B, p)
        ctx.log.append({"scenario": name, "bar": t, "date": D["date"][t]})
        return t

    flat_after = lambda R, t: math.isnan(R.post_ep[t]) and not R.post_enp[t]
    rng_list = list(range(lo, n))
    if name == "end_signal_last":
        c = [t for t in rng_list if has(R, t, "SIGNAL")]
        return truncate(c[-1]) if c else None
    if name == "end_exit_pending":
        c = [t for t in rng_list if R.post_exp[t]]
        return truncate(c[-1]) if c else None
    if name == "end_in_position":
        c = [t for t in rng_list if not math.isnan(R.post_ep[t]) and not R.post_exp[t]]
        return truncate(rng.choice(c)) if c else None
    if name == "end_regime_off":
        c = [t for t in rng_list if flat_after(R, t) and R.cand[t] and not R.regime[t]]
        return truncate(rng.choice(c)) if c else None
    if name == "end_not_tt":
        c = [t for t in rng_list if flat_after(R, t) and not R.tt_pass[t]]
        return truncate(rng.choice(c)) if c else None
    if name == "end_near":
        c = [t for t in rng_list if flat_after(R, t) and R.cand[t] and R.regime[t] and not R.breakout[t]]
        return truncate(rng.choice(c)) if c else None
    # modifications on the chosen last bar (flat before and after, candidate + regime on)
    base = [t for t in rng_list if not R.pre_enp[t] and not R.pre_exp[t] and math.isnan(R.pos_ep[t])
            and R.cand[t] and R.regime[t] and R.pivot[t] == R.pivot[t] and R.vol_avg[t] > 0]
    rng.shuffle(base)
    for t in base[:15]:
        snap = copy.deepcopy(D)
        pv = float(R.pivot[t])
        info = {}
        if name == "end_close_eq_pivot":
            D["close"][t] = pv
        elif name == "end_chase":
            if not p["cap_on"]:
                break
            D["close"][t] = pv * (1 + rng.uniform(0.16, 0.35))
            D["volume"][t] = spike_volume(D, R, t, rng, rng.uniform(1.6, 3.0))
        elif name == "end_chase_fmt_tie":
            if not p["cap_on"]:
                break
            r = fmt_tie_c(pv, rng)
            if r is None:
                continue
            D["close"][t] = r[0]
            info["breakout_pct"] = r[1]
            D["volume"][t] = spike_volume(D, R, t, rng, rng.uniform(1.6, 3.0))
        elif name == "end_low_vol":
            D["close"][t] = pv * (1 + rng.uniform(0.002, 0.05))
            v = math.floor(R.vol_avg[t] * rng.uniform(0.3, 1.35))
            D["volume"][t] = float(v)
        fix_bar(D, t)
        R2 = oracle({k: D[k][:t + 1] for k in ("date", "open", "high", "low", "close", "volume")}, ctx.B, p)
        tt = t
        ok = math.isnan(R2.post_ep[tt]) and R2.cand[tt] and R2.regime[tt]
        if name == "end_close_eq_pivot":
            ok = ok and R2.c[tt] == R2.pivot[tt] and not R2.post_enp[tt]
        elif name in ("end_chase", "end_chase_fmt_tie"):
            ok = ok and R2.breakout[tt] and not R2.cap_ok[tt] and not R2.post_enp[tt]
        elif name == "end_low_vol":
            ok = ok and R2.breakout[tt] and not R2.vol_ok[tt] and not R2.post_enp[tt]
        if ok:
            t_ = truncate(t)
            if info:
                ctx.log[-1].update(info)
            return t_
        D.clear(); D.update(snap)
    ctx.log.append({"scenario": name, "bar": None, "failed": True})
    return None


# ---------------------------------------------------------------------------
# volume quirks (applied to the base series before injections)
# ---------------------------------------------------------------------------

def volume_quirks(rng, D, kinds):
    n = len(D["volume"])
    notes = []
    V = D["volume"]
    if "all_nan" in kinds:
        for i in range(n):
            V[i] = None
        return ["all_nan"]
    if "nan_sprinkle" in kinds:
        f = rng.uniform(0.005, 0.04)
        k = 0
        for i in range(n):
            if rng.random() < f:
                V[i] = None; k += 1
        notes.append("nan_sprinkle:%d" % k)
    if "nan_block" in kinds:
        a = rng.randrange(0, n - 70)
        m = rng.randint(3, 60)
        for i in range(a, a + m):
            V[i] = None
        notes.append("nan_block:%d@%d" % (m, a))
    if "zero_sprinkle" in kinds:
        f = rng.uniform(0.005, 0.03)
        k = 0
        for i in range(n):
            if rng.random() < f:
                V[i] = 0.0; k += 1
        notes.append("zero_sprinkle:%d" % k)
    if "zero_block" in kinds:
        a = rng.randrange(0, n - 90)
        m = rng.randint(50, 80)          # >= vol_len zeros -> vol_avg == 0 -> vol_x na
        for i in range(a, a + m):
            V[i] = 0.0
        notes.append("zero_block:%d@%d" % (m, a))
    if "leading_nan" in kinds:
        m = rng.randint(1, 80)
        for i in range(m):
            V[i] = None
        notes.append("leading_nan:%d" % m)
    return notes


# ---------------------------------------------------------------------------
# dataset assembly
# ---------------------------------------------------------------------------

CALS = ["long_history", "same", "bench_later", "bench_missing", "bench_extra", "bench_7day",
        "bench_ends_early", "bench_mixed", "long_history", "bench_missing", "bench_later", "long_history",
        "bench_short", "long_history", "bench_extra", "same", "bench_mixed"]
VARIANTS = [
    ("use_tt_off", dict(use_tt=False)),
    ("value_filter", dict(use_value_filter=True)),       # min_trading_value set from the data
    ("cap_exact", {}),                                    # max_breakout_pct = an achieved value
    ("rs_min_pos", dict(rs_min_diff=5.0)),
    ("rs_min_neg", dict(rs_min_diff=-5.0)),
    ("short_windows", dict(pivot_len=10, vol_len=20, exit_ma_len=20, ma200_rise_bars=5)),
    ("stop_5", dict(stop_pct=5.0)),
    ("stop_8_5", dict(stop_pct=8.5)),
]


def make_dataset(idx, n_base, probe=None):
    seed = MASTER_SEED * 1000 + idx + (10 ** 6 if probe else 0)
    rng = random.Random(seed)
    preset = PRESET_ORDER[idx % 5]
    variant = None
    over = {}
    if probe == "flat_bench":        # presets with a benchmark regime
        preset = ["SP500", "NDX100", "KOSPI", "CRYPTO"][idx % 4]
    elif probe == "halt_nonint":     # presets whose prices are not integers
        preset = ["SP500", "NDX100", "CRYPTO"][idx % 3]
    if probe:
        variant = "probe_" + probe
    elif idx >= n_base:
        variant, over = VARIANTS[(idx - n_base) % len(VARIANTS)]
        over = dict(over)
    crypto = preset == "CRYPTO"
    k5 = idx // 5
    # length
    if crypto and k5 % 4 == 0 and variant is None:
        n = rng.randint(300, 364)                 # shorter than year_bars = 365
    else:
        n = rng.choice([rng.randint(300, 700), rng.randint(700, 1200), rng.randint(1000, 1500), rng.randint(1200, 1500)])
    style = wchoice(rng, [("leader", 7.5), ("cyclical", 1.8), ("choppy", 0.5), ("bear", 0.4)])
    cal = CALS[k5 % len(CALS)]
    if variant is None and k5 == 7:
        cal = "no_bench"
    if variant is None and k5 % 23 == 11:
        cal = "self"                              # benchmark == the symbol itself: rs_diff == 0
    if probe:
        cal = "same" if idx % 2 else "long_history"
    sym_dates, bench_dates = build_calendars(rng, preset, n, cal)
    n = len(sym_dates)
    scen_mid = [MID[(k5 * 7 + j * 3 + idx) % len(MID)] for j in range(rng.randint(4, 8))]
    scen_mid = list(dict.fromkeys(scen_mid))
    end = END[(k5 + idx) % len(END)]
    int_volume = (not crypto) or any(s.startswith("vol_") for s in scen_mid) or rng.random() < 0.3
    sym = gen_symbol(rng, n, preset, style, int_volume)
    if probe == "flat_bench":
        n_ = len(bench_dates)
        bench_close = gen_bench(rng, n_, preset, flat=True, flat_int=False)
    else:
        bench_close = gen_bench(rng, len(bench_dates), preset, flat=(k5 % 9 == 4 and not probe))
    D = {"date": sym_dates, **sym, "_intvol": int_volume}
    B = {"date": bench_dates, "close": bench_close}
    halt = None
    if preset in ("KOSPI", "KOSDAQ") and rng.random() < 0.3 and n > 200:
        # trading halt: flat integer price, zero volume (KRX ticks are integers -> exact means)
        a = rng.randrange(260, n - 60) if n > 420 else rng.randrange(60, n - 60)
        m = rng.randint(20, 80)
        px = D["close"][a - 1]
        for i in range(a, min(n, a + m)):
            D["open"][i] = D["high"][i] = D["low"][i] = D["close"][i] = px
            D["volume"][i] = 0.0
        halt = "halt:%d@%d" % (m, a)
    if cal == "self":
        B["close"] = list(D["close"])
    if probe == "halt_nonint":
        # non-integer flat price held for >= exit_ma_len bars while in a position
        R0 = oracle(D, B, resolve(preset))
        ents = [t for t, typ, _ in R0.events if typ == "ENTRY" and t + 90 < n
                and not any(math.isnan(R0.post_ep[k]) for k in range(t, t + 4))]
        if ents:
            a = ents[rng.randrange(len(ents))] + 3
            m = rng.randint(55, 85)
            px = D["close"][a - 1]
            for i in range(a, min(n, a + m)):
                D["open"][i] = D["high"][i] = D["low"][i] = D["close"][i] = px
                D["volume"][i] = 0.0
            halt = "halt_nonint:%d@%d px=%r" % (m, a, px)
    # volume quirks
    quirks = []
    r = rng.random()
    if variant is None and k5 == 3:
        quirks = ["all_nan"]
    else:
        if r < 0.30: quirks.append("nan_sprinkle")
        if rng.random() < 0.15: quirks.append("nan_block")
        if rng.random() < 0.20: quirks.append("zero_sprinkle")
        if rng.random() < 0.12: quirks.append("zero_block")
        if rng.random() < 0.08: quirks.append("leading_nan")
    qnotes = volume_quirks(rng, D, quirks) + ([halt] if halt else [])
    p = resolve(preset, **over)
    if variant == "value_filter":
        p0 = dict(p, use_value_filter=False)
        R0 = oracle(D, B, p0)
        sigs = [t for t, typ, _ in R0.events if typ == "SIGNAL" and D["volume"][t]]
        if sigs:     # threshold == close*volume of one signal bar (>= boundary)
            t = sigs[len(sigs) // 2]
            p["min_trading_value"] = D["close"][t] * D["volume"][t]
        else:
            cv = sorted(c * v for c, v in zip(D["close"], D["volume"]) if v is not None)
            p["min_trading_value"] = float(f"{(cv[len(cv) // 2] if cv else 1.0):.3g}")
    ctx = Ctx(D, B, p, rng, preset)
    if variant == "cap_exact":
        sigs = [t for t, typ, _ in ctx.R.events if typ == "SIGNAL"]
        if sigs:
            t = sigs[len(sigs) // 2]
            x = float(ctx.R.bo[t])
            p["max_breakout_pct"] = x                  # breakout_pct == cap exactly on bar t
            ctx.p = p
            ctx.R = oracle(D, B, p)
            ctx.log.append({"scenario": "cap_exact", "bar": t, "date": D["date"][t], "cap": x})
    # mid-series injections: one segment per scenario, in increasing bar order
    S = mid_scenarios(ctx)
    if probe:
        scen_mid, end = [], "end_none"
    start = p["year_bars"] if p["use_tt"] else max(p["vol_len"], p["pivot_len"]) + 2
    stop_at = len(D["close"]) - 3
    if scen_mid and stop_at - start > 20 * len(scen_mid):
        seg = (stop_at - start) // len(scen_mid)
        last = start
        for j, name in enumerate(scen_mid):
            lo, hi = max(last + 3, start + j * seg), start + (j + 1) * seg
            t = S[name](lo, hi)
            if t is not None:
                last = t
    last_bar = max([e["bar"] for e in ctx.log if e.get("bar") is not None] + [0])
    end_scenario(ctx, end, last_bar + 2)
    D.pop("_intvol", None)
    if cal == "self":
        B = {"date": list(D["date"]), "close": list(D["close"])}
    rows = []
    for i in range(len(D["date"])):
        v = D["volume"][i]
        rows.append({"date": D["date"][i], "open": float(D["open"][i]), "high": float(D["high"][i]),
                     "low": float(D["low"][i]), "close": float(D["close"][i]),
                     "volume": None if v is None else float(v)})
    brows = [{"date": d, "close": float(c)} for d, c in zip(B["date"], B["close"])]
    R = ctx.R
    ev_counts = {}
    for _, typ, _ in R.events:
        ev_counts[typ] = ev_counts.get(typ, 0) + 1
    meta = {"seed": seed, "style": style, "calendar": cal, "volume_quirks": qnotes,
            "int_volume": int_volume, "scenarios": ctx.log, "oracle_events": ev_counts,
            "overrides": over}
    return {"id": ("probe_%03d" if probe else "ds_%03d") % idx, "preset": preset, "variant": variant, "params": p,
            "symbol_rows": rows, "bench_rows": brows, "meta": meta}


def main(argv):
    n_base = 500
    n_var = 40
    probe = "--probe" in argv
    for a in argv:
        if a.startswith("--n-base="):
            n_base = int(a.split("=")[1])
        if a.startswith("--n-var="):
            n_var = int(a.split("=")[1])
    out = os.path.join(HERE, "data_probe") if probe else OUT
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if (f.startswith("ds_") or f.startswith("probe_")) and f.endswith(".json"):
            os.remove(os.path.join(out, f))
    manifest = []
    tot = {}
    scen_ok, scen_fail = {}, {}
    jobs = [(i, "flat_bench") for i in range(20)] + [(20 + i, "halt_nonint") for i in range(20)] if probe \
        else [(i, None) for i in range(n_base + n_var)]
    for idx, pr in jobs:
        ds = make_dataset(idx, n_base, probe=pr)
        blob = json.dumps(ds, sort_keys=True, separators=(",", ":"), allow_nan=False)
        path = os.path.join(out, ds["id"] + ".json")
        with open(path, "w") as fh:
            fh.write(blob)
        manifest.append({"id": ds["id"], "preset": ds["preset"], "variant": ds["variant"],
                         "bars": len(ds["symbol_rows"]), "bench_bars": len(ds["bench_rows"]),
                         "sha256": hashlib.sha256(blob.encode()).hexdigest()})
        for k, v in ds["meta"]["oracle_events"].items():
            tot[k] = tot.get(k, 0) + v
        for e in ds["meta"]["scenarios"]:
            d = scen_fail if e.get("failed") else scen_ok
            d[e["scenario"]] = d.get(e["scenario"], 0) + 1
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    h = hashlib.sha256("".join(m["sha256"] for m in manifest).encode()).hexdigest()
    print("datasets:", len(manifest), " bars:", sum(m["bars"] for m in manifest), " manifest hash:", h[:16])
    print("oracle events:", tot)
    print("injections ok:", dict(sorted(scen_ok.items())))
    print("injections failed:", dict(sorted(scen_fail.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
