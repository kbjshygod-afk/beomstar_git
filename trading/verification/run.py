#!/usr/bin/env python3
"""Cross-check the primary engine against the Pine reference on every dataset in data/.

  primary   : trading/swing_engine/compare_api.py                            compute(...)
  reference : trading/verification/pine_ref.py                               compute(...)

For every dataset (written by gen.py) both implementations get their own deep copy of the
same inputs.  Every field of every bar, the whole events list and the status string are
diffed:
  * bools / ints / strings / event (date, type) must match exactly;
  * floats must match within 1e-9 relative (or both be None);
  * a boolean flip counts as a numerical TIE (not a mismatch) only when the comparison(s)
    behind it have operands within 1e-9 relative of each other.  Derived booleans
    (tt_count, tt_pass, candidate, full_signal) whose difference is fully explained by
    such tie flips on the same bar are reported as tie-derived.  State-machine fields,
    events and the status are never excused: a divergence there is a real mismatch (it
    is annotated when a tie happened earlier in the same dataset).
Also checks output schema/types, that inputs were not mutated, and reports coverage of
the edge cases the datasets were built to contain (computed from the outputs themselves).

Run:  python gen.py && python run.py        (python run.py --jobs 4 --quiet)
Outputs: out/summary.json, out/mismatches.jsonl (every real mismatch and tie).
"""
from __future__ import annotations

import copy
import difflib
import glob
import json
import math
import multiprocessing as mp
import os
import sys
import time

sys.dont_write_bytecode = True   # never write __pycache__ into the repository

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING = os.path.dirname(HERE)          # trading/
REF_DIR = HERE                            # pine_ref.py lives next to this file
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
REL = 1e-9

FLOATS = ("ma50", "ma150", "ma200", "exit_ma", "hi52", "lo52", "rs_diff", "pivot", "vol_x",
          "entry_price", "stop_price")
PRIM_BOOLS = ("breakout", "vol_ok", "cap_ok", "regime_on")
DERIVED = ("tt_count", "tt_pass", "candidate", "full_signal")
STATE_BOOLS = ("entry_pending", "exit_pending")
BAR_KEYS = set(("date", "tt") + FLOATS + PRIM_BOOLS + DERIVED + STATE_BOOLS)
EVENT_KEYS = {"date", "type", "price", "pnl_pct"}
EVENT_TYPES = {"SIGNAL", "ENTRY", "STOP", "EXIT_SIGNAL", "EXIT_MA"}

_P = _R = None


def _init():
    global _P, _R
    sys.path.insert(0, TRADING)
    sys.path.insert(0, REF_DIR)
    from swing_engine.compare_api import compute as primary   # noqa: E402
    import pine_ref                                            # noqa: E402
    _P, _R = primary, pine_ref.compute


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def rel_close(a, b):
    if a is None or b is None:
        return False
    if a == b:
        return True
    return abs(a - b) <= REL * max(abs(a), abs(b))


def feq(a, b):
    if a is None or b is None:
        return a is None and b is None
    return rel_close(a, b)


def cmp(op, a, b):
    if a is None or b is None:
        return False
    return {">": a > b, ">=": a >= b, "<=": a <= b, "<": a < b}[op]


def mul(a, k):
    return None if a is None else a * k


def fmt(x):
    if isinstance(x, float):
        return repr(x)
    return json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x


