"""Is the breadth-regime filter a plateau or a lucky threshold?

    python tools/breadth_sensitivity.py --data DATA_DIR --out OUT_DIR \
        [--market KOSDAQ] [--thresholds 40 45 50 55]

The 2026-10-02 upgrade study passed "breadth >= 50%" and failed "breadth >= 40%"; on the data with
the delisted members restored (2026-11-13) the order was close to reversed. A filter is worth
trusting only if nearby thresholds give similar results. This runs the current rules plus the
breadth gate (tools/upgrade_study.py: % of the day's index members above their 200-day MA) at each
threshold on the point-in-time universe and checks the plateau criteria below.

Plateau criteria, fixed on 2026-11-13 before thresholds 45 and 55 were ever run
(docs/swing-breadth-threshold-prereg-2026-11.md; 40 and 50 had been seen, which the document says):

  P1  every threshold has a higher CAGR than the baseline (the rules without the gate)
  P2  no threshold has a deeper maximum drawdown than the baseline
  P3  at least all but one threshold have a profit factor >= baseline + 0.10
  P4  every threshold keeps both half-period excess returns >= baseline - 2pp
  P5  the CAGR spread between the best and the worst threshold is <= 3.0pp

All five -> "plateau". The threshold of the paper ledger (50) is not replaced by the best one,
whatever the table shows. Research tooling only: nothing here touches the ledger or the rules.

Writes OUT_DIR/<MARKET>/breadth_sensitivity.json and prints the table.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

PF_GAIN, HALF_SLACK_PP, SPREAD_MAX_PP = 0.10, 2.0, 3.0
EPS = 1e-9                         # the boundaries themselves pass (1.20 + 0.10 is not exactly 1.30 in floats)


def row(summary: dict) -> dict:
    f = summary.get("full") or {}                 # a half (or everything) is missing on a short window
    return {"trades": f.get("trades"), "cagr_pct": f.get("cagr_pct"), "excess_cagr_pp": f.get("excess_cagr_pp"),
            "profit_factor": f.get("profit_factor"), "win_rate_pct": f.get("win_rate_pct"),
            "max_drawdown_pct": f.get("max_drawdown_pct"), "exposure_pct": f.get("exposure_pct"),
            "h1_excess_pp": (summary.get("h1") or {}).get("excess_cagr_pp"),
            "h2_excess_pp": (summary.get("h2") or {}).get("excess_cagr_pp")}


def plateau(base: dict, by_threshold: dict) -> dict:
    """The five fixed checks. `base` and the values of `by_threshold` are row() dicts."""
    rows = list(by_threshold.values())
    if len(rows) < 2:
        return {"plateau": False, "reason": "at least two thresholds are needed"}
    need = ("cagr_pct", "profit_factor", "max_drawdown_pct", "h1_excess_pp", "h2_excess_pp")
    if any(r.get(k) is None or r[k] != r[k] for r in [base, *rows] for k in need):
        return {"plateau": False, "reason": "a metric is missing (too few trades to judge)"}
    cagr = [r["cagr_pct"] for r in rows]
    pf_ok = sum(r["profit_factor"] >= base["profit_factor"] + PF_GAIN - EPS for r in rows)
    checks = {
        "P1_cagr_above_baseline": all(c > base["cagr_pct"] for c in cagr),
        "P2_drawdown_not_deeper": all(r["max_drawdown_pct"] >= base["max_drawdown_pct"] - EPS for r in rows),
        "P3_profit_factor": pf_ok >= len(rows) - 1,
        "P4_both_halves": all(r["h1_excess_pp"] >= base["h1_excess_pp"] - HALF_SLACK_PP - EPS
                              and r["h2_excess_pp"] >= base["h2_excess_pp"] - HALF_SLACK_PP - EPS for r in rows),
        "P5_cagr_spread": max(cagr) - min(cagr) <= SPREAD_MAX_PP + EPS,
    }
    return {"plateau": all(checks.values()), "checks": checks, "cagr_spread_pp": max(cagr) - min(cagr),
            "profit_factor_ok": pf_ok, "thresholds": len(rows)}


def run(data_dir: str, market: str, thresholds: list) -> dict:
    import robustness as R
    import upgrade_study as U
    from swing_engine.indicators import normalize_bars
    from swing_engine.params import COST_PCT, resolve
    from swing_engine.portfolio import simulate
    snap, _, bench = R.load(data_dir, market)
    frames_all = dict(snap["frames"])
    cfg = R._cfg(resolve(market), 70.0, COST_PCT)
    dates = normalize_bars(bench, require_ohlc=False).index
    rdates, sets = R.membership_rows(market, Path(data_dir) / R.MEMBERSHIP_FILES[market], sorted(frames_all))
    member = R.membership_mask(rdates, sets, dates, sorted(frames_all))
    frames = R.prepare_pit(frames_all, bench, cfg, member)
    orig = {s: f["full_signal"].to_numpy().copy() for s, f in frames.items()}
    ctx = {"breadth": U.breadth_pct(frames, member)}
    base = row(R.summarize(simulate(frames, cfg), bench, market))
    out = {}
    for t in thresholds:
        U.apply_gate(frames, orig, lambda f, x, t=t: x["breadth"].reindex(f.index) >= float(t), ctx)
        out[str(t)] = row(R.summarize(simulate(frames, cfg), bench, market))
        r = out[str(t)]
        print(f"{market} breadth >= {t}: cagr {_n(r['cagr_pct'], '.2f')} pf {_n(r['profit_factor'], '.3f')} "
              f"mdd {_n(r['max_drawdown_pct'])} trades {r['trades']}", flush=True)
    return {"market": market, "baseline": base, "thresholds": out, "result": plateau(base, out)}


def _n(v, spec=".1f", unit="") -> str:
    """A number for the table; a missing value (too few trades) prints as n/a instead of raising."""
    return "n/a" if v is None or v != v else format(v, spec) + unit


def table(res: dict) -> str:
    head = ("| 문턱 | 거래 | CAGR | 지수 초과 | PF | 승률 | 최대 낙폭 | 노출 | 전반 초과 | 후반 초과 |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n")
    def line(name, r):
        return (f"| {name} | {_n(r['trades'], ',')} | {_n(r['cagr_pct'], '.1f', '%')} | "
                f"{_n(r['excess_cagr_pp'], '+.1f', '%p')} | {_n(r['profit_factor'], '.2f')} | "
                f"{_n(r['win_rate_pct'], '.1f', '%')} | {_n(r['max_drawdown_pct'], '.1f', '%')} | "
                f"{_n(r['exposure_pct'], '.1f', '%')} | {_n(r['h1_excess_pp'], '+.1f', '%p')} | "
                f"{_n(r['h2_excess_pp'], '+.1f', '%p')} |\n")
    return head + line("기준 (필터 없음)", res["baseline"]) + "".join(
        line(f"폭 ≥ {t}%", r) for t, r in res["thresholds"].items())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--market", default="KOSDAQ")
    ap.add_argument("--thresholds", type=float, nargs="+", default=[40, 45, 50, 55])
    a = ap.parse_args(argv)
    res = run(a.data, a.market, [int(t) if float(t).is_integer() else t for t in a.thresholds])
    out = Path(a.out) / a.market
    out.mkdir(parents=True, exist_ok=True)
    (out / "breadth_sensitivity.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(table(res))
    r = res["result"]
    print(f"plateau: {r['plateau']} · checks {r.get('checks')} · CAGR spread {_n(r.get('cagr_spread_pp'), '.2f')}pp"
          + (f" · {r['reason']}" if r.get("reason") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
