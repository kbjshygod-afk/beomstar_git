"""Cross-check statistics of the paper-trading ledger (checklist 1.6 / 5.3): how often, where and
on which field Yahoo disagreed with the second source (KRX, KIS, Tiingo, Coinbase/Kraken).

    python tools/xcheck_stats.py [--repo ..] [--ref origin/paper-trading] [--since 2026-10-01] [--json]

Reads paper/<market>/xcheck/*.json straight from a git ref and prints a Markdown summary per
market and source (records, days ok / mismatch / error, symbols compared, mismatches by
field, index mismatches) and the list of mismatches, so the monthly review (docs/
swing-monthly-review.md) can paste it. Observation only; nothing is changed.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

MARKET_KO = {"SP500": "S&P500", "NDX100": "나스닥100", "KOSPI": "코스피", "KOSDAQ": "코스닥", "KOSDAQ_V2": "코스닥 v2",
             "CRYPTO": "크립토"}


def _git(repo: Path, *args) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def load_records(repo: Path, ref: str) -> list[dict]:
    """Every xcheck record under paper/*/xcheck/ at `ref`, each with its market from the path."""
    listing = _git(repo, "ls-tree", "-r", "--name-only", ref, "paper") or ""
    out = []
    for path in sorted(ln for ln in listing.splitlines() if "/xcheck/" in ln and ln.endswith(".json")):
        raw = _git(repo, "show", f"{ref}:{path}")
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        rec.setdefault("market", path.split("/")[1])
        rec["ledger_market"] = path.split("/")[1]
        rec["path"] = path
        out.append(rec)
    return out


def summarize(records: list[dict], since: str | None = None) -> list[dict]:
    """One row per (ledger market, source), sorted; mismatches are listed per row."""
    groups: dict[tuple, dict] = defaultdict(lambda: {"records": 0, "ok": 0, "mismatch": 0, "error": 0, "not_published": 0,
                                                     "compared": 0, "mismatched_symbols": 0, "by_field": Counter(),
                                                     "index_mismatch": 0, "missing": 0, "guard_blocked": 0, "guard_late": 0,
                                                     "mismatches": []})
    for r in records:
        day = r.get("checked") or r.get("as_of") or ""
        if since and day < since:
            continue
        g = groups[(r["ledger_market"], r.get("source") or "KRX Open API")]
        g["records"] += 1
        g[r.get("status", "error") if r.get("status") in ("ok", "mismatch", "error", "not_published") else "error"] += 1
        s = r.get("symbols") or {}
        g["compared"] += int(s.get("compared") or 0)
        g["missing"] += len(s.get("missing") or [])
        mm = s.get("mismatches") or []
        g["mismatched_symbols"] += len({m["symbol"] for m in mm})
        for m in mm:
            g["by_field"][m["field"]] += 1
            g["mismatches"].append({"date": day, "symbol": m["symbol"], "field": m["field"], "yahoo": m["yahoo"],
                                    "source": m["krx"], "diff_pct": m["diff_pct"]})
        if (r.get("index") or {}).get("match") is False:
            g["index_mismatch"] += 1
        gd = r.get("guard") or {}
        g["guard_blocked"] += int(bool(gd.get("blocked")))
        g["guard_late"] += int(bool(gd.get("late")))
    rows = []
    for (market, source), g in sorted(groups.items()):
        g["by_field"] = dict(sorted(g["by_field"].items()))
        rows.append({"market": market, "source": source, **g})
    return rows


def _fmt(v, crypto=False):
    try:
        return f"{float(v):,.4g}" if crypto else f"{float(v):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def render(rows: list[dict], max_list: int = 40) -> str:
    L = ["| 시장 | 출처 | 기록 | 일치 | 불일치 | 실패 | 미공개 | 비교 종목 | 불일치 종목 | 항목별 | 지수 불일치 | 가드 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        fields = ", ".join(f"{k} {v}" for k, v in r["by_field"].items()) or "-"
        guard = (f"보류 {r['guard_blocked']} · 해제 {r['guard_late']}" if r["guard_blocked"] or r["guard_late"] else "-")
        L.append(f"| {MARKET_KO.get(r['market'], r['market'])} | {r['source']} | {r['records']} | {r['ok']} | {r['mismatch']} | "
                 f"{r['error']} | {r['not_published']} | {r['compared']} | {r['mismatched_symbols']} | {fields} | "
                 f"{r['index_mismatch']} | {guard} |")
    listed = [(r, m) for r in rows for m in r["mismatches"]]
    if listed:
        L += ["", "| 날짜 | 시장 | 출처 | 종목 | 항목 | Yahoo | 출처 값 | 차이 |", "|---|---|---|---|---|---|---|---|"]
        for r, m in listed[:max_list]:
            crypto = r["market"] == "CRYPTO"
            L.append(f"| {m['date']} | {MARKET_KO.get(r['market'], r['market'])} | {r['source']} | {m['symbol']} | {m['field']} | "
                     f"{_fmt(m['yahoo'], crypto)} | {_fmt(m['source'], crypto)} | {m['diff_pct']:+.2f}% |")
        if len(listed) > max_list:
            L.append(f"| … | | | 외 {len(listed) - max_list}건 | | | | |")
    if not rows:
        L.append("| (기록 없음) | | | | | | | | | | | |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--ref", default="origin/paper-trading")
    ap.add_argument("--since", default=None, help="first checked date to include (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = summarize(load_records(Path(a.repo), a.ref), a.since)
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
