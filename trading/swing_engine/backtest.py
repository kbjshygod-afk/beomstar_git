"""Portfolio backtest CLI (SPEC section 8).

    python -m swing_engine.backtest --market SP500 --start 2014-01-01 --end 2026-09-25 \
        --test-start 2016-09-25 --rs-mode percentile --cache-dir .cache --out results/SP500

Offline: --offline-dir DIR reads {TICKER}.csv files (TradingView export or generic OHLCV);
the benchmark is DIR/{benchmark}.csv (a leading '^' may be dropped, e.g. GSPC.csv).
Writes results.json, trades.csv, equity.csv and a Korean summary.md.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as D
from .notes import (DISCLAIMER, SCANNER_FOOTNOTE, SCANNER_TABLE, UNCONFIRMED_LINE, scanner_table_md,
                    unconfirmed_table_md)
from .params import COST_PCT, RISK_PCT, get_preset, normalize_preset, resolve
from .portfolio import PortfolioConfig, compute_metrics, prepare_frames, simulate

log = logging.getLogger("swing_engine.backtest")


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.strftime("%Y-%m-%d")
    return o


def _p(x, unit="%", signed=True):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:+.1f}{unit}" if signed else f"{x:.1f}{unit}"


def _n(x, fmt="{:.2f}"):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return fmt.format(x)


def metrics_row(label, m, returns: bool = False) -> str:
    """One table row. returns=True (calendar years) shows the period return instead of CAGR."""
    if not m:
        return f"| {label} | - | - | - | - | - | - | - | - | - | - | - | - |"
    k_s, k_b, k_x = (("return_pct", "bench_return_pct", "excess_return_pp") if returns
                     else ("cagr_pct", "bench_cagr_pct", "excess_cagr_pp"))
    return ("| {l} | {cagr} | {bcagr} | {ex} | {mdd} | {n} | {wr} | {aw} | {al} | {pf} | {bt} | {bp} | {exp} |"
            .format(l=label, cagr=_p(m[k_s]), bcagr=_p(m[k_b]),
                    ex=_p(m[k_x], "%p"), mdd=_p(m["max_drawdown_pct"]),
                    n=m["trades"], wr=_p(m["win_rate_pct"], signed=False), aw=_p(m["avg_win_pct"]),
                    al=_p(m["avg_loss_pct"]), pf=_n(m["profit_factor"]),
                    bt=_p(m["big_win_trade_share_pct"], signed=False),
                    bp=_p(m["big_win_profit_share_pct"], signed=False), exp=_p(m["exposure_pct"], signed=False)))


def warmup_bars(params: dict) -> int:
    """Bars of history before the first bar that can give a full signal (SPEC 4):
    weighted_perf needs close[year_bars], tt3 needs ma200 from ma200_rise_bars ago,
    and the pivot / volume / exit windows need their own history."""
    return max(int(params["year_bars"]) + 1, 200 + int(params["ma200_rise_bars"]),
               int(params["vol_len"]) + 1, int(params["pivot_len"]) + 1, int(params["exit_ma_len"]))


def default_test_start(bench: pd.DataFrame, params: dict, end) -> pd.Timestamp:
    """Default test start: the later of the benchmark bar that completes the indicator
    warm-up and `end` minus 10 years (SPEC 8.7 compares a 10-year window). Without it the
    first ~year of the window is forced cash that still counts against the index."""
    ten_years = pd.Timestamp(end) - pd.DateOffset(years=10)
    wb = warmup_bars(params)
    if len(bench) < wb:
        log.warning("benchmark has %d bars, fewer than the %d-bar indicator warm-up", len(bench), wb)
        return max(ten_years, bench.index[-1]) if len(bench) else ten_years
    return max(ten_years, bench.index[wb - 1])


def _years(first, last) -> str:
    if not first or not last:
        return "-"
    return f"{(pd.Timestamp(last) - pd.Timestamp(first)).days / 365.25:.1f}년"


METRICS_HEADER = ("| 구간 | CAGR | 지수 CAGR | 초과 | MDD | 거래 | 승률 | 평균 이익 | 평균 손실 | PF | "
                  "+20% 초과 거래 비중 | +20% 초과 거래의 이익 비중 | 평균 노출 |\n"
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def render_summary(res: dict) -> str:
    mk = res["market"]
    pr = get_preset(mk)
    cfg = res["config"]
    p = cfg["params"]
    cov = res["coverage"]
    L = []
    L.append(f"# 스윙 스캐너 룰 포트폴리오 백테스트 — {pr.label_ko} ({mk})")
    L.append("")
    L.append(f"> {DISCLAIMER}")
    L.append("")
    last, first = res.get("data_last_date"), res.get("test_first_date")
    L.append("## 설정")
    L.append(f"- 데이터 요청: {cfg['start']} ~ {cfg['end']} · 기준일(마지막 확정 봉) = {last or '-'}"
             + (f" (요청한 끝 {cfg['end']}보다 이전: 휴장일이거나 장중 미확정 봉 제외)"
                if last and pd.Timestamp(last) < pd.Timestamp(cfg["end"]) else ""))
    auto = " (자동: 지표 워밍업 완료일과 끝−10년 중 늦은 날)" if cfg.get("test_start_auto") else ""
    L.append(f"- 테스트 구간: {first or '-'} ~ {last or '-'} ({_years(first, last)}) · 테스트 시작 {cfg['test_start']}{auto} — "
             f"이전 데이터는 지표 워밍업(최소 {cfg.get('warmup_bars', '-')}봉)에만 사용")
    if cfg.get("warmup_end") and pd.Timestamp(cfg["test_start"]) < pd.Timestamp(cfg["warmup_end"]):
        L.append(f"- 주의: 테스트 시작이 지표 워밍업 완료일({cfg['warmup_end']})보다 이릅니다. 그 전에는 신호가 나올 수 없어 "
                 "현금 보유 구간이 수익률에 섞입니다.")
    L.append(f"- 벤치마크: {p['benchmark']} (TradingView {pr.benchmark_tv}) · 레짐 {p['regime_mode']} · "
             f"손절 -{p['stop_pct']:g}% · 돌파폭 상한 {'켜짐 ' + format(p['max_breakout_pct'], 'g') + '%' if p['cap_on'] else '꺼짐'} · "
             f"1년 봉 수 {p['year_bars']}")
    L.append(f"- 신호: 피벗 직전 {p['pivot_len']}봉 고가 돌파 · 거래량 ≥ 직전 {p['vol_len']}일 평균 × {p['vol_mult']:g} · "
             f"트렌드 템플릿 8/8 · 청산 {p['exit_ma_len']}일선 종가 이탈 → 다음 시가")
    L.append(f"- 자본 {cfg['initial_equity']:,.0f} · 1회 리스크 {cfg['risk_pct']:g}% · 비용 편도 {cfg['cost_pct']:g}% · "
             f"수량 {'정수(주)' if p['integer_shares'] else '소수점 허용'} · 현금 한도 내 RS 순 배분(레버리지 없음)")
    L.append("- 유니버스: 현재 지수 구성종목 — 스캐너와 같은 생존편향. 수치는 낙관적 상한으로 보세요.")
    if mk == "CRYPTO":
        L.append("- 크립토 유니버스는 스테이블코인과 함께 래핑·스테이킹 토큰(WBTC, stETH 등)도 제외했습니다(SPEC 밖의 추가 가정).")
    L.append("")
    L.append("## 데이터 커버리지")
    L.append("| 요청 | 로드 | 실패 | 이력 1년 미만 |")
    L.append("|---|---|---|---|")
    L.append(f"| {cov['requested']} | {cov['loaded']} | {len(cov['failed'])} | {len(cov['short_history'])} |")
    if cov["failed"]:
        L.append("")
        L.append("실패 종목: " + ", ".join(cov["failed"][:60]) + (" …" if len(cov["failed"]) > 60 else ""))
    L.append(f"\n벤치마크 {cov['benchmark']}: {cov['benchmark_rows']}봉")
    for mode, mres in res["modes"].items():
        m = mres["metrics"]
        L.append("")
        L.append(f"## 결과 — RS 방식 `{mode}`" + (" (유니버스 백분위 ≥ 70)" if mode == "percentile" else " (지수 대비 가중수익 ≥ 0%p)"))
        L.append("")
        L.append(METRICS_HEADER)
        L.append(metrics_row("전체 테스트 구간", m["full"]))
        if m.get("oos"):
            L.append(metrics_row(f"OOS ({m['oos']['start']}~)", m["oos"]))
        L.append(metrics_row("최근 1년", m["last_1y"]))
        for y, ym in m["years"].items():
            L.append(metrics_row(f"{y} 수익률" + ("" if ym.get("full_year") else " (부분 연도)"), ym, returns=True))
        L.append("")
        L.append("전체·OOS·최근 1년 행은 CAGR과 초과 = CAGR − 지수 가격지수 CAGR(같은 구간). 연도 행은 연율화하지 않은 "
                 "구간 수익률과 지수 수익률 차이. 모두 수수료 차감 후 시가평가 자본 기준. "
                 "거래 통계는 해당 구간에 청산된 거래 기준(순손익).")
        L.append(f"\n미체결(현금 부족) 신호 {mres['skipped_count']}건 · 기준일 보유 {len(mres['open_positions'])}종목 · "
                 f"다음 시가 진입 대기 {len(mres['pending_entries'])}건 · 다음 시가 청산 대기 {len(mres['pending_exits'])}건")
    L.append("")
    L.append("## 스캐너 계기판 수치와 비교 (SPEC §8)")
    L.append("")
    L.append("스캐너 계기판(2026-09-04 생성), CAGR − 지수 CAGR:")
    L.append("")
    L.append(scanner_table_md())
    L.append("")
    L.append(SCANNER_FOOTNOTE)
    L.append("")
    sc = SCANNER_TABLE.get(mk)
    L.append("이 엔진(같은 시장):")
    L.append("")
    L.append(f"| RS 방식 | 전체 구간 {_years(first, last)} (↔ 스캐너 10년) | OOS | 최근 1년 | 승률 | +20% 초과 거래 비중 | "
             "+20% 초과 거래의 이익 비중 | MDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    if sc:
        L.append(f"| 스캐너 | {sc[1]} | {sc[2]} | {sc[3]} | 30%대 | 8~9% | 77~84% | {'−53.7%' if mk == 'KOSDAQ' else '-'} |")
    for mode, mres in res["modes"].items():
        m = mres["metrics"]
        full, oos, l1 = m["full"] or {}, m.get("oos") or {}, m["last_1y"] or {}
        L.append(f"| {mode} | {_p(full.get('excess_cagr_pp'), '%p')} | "
                 f"{_p(oos.get('excess_cagr_pp'), '%p') if oos else '구간 미정'} | {_p(l1.get('excess_cagr_pp'), '%p')} | "
                 f"{_p(full.get('win_rate_pct'), signed=False)} | {_p(full.get('big_win_trade_share_pct'), signed=False)} | "
                 f"{_p(full.get('big_win_profit_share_pct'), signed=False)} | {_p(full.get('max_drawdown_pct'))} |")
    L.append("")
    L.append("- 스캐너의 OOS 구간 정의는 확인되지 않았습니다. `--oos-start`로 구간을 주면 같은 방식으로 계산합니다.")
    L.append("- 스캐너 원본 코드가 없어 배분·체결·비용 세부가 다를 수 있습니다(SPEC §8의 가정). 방향과 크기를 비교하는 용도입니다.")
    L.append("")
    L.append("## 확인되지 않은 값 (SPEC §9)")
    L.append("")
    L.append("스캐너 원본 코드는 소유자의 맥에만 있어 아래 값은 추정값입니다.")
    L.append("")
    L.append(unconfirmed_table_md())
    L.append("")
    for mode, mres in res["modes"].items():
        if mres["open_positions"] or mres["pending_entries"]:
            L.append(f"## 기준일 상태 — `{mode}` ({mres.get('last_date') or '-'} 종가 기준)")
            L.append("")
            if mres["open_positions"]:
                L.append("| 보유 | 진입일 | 진입가 | 손절가 | 종가 | 손익 | 50일선 | 다음 시가 청산 |")
                L.append("|---|---|---|---|---|---|---|---|")
                for x in mres["open_positions"]:
                    L.append(f"| {x['symbol']} | {x['entry_date']} | {x['entry_price']:.4g} | {x['stop_price']:.4g} | "
                             f"{x['last_close']:.4g} | {_p(x['price_pnl_pct'])} | {x['exit_ma']:.4g} | "
                             f"{'예' if x['exit_pending'] else '-'} |")
                L.append("")
            if mres["pending_entries"]:
                L.append("다음 시가 진입 대기(RS 순): " + ", ".join(x["symbol"] for x in mres["pending_entries"]))
                L.append("")
    L.append(f"_{DISCLAIMER}_")
    return "\n".join(L) + "\n"


def load_inputs(args, market: str, bench_ticker: str):
    """Returns (symbol frames, benchmark frame, coverage dict)."""
    start = pd.Timestamp(args.start).date()
    end = pd.Timestamp(args.end).date()
    cache = None if args.no_cache else args.cache_dir
    if args.offline_dir:
        if args.universe_file:
            tickers = D.read_universe_file(args.universe_file)
        else:
            tickers = None
        frames, failed = D.load_offline_dir(args.offline_dir, tickers=tickers, exclude=[bench_ticker])
        requested = (len(tickers) if tickers is not None else len(frames) + len(failed))
        if args.max_symbols:
            keep = sorted(frames)[: args.max_symbols] if tickers is None else [t for t in tickers if t in frames][: args.max_symbols]
            frames = {t: frames[t] for t in keep}
            requested = min(requested, args.max_symbols)
        bp = D.find_offline_csv(args.offline_dir, bench_ticker)
        bench = D.read_bars_csv(bp, require_ohlc=False) if bp else None
    else:
        tickers = (D.read_universe_file(args.universe_file) if args.universe_file
                   else D.fetch_universe(market, cache_dir=cache))
        if args.max_symbols:
            tickers = tickers[: args.max_symbols]
        requested = len(tickers)
        now = getattr(args, "now", None)
        frames, failed = D.download_yahoo(tickers, start, end, cache_dir=cache, chunk_size=args.chunk_size,
                                          market=market, now=now)
        bframes, _ = D.download_yahoo([bench_ticker], start, end, cache_dir=cache, market=market, now=now,
                                      close_only=[bench_ticker])
        bench = bframes.get(bench_ticker)
        # Pine only evaluates confirmed bars (line 163): drop a still-forming bar of today
        frames = {t: D.drop_unconfirmed_last_bar(df, market, now=now, ticker=t)[0] for t, df in frames.items()}
        if bench is not None:
            bench = D.drop_unconfirmed_last_bar(bench, market, now=now, ticker=bench_ticker)[0]
    frames = {t: D.truncate(df, end, start) for t, df in frames.items()}
    frames = {t: df for t, df in frames.items() if len(df)}
    if bench is not None:
        bench = D.truncate(bench, end, start)
    return frames, bench, {"requested": requested, "loaded": len(frames), "failed": sorted(failed),
                           "benchmark": bench_ticker, "benchmark_rows": 0 if bench is None else int(len(bench))}


def run(args) -> dict:
    market = normalize_preset(args.market)
    overrides = {}
    if args.benchmark:
        overrides["benchmark"] = args.benchmark
    params = resolve(market, **overrides)
    frames, bench, cov = load_inputs(args, market, params["benchmark"])
    if bench is None or len(bench) == 0:
        raise SystemExit(f"benchmark {params['benchmark']} could not be loaded")
    yb = params["year_bars"]
    cov["short_history"] = sorted(t for t, df in frames.items() if len(df) < yb + 1)
    modes = ["proxy", "percentile"] if args.rs_mode == "both" else [args.rs_mode]
    wb = warmup_bars(params)
    warm_end = bench.index[wb - 1] if len(bench) >= wb else None
    if args.test_start:
        test_start = pd.Timestamp(args.test_start)
        if warm_end is not None and test_start < warm_end:
            log.warning("test start %s is before the indicator warm-up ends (%s)", test_start.date(), warm_end.date())
    else:
        test_start = default_test_start(bench, params, args.end)
    test_start = test_start.strftime("%Y-%m-%d")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"market": market, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "config": {"start": args.start, "end": args.end, "test_start": test_start,
                      "test_start_auto": not args.test_start, "warmup_bars": wb,
                      "warmup_end": None if warm_end is None else warm_end.strftime("%Y-%m-%d"),
                      "initial_equity": args.initial_equity, "risk_pct": args.risk_pct,
                      "cost_pct": args.cost_pct, "params": params, "oos_start": args.oos_start,
                      "rs_modes": modes},
           "coverage": cov, "modes": {}}
    trades_all, eq_all = [], {}
    for mode in modes:
        cfg = PortfolioConfig(params=params, rs_mode=mode, initial_equity=args.initial_equity,
                              risk_pct=args.risk_pct, cost_pct=args.cost_pct,
                              test_start=test_start, as_of=args.end)
        log.info("simulating %s (%d symbols)", mode, len(frames))
        r = simulate(prepare_frames(frames, bench, cfg), cfg)
        m = compute_metrics(r, bench, oos_start=args.oos_start)
        res["modes"][mode] = {"metrics": m, "open_positions": r.open_positions,
                              "pending_entries": r.pending_entries, "pending_exits": r.pending_exits,
                              "skipped_count": int(len(r.skipped)), "first_date": r.config.get("first_date"),
                              "last_date": r.config.get("last_date")}
        if len(r.trades):
            t = r.trades.copy()
            t.insert(0, "rs_mode", mode)
            trades_all.append(t)
        eq_all[mode] = r.equity
    first_mode = next(iter(res["modes"].values()), {})
    res["test_first_date"] = first_mode.get("first_date")
    res["data_last_date"] = first_mode.get("last_date")      # the actual as-of (last confirmed bar)
    res["unconfirmed"] = UNCONFIRMED_LINE                     # SPEC 9: shown wherever results are shown
    res["disclaimer"] = DISCLAIMER
    res = _jsonable(res)
    (out_dir / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    tdf = pd.concat(trades_all, ignore_index=True) if trades_all else pd.DataFrame(
        columns=["rs_mode", "symbol", "signal_date", "entry_date", "entry_price", "qty", "exit_date",
                 "exit_price", "exit_type", "net_pnl", "pnl_pct"])
    tdf.to_csv(out_dir / "trades.csv", index=False)
    eq = pd.DataFrame(index=sorted(set().union(*[e.index for e in eq_all.values()])) if eq_all else [])
    for mode, e in eq_all.items():
        eq[f"equity_{mode}"] = e["equity"]
        eq[f"exposure_pct_{mode}"] = e["exposure_pct"]
        eq[f"n_positions_{mode}"] = e["n_positions"]
    if len(eq):
        from .indicators import align_asof
        eq["benchmark_close"] = align_asof(bench[["close"]], eq.index)["close"].to_numpy()
    eq.index.name = "date"
    eq.index = pd.DatetimeIndex(eq.index).strftime("%Y-%m-%d")
    eq.to_csv(out_dir / "equity.csv")
    (out_dir / "summary.md").write_text(render_summary(res))
    return res


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m swing_engine.backtest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, help="SP500 | NDX100 | KOSPI | KOSDAQ | CRYPTO | CUSTOM")
    ap.add_argument("--start", default="2014-01-01", help="first data date (indicator warm-up starts here)")
    ap.add_argument("--end", default=date.today().isoformat(), help="last data date = as_of (inclusive)")
    ap.add_argument("--test-start", default=None,
                    help="first date on which signals are acted on (default: the later of the end of the "
                         "indicator warm-up and --end minus 10 years)")
    ap.add_argument("--oos-start", default=None, help="optional out-of-sample start for an extra period")
    ap.add_argument("--rs-mode", choices=["percentile", "proxy", "both"], default="percentile")
    ap.add_argument("--cache-dir", default=".cache")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline-dir", default=None, help="read {TICKER}.csv files instead of Yahoo")
    ap.add_argument("--universe-file", default=None, help="tickers (one per line or comma-separated)")
    ap.add_argument("--max-symbols", type=int, default=None)
    ap.add_argument("--benchmark", default=None, help="override the preset's benchmark ticker")
    ap.add_argument("--initial-equity", type=float, default=100_000_000.0)
    ap.add_argument("--risk-pct", type=float, default=RISK_PCT)
    ap.add_argument("--cost-pct", type=float, default=COST_PCT)
    ap.add_argument("--chunk-size", type=int, default=40)
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    res = run(args)
    for mode, mres in res["modes"].items():
        f = mres["metrics"]["full"] or {}
        print(f"[{res['market']} {mode}] CAGR {_p(f.get('cagr_pct'))} vs 지수 {_p(f.get('bench_cagr_pct'))} "
              f"(초과 {_p(f.get('excess_cagr_pp'), '%p')}), MDD {_p(f.get('max_drawdown_pct'))}, 거래 {f.get('trades')}")
    print(f"테스트 구간 {res.get('test_first_date') or '-'} ~ {res.get('data_last_date') or '-'} "
          f"({_years(res.get('test_first_date'), res.get('data_last_date'))}, 기준일 = 마지막 확정 봉)")
    print(f"로드 {res['coverage']['loaded']}/{res['coverage']['requested']} · 결과: {args.out}")
    print(UNCONFIRMED_LINE)
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
