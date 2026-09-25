"""Daily paper trading with pre-committed signals (docs/paper-trading-plan.md).

One run per market after its close:

1. Load the frozen universe (fixed on the first run) and confirmed bars up to now.
2. Simulate the portfolio from the paper start date to the last confirmed bar (as_of).
   The simulation is the same one the backtest uses (portfolio.simulate).
3. Write signals/<as_of>.json - entries and exits for the next open - and commit + push it
   BEFORE anything else, so the commit time proves the signal existed before the open.
4. Recompute the ledger from the start and audit every committed signal file:
   on time (committed before the next session's open) and identical to the recomputation.
5. Write trades.csv, equity.csv, positions.json, audit.json, report.md (Korean) and the
   combined latest.json, then commit + push again.

The ledger is recomputed from scratch each day, so a missed run loses nothing; the audit
records which days had no pre-committed signal file.

    python -m swing_engine.paper --market SP500 --ledger-dir ../ledger/paper \
        --cache-dir .cache --push-branch paper-trading
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import data as D
from .backtest import _jsonable, warmup_bars
from .notes import DISCLAIMER, UNCONFIRMED_LINE
from .params import COST_PCT, RISK_PCT, normalize_preset, resolve
from .portfolio import PortfolioConfig, prepare_frames, simulate

log = logging.getLogger("swing_engine.paper")

MARKET_KO = {"SP500": "S&P500", "NDX100": "나스닥100", "KOSPI": "코스피", "KOSDAQ": "코스닥", "CRYPTO": "크립토"}
# Session opens used for the "committed before the next open" check. Weekends are skipped;
# exchange holidays are not modelled, which only makes the deadline earlier (stricter).
OPENS = {"America/New_York": dtime(9, 30), "Asia/Seoul": dtime(9, 0)}
# Crypto fills at the 00:00 UTC open, the same instant its signal bar closes, so no commit can
# precede it. The plan instead requires the signal file within 3 hours of the close.
CRYPTO_DEADLINE_HOURS = 3
WATCH_MAX = 15


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return _utc(dt).isoformat(timespec="seconds").replace("+00:00", "Z")


def _day(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def _num(x, nd=4):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else round(f, nd)


def next_open_deadline(market: str, as_of) -> datetime:
    """Latest commit time (UTC) for the signal file of bar `as_of`."""
    d = pd.Timestamp(as_of).date()
    sess = D.session_for(market)
    if sess is None:
        return datetime.combine(d + timedelta(days=1), dtime(CRYPTO_DEADLINE_HOURS, 0), tzinfo=timezone.utc)
    tz = sess[0]
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return datetime.combine(nxt, OPENS[tz], tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def _git(repo: Path, *args, check=True, env=None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def git_root(path: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def first_commit_time(repo: Path, file: Path) -> datetime | None:
    """Commit time of the commit that first added `file` (None if never committed)."""
    out = _git(repo, "log", "--diff-filter=A", "--format=%cI", "--", str(file.relative_to(repo)), check=False)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return _utc(datetime.fromisoformat(lines[-1])) if lines else None


def commit_and_push(repo: Path | None, message: str, branch: str | None, attempts: int = 4) -> bool:
    """git add -A, commit, and (optionally) push to `branch`, retrying a rejected push."""
    if repo is None:
        log.warning("ledger is not a git repository; nothing committed")
        return False
    _git(repo, "add", "-A")
    if not _git(repo, "status", "--porcelain", check=False):
        return True
    _git(repo, "commit", "-q", "-m", message)
    if not branch:
        return True
    for i in range(attempts):
        r = subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", f"HEAD:{branch}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True
        log.warning("push attempt %d failed: %s", i + 1, r.stderr.strip())
        subprocess.run(["git", "-C", str(repo), "pull", "-q", "--rebase", "origin", branch],
                       capture_output=True, text=True)
        time.sleep(2 ** i)
    raise RuntimeError(f"could not push to {branch}")


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_config(root: Path, market: str, args, now: datetime) -> dict:
    p = root / "config.json"
    if p.exists():
        return json.loads(p.read_text())
    if args.universe_file:
        universe = D.read_universe_file(args.universe_file)
    elif args.offline_dir:
        universe = sorted(D.load_offline_dir(args.offline_dir, exclude=[D.benchmark_ticker(market)])[0])
    else:
        universe = D.fetch_universe(market, cache_dir=args.cache_dir, now=now)
    if args.max_symbols:
        universe = universe[: args.max_symbols]
    return {"market": market, "created_at": _iso(now), "start_date": None,
            "rs_mode": args.rs_mode, "initial_equity": args.initial_equity,
            "risk_pct": args.risk_pct, "cost_pct": args.cost_pct,
            "engine_commit": os.environ.get("GITHUB_SHA") or None,
            "universe": list(universe)}


def load_bars(market: str, params: dict, universe: list[str], start: date, now: datetime, args):
    bench_t = params["benchmark"]
    if args.offline_dir:
        frames, failed = D.load_offline_dir(args.offline_dir, tickers=universe, exclude=[bench_t])
        bp = D.find_offline_csv(args.offline_dir, bench_t)
        bench = D.read_bars_csv(bp, require_ohlc=False) if bp else None
        # offline files are treated as confirmed only up to `now` (tests pass --now)
        frames = {t: D.truncate(df, now.date()) for t, df in frames.items()}
        bench = D.truncate(bench, now.date()) if bench is not None else None
    else:
        end = now.date() + timedelta(days=1)
        frames, failed = D.download_yahoo(universe, start, end, cache_dir=args.cache_dir,
                                          chunk_size=args.chunk_size, market=market, now=now)
        bf, _ = D.download_yahoo([bench_t], start, end, cache_dir=args.cache_dir, market=market,
                                 now=now, close_only=[bench_t])
        bench = bf.get(bench_t)
    frames = {t: D.drop_unconfirmed_last_bar(df, market, now=now, ticker=t)[0] for t, df in frames.items()}
    frames = {t: D.truncate(df, None, start) for t, df in frames.items()}
    frames = {t: df for t, df in frames.items() if len(df)}
    if bench is not None:
        bench = D.truncate(D.drop_unconfirmed_last_bar(bench, market, now=now, ticker=bench_t)[0], None, start)
    return frames, bench, sorted(set(failed) | (set(universe) - set(frames)))


# ---------------------------------------------------------------------------
# snapshot, audit, report
# ---------------------------------------------------------------------------

def regime_info(prepared: dict, bench: pd.DataFrame, params: dict, as_of) -> dict:
    row = None
    for f in prepared.values():
        if pd.Timestamp(as_of) in f.index:
            row = f.loc[pd.Timestamp(as_of)]
            break
    b_close = _num(bench["close"].iloc[-1]) if bench is not None and len(bench) else None
    if row is None:
        return {"benchmark": params["benchmark"], "mode": params["regime_mode"], "close": b_close,
                "ma200": None, "ma20": None, "on": None}
    return {"benchmark": params["benchmark"], "mode": params["regime_mode"], "close": _num(row.get("b_close")),
            "ma200": _num(row.get("b_ma200")), "ma20": _num(row.get("b_ma20")), "on": bool(row.get("regime_on"))}


def watchlist(prepared: dict, held: set, as_of) -> list[dict]:
    out = []
    ts = pd.Timestamp(as_of)
    for s, f in prepared.items():
        if s in held or ts not in f.index:
            continue
        r = f.loc[ts]
        if not (bool(r.get("candidate")) and bool(r.get("regime_on"))) or bool(r.get("breakout")):
            continue
        tp = r.get("to_pivot_pct")
        if tp is None or not (tp <= 3):
            continue
        out.append({"symbol": s, "label": "1순위 · 임박 (피벗 1% 이내)" if tp <= 1 else "2순위 · 근접 (피벗 3% 이내)",
                    "close": _num(r["close"]), "pivot": _num(r.get("pivot")), "to_pivot_pct": _num(tp, 2),
                    "rs": _num(r.get("rs_key"), 2)})
    out.sort(key=lambda x: (-(x["rs"] if x["rs"] is not None else -1e9), x["symbol"]))
    return out[:WATCH_MAX]


def build_snapshot(market, as_of, res, prepared, bench, params, cov) -> dict:
    """Everything a trader needs before the next open. Deterministic given the data."""
    entries = [{"symbol": e["symbol"], "signal_close": _num(e["signal_close"]), "rs": _num(e["rs"], 2),
                "desired_qty": _num(e["desired_qty"], 6), "est_stop_from_close": _num(e["est_stop_from_close"])}
               for e in res.pending_entries]
    held = {p["symbol"] for p in res.open_positions}
    return {"market": market, "as_of": _day(as_of),
            "regime": regime_info(prepared, bench, params, as_of),
            "entries_next_open": entries,
            "exits_next_open": sorted(res.pending_exits),
            "positions": sorted(held),
            "watchlist": watchlist(prepared, held, as_of),
            "coverage": cov}


SIGNAL_KEYS = ("entries_next_open", "exits_next_open")


def _signal_sets(snap: dict) -> tuple[set, set]:
    return ({e["symbol"] for e in snap.get("entries_next_open", [])}, set(snap.get("exits_next_open", [])))


def write_signal_file(sig_dir: Path, snap: dict, now: datetime) -> tuple[Path, str]:
    """Write signals/<as_of>.json once. A rerun with the same signals keeps the original file;
    different signals go to <as_of>.revN.json and are reported as a revision."""
    sig_dir.mkdir(parents=True, exist_ok=True)
    body = dict(snap, generated_at=_iso(now))
    p = sig_dir / f"{snap['as_of']}.json"
    if not p.exists():
        p.write_text(json.dumps(_jsonable(body), ensure_ascii=False, indent=1))
        return p, "new"
    old = json.loads(p.read_text())
    if _signal_sets(old) == _signal_sets(snap):
        return p, "unchanged"
    n = 1
    while (sig_dir / f"{snap['as_of']}.rev{n}.json").exists():
        n += 1
    q = sig_dir / f"{snap['as_of']}.rev{n}.json"
    q.write_text(json.dumps(_jsonable(body), ensure_ascii=False, indent=1))
    return q, "revised"


def recomputed_sets(res, as_of) -> dict:
    """{date: (entry symbols armed at that close, exit symbols signalled at that close)}."""
    ent, ext = {}, {}
    t = res.trades
    if len(t):
        for r in t.itertuples():
            ent.setdefault(r.signal_date, set()).add(r.symbol)
            esd = getattr(r, "exit_signal_date", None)
            if isinstance(esd, str) and esd:
                ext.setdefault(esd, set()).add(r.symbol)
    if len(res.skipped):
        for r in res.skipped.itertuples():
            ent.setdefault(r.signal_date, set()).add(r.symbol)
    for e in res.pending_entries:
        ent.setdefault(e["signal_date"], set()).add(e["symbol"])
    for p in res.open_positions:                       # filled entries that are still open
        ent.setdefault(p["signal_date"], set()).add(p["symbol"])
        if p.get("exit_pending"):
            ext.setdefault(p.get("exit_signal_date") or _day(as_of), set()).add(p["symbol"])
    return {"entries": ent, "exits": ext}


def audit(market: str, root: Path, repo: Path | None, res, bench: pd.DataFrame, start_date, as_of) -> dict:
    sig_dir = root / "signals"
    rec = recomputed_sets(res, as_of)
    days = [_day(d) for d in bench.index if pd.Timestamp(start_date) <= d <= pd.Timestamp(as_of)]
    rows, missing = [], []
    for d in days:
        p = sig_dir / f"{d}.json"
        if not p.exists():
            missing.append(d)
            continue
        snap = json.loads(p.read_text())
        ce, cx = _signal_sets(snap)
        re_, rx = rec["entries"].get(d, set()), rec["exits"].get(d, set())
        committed = first_commit_time(repo, p) if repo else None
        deadline = next_open_deadline(market, d)
        revs = sorted(x.name for x in sig_dir.glob(f"{d}.rev*.json"))
        rows.append({"date": d, "committed_at": _iso(committed) if committed else None,
                     "deadline": _iso(deadline),
                     "on_time": None if committed is None else committed <= deadline,
                     "entries_match": ce == re_, "exits_match": cx == rx,
                     "entries_only_committed": sorted(ce - re_), "entries_only_recomputed": sorted(re_ - ce),
                     "exits_only_committed": sorted(cx - rx), "exits_only_recomputed": sorted(rx - cx),
                     "revisions": revs})
    late = [r["date"] for r in rows if r["on_time"] is False]
    mism = [r["date"] for r in rows if not (r["entries_match"] and r["exits_match"])]
    return {"market": market, "start_date": _day(start_date), "as_of": _day(as_of),
            "days": len(days), "signal_files": len(rows), "missing_days": missing,
            "late": late, "uncommitted": [r["date"] for r in rows if r["committed_at"] is None],
            "mismatched": mism, "revised": [r["date"] for r in rows if r["revisions"]], "rows": rows}


def performance(res, bench: pd.DataFrame, start_date, initial_equity: float) -> dict:
    eq = res.equity
    out = {"equity": None, "return_pct": None, "bench_return_pct": None, "mdd_pct": None,
           "closed_trades": 0, "win_rate_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
           "open_positions": len(res.open_positions)}
    if len(eq):
        e = eq["equity"]
        out["equity"] = _num(e.iloc[-1], 0)
        out["return_pct"] = _num((e.iloc[-1] / initial_equity - 1) * 100, 2)
        out["mdd_pct"] = _num(((e / e.cummax()) - 1).min() * 100, 2)
        b = bench["close"]
        b0 = b[b.index <= pd.Timestamp(start_date)]
        if len(b0):
            out["bench_return_pct"] = _num((b.iloc[-1] / b0.iloc[-1] - 1) * 100, 2)
    t = res.trades
    if len(t):
        out["closed_trades"] = int(len(t))
        w = t[t["net_pnl"] > 0]
        l = t[t["net_pnl"] <= 0]
        out["win_rate_pct"] = _num(len(w) / len(t) * 100, 1)
        out["avg_win_pct"] = _num(w["pnl_pct"].mean(), 2) if len(w) else None
        out["avg_loss_pct"] = _num(l["pnl_pct"].mean(), 2) if len(l) else None
    return out


def _f(x, fmt="{:,.2f}"):
    return "-" if x is None else fmt.format(x)


def _pct(x):
    return "-" if x is None else f"{x:+.2f}%"


def render_report(market, cfg, snap, perf, aud, res, params) -> str:
    name = MARKET_KO.get(market, market)
    rg = snap["regime"]
    L = [f"# 모의투자 일일 보고 — {name} ({snap['as_of']})", "",
         f"> {DISCLAIMER}", "",
         f"- 시작일 {cfg['start_date']} · 기준일(마지막 확정 봉) {snap['as_of']} · RS 방식 {cfg['rs_mode']} · "
         f"손절 -{params['stop_pct']:g}% · 1회 리스크 {cfg['risk_pct']}% · 비용 편도 {cfg['cost_pct']}%",
         f"- 레짐 ({rg['mode']}): **{'ON' if rg['on'] else 'OFF' if rg['on'] is not None else '?'}** — "
         f"{rg['benchmark']} 종가 {_f(rg['close'])} · 200일선 {_f(rg['ma200'])}"
         + (f" · 20일선 {_f(rg['ma20'])}" if rg["mode"] == "MA200_AND_MA20" else ""),
         f"- 데이터: 유니버스 {snap['coverage']['requested']}종목 중 {snap['coverage']['loaded']}종목 로드"
         f" (실패 {len(snap['coverage']['failed'])})", ""]
    L += ["## 다음 시가 진입 (오늘 신호)", ""]
    if snap["entries_next_open"]:
        L += ["| 종목 | 신호 종가 | RS | 계획 수량 | 손절가 추정 (종가 기준) |", "|---|---|---|---|---|"]
        for e in snap["entries_next_open"]:
            L.append(f"| {e['symbol']} | {_f(e['signal_close'])} | {_f(e['rs'], '{:.1f}')} | "
                     f"{_f(e['desired_qty'], '{:,.4f}')} | {_f(e['est_stop_from_close'])} |")
        L += ["", "실제 손절가는 체결가(다음 시가) × (1 − 손절%)입니다. 현금이 모자라면 RS 순으로 배분합니다."]
    else:
        L.append("없음")
    L += ["", "## 다음 시가 청산 (50일선 종가 이탈)", "", ", ".join(snap["exits_next_open"]) or "없음", ""]
    L += ["## 보유 종목", ""]
    if res.open_positions:
        L += ["| 종목 | 진입일 | 진입가 | 손절가 | 현재가 | 50일선 | 수익률 |", "|---|---|---|---|---|---|---|"]
        for p in sorted(res.open_positions, key=lambda x: x["entry_date"]):
            L.append(f"| {p['symbol']} | {p['entry_date']} | {_f(p['entry_price'])} | {_f(p['stop_price'])} | "
                     f"{_f(p['last_close'])} | {_f(p['exit_ma'])} | {_pct(p['price_pnl_pct'])} |")
    else:
        L.append("없음")
    L += ["", "## 누적 성과 (시작일 ~ 기준일, 수수료 차감)", "",
          "| 자본 | 수익률 | 지수 수익률 | 최대 낙폭 | 청산 거래 | 승률 | 평균 이익 | 평균 손실 |",
          "|---|---|---|---|---|---|---|---|",
          f"| {_f(perf['equity'], '{:,.0f}')} | {_pct(perf['return_pct'])} | {_pct(perf['bench_return_pct'])} | "
          f"{_pct(perf['mdd_pct'])} | {perf['closed_trades']} | {_f(perf['win_rate_pct'], '{:.1f}%')} | "
          f"{_pct(perf['avg_win_pct'])} | {_pct(perf['avg_loss_pct'])} |", ""]
    on_time = sum(1 for r in aud["rows"] if r["on_time"])
    L += ["## 무결성 점검", "",
          f"- 거래일 {aud['days']}일 · 신호 파일 {aud['signal_files']}개 · 누락 {len(aud['missing_days'])}일",
          f"- 다음 시가 전 커밋: {on_time}/{aud['signal_files']} (늦음 {len(aud['late'])}, 미커밋 {len(aud['uncommitted'])})",
          f"- 재계산과 일치: {aud['signal_files'] - len(aud['mismatched'])}/{aud['signal_files']}"
          + (f" — 불일치 {', '.join(aud['mismatched'])}" if aud["mismatched"] else ""),
          f"- 신호 수정본: {len(aud['revised'])}건" + (f" ({', '.join(aud['revised'])})" if aud["revised"] else ""), ""]
    if snap["watchlist"]:
        L += ["## 관찰 (트렌드 템플릿 통과 · 레짐 ON · 피벗 3% 이내, RS 순)", "",
              "| 종목 | 상태 | 종가 | 피벗 | 피벗까지 |", "|---|---|---|---|---|"]
        for w in snap["watchlist"]:
            L.append(f"| {w['symbol']} | {w['label']} | {_f(w['close'])} | {_f(w['pivot'])} | {_f(w['to_pivot_pct'], '{:.2f}%')} |")
        L.append("")
    L += [f"※ {UNCONFIRMED_LINE}", "", "※ 목표가는 두지 않습니다. 청산은 손절가 도달 또는 50일선 종가 이탈 → 다음 시가뿐입니다."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(args) -> dict:
    market = normalize_preset(args.market)
    params = resolve(market)
    now = _utc(datetime.fromisoformat(args.now)) if args.now else datetime.now(timezone.utc)
    ledger = Path(args.ledger_dir)
    root = ledger / market
    root.mkdir(parents=True, exist_ok=True)
    repo = git_root(ledger)

    cfg = load_config(root, market, args, now)
    start_hint = pd.Timestamp(cfg["start_date"]).date() if cfg["start_date"] else now.date()
    wb = warmup_bars(params)
    cal_days = wb + 30 if market == "CRYPTO" else int(wb * 1.5) + 45
    data_start = start_hint - timedelta(days=cal_days)
    frames, bench, failed = load_bars(market, params, cfg["universe"], data_start, now, args)
    if bench is None or len(bench) == 0:
        raise SystemExit(f"benchmark {params['benchmark']} could not be loaded")
    as_of = bench.index[-1]
    if cfg["start_date"] is None:
        cfg["start_date"] = _day(as_of)                      # frozen from here on
        (root / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
        log.info("paper trading for %s starts at the close of %s", market, cfg["start_date"])
    start_date = pd.Timestamp(cfg["start_date"])
    cov = {"requested": len(cfg["universe"]), "loaded": len(frames), "failed": failed}

    pcfg = PortfolioConfig(params=params, rs_mode=cfg["rs_mode"], initial_equity=cfg["initial_equity"],
                           risk_pct=cfg["risk_pct"], cost_pct=cfg["cost_pct"], test_start=start_date, as_of=as_of)
    prepared = prepare_frames(frames, bench, pcfg)
    res = simulate(prepared, pcfg)

    # (3) signals first
    snap = build_snapshot(market, as_of, res, prepared, bench, params, cov)
    sig_path, sig_state = write_signal_file(root / "signals", snap, now)
    log.info("%s signals %s: %d entries, %d exits (%s)", market, snap["as_of"],
             len(snap["entries_next_open"]), len(snap["exits_next_open"]), sig_state)
    if not args.no_commit:
        commit_and_push(repo, f"{market} signals {snap['as_of']} ({sig_state})", args.push_branch)

    # (4)-(5) ledger, audit, report
    aud = audit(market, root, repo, res, bench, start_date, as_of)
    perf = performance(res, bench, start_date, cfg["initial_equity"])
    (root / "audit.json").write_text(json.dumps(_jsonable(aud), ensure_ascii=False, indent=1))
    (res.trades if len(res.trades) else pd.DataFrame(columns=["symbol"])).to_csv(root / "trades.csv", index=False)
    eq = res.equity.copy()
    eq.index = pd.DatetimeIndex(eq.index).strftime("%Y-%m-%d")
    eq.index.name = "date"
    eq.to_csv(root / "equity.csv")
    (root / "positions.json").write_text(json.dumps(_jsonable(res.open_positions), ensure_ascii=False, indent=1))
    report = render_report(market, cfg, snap, perf, aud, res, params)
    (root / "report.md").write_text(report)

    latest_p = ledger / "latest.json"
    latest = json.loads(latest_p.read_text()) if latest_p.exists() else {"markets": {}}
    latest["updated_at"] = _iso(now)
    latest["disclaimer"] = DISCLAIMER
    latest["unconfirmed"] = UNCONFIRMED_LINE
    latest["markets"][market] = {
        "as_of": snap["as_of"], "start_date": cfg["start_date"], "regime": snap["regime"],
        "entries_next_open": snap["entries_next_open"], "exits_next_open": snap["exits_next_open"],
        "positions": _jsonable(res.open_positions), "watchlist": snap["watchlist"], "performance": perf,
        "audit": {k: aud[k] for k in ("days", "signal_files", "missing_days", "late", "uncommitted", "mismatched", "revised")},
    }
    latest_p.write_text(json.dumps(_jsonable(latest), ensure_ascii=False, indent=1))
    if not args.no_commit:
        commit_and_push(repo, f"{market} ledger {snap['as_of']}", args.push_branch)
    print(report)
    return {"snapshot": snap, "signal_file": str(sig_path), "signal_state": sig_state, "audit": aud, "performance": perf}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m swing_engine.paper", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--market", required=True)
    p.add_argument("--ledger-dir", required=True, help="directory inside a git checkout of the ledger branch")
    p.add_argument("--cache-dir", default=".cache")
    p.add_argument("--push-branch", default=None, help="push each commit to this branch (omit to only commit)")
    p.add_argument("--no-commit", action="store_true", help="write files but do not commit")
    p.add_argument("--rs-mode", default="percentile", choices=["percentile", "proxy"],
                   help="used only when the market's config.json is created")
    p.add_argument("--initial-equity", type=float, default=100_000_000.0)
    p.add_argument("--risk-pct", type=float, default=RISK_PCT)
    p.add_argument("--cost-pct", type=float, default=COST_PCT)
    p.add_argument("--universe-file", default=None)
    p.add_argument("--offline-dir", default=None, help="read {TICKER}.csv instead of Yahoo (tests)")
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--chunk-size", type=int, default=40)
    p.add_argument("--now", default=None, help="override the current time (ISO, UTC if naive; tests)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
