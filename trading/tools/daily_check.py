"""Daily status summary of the paper-trading ledger (docs/swing-improvement-policy.md, 점검 주기).

    python tools/daily_check.py [--repo ..] [--ref origin/paper-trading] [--json]

Reads the ledger straight from a git ref (no checkout needed) and prints, per market: the
last signal date, the entries and exits for the next open, open positions, positions whose
quotes stopped (stale), the regime (and breadth for BREADTH50), audit flags, trades closed
in the last few days and the equity return. The fields are the ones the engine writes
(`paper/latest.json`, `paper/<market>/audit.json`, `trades.csv`, `equity.csv`); a field it
cannot find is reported as missing instead of being read as empty, so a renamed key shows up
as a problem rather than as "0 signals" (2026-10-16 check read the wrong keys).
Judgment criteria A-C (tools/paper_verdict.py) are checked too: a failure not in KNOWN_CRITERIA
is a PROBLEM and the exit code is 1.
"""
import argparse
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_verdict as V  # noqa: E402
from trade_analysis import Source  # noqa: E402

AUDIT_FLAGS = ("late", "uncommitted", "mismatched", "revised", "revised_after_open", "missing_days")
# Judgment-criteria failures already reported to the owner. Listed here they print as "known";
# anything else that fails A, B or C is a PROBLEM (exit 1), so a new violation is never read past
# as an ordinary audit flag again (2026-11-05: the KOSDAQ 11-04 late commit was).
KNOWN_CRITERIA = {
    ("KOSDAQ", "늦은 커밋 2026-11-04"): "11-06 보고, 해석 결정 대기",
    ("KOSDAQ_V2", "늦은 커밋 2026-11-04"): "11-06 보고, 해석 결정 대기",
    ("CRYPTO", "B"): "11-06 보고: Yahoo에 없는 5종목, 다음 기간 유니버스 재구성",
}
MARKET_REQUIRED = ("as_of", "regime", "entries_next_open", "exits_next_open", "positions",
                   "stale_positions")


