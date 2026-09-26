"""Common comparison interface (COMPARE_API.md).

compute(symbol_rows, bench_rows, params) -> {"bars": [...], "events": [...], "status": str}
NaN is emitted as None. `params` is a fully resolved dict (see params.resolve); no
preset lookup happens here.
"""
from __future__ import annotations

import math

from .indicators import bars_from_rows, compute_indicators
from .state import run_state_machine
from .status import status_from


def _f(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


def analyze_frames(sym, bench, params, tt8_override=None):
    """Indicators + state machine for normalized frames (shared by analyze.py)."""
    ind = compute_indicators(sym, bench, params, tt8_override=tt8_override)
    states, events = run_state_machine(ind, sym, params["stop_pct"])
    if len(sym):
        status = status_from(ind.iloc[-1], states.iloc[-1].to_dict(), params["exit_ma_len"])
    else:
        status = ""
    return ind, states, events, status


def compute(symbol_rows, bench_rows, params) -> dict:
    sym = bars_from_rows(symbol_rows, require_ohlc=True)
    bench = bars_from_rows(bench_rows, require_ohlc=False)
    ind, states, events, status = analyze_frames(sym, bench, params)

    bars = []
    cols = {k: ind[k].to_numpy() for k in (
        "ma50", "ma150", "ma200", "exit_ma", "hi52", "lo52", "rs_diff", "pivot", "vol_x",
        "tt_count", "tt_pass", "breakout", "vol_ok", "cap_ok", "regime_on", "candidate", "full_signal")}
    tts = ind[[f"tt{i}" for i in range(1, 9)]].to_numpy(bool)
    st = {k: states[k].to_numpy() for k in states.columns}
    for i, d in enumerate(sym.index):
        bars.append({
            "date": d.strftime("%Y-%m-%d"),
            "ma50": _f(cols["ma50"][i]), "ma150": _f(cols["ma150"][i]), "ma200": _f(cols["ma200"][i]),
            "exit_ma": _f(cols["exit_ma"][i]),
            "hi52": _f(cols["hi52"][i]), "lo52": _f(cols["lo52"][i]), "rs_diff": _f(cols["rs_diff"][i]),
            "tt": [bool(x) for x in tts[i]], "tt_count": int(cols["tt_count"][i]),
            "tt_pass": bool(cols["tt_pass"][i]),
            "pivot": _f(cols["pivot"][i]), "vol_x": _f(cols["vol_x"][i]),
            "breakout": bool(cols["breakout"][i]), "vol_ok": bool(cols["vol_ok"][i]),
            "cap_ok": bool(cols["cap_ok"][i]), "regime_on": bool(cols["regime_on"][i]),
            "candidate": bool(cols["candidate"][i]), "full_signal": bool(cols["full_signal"][i]),
            "entry_price": _f(st["entry_price"][i]), "stop_price": _f(st["stop_price"][i]),
            "entry_pending": bool(st["entry_pending"][i]), "exit_pending": bool(st["exit_pending"][i]),
        })
    return {"bars": bars, "events": [e.as_dict() for e in events], "status": status}
