"""How much of the difference between two rule presets is path noise?

    python tools/path_noise.py --data DATA_DIR --out OUT_DIR \
        [--market KOSDAQ] [--a KOSDAQ] [--b KOSDAQ_V2] [--reps 40] [--drop-pct 10] [--jobs 4]

The portfolio is cash-limited: when more signals arrive than cash allows, the fills that are taken
decide which later signals can be taken, so one backtest is one path out of many near-identical
ones. Until now that was quoted from experience as "1-2pp of CAGR a year". This tool measures it,
on the point-in-time universe (tools/robustness.py, prepare_pit), with two perturbations that
leave the rules' signals as they are and change only which of them become trades:

  priority  the order in which same-day entry candidates are filled is random instead of by RS
            (it only matters on days when cash runs out)
  drop      each entry signal is skipped with probability --drop-pct (a missed fill, a data gap)

Every repetition uses the same random numbers for preset A and preset B (the frames of a symbol
have the same dates under both presets), so the difference B - A is a paired difference: both
presets meet the same luck. Research tooling only: nothing here touches the ledger or the rules.

Reading rule, fixed on 2026-11-13 before the first run (docs/swing-breadth-threshold-prereg-2026-11.md):

  * "outside the noise"  the 5th percentile of the paired CAGR difference B - A is above 0 in
                         BOTH perturbations, i.e. B beats A in at least 95% of the paired paths.
  * "inside the noise"   anything else.

Only the full-period CAGR difference decides. The same statistics for the profit factor, the
maximum drawdown and the two half-period excess returns are reported for reading, not as a verdict.
The single-preset noise band is the 5th-95th percentile range of its CAGR.

Writes OUT_DIR/path_noise.json (every repetition and the summary) and prints the summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from multiprocessing import get_context
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

MODES = ("priority", "drop")
COLS = ["open", "high", "low", "close", "exit_ma", "full_signal", "rs_key"]   # all simulate() reads
METRICS = ("cagr_pct", "excess_cagr_pp", "profit_factor", "max_drawdown_pct", "h1_excess_pp", "h2_excess_pp")
SEED = 20261113
_W: dict = {}                      # worker state, filled before the pool forks


def _rng(seed: int, rep: int, mode: str, symbol: str) -> np.random.Generator:
    """One generator per (repetition, perturbation, symbol): the same stream for both presets."""
    return np.random.default_rng([seed, rep, MODES.index(mode), zlib.crc32(symbol.encode())])


def perturb(frames: dict, mode: str, rep: int, drop_pct: float = 10.0, seed: int = SEED) -> dict:
    """A copy of the slim frames with one perturbation applied. Signals are never added."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    out = {}
    for s, f in frames.items():
        g = f.copy()
        u = _rng(seed, rep, mode, s).random(len(f))
        if mode == "priority":
            g["rs_key"] = u * 100.0
        else:
            g["full_signal"] = f["full_signal"].to_numpy(bool) & (u >= drop_pct / 100.0)
        out[s] = g
    return out


def dist(values) -> dict:
    x = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if len(x) == 0:
        return {"n": 0}
    return {"n": int(len(x)), "p05": float(np.percentile(x, 5)), "p50": float(np.percentile(x, 50)),
            "p95": float(np.percentile(x, 95)), "min": float(x.min()), "max": float(x.max()),
            "mean": float(x.mean())}


def summarize_runs(rows: list, rule: dict) -> dict:
    """Per perturbation: the distribution of each metric for A, for B and for the paired B - A,
    and how often B was ahead. `rule` holds the unperturbed values {"a": {...}, "b": {...}}."""
    out = {}
    for mode in MODES:
        rs = [r for r in rows if r["mode"] == mode]
        if not rs:
            continue
        m = {}
        for k in METRICS:
            a = [r["a"].get(k) for r in rs]
            b = [r["b"].get(k) for r in rs]
            pairs = [(x, y) for x, y in zip(a, b)
                     if x is not None and y is not None and np.isfinite(x) and np.isfinite(y)]
            d = [y - x for x, y in pairs]
            m[k] = {"a": dist(a), "b": dist(b), "b_minus_a": dist(d),
                    "b_ahead_pct": float(np.mean([v > 0 for v in d]) * 100) if d else None,
                    "rule_a": rule["a"].get(k), "rule_b": rule["b"].get(k)}
        out[mode] = {"reps": len(rs), "metrics": m}
    return out


def verdict(summary: dict) -> dict:
    """The fixed reading rule: B is outside the noise only if the 5th percentile of the paired
    CAGR difference is above 0 in every perturbation that was run (and both were run)."""
    p05 = {mode: summary[mode]["metrics"]["cagr_pct"]["b_minus_a"].get("p05") for mode in MODES if mode in summary}
    complete = len(p05) == len(MODES) and all(v is not None for v in p05.values())
    outside = complete and all(v > 0 for v in p05.values())
    return {"cagr_diff_p05": p05, "complete": complete,
            "verdict": "outside the noise" if outside else ("inside the noise" if complete else "incomplete")}


def _n(v, spec=".2f") -> str:
    """A number for the console table; a missing value prints as n/a instead of raising."""
    return "n/a" if v is None or not np.isfinite(v) else format(v, spec)


