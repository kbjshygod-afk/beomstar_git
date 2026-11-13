"""Dashboard data files from the ledger (paper-trading) and backtest (swing-results) branches.

    python tools/dash_data.py --repo .. --out /path/dir
        [--ledger-ref origin/paper-trading] [--results-ref origin/swing-results]

Writes four JSON files of row objects for the dashboard's attached datasets:
  latest.json    one row per market from paper/latest.json (regime, performance, pending signals,
                 audit, cross-checks; nested lists as JSON text)
  equity.json    every market's equity.csv rows with a `market` column
  trades.json    every market's trades.csv rows with a `market` column
  backtest.json  swing-results metrics per market and period (full, last_1y, each year)
Fetch the two branches first (git fetch origin paper-trading swing-results). Read-only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "KOSDAQ_V2", "CRYPTO"]
BACKTEST_MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO"]
EQUITY_NUM = {"cash", "positions_value", "equity", "n_positions", "exposure_pct"}
TRADE_NUM = {"signal_close", "rs_at_signal", "entry_price", "qty", "desired_qty", "stop_price", "entry_cost",
             "cost_basis", "exit_price", "exit_cost", "net_pnl", "pnl_pct", "price_pnl_pct", "bars_held", "days_held"}
METRIC_KEYS = {"return_pct": "return_pct", "cagr_pct": "cagr_pct", "bench_return_pct": "bench_return_pct",
               "bench_cagr_pct": "bench_cagr_pct", "excess_cagr_pp": "excess_cagr_pp", "excess_return_pp": "excess_return_pp",
               "mdd_pct": "max_drawdown_pct", "trades": "trades", "win_rate_pct": "win_rate_pct", "avg_win_pct": "avg_win_pct",
               "avg_loss_pct": "avg_loss_pct", "profit_factor": "profit_factor", "exposure_pct": "exposure_pct",
               "big_win_trade_share_pct": "big_win_trade_share_pct", "big_win_profit_share_pct": "big_win_profit_share_pct"}


def git_show(repo: Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _guard_label(k: dict | None) -> str | None:
    g = (k or {}).get("guard")
    if not g:
        return None
    if g.get("late"):
        return "late"
    if g.get("blocked"):
        return "blocked"
    return "ok" if g.get("enforced", True) else "observe"


def latest_rows(latest: dict) -> list[dict]:
    rows = []
    for market, m in (latest.get("markets") or {}).items():
        r, p, a = m.get("regime") or {}, m.get("performance") or {}, m.get("audit") or {}
        x, k = m.get("xcheck") or None, m.get("xcheck_kis") or None
        ret, bench = p.get("return_pct"), p.get("bench_return_pct")
        rows.append({
            "market": market, "as_of": m.get("as_of"), "start_date": m.get("start_date"), "updated_at": latest.get("updated_at"),
            "regime_on": 1 if r.get("on") is True else 0 if r.get("on") is False else None, "regime_mode": r.get("mode"),
            "benchmark": r.get("benchmark"), "bench_close": r.get("close"), "ma200": r.get("ma200"), "ma20": r.get("ma20"),
            "breadth_pct": r.get("breadth_pct"),
            "equity": p.get("equity"), "return_pct": ret, "bench_return_pct": bench,
            "excess_pp": round(ret - bench, 2) if ret is not None and bench is not None else None,
            "mdd_pct": p.get("mdd_pct"), "closed_trades": p.get("closed_trades"), "win_rate_pct": p.get("win_rate_pct"),
            "avg_win_pct": p.get("avg_win_pct"), "avg_loss_pct": p.get("avg_loss_pct"), "open_positions": p.get("open_positions"),
            "n_entries": len(m.get("entries_next_open") or []), "n_exits": len(m.get("exits_next_open") or []),
            "n_watch": len(m.get("watchlist") or []),
            "entries_json": json.dumps(m.get("entries_next_open") or [], ensure_ascii=False),
            "exits_json": json.dumps(m.get("exits_next_open") or [], ensure_ascii=False),
            "positions_json": json.dumps(m.get("positions") or [], ensure_ascii=False),
            "watchlist_json": json.dumps(m.get("watchlist") or [], ensure_ascii=False),
            "audit_days": a.get("days"), "audit_files": a.get("signal_files"), "audit_late": len(a.get("late") or []),
            "audit_mismatched": ", ".join(a.get("mismatched") or []), "audit_revised": ", ".join(a.get("revised") or []),
            "xcheck_source": (x.get("source") or "KRX Open API") if x else None, "xcheck_status": x.get("status") if x else None,
            "xcheck_checked": x.get("checked") if x else None, "xcheck_bad": len(x.get("mismatched_symbols") or []) if x else None,
            "kis_status": k.get("status") if k else None, "kis_checked": k.get("checked") if k else None,
            "kis_bad": len(k.get("mismatched_symbols") or []) if k else None, "kis_guard": _guard_label(k)})
    return rows


def csv_rows(text: str | None, market: str, numeric: set) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text or "")):
        rec = {"market": market}
        for k, v in row.items():
            if k in numeric:
                rec[k] = float(v) if v not in ("", None) else None
            else:
                rec[k] = None if v == "" else v
        out.append(rec)
    return out


def backtest_rows(market: str, results: dict) -> list[dict]:
    met = (((results.get("modes") or {}).get("percentile") or {}).get("metrics")) or {}
    test = f"{results.get('test_first_date')} ~ {results.get('data_last_date')}"

    def row(period, x):
        r = {"market": market, "period": period, "start": x.get("start"), "end": x.get("end")}
        r.update({k: x.get(src) for k, src in METRIC_KEYS.items()})
        r.update({"generated_at": results.get("generated_at"), "test": test})
        return r

    rows = []
    for period in ("full", "last_1y"):
        if met.get(period):
            rows.append(row(period, met[period]))
    for y, x in (met.get("years") or {}).items():
        rows.append(row(y, x))
    return rows


def build(repo: Path, ledger_ref: str, results_ref: str) -> dict[str, list[dict]]:
    latest = json.loads(git_show(repo, ledger_ref, "paper/latest.json") or "{}")
    eq, tr, bt = [], [], []
    for m in MARKETS:
        eq += csv_rows(git_show(repo, ledger_ref, f"paper/{m}/equity.csv"), m, EQUITY_NUM)
        tr += csv_rows(git_show(repo, ledger_ref, f"paper/{m}/trades.csv"), m, TRADE_NUM)
    for m in BACKTEST_MARKETS:
        raw = git_show(repo, results_ref, f"latest/results/{m}/results.json")
        if raw:
            bt += backtest_rows(m, json.loads(raw))
    return {"latest": latest_rows(latest), "equity": eq, "trades": tr, "backtest": bt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--ledger-ref", default="origin/paper-trading")
    ap.add_argument("--results-ref", default="origin/swing-results")
    ap.add_argument("--out", required=True, help="directory for latest/equity/trades/backtest .json")
    args = ap.parse_args(argv)
    data = build(Path(args.repo), args.ledger_ref, args.results_ref)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in data.items():
        (out / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    print(f"{stamp} " + " ".join(f"{k}={len(v)}" for k, v in data.items()))
    return 0 if data["latest"] else 1


if __name__ == "__main__":
    sys.exit(main())
