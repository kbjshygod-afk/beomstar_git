"""Paper-trading verdict per market against the fixed criteria A-D (docs/paper-trading-plan.md).

    python tools/paper_verdict.py --repo .. --out reports/paper_verdict
        [--ledger-ref origin/paper-trading] [--results-ref origin/swing-results] [--markets ...]
    python tools/paper_verdict.py --ledger-dir PAPER_DIR --results-dir RESULTS_DIR ...   (tests)

A  integrity  every signal file committed before the next open (audit `late`, `uncommitted`);
              recomputed vs committed mismatches other than the explained days (plan, 10-22 decision)
B  operation  missing days <= 2; symbols without data <= 5% on every signal file
C  rules      exits only by stop or the 50-day line (no target sells); no loss beyond the stop
              except gaps (filled at an open below the stop)
D  health     60-day return and max drawdown not below the fixed warning lines; average loss
              within the backtest average loss +-3pp
Verdict wording follows the plan: A/B/C pass and no D warning -> small live start possible;
A or C fail -> fix and restart a new period; D warning -> owner reviews (rules or regime).
Before 60 trading days the result is an interim reading.

The regime section puts today's index distance from its 200-day line next to the backtest
trades taken in the same band (swing-results signals.csv), to separate rules from regime.
Reference only: nothing here changes the ledger, a rule or a parameter.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trade_analysis import MARKET_KO, Source  # noqa: E402

MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "KOSDAQ_V2", "CRYPTO"]
PERIOD_DAYS = 60
# Fixed warning lines (plan "기준값", backtest of 2026-09-25): 60-day return p5, 60-day max DD p5,
# backtest average loss. KOSDAQ_V2 is judged by the same lines as KOSDAQ (plan, v2 section).
LINES = {
    "SP500": (-10.9, -16.8, -6.5),
    "NDX100": (-10.9, -20.1, -6.0),
    "KOSPI": (-9.4, -18.1, -6.5),
    "KOSDAQ": (-12.1, -21.6, -8.9),
    "KOSDAQ_V2": (-12.1, -21.6, -8.9),
    "CRYPTO": (-5.5, -14.8, -9.5),
}
AVG_LOSS_BAND = 3.0
STOP_PCT = {"SP500": 10.0, "NDX100": 7.0, "KOSPI": 7.0, "KOSDAQ": 10.0, "KOSDAQ_V2": 10.0, "CRYPTO": 10.0}
ALLOWED_EXITS = {"STOP", "EXIT_MA"}
# Days whose recomputed/committed difference is explained by a provider's later revision
# (plan, A item, owner decision 2026-10-22).
EXPLAINED_MISMATCH = {"KOSDAQ": {"2026-10-06"}, "KOSDAQ_V2": {"2026-10-06"}}
MAX_MISSING_DAYS = 2
MAX_FAIL_SHARE = 0.05
REGIME_BANDS = [(-999, -15, "< -15%"), (-15, -5, "-15 ~ -5%"), (-5, 0, "-5 ~ 0%"), (0, 5, "0 ~ 5%"), (5, 999, "> 5%")]


def _rows(text: str | None) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text or "")))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def check_a(audit: dict, market: str) -> dict:
    late = list(audit.get("late") or [])
    unc = list(audit.get("uncommitted") or [])
    explained = EXPLAINED_MISMATCH.get(market, set())
    mism = [d for d in audit.get("mismatched") or [] if d not in explained]
    issues = [f"늦은 커밋 {d}" for d in late] + [f"미커밋 {d}" for d in unc] + [f"설명 안 된 불일치 {d}" for d in mism]
    return {"pass": not issues, "issues": issues, "explained": sorted(set(audit.get("mismatched") or []) & explained)}


def check_b(audit: dict, coverages: list[dict]) -> dict:
    missing = list(audit.get("missing_days") or [])
    worst = 0.0
    for c in coverages:
        req = c.get("requested") or 0
        if req:
            worst = max(worst, len(c.get("failed") or []) / req)
    issues = []
    if len(missing) > MAX_MISSING_DAYS:
        issues.append(f"누락일 {len(missing)}일 > {MAX_MISSING_DAYS}")
    if worst > MAX_FAIL_SHARE:
        issues.append(f"데이터 실패 최대 {worst:.1%} > {MAX_FAIL_SHARE:.0%}")
    return {"pass": not issues, "issues": issues, "missing_days": missing, "worst_fail_share": round(worst, 4)}


def check_c(trades: list[dict], market: str) -> dict:
    stop = STOP_PCT[market]
    issues, gaps = [], []
    for t in trades:
        et = t.get("exit_type")
        if et and et not in ALLOWED_EXITS:
            issues.append(f"{t['symbol']} 청산 유형 {et}")
        pp, ep, sp = _f(t.get("price_pnl_pct")), _f(t.get("exit_price")), _f(t.get("stop_price"))
        if pp is not None and pp < -stop - 0.05:
            if ep is not None and sp is not None and ep < sp - 1e-9:
                gaps.append(f"{t['symbol']} {pp:+.1f}% (시가 갭, 허용)")
            else:
                issues.append(f"{t['symbol']} 손절폭 초과 {pp:+.1f}%")
    return {"pass": not issues, "issues": issues, "gaps": gaps}


def equity_stats(equity: list[dict]) -> dict:
    e = np.array([_f(r.get("equity")) for r in equity if _f(r.get("equity")) is not None], float)
    if len(e) < 2:
        return {"days": len(e), "return_pct": None, "mdd_pct": None}
    peak = np.maximum.accumulate(e)
    return {"days": len(e), "return_pct": round((e[-1] / e[0] - 1) * 100, 2), "mdd_pct": round(((e / peak) - 1).min() * 100, 2)}


def check_d(stats: dict, trades: list[dict], market: str) -> dict:
    ret_l, mdd_l, base_loss = LINES[market]
    losses = [v for v in (_f(t.get("pnl_pct")) for t in trades if t.get("exit_date")) if v is not None and v <= 0]
    avg_loss = round(float(np.mean(losses)), 2) if losses else None
    warns = []
    if stats["return_pct"] is not None and stats["return_pct"] < ret_l:
        warns.append(f"수익률 {stats['return_pct']:+.1f}% < 경고선 {ret_l}%")
    if stats["mdd_pct"] is not None and stats["mdd_pct"] < mdd_l:
        warns.append(f"최대낙폭 {stats['mdd_pct']:.1f}% < 경고선 {mdd_l}%")
    if avg_loss is not None and abs(avg_loss - base_loss) > AVG_LOSS_BAND:
        warns.append(f"평균 손실 {avg_loss:+.1f}% (기준 {base_loss}±{AVG_LOSS_BAND:.0f}%p 밖, 손실 {len(losses)}건)")
    return {"warn": bool(warns), "warnings": warns, "avg_loss_pct": avg_loss, "losses": len(losses),
            "lines": {"return": ret_l, "mdd": mdd_l, "avg_loss": base_loss}}


def verdict(a: dict, b: dict, c: dict, d: dict, days: int) -> str:
    final = days >= PERIOD_DAYS
    failed = [k for k, x in (("A", a), ("C", c)) if not x["pass"]]
    if failed:
        v = f"{'·'.join(failed)} 실패 → 원인 수정 후 새 기간"
    elif not b["pass"]:
        v = "B 실패 → 운영 원인 확인"
    elif d["warn"]:
        v = "D 경고 → 대표님 검토(룰 vs 국면)"
    else:
        v = "통과 → 실전 소액(계획 비중 1/4) 가능" if final else "현재까지 기준 충족"
    return v if final else f"중간({days}/{PERIOD_DAYS}일): {v}"


def regime_now(latest: dict, market: str) -> float | None:
    r = ((latest.get("markets") or {}).get(market) or {}).get("regime") or {}
    c, ma = _f(r.get("close")), _f(r.get("ma200"))
    return round((c / ma - 1) * 100, 1) if c and ma else None


def regime_reference(signals_csv: str | None, dist: float | None) -> dict | None:
    """Backtest trades whose index was in the same band from its 200-day line at the signal."""
    if not signals_csv or dist is None:
        return None
    d = pd.read_csv(io.StringIO(signals_csv))
    d = d[(d.exit_type != "OPEN") & d.net_pnl_pct.notna() & d.b_dist200_pct.notna()]
    lo, hi, label = next(b for b in REGIME_BANDS if b[0] <= dist < b[1])
    band = d[(d.b_dist200_pct >= lo) & (d.b_dist200_pct < hi)]
    def stats(x):
        return {"n": int(len(x)), "win_rate_pct": round(float((x.net_pnl_pct > 0).mean() * 100), 1) if len(x) else None,
                "avg_pnl_pct": round(float(x.net_pnl_pct.mean()), 2) if len(x) else None,
                "stop_share_pct": round(float((x.exit_type == "STOP").mean() * 100), 1) if len(x) else None}
    return {"band": label, "dist_now_pct": dist, "band_stats": stats(band), "all_stats": stats(d),
            "deepest_in_backtest_pct": round(float(d.b_dist200_pct.min()), 1) if len(d) else None}


def coverages(src: Source, market: str) -> list[dict]:
    out = []
    for n in src.listdir(f"paper/{market}/signals"):
        if n.endswith(".json"):
            try:
                out.append(json.loads(src.read(f"paper/{market}/signals/{n}") or "{}").get("coverage") or {})
            except ValueError:
                continue
    return out


def evaluate(market: str, ledger: Source, results: Source, latest: dict) -> dict:
    audit = json.loads(ledger.read(f"paper/{market}/audit.json") or "{}")
    trades = _rows(ledger.read(f"paper/{market}/trades.csv"))
    stats = equity_stats(_rows(ledger.read(f"paper/{market}/equity.csv")))
    a, b, c = check_a(audit, market), check_b(audit, coverages(ledger, market)), check_c(trades, market)
    d = check_d(stats, trades, market)
    bt_market = "KOSDAQ" if market == "KOSDAQ_V2" else market
    reg = regime_reference(results.read(f"latest/results/{bt_market}/signals.csv"), regime_now(latest, market))
    closed = [t for t in trades if t.get("exit_date")]
    return {"market": market, "start_date": audit.get("start_date"), "as_of": audit.get("as_of"), "days": stats["days"],
            "return_pct": stats["return_pct"], "mdd_pct": stats["mdd_pct"], "closed": len(closed),
            "wins": sum(1 for t in closed if (_f(t.get("pnl_pct")) or 0) > 0),
            "A": a, "B": b, "C": c, "D": d, "regime": reg, "verdict": verdict(a, b, c, d, stats["days"])}


def _mark(ok: bool) -> str:
    return "통과" if ok else "**실패**"


def render(rows: list[dict], now: datetime) -> str:
    L = [f"# 모의투자 판정표 — {now.date().isoformat()}", "",
         "고정 판정 기준 A~D(`docs/paper-trading-plan.md`)를 장부에서 그대로 계산한다. 60거래일 전에는 중간 판정이다. 참고 자료이며 룰은 바꾸지 않는다.", "",
         "| 시장 | 경과일 | A 무결성 | B 운영 | C 룰 준수 | D 건전성 | 판정 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        d = "경고" if r["D"]["warn"] else "경고 없음"
        L.append(f"| {MARKET_KO.get(r['market'], r['market'])} | {r['days']}/{PERIOD_DAYS} | {_mark(r['A']['pass'])} | {_mark(r['B']['pass'])} | "
                 f"{_mark(r['C']['pass'])} | {d} | {r['verdict']} |")
    L.append("")
    for r in rows:
        L.append(f"## {MARKET_KO.get(r['market'], r['market'])} (시작 {r['start_date']} · 기준일 {r['as_of']})")
        L.append(f"- 수익률 {r['return_pct']:+.2f}% · 최대낙폭 {r['mdd_pct']:.2f}% · 청산 {r['closed']}건 {r['wins']}승"
                 if r["return_pct"] is not None else "- 자본 기록 부족")
        a, b, c, d = r["A"], r["B"], r["C"], r["D"]
        L.append(f"- A: {', '.join(a['issues']) or '위반 없음'}" + (f" (설명된 불일치 제외: {', '.join(a['explained'])})" if a["explained"] else ""))
        L.append(f"- B: {', '.join(b['issues']) or '문제 없음'} (누락일 {len(b['missing_days'])}, 데이터 실패 최대 {b['worst_fail_share']:.1%})")
        L.append(f"- C: {', '.join(c['issues']) or '위반 없음'}" + (f" · 허용된 갭: {', '.join(c['gaps'])}" if c["gaps"] else ""))
        ln = d["lines"]
        L.append(f"- D: {', '.join(d['warnings']) or '경고 없음'} (경고선 수익률 {ln['return']}% · 낙폭 {ln['mdd']}% · 평균 손실 {ln['avg_loss']}±{AVG_LOSS_BAND:.0f}%p, 현재 평균 손실 "
                 + (f"{d['avg_loss_pct']:+.1f}% / {d['losses']}건)" if d["avg_loss_pct"] is not None else "없음)"))
        g = r["regime"]
        if g:
            bs, al = g["band_stats"], g["all_stats"]
            band_txt = (f"{bs['n']}건 · 승률 {bs['win_rate_pct']}% · 평균 {bs['avg_pnl_pct']:+.1f}% · 손절 {bs['stop_share_pct']}%" if bs["n"]
                        else "거래 없음(레짐 필터가 이 국면 진입을 막음)")
            if g["deepest_in_backtest_pct"] is not None and g["dist_now_pct"] < g["deepest_in_backtest_pct"]:
                band_txt += f". 지금 이격은 10년 백테스트 거래 중 가장 깊은 {g['deepest_in_backtest_pct']}%보다 깊어 비교할 과거가 없음"
            L.append(f"- 국면: 지수가 200일선 대비 {g['dist_now_pct']:+.1f}% ({g['band']} 구간). 같은 구간 백테스트 {band_txt}. "
                     f"전체 {al['n']}건 · 승률 {al['win_rate_pct']}% · 평균 {al['avg_pnl_pct']:+.1f}%.")
        L.append("")
    L.append("## 판정 규칙 (계획서 고정)")
    L.append("- A·B·C 통과, D 경고 없음 → 실전 소액 적용 가능(계획 비중의 1/4, 20거래일마다 재점검).")
    L.append("- A 또는 C 실패 → 원인을 고친 뒤 새 기간으로 다시 시작(이전 기록 보존).")
    L.append("- D 경고 → 대표님 검토: 룰 문제인지 시장 국면 문제인지 구분(국면 줄 참고).")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--ledger-ref", default="origin/paper-trading")
    ap.add_argument("--results-ref", default="origin/swing-results")
    ap.add_argument("--ledger-dir", default=None)
    ap.add_argument("--results-dir", default=None)
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--out", default="reports/paper_verdict")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    ledger = Source(directory=Path(args.ledger_dir).parent) if args.ledger_dir else Source(repo, args.ledger_ref)
    results = Source(directory=args.results_dir) if args.results_dir else Source(repo, args.results_ref)
    latest = json.loads(ledger.read("paper/latest.json") or "{}")
    rows = [evaluate(m.strip(), ledger, results, latest) for m in args.markets.split(",") if m.strip()]
    now = datetime.now(timezone.utc)
    text = render(rows, now)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text(text, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({"generated_at": now.isoformat(), "markets": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