def report(summary: dict) -> str:
    """The console table. Any metric may be missing (no losing trade means no profit factor)."""
    lines = []
    for mode, s in summary.items():
        lines.append(f"\n[{mode}] {s['reps']} paired paths")
        for k, m in s["metrics"].items():
            a, b, d = m["a"], m["b"], m["b_minus_a"]
            lines.append(
                f"  {k:18s} A p05/p50/p95 {_n(a.get('p05')):>7} {_n(a.get('p50')):>7} {_n(a.get('p95')):>7} "
                f"(rule {_n(m.get('rule_a'))}) · B {_n(b.get('p05')):>7} {_n(b.get('p50')):>7} {_n(b.get('p95')):>7} "
                f"(rule {_n(m.get('rule_b'))}) · B-A {_n(d.get('p05')):>6} {_n(d.get('p50')):>6} {_n(d.get('p95')):>6} "
                f"· B ahead {_n(m.get('b_ahead_pct'), '.0f')}%")
    return "\n".join(lines)


def metrics_of(summary: dict) -> dict:
    """The numbers compared, from robustness.summarize()."""
    if not summary:
        return {}
    f = summary.get("full") or {}                 # a half is None when the window does not reach it
    return {"cagr_pct": f.get("cagr_pct"), "excess_cagr_pp": f.get("excess_cagr_pp"),
            "profit_factor": f.get("profit_factor"), "max_drawdown_pct": f.get("max_drawdown_pct"),
            "trades": f.get("trades"), "win_rate_pct": f.get("win_rate_pct"),
            "h1_excess_pp": (summary.get("h1") or {}).get("excess_cagr_pp"),
            "h2_excess_pp": (summary.get("h2") or {}).get("excess_cagr_pp")}


def _prepare(data_dir: str, market: str, preset: str):
    import robustness as R
    from swing_engine.indicators import normalize_bars
    from swing_engine.params import resolve
    snap, _, bench = R.load(data_dir, market)
    frames = dict(snap["frames"])
    cfg = R._cfg(resolve(preset))
    dates = normalize_bars(bench, require_ohlc=False).index
    rdates, sets = R.membership_rows(market, Path(data_dir) / R.MEMBERSHIP_FILES[market], sorted(frames))
    member = R.membership_mask(rdates, sets, dates, sorted(frames))
    prep = R.prepare_pit(frames, bench, cfg, member)
    return {s: f[COLS].copy() for s, f in prep.items()}, cfg, bench


def _run_one(frames: dict, cfg, bench, market: str) -> dict:
    import robustness as R
    from swing_engine.portfolio import simulate
    return metrics_of(R.summarize(simulate(frames, cfg), bench, market))


def _job(job):
    mode, rep = job
    w = _W
    out = {"mode": mode, "rep": rep}
    for side in ("a", "b"):
        frames, cfg = w[side]
        out[side] = _run_one(perturb(frames, mode, rep, w["drop_pct"], w["seed"]), cfg, w["bench"], w["market"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="snapshot directory with the membership file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--market", default="KOSDAQ", help="snapshot and membership to load")
    ap.add_argument("--a", default="KOSDAQ", help="baseline preset")
    ap.add_argument("--b", default="KOSDAQ_V2", help="preset compared with the baseline")
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--drop-pct", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)

    fa, cfg_a, bench = _prepare(a.data, a.market, a.a)
    fb, cfg_b, _ = _prepare(a.data, a.market, a.b)
    if set(fa) != set(fb) or any(not fa[s].index.equals(fb[s].index) for s in fa):
        print("the two presets do not share symbols and dates; paired random numbers are impossible", file=sys.stderr)
        return 2
    rule = {"a": _run_one(fa, cfg_a, bench, a.market), "b": _run_one(fb, cfg_b, bench, a.market)}
    print(f"rule {a.a}: {rule['a']}\nrule {a.b}: {rule['b']}", flush=True)

    _W.update(a=(fa, cfg_a), b=(fb, cfg_b), bench=bench, market=a.market, drop_pct=a.drop_pct, seed=a.seed)
    jobs = [(mode, rep) for mode in MODES for rep in range(a.reps)]
    rows = []
    with get_context("fork").Pool(max(1, a.jobs)) as pool:      # fork: the prepared frames are shared
        for r in pool.imap_unordered(_job, jobs):
            rows.append(r)
            print(f"{r['mode']} {r['rep']:02d}: {a.a} {_n(r['a'].get('cagr_pct'))} · {a.b} {_n(r['b'].get('cagr_pct'))}",
                  flush=True)
    rows.sort(key=lambda r: (MODES.index(r["mode"]), r["rep"]))
    summary = summarize_runs(rows, rule)
    v = verdict(summary)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "path_noise.json").write_text(json.dumps(
        {"market": a.market, "a": a.a, "b": a.b, "reps": a.reps, "drop_pct": a.drop_pct, "seed": a.seed,
         "rule": rule, "summary": summary, "verdict": v, "runs": rows}, ensure_ascii=False, indent=1))
    print(report(summary))
    print(f"\nVERDICT: {a.b} vs {a.a}: {v['verdict']} (5th percentile of the paired CAGR difference: {v['cagr_diff_p05']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
