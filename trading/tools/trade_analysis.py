"""Trade autopsy for the paper ledgers: what each trade did between entry and exit.

    python tools/trade_analysis.py --repo .. --out reports/trade_analysis
        [--markets SP500,NDX100,KOSPI,KOSDAQ,KOSDAQ_V2,CRYPTO]
        [--ledger-ref origin/paper-trading] [--results-ref origin/swing-results]
        [--cache-dir .cache | --offline-dir DIR] [--now ISO]
    python tools/trade_analysis.py --ledger-dir PAPER_DIR --results-dir RESULTS_DIR ...   (tests)

Per trade (closed from trades.csv, open from positions.json): pivot and breakout at the signal
bar, volume multiple, entry gap, MFE/MAE from the entry (highs/lows and closes), days to each,
R multiples against the stop distance, the benchmark's move over the holding period, the regime
at the signal and the exit type. Per market the backtest trades (swing-results) give the
reference: win rate, average P&L, median holding, stop share, longest losing streak, and the
binomial chance of a run of losses as long as the paper run at the backtest win rate.

Reference material for the December judgment (grade 1): nothing here changes a rule, a
parameter or a data source.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import data as D  # noqa: E402
from swing_engine import params as P  # noqa: E402

MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "KOSDAQ_V2", "CRYPTO"]
MARKET_KO = {"SP500": "S&P500", "NDX100": "나스닥100", "KOSPI": "코스피", "KOSDAQ": "코스닥",
             "KOSDAQ_V2": "코스닥 v2", "CRYPTO": "크립토"}
LOOKBACK_BARS = 80          # bars before the signal needed for pivot (20) and volume (50)
NUM = {"signal_close", "rs_at_signal", "entry_price", "qty", "stop_price", "exit_price", "net_pnl",
       "pnl_pct", "price_pnl_pct", "bars_held", "days_held"}


# ---------------------------------------------------------------------------
# sources: a git ref or a plain directory
# ---------------------------------------------------------------------------

class Source:
    """Files of the ledger (paper/<M>/...) or the results (latest/results/<M>/...)."""

    def __init__(self, repo: Path | None = None, ref: str | None = None, directory: Path | None = None):
        self.repo, self.ref, self.dir = repo, ref, (Path(directory) if directory else None)

    def read(self, rel: str) -> str | None:
        if self.dir is not None:
            p = self.dir / rel
            return p.read_text(encoding="utf-8") if p.exists() else None
        r = subprocess.run(["git", "-C", str(self.repo), "show", f"{self.ref}:{rel}"],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    def listdir(self, rel: str) -> list[str]:
        if self.dir is not None:
            p = self.dir / rel
            return sorted(x.name for x in p.iterdir()) if p.is_dir() else []
        r = subprocess.run(["git", "-C", str(self.repo), "ls-tree", "--name-only", f"{self.ref}:{rel}"],
                           capture_output=True, text=True)
        return sorted(r.stdout.split()) if r.returncode == 0 else []


def read_csv_rows(text: str | None) -> list[dict]:
    if not text:
        return []
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        out = {}
        for k, v in row.items():
            if k in NUM:
                out[k] = float(v) if v not in ("", None) else None
            else:
                out[k] = v if v != "" else None
        rows.append(out)
    return rows


def signal_close_at(src: Source, market: str, day: str, symbol: str) -> float | None:
    """signal_close of `symbol` in the latest signal file for `day` (open positions lack it)."""
    names = [n for n in src.listdir(f"paper/{market}/signals") if n.startswith(day)]
    if not names:
        return None
    best = max(names, key=_rev)
    try:
        snap = json.loads(src.read(f"paper/{market}/signals/{best}") or "{}")
    except ValueError:
        return None
    for e in snap.get("entries_next_open") or []:
        if e.get("symbol") == symbol:
            return e.get("signal_close")
    return None


def ledger_trades(src: Source, market: str) -> list[dict]:
    """Closed trades, then open positions as trades without an exit."""
    rows = [r for r in read_csv_rows(src.read(f"paper/{market}/trades.csv")) if r.get("exit_date")]
    pos = src.read(f"paper/{market}/positions.json")
    if pos:
        for p in json.loads(pos) or []:
            sc = p.get("signal_close")
            if sc is None and p.get("signal_date"):
                sc = signal_close_at(src, market, p["signal_date"], p.get("symbol"))
            rows.append({"symbol": p.get("symbol"), "signal_date": p.get("signal_date"),
                         "signal_close": sc, "entry_date": p.get("entry_date"),
                         "entry_price": p.get("entry_price"), "stop_price": p.get("stop_price"),
                         "qty": p.get("qty"), "exit_date": None, "exit_price": None, "exit_type": "OPEN",
                         "pnl_pct": None, "price_pnl_pct": None, "days_held": None})
    return rows


def _rev(name: str) -> int:
    m = re.search(r"\.rev(\d+)\.json$", name)
    return int(m.group(1)) if m else 0


def regime_at(src: Source, market: str, day: str) -> bool | None:
    """regime.on of the latest signal file for `day` (revisions win)."""
    names = [n for n in src.listdir(f"paper/{market}/signals") if n.startswith(day)]
    if not names:
        return None
    best = max(names, key=_rev)
    try:
        return (json.loads(src.read(f"paper/{market}/signals/{best}") or "{}").get("regime") or {}).get("on")
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# per-trade figures
# ---------------------------------------------------------------------------

def _pct(a, b):
    return (a / b - 1) * 100 if a is not None and b not in (None, 0) and not pd.isna(a) and not pd.isna(b) else None


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), nd)


def signal_features(bars: pd.DataFrame, signal_date, p: dict) -> dict:
    """Pivot (highest of the previous pivot_len highs, signal bar excluded), breakout and the
    volume multiple at the signal bar, as the engine defines them."""
    t = pd.Timestamp(signal_date)
    before = bars.loc[: t - pd.Timedelta(seconds=1)]
    row = bars.loc[t] if t in bars.index else None
    out = {"pivot": None, "breakout_pct": None, "vol_x": None}
    if row is None:
        return out
    n_p, n_v = int(p["pivot_len"]), int(p["vol_len"])
    if len(before) >= n_p:
        pivot = float(before["high"].tail(n_p).max())
        out["pivot"] = _r(pivot, 4)
        out["breakout_pct"] = _r(_pct(float(row["close"]), pivot))
    if len(before) >= n_v:
        vmean = float(before["volume"].tail(n_v).mean())
        out["vol_x"] = _r(float(row["volume"]) / vmean) if vmean > 0 else None
    return out


def trade_path(bars: pd.DataFrame, entry_date, exit_date, entry_price: float, stop_price: float | None) -> dict:
    """MFE/MAE from the entry price over the bars from the entry day to the exit day (or the last
    bar for an open trade), by highs/lows and by closes, with the bar count to each and the R
    multiples against the stop distance."""
    e = pd.Timestamp(entry_date)
    seg = bars.loc[e:] if exit_date is None else bars.loc[e: pd.Timestamp(exit_date)]
    if not len(seg) or not entry_price:
        return {}
    hi, lo = seg["high"].to_numpy(dtype=float), seg["low"].to_numpy(dtype=float)
    cl = seg["close"].to_numpy(dtype=float)
    i_hi, i_lo = int(np.nanargmax(hi)), int(np.nanargmin(lo))
    mfe, mae = _pct(float(hi[i_hi]), entry_price), _pct(float(lo[i_lo]), entry_price)
    risk_pct = (entry_price - stop_price) / entry_price * 100 if stop_price else None
    out = {"bars": int(len(seg)), "mfe_pct": _r(mfe), "mae_pct": _r(mae),
           "mfe_close_pct": _r(_pct(float(np.nanmax(cl)), entry_price)),
           "mae_close_pct": _r(_pct(float(np.nanmin(cl)), entry_price)),
           "bars_to_mfe": i_hi, "bars_to_mae": i_lo, "risk_pct": _r(risk_pct),
           "mfe_r": _r(mfe / risk_pct) if risk_pct else None,
           "mae_r": _r(mae / risk_pct) if risk_pct else None,
           "last_close": _r(float(cl[-1]), 4)}
    # first bar whose low touched the stop (0 = entry day)
    if stop_price:
        hit = np.where(lo <= stop_price)[0]
        out["bars_to_stop"] = int(hit[0]) if len(hit) else None
    return out


def bench_move(bench: pd.DataFrame | None, entry_date, exit_date) -> float | None:
    if bench is None or not len(bench):
        return None
    e = pd.Timestamp(entry_date)
    seg = bench.loc[e:] if exit_date is None else bench.loc[e: pd.Timestamp(exit_date)]
    if len(seg) < 2:
        return None
    return _r(_pct(float(seg["close"].iloc[-1]), float(seg["close"].iloc[0])))


def analyze_trade(t: dict, bars: pd.DataFrame | None, bench: pd.DataFrame | None, p: dict,
                  regime_on: bool | None) -> dict:
    entry, stop = t.get("entry_price"), t.get("stop_price")
    out = {"symbol": t["symbol"], "signal_date": t.get("signal_date"), "entry_date": t.get("entry_date"),
           "exit_date": t.get("exit_date"), "exit_type": t.get("exit_type") or "OPEN",
           "entry_price": entry, "stop_price": stop, "exit_price": t.get("exit_price"),
           "pnl_pct": _r(t.get("pnl_pct")), "price_pnl_pct": _r(t.get("price_pnl_pct")),
           "days_held": t.get("days_held"), "rs_at_signal": _r(t.get("rs_at_signal"), 1),
           "regime_on": regime_on, "entry_gap_pct": _r(_pct(entry, t.get("signal_close"))),
           "bars_missing": bars is None or not len(bars)}
    if bars is None or not len(bars):
        return out
    out.update(signal_features(bars, t["signal_date"], p))
    path = trade_path(bars, t["entry_date"], t.get("exit_date"), entry, stop)
    out.update(path)
    risk = path.get("risk_pct")
    pnl = out["price_pnl_pct"]
    if pnl is None and out["exit_type"] == "OPEN" and path.get("last_close") and entry:
        pnl = out["price_pnl_pct"] = _r(_pct(path["last_close"], entry))
    out["result_r"] = _r(pnl / risk) if pnl is not None and risk else None
    out["bench_pct"] = bench_move(bench, t["entry_date"], t.get("exit_date"))
    return out


# ---------------------------------------------------------------------------
# reference from the backtest trades
# ---------------------------------------------------------------------------

def longest_losing_streak(pnls: list[float]) -> int:
    best = cur = 0
    for x in pnls:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


def backtest_reference(rows: list[dict], since: str | None = None) -> dict | None:
    closed = [r for r in rows if r.get("exit_type") and r["exit_type"] != "OPEN" and r.get("pnl_pct") is not None]
    if since:
        closed = [r for r in closed if (r.get("exit_date") or "") >= since]
    if not closed:
        return None
    closed.sort(key=lambda r: (r.get("exit_date") or "", r.get("entry_date") or ""))
    pnl = [r["pnl_pct"] for r in closed]
    wins = [x for x in pnl if x > 0]
    n = len(pnl)
    days = [r["days_held"] for r in closed if r.get("days_held") is not None]
    return {"n": n, "win_rate_pct": _r(len(wins) / n * 100, 1), "avg_pnl_pct": _r(float(np.mean(pnl))),
            "avg_win_pct": _r(float(np.mean(wins))) if wins else None,
            "avg_loss_pct": _r(float(np.mean([x for x in pnl if x <= 0]))) if len(wins) < n else None,
            "median_days": _r(float(np.median(days)), 1) if days else None,
            "stop_share_pct": _r(sum(r["exit_type"] == "STOP" for r in closed) / n * 100, 1),
            "longest_losing_streak": longest_losing_streak(pnl),
            "first": closed[0].get("exit_date"), "last": closed[-1].get("exit_date")}


def chance_of_run(win_rate_pct: float | None, n_losses: int) -> float | None:
    """P(n_losses straight losses) at the reference win rate, in percent."""
    if win_rate_pct is None or n_losses <= 0:
        return None
    return _r((1 - win_rate_pct / 100) ** n_losses * 100, 2)


# ---------------------------------------------------------------------------
# bars
# ---------------------------------------------------------------------------

def load_bars(market: str, symbols: list[str], start, end, args, now: datetime):
    dm = P.data_market(market)
    bench_t = D.benchmark_ticker(dm)
    if args.offline_dir:
        frames, _ = D.load_offline_dir(args.offline_dir, tickers=symbols)
        bp = D.find_offline_csv(args.offline_dir, bench_t)
        bench = D.read_bars_csv(bp, require_ohlc=False) if bp else None
        frames = {t: D.truncate(df, now.date()) for t, df in frames.items()}
        return frames, D.truncate(bench, now.date()) if bench is not None else None
    frames, _ = D.download_yahoo(symbols, start, end, cache_dir=args.cache_dir, market=dm, now=now)
    bf, _ = D.download_yahoo([bench_t], start, end, cache_dir=args.cache_dir, market=dm, now=now,
                             close_only=[bench_t])
    return frames, bf.get(bench_t)


def analyze_market(market: str, ledger: Source, results: Source, args, now: datetime) -> dict:
    trades = ledger_trades(ledger, market)
    p = P.resolve(P.normalize_preset(market))
    out = {"market": market, "trades": [], "reference": None, "reference_1y": None}
    if trades:
        dates = [t["signal_date"] for t in trades if t.get("signal_date")]
        start = (pd.Timestamp(min(dates)) - pd.Timedelta(days=int(LOOKBACK_BARS * 1.6))).date()
        end = now.date() + timedelta(days=1)
        symbols = sorted({t["symbol"] for t in trades})
        frames, bench = load_bars(market, symbols, start, end, args, now)
        for t in trades:
            out["trades"].append(analyze_trade(t, frames.get(t["symbol"]), bench, p,
                                               regime_at(ledger, market, t["signal_date"]) if t.get("signal_date") else None))
    bt_market = P.data_market(market)
    bt_rows = read_csv_rows(results.read(f"latest/results/{bt_market}/trades.csv"))
    out["reference_market"] = bt_market
    out["reference"] = backtest_reference(bt_rows)
    out["reference_1y"] = backtest_reference(bt_rows, since=(now.date() - timedelta(days=365)).isoformat())
    out["summary"] = summarize(out["trades"], out["reference"])
    return out


def summarize(trades: list[dict], ref: dict | None) -> dict:
    closed = [t for t in trades if t["exit_type"] != "OPEN" and t.get("pnl_pct") is not None]
    n = len(closed)
    wins = [t for t in closed if t["pnl_pct"] > 0]
    with_path = [t for t in closed if t.get("mfe_r") is not None]
    s = {"closed": n, "open": len(trades) - n, "wins": len(wins),
         "win_rate_pct": _r(len(wins) / n * 100, 1) if n else None,
         "avg_pnl_pct": _r(float(np.mean([t["pnl_pct"] for t in closed]))) if n else None,
         "stop_share_pct": _r(sum(t["exit_type"] == "STOP" for t in closed) / n * 100, 1) if n else None,
         "median_days": _r(float(np.median([t["days_held"] for t in closed if t.get("days_held") is not None])), 1) if n else None,
         "reached_1r": sum(t["mfe_r"] >= 1 for t in with_path), "reached_half_r": sum(t["mfe_r"] >= 0.5 for t in with_path),
         "avg_mfe_r": _r(float(np.mean([t["mfe_r"] for t in with_path]))) if with_path else None,
         "avg_mae_r": _r(float(np.mean([t["mae_r"] for t in with_path if t.get("mae_r") is not None]))) if with_path else None,
         "stopped_within_3_bars": sum(1 for t in closed if t["exit_type"] == "STOP" and t.get("bars_to_stop") is not None and t["bars_to_stop"] <= 3),
         "avg_entry_gap_pct": _r(float(np.mean([t["entry_gap_pct"] for t in closed if t.get("entry_gap_pct") is not None]))) if n else None,
         "avg_breakout_pct": _r(float(np.mean([t["breakout_pct"] for t in closed if t.get("breakout_pct") is not None]))) if n else None,
         "avg_bench_pct": _r(float(np.mean([t["bench_pct"] for t in closed if t.get("bench_pct") is not None]))) if n else None,
         "regime_off_at_signal": sum(1 for t in closed if t.get("regime_on") is False),
         "losing_streak": longest_losing_streak([t["pnl_pct"] for t in sorted(closed, key=lambda t: t["exit_date"] or "")])}
    s["chance_of_streak_pct"] = chance_of_run(ref["win_rate_pct"], s["losing_streak"]) if ref else None
    return s


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _f(x, fmt="{:.1f}", none="—"):
    return none if x is None else fmt.format(x)


def _price(x):
    if x is None:
        return "—"
    return f"{x:,.0f}" if x >= 1000 else f"{x:,.2f}"


EXIT_KO = {"STOP": "손절", "EXIT_MA": "50일선", "OPEN": "보유 중", "REGIME": "국면", "MANUAL": "수동"}


def render(markets: list[dict], now: datetime) -> str:
    L = [f"# 모의투자 청산 분석 — {now.date().isoformat()}", "",
         "각 거래가 진입부터 청산까지 실제로 어떻게 움직였는지(최대 평가익 MFE·최대 평가손 MAE, 손절 거리 R 기준)와 "
         "백테스트 거래 분포를 나란히 둔다. 참고 자료이며 룰은 바꾸지 않는다.", ""]
    tot_n = tot_w = 0
    chance = 1.0
    chance_ok = False
    for m in markets:
        s, ref = m["summary"], m["reference"]
        tot_n += s["closed"]; tot_w += s["wins"]
        if ref and s["closed"]:
            chance *= (1 - ref["win_rate_pct"] / 100) ** (s["closed"] - s["wins"]) if s["wins"] == 0 else 1.0
            chance_ok = chance_ok or s["wins"] == 0
    L.append("## 요약")
    L.append("| 시장 | 청산 | 승 | 승률 | 평균 손익 | 손절 비중 | 중앙 보유일 | +1R 도달 | 평균 MFE(R) | 3봉 내 손절 | 백테스트 승률 | 최근 1년 승률 | 백테스트 최장 연패 | 이번 연패 | 연패 확률 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m in markets:
        s, ref, r1 = m["summary"], m["reference"], m["reference_1y"]
        L.append(f"| {MARKET_KO.get(m['market'], m['market'])} | {s['closed']} | {s['wins']} | {_f(s['win_rate_pct'])}% | {_f(s['avg_pnl_pct'], '{:+.1f}')}% | "
                 f"{_f(s['stop_share_pct'], '{:.0f}')}% | {_f(s['median_days'], '{:.0f}')} | {s['reached_1r']}/{s['closed']} | {_f(s['avg_mfe_r'], '{:.2f}')} | {s['stopped_within_3_bars']} | "
                 f"{_f(ref['win_rate_pct'] if ref else None)}% ({ref['n'] if ref else 0}) | {_f(r1['win_rate_pct'] if r1 else None)}% ({r1['n'] if r1 else 0}) | "
                 f"{ref['longest_losing_streak'] if ref else '—'} | {s['losing_streak']} | {_f(s['chance_of_streak_pct'], '{:.1f}')}% |")
    L.append("")
    if tot_n:
        L.append(f"- 전체 청산 {tot_n}건 중 {tot_w}승. " + (f"시장별 백테스트 승률로 본 '전부 패' 확률 {chance * 100:.2f}%." if tot_w == 0 and chance_ok else ""))
    L.append("- 읽는 법: **+1R 도달**은 손절 거리만큼 평가익이 난 적이 있는 거래 수(진입이 한 번도 안 먹혔는지, 먹혔다가 반납했는지). **3봉 내 손절**은 진입 3일 안에 손절가를 찍은 거래(추격·갭 문제). "
             "**연패 확률**은 백테스트 승률이 참일 때 이 길이의 연패가 나올 확률(이항)로, 낮을수록 지금 표본이 백테스트 분포 밖에 있다는 뜻이다.")
    L.append("")
    for m in markets:
        name = MARKET_KO.get(m["market"], m["market"])
        L.append(f"## {name}")
        if not m["trades"]:
            L.append("거래 없음."); L.append(""); continue
        L.append("| 종목 | 신호일 | 진입일 | 청산일 | 유형 | 보유일 | 손익 | 결과(R) | 돌파폭 | 거래량× | 진입 갭 | MFE | MFE(R) | MFE까지 | MAE | 손절 도달 | 지수 | 국면 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for t in m["trades"]:
            reg = "ON" if t.get("regime_on") is True else "OFF" if t.get("regime_on") is False else "—"
            L.append(f"| {t['symbol']} | {t.get('signal_date') or '—'} | {t.get('entry_date') or '—'} | {t.get('exit_date') or '—'} | {EXIT_KO.get(t['exit_type'], t['exit_type'])} | "
                     f"{_f(t.get('days_held'), '{:.0f}')} | {_f(t.get('price_pnl_pct'), '{:+.1f}')}% | {_f(t.get('result_r'), '{:+.2f}')} | {_f(t.get('breakout_pct'), '{:+.1f}')}% | {_f(t.get('vol_x'))} | "
                     f"{_f(t.get('entry_gap_pct'), '{:+.1f}')}% | {_f(t.get('mfe_pct'), '{:+.1f}')}% | {_f(t.get('mfe_r'), '{:.2f}')} | {_f(t.get('bars_to_mfe'), '{:.0f}')}봉 | {_f(t.get('mae_pct'), '{:+.1f}')}% | "
                     f"{('없음' if t.get('bars_to_stop') is None else str(t['bars_to_stop']) + '봉')} | {_f(t.get('bench_pct'), '{:+.1f}')}% | {reg} |")
        missing = [t["symbol"] for t in m["trades"] if t.get("bars_missing")]
        if missing:
            L.append(f"- 봉을 못 받아 경로를 계산하지 못한 종목: {', '.join(missing)}")
        ref, r1 = m["reference"], m["reference_1y"]
        if ref:
            L.append(f"- 백테스트 기준({m['reference_market']}, {ref['first']}~{ref['last']}): {ref['n']}건, 승률 {ref['win_rate_pct']}%, 평균 {ref['avg_pnl_pct']:+.1f}% "
                     f"(승 {_f(ref['avg_win_pct'], '{:+.1f}')}% / 패 {_f(ref['avg_loss_pct'], '{:+.1f}')}%), 중앙 보유 {_f(ref['median_days'], '{:.0f}')}일, 손절 비중 {ref['stop_share_pct']}%, 최장 연패 {ref['longest_losing_streak']}."
                     + (f" 최근 1년: {r1['n']}건, 승률 {r1['win_rate_pct']}%, 평균 {r1['avg_pnl_pct']:+.1f}%, 최장 연패 {r1['longest_losing_streak']}." if r1 else ""))
        s = m["summary"]
        if s["closed"]:
            L.append(f"- 이번 장부: 평균 돌파폭 {_f(s['avg_breakout_pct'], '{:+.1f}')}%, 평균 진입 갭 {_f(s['avg_entry_gap_pct'], '{:+.1f}')}%, 보유 중 지수 평균 {_f(s['avg_bench_pct'], '{:+.1f}')}%, "
                     f"신호 시 국면 OFF {s['regime_off_at_signal']}건, 평균 MAE {_f(s['avg_mae_r'], '{:.2f}')}R.")
        L.append("")
    L.append("## 해석 규칙")
    L.append("- 사실: 표의 숫자는 장부·Yahoo 봉·백테스트 거래 파일에서 계산한 값이다. 해석: '왜'는 아래 세 갈래로만 읽는다.")
    L.append("  1. +1R 도달이 거의 없고 3봉 내 손절이 많다 → 진입 시점 문제(추격·갭·돌파 직후 되밀림). 백테스트에서도 같은 특성의 거래가 지는지 신호 연구(`signal_patterns`)로 확인.")
    L.append("  2. +1R에 닿았다가 손절로 끝난다 → 보유·청산 쪽 문제. 룰 변경은 판정일 이후 3등급 절차.")
    L.append("  3. 연패 확률이 수 % 이상이면 백테스트 분포 안의 불운일 수 있다. 1% 아래면 국면(지수 200일선 아래, 폭 약함)이나 구현 차이를 먼저 의심.")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--ledger-ref", default="origin/paper-trading")
    ap.add_argument("--results-ref", default="origin/swing-results")
    ap.add_argument("--ledger-dir", default=None, help="paper/ ledger directory instead of a git ref (tests)")
    ap.add_argument("--results-dir", default=None, help="results directory with latest/results/<M>/trades.csv (tests)")
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--cache-dir", default=".cache")
    ap.add_argument("--offline-dir", default=None, help="read {TICKER}.csv instead of Yahoo (tests)")
    ap.add_argument("--now", default=None, help="override the current time (ISO, UTC if naive)")
    ap.add_argument("--out", default="reports/trade_analysis", help="stem: writes <stem>.md and <stem>.json")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    repo = Path(args.repo)
    ledger = Source(directory=Path(args.ledger_dir).parent) if args.ledger_dir else Source(repo, args.ledger_ref)
    results = Source(directory=args.results_dir) if args.results_dir else Source(repo, args.results_ref)
    markets = [analyze_market(m.strip(), ledger, results, args, now) for m in args.markets.split(",") if m.strip()]
    text = render(markets, now)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text(text, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({"generated_at": now.isoformat(), "markets": markets}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