def schema_problems(out, n_rows, who):
    probs = []
    if not isinstance(out, dict) or set(out) != {"bars", "events", "status"}:
        return ["%s: top-level keys %r" % (who, sorted(out) if isinstance(out, dict) else type(out))]
    if len(out["bars"]) != n_rows:
        probs.append("%s: %d bars for %d rows" % (who, len(out["bars"]), n_rows))
    for i, b in enumerate(out["bars"]):
        if set(b) != BAR_KEYS:
            probs.append("%s bar %d keys %r" % (who, i, sorted(set(b) ^ BAR_KEYS)))
            break
        bad = [k for k in FLOATS if not (b[k] is None or (type(b[k]) is float and not math.isnan(b[k])))]
        bad += [k for k in PRIM_BOOLS + ("tt_pass", "candidate", "full_signal") + STATE_BOOLS if type(b[k]) is not bool]
        if type(b["tt_count"]) is not int:
            bad.append("tt_count")
        if not (isinstance(b["tt"], list) and len(b["tt"]) == 8 and all(type(x) is bool for x in b["tt"])):
            bad.append("tt")
        if type(b["date"]) is not str:
            bad.append("date")
        if bad:
            probs.append("%s bar %d bad types %r" % (who, i, bad))
            break
    for e in out["events"]:
        if set(e) != EVENT_KEYS or e["type"] not in EVENT_TYPES or type(e["date"]) is not str or \
                not all(e[k] is None or (type(e[k]) is float and not math.isnan(e[k])) for k in ("price", "pnl_pct")):
            probs.append("%s event malformed %r" % (who, e))
            break
    if type(out["status"]) is not str:
        probs.append("%s status type %r" % (who, type(out["status"])))
    return probs


def bench_aligned(bench_rows, sym_dates):
    """Harness-side b_close / b_ma200 / b_ma20 per symbol date (fsum means), for regime ties."""
    bd = [r["date"] for r in bench_rows]
    bc = [r["close"] for r in bench_rows]
    ma = {}
    for L in (200, 20):
        arr = [None] * len(bc)
        for j in range(L - 1, len(bc)):
            arr[j] = math.fsum(bc[j - L + 1:j + 1]) / L
        ma[L] = arr
    out = []
    j = -1
    for d in sym_dates:
        while j + 1 < len(bd) and bd[j + 1] <= d:
            j += 1
        out.append((None, None, None) if j < 0 else (bc[j], ma[200][j], ma[20][j]))
    return out


# ---------------------------------------------------------------------------
# per-dataset comparison
# ---------------------------------------------------------------------------