def _show(repo: Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def market_summary(market: str, latest: dict | None, audit: dict | None,
                   trades_csv: str | None, equity_csv: str | None, recent_days: int = 3) -> dict:
    s: dict = {"market": market, "problems": []}
    if latest is None:
        s["problems"].append("paper/latest.json has no entry for this market")
        return s
    missing = [k for k in MARKET_REQUIRED if k not in latest]
    if missing:
        s["problems"].append(f"latest.json missing keys: {', '.join(missing)}")
    s["as_of"] = latest.get("as_of")
    reg = latest.get("regime") or {}
    s["regime_on"] = reg.get("on")
    s["regime_mode"] = reg.get("mode")
    s["breadth_pct"] = reg.get("breadth_pct")
    s["entries"] = [e["symbol"] for e in latest.get("entries_next_open") or []]
    s["exits"] = [e["symbol"] if isinstance(e, dict) else e for e in latest.get("exits_next_open") or []]
    s["positions"] = [p["symbol"] for p in latest.get("positions") or []]
    s["stale"] = [st.get("symbol", st) if isinstance(st, dict) else st
                  for st in latest.get("stale_positions") or []]
    s["xcheck"] = latest.get("xcheck")                  # Yahoo vs KRX / Coinbase-Kraken (when configured)
    s["xcheck_kis"] = latest.get("xcheck_kis")          # Yahoo vs KIS, the signal day itself
    if audit is None:
        s["problems"].append("audit.json not found")
        s["audit"] = {}
    else:
        s["audit"] = {k: audit[k] for k in AUDIT_FLAGS if audit.get(k)}
    s["closed_recent"] = []
    if trades_csv:
        rows = [r for r in csv.DictReader(io.StringIO(trades_csv)) if r.get("exit_date")]
        dates = sorted({r["exit_date"] for r in rows})[-recent_days:]
        s["closed_recent"] = [{"symbol": r["symbol"], "exit_date": r["exit_date"],
                               "type": r["exit_type"], "pnl_pct": round(float(r["pnl_pct"]), 2)}
                              for r in rows if r["exit_date"] in dates]
        s["closed_total"] = len(rows)
        s["wins"] = sum(float(r["net_pnl"]) > 0 for r in rows)
    if equity_csv:
        eq = list(csv.DictReader(io.StringIO(equity_csv)))
        if eq:
            s["return_pct"] = round((float(eq[-1]["equity"]) / float(eq[0]["equity"]) - 1) * 100, 2)
    return s


def criteria(market: str, audit: dict | None, trades_csv: str | None, coverages: list[dict]) -> dict:
    """Judgment criteria A, B, C (paper_verdict) split into known and new failures."""
    if audit is None or market not in V.STOP_PCT:
        return {"new": [], "known": []}
    trades = list(csv.DictReader(io.StringIO(trades_csv or "")))
    a, b, c = V.check_a(audit, market), V.check_b(audit, coverages), V.check_c(trades, market)
    new, known = [], []
    for item in a["issues"] + c["issues"]:
        (known if (market, item) in KNOWN_CRITERIA else new).append(item)
    for item in b["issues"]:
        (known if (market, "B") in KNOWN_CRITERIA else new).append(item)
    return {"new": new, "known": known}


def collect(repo: Path, ref: str) -> list[dict]:
    raw = _show(repo, ref, "paper/latest.json")
    if raw is None:
        raise SystemExit(f"{ref}:paper/latest.json not found")
    markets = json.loads(raw).get("markets", {})
    src = Source(repo, ref)
    out = []
    for m in markets:
        aud = _show(repo, ref, f"paper/{m}/audit.json")
        audit = json.loads(aud) if aud else None
        trades = _show(repo, ref, f"paper/{m}/trades.csv")
        s = market_summary(m, markets[m], audit, trades, _show(repo, ref, f"paper/{m}/equity.csv"))
        cr = criteria(m, audit, trades, V.coverages(src, m))
        s["criteria_known"] = cr["known"]
        s["problems"] += [f"판정 기준 위반(새로 발생): {x}" for x in cr["new"]]
        out.append(s)
    return out


def _names(xs: list) -> str:
    return f"{len(xs)}" + (f" ({', '.join(xs)})" if xs else "")


def render(summaries: list[dict]) -> str:
    lines = []
    for s in summaries:
        if "as_of" not in s:
            lines.append(f"{s['market']}: PROBLEM {'; '.join(s['problems'])}")
            continue
        reg = "ON" if s["regime_on"] else "OFF"
        if s.get("breadth_pct") is not None:
            reg += f" breadth {s['breadth_pct']}%"
        lines.append(f"{s['market']} as_of {s['as_of']} · regime {reg} · return {s.get('return_pct')}%"
                     f" · closed {s.get('closed_total', 0)} (wins {s.get('wins', 0)})")
        lines.append(f"  entries next open: {_names(s['entries'])}")
        lines.append(f"  exits next open:   {_names(s['exits'])}")
        lines.append(f"  positions:         {_names(s['positions'])}")
        if s["stale"]:
            lines.append(f"  STALE quotes:      {', '.join(map(str, s['stale']))}")
        if s["audit"]:
            lines.append(f"  audit flags:       {s['audit']}")
        for x in (s.get("xcheck"), s.get("xcheck_kis")):
            if not x:
                continue
            lines.append(f"  cross-check {str(x.get('source') or 'KRX')[:7]:7s} {x['status']} ({x.get('checked') or '-'})"
                         + (f" mismatched {x['mismatched_symbols']}" if x.get("mismatched_symbols") else "")
                         + (f" index_match={x['index_match']}" if x.get("index_match") is not None else "")
                         + (f" error={x['error']}" if x.get("error") else "")
                         + (f" guard={'late' if x['guard'].get('late') else 'blocked' if x['guard'].get('blocked') else 'ok' if x['guard'].get('enforced', True) else 'observe'}"
                            f" ({x['guard'].get('close_mismatched')}/{x['guard'].get('compared')} close)" if x.get("guard") else ""))
        for t in s["closed_recent"]:
            lines.append(f"  closed {t['exit_date']} {t['symbol']} {t['type']} {t['pnl_pct']:+.2f}%")
        if s.get("criteria_known"):
            lines.append(f"  criteria (known):  {'; '.join(s['criteria_known'])}")
        for p in s["problems"]:
            lines.append(f"  PROBLEM: {p}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--ref", default="origin/paper-trading")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    summaries = collect(Path(a.repo), a.ref)
    print(json.dumps(summaries, ensure_ascii=False, indent=1) if a.json else render(summaries))
    return 1 if any(s["problems"] for s in summaries) else 0


if __name__ == "__main__":
    sys.exit(main())