def compare_dataset(path):
    with open(path) as fh:
        ds = json.load(fh)
    rows, brows, p = ds["symbol_rows"], ds["bench_rows"], ds["params"]
    rows_p, brows_p, p_p = copy.deepcopy(rows), copy.deepcopy(brows), copy.deepcopy(p)
    rows_r, brows_r, p_r = copy.deepcopy(rows), copy.deepcopy(brows), copy.deepcopy(p)
    t0 = time.time()
    P = _P(rows_p, brows_p, p_p)
    t1 = time.time()
    R = _R(rows_r, brows_r, p_r)
    t2 = time.time()
    did = ds["id"]
    res = {"id": did, "preset": ds["preset"], "variant": ds["variant"], "n_rows": len(rows),
           "t_primary": t1 - t0, "t_reference": t2 - t1, "real": [], "ties": [], "tie_derived": [],
           "notes": []}

    def real(date, field, pv, rv, why=""):
        res["real"].append({"dataset": did, "date": date, "field": field, "primary": fmt(pv),
                            "reference": fmt(rv), "why": why})

    # inputs untouched?
    for who, a, b, c in (("primary", rows_p, brows_p, p_p), ("reference", rows_r, brows_r, p_r)):
        if a != rows or b != brows or c != p:
            real(None, "input_mutated", who, "", "implementation mutated its inputs")
    # output must be JSON-clean and schema-correct
    for who, out in (("primary", P), ("reference", R)):
        try:
            json.dumps(out, allow_nan=False)
        except (TypeError, ValueError) as e:
            real(None, "schema", who, str(e)[:120], "output not JSON-serialisable without NaN")
        for pr in schema_problems(out, len(rows), who):
            real(None, "schema", who, pr, "schema")

    PB, RB = P["bars"], R["bars"]
    n = min(len(PB), len(RB))
    res["bars_compared"] = max(len(PB), len(RB))
    if len(PB) != len(RB):
        real(None, "bars_len", len(PB), len(RB))
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    sym_dates = [r["date"] for r in rows]
    bal = bench_aligned(brows, sym_dates)
    k_rise = int(p["ma200_rise_bars"])

    def liq(t):
        if not p["use_value_filter"]:
            return True
        v = vols[t]
        return v is not None and closes[t] * v >= p["min_trading_value"]

    # primitive comparisons behind each boolean: list of (lhs(bars,t), op, rhs(bars,t))
    def g(k):
        return lambda B, t: B[t][k]
    C = lambda B, t: closes[t]
    SUBS = {
        0: [(C, ">", g("ma150")), (C, ">", g("ma200"))],
        1: [(g("ma150"), ">", g("ma200"))],
        2: [(g("ma200"), ">", lambda B, t: B[t - k_rise]["ma200"] if t - k_rise >= 0 else None)],
        3: [(g("ma50"), ">", g("ma150")), (g("ma50"), ">", g("ma200"))],
        4: [(C, ">", g("ma50"))],
        5: [(C, ">=", lambda B, t: mul(B[t]["lo52"], 1.30))],
        6: [(C, ">=", lambda B, t: mul(B[t]["hi52"], 0.75))],
        7: [(g("rs_diff"), ">=", lambda B, t: float(p["rs_min_diff"]))],
        "breakout": [(C, ">", g("pivot"))],
        "vol_ok": [(g("vol_x"), ">=", lambda B, t: float(p["vol_mult"]))],
        "cap_ok": [((lambda B, t: None if B[t]["pivot"] is None else (closes[t] / B[t]["pivot"] - 1) * 100),
                    "<=", lambda B, t: float(p["max_breakout_pct"]))] if p["cap_on"] else [],
    }

    def classify_flip(key, t):
        """True if the flip of primitive `key` on bar t is a numerical tie."""
        if key == "regime_on":
            bc, b200, b20 = bal[t]
            pairs = [] if p["regime_mode"] == "NONE" else [(bc, b200)] + (
                [(bc, b20)] if p["regime_mode"] == "MA200_AND_MA20" else [])
            return any(rel_close(a, b) for a, b in pairs)
        subs = SUBS[key]
        if not subs:
            return False
        differing = []
        for lf, op, rf in subs:
            lp, rp_, lr, rr = lf(PB, t), rf(PB, t), lf(RB, t), rf(RB, t)
            if cmp(op, lp, rp_) != cmp(op, lr, rr):
                differing.append((lp, rp_, lr, rr))
        if not differing:
            return False
        return all(rel_close(lp, rp_) or rel_close(lr, rr) for lp, rp_, lr, rr in differing)

    first_tie_bar = None
    first_state_div = None
    for t in range(n):
        pb, rb = PB[t], RB[t]
        d = rb["date"]
        state_same_before = first_state_div is None
        full_tie = False
        if pb["date"] != rb["date"]:
            real(d, "date", pb["date"], rb["date"])
        for k in FLOATS:
            if not feq(pb[k], rb[k]):
                if k in ("entry_price", "stop_price"):
                    first_state_div = t if first_state_div is None else first_state_div
                real(d, k, pb[k], rb[k])
        flips_ok = True     # every primitive flip on this bar is a tie
        any_flip = False
        for i in range(8):
            if pb["tt"][i] != rb["tt"][i]:
                any_flip = True
                if classify_flip(i, t):
                    res["ties"].append({"dataset": did, "date": d, "field": "tt[%d]" % (i + 1),
                                        "primary": fmt(pb["tt"][i]), "reference": fmt(rb["tt"][i])})
                else:
                    flips_ok = False
                    real(d, "tt[%d]" % (i + 1), pb["tt"][i], rb["tt"][i])
        for k in PRIM_BOOLS:
            if pb[k] != rb[k]:
                any_flip = True
                if classify_flip(k, t):
                    res["ties"].append({"dataset": did, "date": d, "field": k,
                                        "primary": fmt(pb[k]), "reference": fmt(rb[k])})
                else:
                    flips_ok = False
                    real(d, k, pb[k], rb[k])
        if any_flip and flips_ok and first_tie_bar is None:
            first_tie_bar = t
        # derived fields
        der_diff = [k for k in DERIVED if pb[k] != rb[k]]
        if der_diff:
            def recompute(B):
                b = B[t]
                cnt = sum(1 for x in b["tt"] if x)
                tp = (not p["use_tt"]) or cnt == 8
                cand = tp and liq(t)
                full = b["breakout"] and b["vol_ok"] and b["cap_ok"] and cand and b["regime_on"]
                return {"tt_count": cnt, "tt_pass": tp, "candidate": cand, "full_signal": full}
            rp_, rr_ = recompute(PB), recompute(RB)
            for k in der_diff:
                explained = any_flip and flips_ok and pb[k] == rp_[k] and rb[k] == rr_[k]
                if explained:
                    full_tie = full_tie or k == "full_signal"
                    res["tie_derived"].append({"dataset": did, "date": d, "field": k,
                                               "primary": fmt(pb[k]), "reference": fmt(rb[k])})
                else:
                    real(d, k, pb[k], rb[k])
        # state flags: a flip is a tie only on the first divergent bar (identical state
        # before it) when the comparison that set it was a tie
        for k in STATE_BOOLS:
            if pb[k] != rb[k]:
                tie_state = False
                if state_same_before:
                    if k == "exit_pending":      # close < exit_ma while holding
                        tie_state = rel_close(closes[t], pb["exit_ma"]) or rel_close(closes[t], rb["exit_ma"])
                    else:                        # entry_pending = full_signal while flat
                        tie_state = full_tie
                if tie_state:
                    res["ties"].append({"dataset": did, "date": d, "field": k,
                                        "primary": fmt(pb[k]), "reference": fmt(rb[k])})
                    first_tie_bar = t if first_tie_bar is None else first_tie_bar
                else:
                    real(d, k, pb[k], rb[k])
                first_state_div = t if first_state_div is None else first_state_div
    if first_state_div is not None and first_tie_bar is not None and first_tie_bar <= first_state_div:
        res["notes"].append("%s: state diverges at %s (bar %d) after a numerical tie at %s (bar %d)"
                            % (did, PB[first_state_div]["date"], first_state_div, PB[first_tie_bar]["date"], first_tie_bar))

    # events
    PE, RE = P["events"], R["events"]
    res["events_compared"] = max(len(PE), len(RE))
    res["events_p"], res["events_r"] = len(PE), len(RE)
    kp = [(e["date"], e["type"]) for e in PE]
    kr = [(e["date"], e["type"]) for e in RE]
    sm = difflib.SequenceMatcher(a=kp, b=kr, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for a, b in zip(PE[i1:i2], RE[j1:j2]):
                for f in ("price", "pnl_pct"):
                    if not feq(a[f], b[f]):
                        real(b["date"], "event.%s.%s" % (b["type"], f), a[f], b[f])
        else:
            for k in range(max(i2 - i1, j2 - j1)):
                a = PE[i1 + k] if i1 + k < i2 else None
                b = RE[j1 + k] if j1 + k < j2 else None
                date = (b or a)["date"]
                real(date, "event", None if a is None else "%s@%s" % (a["type"], fmt(a["price"])),
                     None if b is None else "%s@%s" % (b["type"], fmt(b["price"])))
    if P["status"] != R["status"]:
        real(sym_dates[-1] if sym_dates else None, "status", P["status"], R["status"])
    # annotate real mismatches that follow a numerical tie in the same dataset (cascades)
    res["real_after_tie"] = 0
    if first_tie_bar is not None:
        tie_date = PB[first_tie_bar]["date"]
        for m in res["real"]:
            if m["date"] is not None and m["date"] >= tie_date and not m["why"]:
                m["why"] = "cascade after numerical tie on %s" % tie_date
                res["real_after_tie"] += 1
    res["status"] = R["status"]

    # coverage (from the reference output; the primary equals it wherever no mismatch was found)
    res["coverage"] = coverage(ds, R, bal)
    res["event_types_r"] = {}
    res["event_types_p"] = {}
    for e in RE:
        res["event_types_r"][e["type"]] = res["event_types_r"].get(e["type"], 0) + 1
    for e in PE:
        res["event_types_p"][e["type"]] = res["event_types_p"].get(e["type"], 0) + 1
    return res


def coverage(ds, OUTR, bal):
    rows, p = ds["symbol_rows"], ds["params"]
    B, E = OUTR["bars"], OUTR["events"]
    n = len(rows)
    s = float(p["stop_pct"])
    cov = {}

    def inc(k, v=1):
        cov[k] = cov.get(k, 0) + v
    by_date = {}
    for e in E:
        by_date.setdefault(e["date"], []).append(e)
    idx = {r["date"]: i for i, r in enumerate(rows)}
    for dte, evs in by_date.items():
        types = [e["type"] for e in evs]
        t = idx[dte]
        o, l = rows[t]["open"], rows[t]["low"]
        for e in evs:
            if e["type"] == "STOP":
                if "ENTRY" in types:
                    inc("stop_on_entry_bar")
                    sp = o * (1 - s / 100)
                else:
                    sp = B[t - 1]["stop_price"]
                    if o < sp and e["price"] == o:
                        inc("stop_gap_down_open_below_stop_fill_at_open")
                if l == sp and e["price"] == sp:
                    inc("stop_low_exactly_equal_stop")
                if "SIGNAL" in types:
                    inc("signal_same_bar_as_stop")
            if e["type"] == "EXIT_MA":
                if t > 0 and B[t - 1]["stop_price"] is not None and o < B[t - 1]["stop_price"]:
                    inc("exit_fill_gap_open_below_stop")
                if "SIGNAL" in types:
                    inc("signal_same_bar_as_exit_fill")
                if t > 0 and any(x["type"] == "EXIT_SIGNAL" for x in by_date.get(rows[t - 1]["date"], [])) \
                        and e["price"] == o:
                    inc("close_below_exit_ma_then_exit_next_open")
    for t in range(n):
        b = B[t]
        c = rows[t]["close"]
        v = rows[t]["volume"]
        pv = b["pivot"]
        others_for_signal = b["cap_ok"] and b["candidate"] and b["regime_on"]
        if pv is not None and c == pv:
            inc("close_exactly_pivot")
            if b["vol_ok"] and others_for_signal:
                inc("close_exactly_pivot_decisive")
        if pv is not None and c == math.nextafter(pv, math.inf):
            inc("close_one_ulp_above_pivot")
        if b["vol_x"] == 1.4:
            inc("vol_x_exactly_1.4")
            if b["full_signal"]:
                inc("vol_x_exactly_1.4_signal")
        if b["vol_x"] is not None and 1.39 < b["vol_x"] < 1.4 and b["breakout"] and others_for_signal:
            inc("vol_x_just_below_1.4_decisive")
        if pv is not None:
            bo = (c / pv - 1) * 100
            if bo == 14.999999999999991:
                inc("breakout_pct_15_minus_1ulp_cap_ok" if b["cap_ok"] else "breakout_pct_15_minus_1ulp_cap_FAIL")
            if bo == 15.000000000000014:
                inc("breakout_pct_15_plus_1ulp_cap_not_ok" if not b["cap_ok"] else "breakout_pct_15_plus_1ulp_cap_ok(capoff)")
            if bo == p["max_breakout_pct"] and p["cap_on"]:
                inc("breakout_pct_exactly_cap_param")
            if bo > 15 and b["full_signal"] and not p["cap_on"]:
                inc("crypto_cap_off_signal_above_15pct")
        if b["lo52"] is not None and c == b["lo52"] * 1.30:
            inc("close_exactly_lo52_x1.30")
        if b["hi52"] is not None and c == b["hi52"] * 0.75:
            inc("close_exactly_hi52_x0.75")
        if v is None:
            inc("nan_volume_bars")
        elif v == 0:
            inc("zero_volume_bars")
            if b["vol_x"] == 0.0:
                inc("zero_volume_vol_x_0")
        if v is not None and b["vol_x"] is None and t > int(p["vol_len"]):
            inc("vol_x_none_despite_volume(window has NaN or avg 0)")
        if b["rs_diff"] == 0.0 and b["tt"][7] and p["rs_min_diff"] == 0.0:
            inc("rs_diff_exactly_0_tt8_true")
        if p["use_value_filter"] and v is not None and c * v == p["min_trading_value"]:
            inc("liquidity_close_x_volume_exactly_min" + ("_candidate" if b["candidate"] else "_tt_fail"))
        bc0, b2000, b200_ = bal[t]
        if bc0 is not None and b2000 is not None and bc0 == b2000:
            inc("bench_close_exactly_ma200" + ("_regime_off" if p["regime_mode"] != "NONE" and not b["regime_on"] else ""))
        if t > 0 and B[t - 1]["entry_price"] is not None and not B[t - 1]["exit_pending"] \
                and b["exit_ma"] is not None and c == b["exit_ma"]:
            inc("close_exactly_exit_ma_while_holding")
        r_ = rows[t]
        if r_["open"] == r_["high"] == r_["low"] == c and v == 0:
            inc("halt_bars_flat_zero_volume")
        if p["regime_mode"] == "MA200_AND_MA20":
            bc, b200, b20 = bal[t]
            if cmp(">", bc, b200) and not cmp(">", bc, b20):
                inc("kospi_ma20_blocks_regime")
        if p["regime_mode"] == "NONE":
            bc, b200, _ = bal[t]
            if not cmp(">", bc, b200) and b["full_signal"]:
                inc("kosdaq_signal_while_bench_below_ma200")
    last = B[-1] if B else None
    if last:
        if last["entry_pending"] and E and E[-1]["type"] == "SIGNAL" and E[-1]["date"] == last["date"]:
            inc("signal_on_last_bar")
        if last["entry_price"] is not None and last["exit_pending"]:
            inc("ends_in_position_exit_pending")
    if n < int(p["year_bars"]):
        inc("short_series_lt_year_bars")
    if int(p["year_bars"]) == 365:
        inc("crypto_365_datasets")
        inc("crypto_365_bars_with_rs", sum(1 for b in B if b["rs_diff"] is not None))
    sd = [r["date"] for r in rows]
    bd = [r["date"] for r in ds["bench_rows"]]
    if not bd:
        inc("bench_empty")
    else:
        sset, bset = set(sd), set(bd)
        if any(d not in bset for d in sd if d >= bd[0]):
            inc("bench_missing_symbol_days")
        if any(d not in sset for d in bd if sd[0] <= d <= sd[-1]):
            inc("bench_extra_days")
        if bd[0] > sd[0]:
            inc("bench_starts_later")
        if bd[-1] < sd[-1]:
            inc("bench_ends_earlier")
        if len(bd) < int(p["year_bars"]) + 1:
            inc("bench_shorter_than_year")
    return cov


# ---------------------------------------------------------------------------

def pick_samples(real, ties, tie_derived, k=25):
    """Up to k representative rows: real mismatches first (spread over fields/datasets)."""
    out = []
    seen = set()
    for pool, tag in ((real, ""), (ties, " (tie)"), (tie_derived, " (tie-derived)")):
        # round-robin over fields for variety
        by_field = {}
        for m in pool:
            by_field.setdefault(m["field"], []).append(m)
        while len(out) < k and any(by_field.values()):
            for f in sorted(by_field):
                if by_field[f] and len(out) < k:
                    m = by_field[f].pop(0)
                    key = (m["dataset"], m["field"])
                    if key in seen and any(by_field.values()):
                        continue
                    seen.add(key)
                    out.append({"dataset": m["dataset"], "date": m["date"] or "",
                                "field": m["field"] + tag, "primary": m["primary"], "reference": m["reference"]})
        if len(out) >= k:
            break
    return out


def main(argv):
    jobs = 4
    quiet = "--quiet" in argv
    for a in argv:
        if a.startswith("--jobs="):
            jobs = int(a.split("=")[1])
    data_dir, out_dir = DATA, OUT
    for a in argv:
        if a.startswith("--data="):
            data_dir = os.path.join(HERE, a.split("=", 1)[1])
        if a.startswith("--out="):
            out_dir = os.path.join(HERE, a.split("=", 1)[1])
    files = sorted(glob.glob(os.path.join(data_dir, "ds_*.json")) + glob.glob(os.path.join(data_dir, "probe_*.json")))
    if not files:
        sys.exit("no datasets in %s; run gen.py first" % data_dir)
    t0 = time.time()
    if jobs > 1:
        with mp.get_context("fork").Pool(jobs, initializer=_init) as pool:
            results = pool.map(compare_dataset, files, chunksize=2)
    else:
        _init()
        results = [compare_dataset(f) for f in files]
    elapsed = time.time() - t0
    real = [m for r in results for m in r["real"]]
    ties = [m for r in results for m in r["ties"]]
    tder = [m for r in results for m in r["tie_derived"]]
    cov, ev_r, ev_p, statuses, presets, variants = {}, {}, {}, {}, {}, {}
    for r in results:
        for k, v in r["coverage"].items():
            cov[k] = cov.get(k, 0) + v
        for k, v in r["event_types_r"].items():
            ev_r[k] = ev_r.get(k, 0) + v
        for k, v in r["event_types_p"].items():
            ev_p[k] = ev_p.get(k, 0) + v
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        presets[r["preset"]] = presets.get(r["preset"], 0) + 1
        variants[r["variant"] or "(preset only)"] = variants.get(r["variant"] or "(preset only)", 0) + 1
    notes = [n for r in results for n in r["notes"]]
    lens = [r["n_rows"] for r in results]
    summary = {
        "datasets": len(results),
        "datasets_by_preset": presets,
        "datasets_by_variant": variants,
        "bars_min_max": [min(lens), max(lens)],
        "bars_compared": sum(r["bars_compared"] for r in results),
        "events_compared": sum(r["events_compared"] for r in results),
        "events_by_type_reference": ev_r,
        "events_by_type_primary": ev_p,
        "real_mismatches": len(real),
        "real_mismatches_following_a_tie_in_same_dataset": sum(r["real_after_tie"] for r in results),
        "ties": len(ties),
        "tie_derived": len(tder),
        "datasets_with_real_mismatch": sorted({m["dataset"] for m in real}),
        "notes": notes,
        "coverage": dict(sorted(cov.items())),
        "status_labels": statuses,
        "seconds": round(elapsed, 1),
        "time_primary_s": round(sum(r["t_primary"] for r in results), 1),
        "time_reference_s": round(sum(r["t_reference"] for r in results), 1),
        "samples": pick_samples(real, ties, tder),
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False, sort_keys=True)
    with open(os.path.join(out_dir, "mismatches.jsonl"), "w") as fh:
        for m in real:
            fh.write(json.dumps({"kind": "real", **m}, ensure_ascii=False) + "\n")
        for m in ties:
            fh.write(json.dumps({"kind": "tie", **m}, ensure_ascii=False) + "\n")
        for m in tder:
            fh.write(json.dumps({"kind": "tie_derived", **m}, ensure_ascii=False) + "\n")
    if quiet:
        s = {k: summary[k] for k in ("datasets", "bars_compared", "events_compared", "real_mismatches", "ties", "tie_derived")}
        print(json.dumps(s))
    else:
        print(json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True))
    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
