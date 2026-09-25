"""Single-symbol rule check (Korean report).

    python -m swing_engine.analyze --preset SP500 --symbol AAPL --csv AAPL.csv --bench-csv SPX.csv
    python -m swing_engine.analyze --preset KOSPI --symbol 005930.KS --yahoo --equity 100000000 --json

The report covers the last confirmed bar: data date, market regime (with benchmark
numbers), the 8 trend-template conditions with their numbers, RS proxy, pivot and
distance, today's volume multiple, the status label, and - for a signal or an open
position - the entry/stop mechanics and a suggested size. Exits are only the stop or a
close below the 50-day MA (filled at the next open). No profit targets are produced.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import pandas as pd

from . import data as D
from .compare_api import analyze_frames
from .notes import CLOSING_LINE, DISCLAIMER, EXIT_RULES, UNCONFIRMED_LINE
from .params import RISK_PCT, get_preset, resolve
from .sizing import size_position, weight_pct
from .status import fmt_pct, fmt_pp


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def fmt_price(x) -> str:
    if _nan(x):
        return "-"
    x = float(x)
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}" if abs(x - round(x)) < 1e-9 else f"{x:,.2f}"
    if ax >= 1:
        return f"{x:,.2f}"
    return f"{x:.6g}"


def fmt_qty(q, whole: bool) -> str:
    if _nan(q):
        return "-"
    return f"{int(q):,}" if whole else f"{q:,.4f}"


def _pct(a, b):
    if _nan(a) or _nan(b) or not b:
        return None
    return (a / b - 1) * 100


TT_NAMES = [
    "종가 > 150일선 · 200일선",
    "150일선 > 200일선",
    "200일선 > {rise}봉 전 200일선",
    "50일선 > 150일선 · 200일선",
    "종가 > 50일선",
    "종가 ≥ 52주 최저(종가) × 1.30",
    "종가 ≥ 52주 최고(종가) × 0.75",
    "RS 프록시(지수 대비 가중 1년 수익률) ≥ {rs_min}%p",
]


def build_report(sym: pd.DataFrame, bench: pd.DataFrame | None, preset: str, symbol: str,
                 equity: float = 100_000_000.0, risk_pct: float = RISK_PCT, params: dict | None = None,
                 as_of=None, dropped_bar: bool = False, n_events: int = 6) -> dict:
    pr = get_preset(preset)
    p = params or resolve(preset)
    if as_of is not None:
        sym = D.truncate(sym, as_of)
        bench = D.truncate(bench, as_of) if bench is not None else None
    if len(sym) == 0:
        raise ValueError("no bars")
    ind, states, events, status = analyze_frames(sym, bench, p)
    r = ind.iloc[-1]
    st = states.iloc[-1]
    bar = sym.iloc[-1]
    last_date = sym.index[-1]
    close = float(bar["close"])
    rise = int(p["ma200_rise_bars"])
    ma200_prev = ind["ma200"].shift(rise).iloc[-1]
    whole = bool(p["integer_shares"])

    bench_date = None
    if bench is not None and len(bench):
        bd = bench.index[bench.index <= last_date]
        bench_date = bd[-1].strftime("%Y-%m-%d") if len(bd) else None

    values = [
        {"close": close, "ma150": r["ma150"], "ma200": r["ma200"]},
        {"ma150": r["ma150"], "ma200": r["ma200"]},
        {"ma200": r["ma200"], "ma200_prev": ma200_prev},
        {"ma50": r["ma50"], "ma150": r["ma150"], "ma200": r["ma200"]},
        {"close": close, "ma50": r["ma50"]},
        {"close": close, "lo52": r["lo52"], "threshold": r["lo52"] * 1.30},
        {"close": close, "hi52": r["hi52"], "threshold": r["hi52"] * 0.75},
        {"rs_diff": r["rs_diff"], "min": p["rs_min_diff"]},
    ]
    conds = []
    for i in range(8):
        conds.append({"no": i + 1,
                      "name": TT_NAMES[i].format(rise=rise, rs_min=format(p["rs_min_diff"], "g")),
                      "pass": bool(r[f"tt{i + 1}"]),
                      "values": {k: _f(v) for k, v in values[i].items()}})

    in_pos = not _nan(st["entry_price"])
    entry_pending = bool(st["entry_pending"])
    exit_pending = bool(st["exit_pending"])
    stop_pct = float(p["stop_pct"])

    position: dict = {"state": "in_position" if in_pos else ("entry_pending" if entry_pending else "flat")}
    if in_pos:
        last_entry = next((e for e in reversed(events) if e.type == "ENTRY"), None)
        sz = size_position(equity, float(st["entry_price"]), stop_pct, risk_pct, whole)
        position.update({
            "entry_date": last_entry.date.strftime("%Y-%m-%d") if last_entry else None,
            "entry_price": _f(st["entry_price"]), "stop_price": _f(st["stop_price"]),
            "stop_rule": f"진입가 × (1 − {stop_pct:g}%)",
            "exit_ma": _f(r["exit_ma"]), "exit_ma_cushion_pct": _f(_pct(close, r["exit_ma"])),
            "stop_distance_pct": _f(_pct(float(st["stop_price"]), close)),
            "price_pnl_pct": _f(_pct(close, float(st["entry_price"]))),
            "exit_pending": exit_pending,
            "sizing": {k: (_f(v) if isinstance(v, float) else v) for k, v in sz.items()},
        })
    elif entry_pending:
        sz = size_position(equity, close, stop_pct, risk_pct, whole)
        position.update({
            "entry": "다음 거래일 시가",
            "signal_date": last_date.strftime("%Y-%m-%d"), "signal_close": close,
            "stop_rule": f"진입가 × (1 − {stop_pct:g}%)",
            "est_stop_from_close": close * (1 - stop_pct / 100),
            "sizing": {k: (_f(v) if isinstance(v, float) else v) for k, v in sz.items()},
        })
    else:
        sz = size_position(equity, close, stop_pct, risk_pct, whole)
        position["reference_sizing"] = {k: (_f(v) if isinstance(v, float) else v) for k, v in sz.items()}

    regime_mode = p["regime_mode"]
    return {
        "symbol": symbol, "preset": pr.name, "preset_label": pr.label_ko,
        "benchmark": p["benchmark"], "benchmark_tv": pr.benchmark_tv,
        "data_date": last_date.strftime("%Y-%m-%d"), "benchmark_date": bench_date,
        "dropped_unconfirmed_bar": bool(dropped_bar), "bars": int(len(sym)),
        "close": close,
        "regime": {"mode": regime_mode, "on": bool(r["regime_on"]),
                   "b_close": _f(r["b_close"]), "b_ma200": _f(r["b_ma200"]), "b_ma20": _f(r["b_ma20"]),
                   "b_vs_ma200_pct": _f(_pct(r["b_close"], r["b_ma200"])),
                   "b_vs_ma20_pct": _f(_pct(r["b_close"], r["b_ma20"]))},
        "trend_template": {"count": int(r["tt_count"]), "pass": bool(r["tt_pass"]), "required": bool(p["use_tt"]),
                           "conditions": conds},
        "rs": {"rs_diff_pp": _f(r["rs_diff"]), "symbol_weighted_perf_pct": _f(r["wp"] * 100),
               "bench_weighted_perf_pct": _f(r["b_perf"] * 100), "min_pp": p["rs_min_diff"]},
        "pivot": {"pivot": _f(r["pivot"]), "pivot_len": p["pivot_len"], "to_pivot_pct": _f(r["to_pivot_pct"]),
                  "breakout": bool(r["breakout"]), "breakout_pct": _f(r["breakout_pct"]),
                  "cap_on": bool(p["cap_on"]), "cap_ok": bool(r["cap_ok"]), "max_breakout_pct": p["max_breakout_pct"]},
        "volume": {"volume": _f(bar["volume"]), "vol_avg": _f(r["vol_avg"]), "vol_x": _f(r["vol_x"]),
                   "vol_mult": p["vol_mult"], "vol_len": p["vol_len"], "vol_ok": bool(r["vol_ok"])},
        "display": {"contraction": _f(r["contraction"]), "dry_up": _f(r["dry_up"]),
                    "from_high52_pct": _f(r["from_high52"])},
        "full_signal": bool(r["full_signal"]),
        "status": status,
        "position": position,
        "stop_pct": stop_pct, "risk_pct": risk_pct, "equity": equity,
        "weight_pct": weight_pct(stop_pct, risk_pct), "integer_shares": whole,
        "recent_events": [e.as_dict() for e in events[-n_events:]],
        "exit_ma_len": int(p["exit_ma_len"]),
        "exit_rules": EXIT_RULES.format(n=int(p["exit_ma_len"])),
        "unconfirmed": UNCONFIRMED_LINE,
        "disclaimer": DISCLAIMER,
        "closing": CLOSING_LINE,
        "params": p,
    }


def _ok(b: bool) -> str:
    return "통과" if b else "미달"


def render_text(rep: dict) -> str:
    L = []
    rg = rep["regime"]
    L.append(f"[{rep['symbol']}] 스윙 스캐너 룰 점검 — {rep['preset_label']} 프리셋")
    extra = " (장중 미확정 봉은 제외)" if rep["dropped_unconfirmed_bar"] else ""
    L.append(f"데이터 기준일: {rep['data_date']} (마지막 확정 일봉{extra}) · 종가 {fmt_price(rep['close'])}")
    mode_ko = {"MA200": "지수 > 200일선", "MA200_AND_MA20": "지수 > 200일선 그리고 > 20일선", "NONE": "무필터"}[rg["mode"]]
    bench_txt = (f"{rep['benchmark']} {rep['benchmark_date'] or '-'} 종가 {fmt_price(rg['b_close'])} · "
                 f"200일선 {fmt_price(rg['b_ma200'])} ({fmt_pct(rg['b_vs_ma200_pct'])}) · "
                 f"20일선 {fmt_price(rg['b_ma20'])} ({fmt_pct(rg['b_vs_ma20_pct'])})")
    L.append(f"시장 · 레짐: {rep['preset_label']} · {'ON' if rg['on'] else 'OFF'} ({mode_ko}) — {bench_txt}")
    tt = rep["trend_template"]
    L.append(f"트렌드 템플릿: {tt['count']}/8 " + ("(8/8 충족)" if tt["count"] == 8 else "(8/8 필요)" if tt["required"] else "(필수 아님)"))
    for c in tt["conditions"]:
        v = c["values"]
        if c["no"] == 1:
            nums = f"종가 {fmt_price(v['close'])} / 150일선 {fmt_price(v['ma150'])} / 200일선 {fmt_price(v['ma200'])}"
        elif c["no"] == 2:
            nums = f"150일선 {fmt_price(v['ma150'])} / 200일선 {fmt_price(v['ma200'])}"
        elif c["no"] == 3:
            nums = f"200일선 {fmt_price(v['ma200'])} / 이전 {fmt_price(v['ma200_prev'])}"
        elif c["no"] == 4:
            nums = f"50일선 {fmt_price(v['ma50'])} / 150일선 {fmt_price(v['ma150'])} / 200일선 {fmt_price(v['ma200'])}"
        elif c["no"] == 5:
            nums = f"종가 {fmt_price(v['close'])} / 50일선 {fmt_price(v['ma50'])}"
        elif c["no"] == 6:
            nums = f"52주 최저 {fmt_price(v['lo52'])} × 1.30 = {fmt_price(v['threshold'])}"
        elif c["no"] == 7:
            nums = f"52주 최고 {fmt_price(v['hi52'])} × 0.75 = {fmt_price(v['threshold'])}"
        else:
            nums = f"RS 프록시 {fmt_pp(v['rs_diff'])}"
        L.append(f"  {c['no']}. {c['name']}: {_ok(c['pass'])} — {nums}")
    rs = rep["rs"]
    L.append(f"RS 프록시: {fmt_pp(rs['rs_diff_pp'])} (종목 가중수익 {fmt_pct(rs['symbol_weighted_perf_pct'])} · "
             f"지수 {fmt_pct(rs['bench_weighted_perf_pct'])}) — 스캐너 원래 기준은 유니버스 백분위 ≥ 70")
    pv = rep["pivot"]
    brk = (f" · 돌파 {fmt_pct(pv['breakout_pct'])}" + ("" if pv["cap_ok"] else f" (상한 {pv['max_breakout_pct']:g}% 초과 = 추격 구간)")
           if pv["breakout"] else "")
    L.append(f"트리거(피벗): {fmt_price(pv['pivot'])} (직전 {pv['pivot_len']}봉 최고가, 당일 제외) · "
             f"피벗까지 {fmt_pct(pv['to_pivot_pct'])}{brk}")
    vo = rep["volume"]
    vx = "-" if vo["vol_x"] is None else f"{vo['vol_x']:.2f}배"
    L.append(f"당일 거래량 배수: {vx} (기준 {vo['vol_mult']:g}배 · 직전 {vo['vol_len']}일 평균, 당일 제외) — {_ok(vo['vol_ok'])}")
    L.append(f"상태: {rep['status']}")
    pos = rep["position"]
    whole = rep["integer_shares"]
    unit = "주" if whole else ""
    if pos["state"] == "entry_pending":
        sz = pos["sizing"]
        L.append("")
        L.append("■ 신호 확정 — 다음 거래일 시가 진입")
        L.append(f"  진입: 다음 거래일 시가 (신호봉 {pos['signal_date']} 종가 {fmt_price(pos['signal_close'])})")
        L.append(f"  손절가: {pos['stop_rule']} — 체결가로 확정. 신호봉 종가 기준 추정 {fmt_price(pos['est_stop_from_close'])}. "
                 f"매수와 동시에 손절 주문")
        L.append(f"  권장 수량: {fmt_qty(sz['qty'], whole)}{unit} (자본 {rep['equity']:,.0f} × 리스크 {rep['risk_pct']:g}% "
                 f"÷ (신호봉 종가 × 손절 {rep['stop_pct']:g}%)) · 비중 {rep['weight_pct']:.1f}%"
                 + ("" if whole else f" · 정수 주로는 {fmt_qty(sz['whole_shares'], True)}주"))
    elif pos["state"] == "in_position":
        sz = pos["sizing"]
        L.append("")
        L.append("■ 보유 중")
        L.append(f"  진입: {pos['entry_date'] or '-'} 시가 {fmt_price(pos['entry_price'])} · 현재 {fmt_pct(pos['price_pnl_pct'])}")
        L.append(f"  손절가: {fmt_price(pos['stop_price'])} ({pos['stop_rule']}) · 종가 대비 {fmt_pct(pos['stop_distance_pct'])}")
        L.append(f"  {rep['exit_ma_len']}일선: {fmt_price(pos['exit_ma'])} · 청산선 여유 {fmt_pct(pos['exit_ma_cushion_pct'])}")
        if pos["exit_pending"]:
            L.append(f"  ▶ 오늘 종가가 {rep['exit_ma_len']}일선 아래로 마감 — 다음 거래일 시가에 전량 청산 대기")
        L.append(f"  룰 기준 수량(진입가 기준): {fmt_qty(sz['qty'], whole)}{unit} · 비중 {rep['weight_pct']:.1f}%")
    else:
        sz = pos["reference_sizing"]
        L.append(f"참고 수량(오늘 종가 기준, 신호 시): {fmt_qty(sz['qty'], whole)}{unit} · 비중 {rep['weight_pct']:.1f}% · "
                 f"손절 -{rep['stop_pct']:g}% (진입가 기준)")
    L.append(rep["exit_rules"])
    if rep["recent_events"]:
        # Pine label: exitMaName + " 이탈" (indicator lines 205, 214)
        ev_ko = {"SIGNAL": "신호", "ENTRY": "진입", "STOP": "손절",
                 "EXIT_SIGNAL": f"{rep['exit_ma_len']}일선 이탈", "EXIT_MA": "청산"}
        evs = []
        for e in rep["recent_events"]:
            s = f"{e['date']} {ev_ko[e['type']]} {fmt_price(e['price'])}"
            if e["pnl_pct"] is not None:
                s += f" ({fmt_pct(e['pnl_pct'])})"
            evs.append(s)
        L.append("최근 기록: " + " · ".join(evs))
    L.append(rep["unconfirmed"])
    L.append(rep["closing"])
    return "\n".join(L)


def _parse_set(items) -> dict:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set expects KEY=VALUE, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m swing_engine.analyze", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", required=True, help="SP500 | NDX100 | KOSPI | KOSDAQ | CRYPTO | CUSTOM")
    ap.add_argument("--symbol", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="symbol CSV (TradingView export or Date/Open/High/Low/Close/Volume)")
    src.add_argument("--yahoo", action="store_true", help="download from Yahoo Finance")
    ap.add_argument("--bench-csv", help="benchmark CSV (required with --csv)")
    ap.add_argument("--equity", type=float, default=100_000_000.0)
    ap.add_argument("--risk-pct", type=float, default=RISK_PCT)
    ap.add_argument("--as-of", default=None, help="evaluate as of this date (inclusive)")
    ap.add_argument("--start", default=None, help="Yahoo history start (default: 10 years before as-of)")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--keep-last-bar", action="store_true",
                    help="Yahoo: keep today's bar even if the session has not closed (bypasses the cache)")
    ap.add_argument("--drop-last-bar", action="store_true", help="CSV: drop the last (unconfirmed) bar")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="parameter override, e.g. pivot_len=30")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    params = resolve(args.preset, **_parse_set(args.set))
    dropped = False
    if args.csv:
        if not args.bench_csv:
            raise SystemExit("--bench-csv is required with --csv")
        sym = D.read_bars_csv(args.csv)
        bench = D.read_bars_csv(args.bench_csv, require_ohlc=False)
        if args.drop_last_bar and len(sym):
            sym, dropped = sym.iloc[:-1], True
    else:
        bt = params["benchmark"]
        end = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(D._now().date())
        start = pd.Timestamp(args.start) if args.start else end - pd.DateOffset(years=10)
        # --keep-last-bar wants Yahoo's live bar; the cache only ever holds closed bars
        frames, failed = D.download_yahoo([args.symbol, bt], start, end,
                                          cache_dir=None if args.keep_last_bar else args.cache_dir,
                                          market=args.preset,
                                          close_only=[bt] if bt.upper() != args.symbol.upper() else [])
        if args.symbol not in frames:
            raise SystemExit(f"Yahoo: no data for {args.symbol}")
        sym, bench = frames[args.symbol], frames.get(bt)
        # Pine evaluates confirmed bars only (line 163). Also with --as-of: an as-of date of
        # today during the session would otherwise evaluate the still-forming bar. For a
        # past as-of the last bar is final and nothing is dropped.
        if not args.keep_last_bar:
            sym, dropped = D.drop_unconfirmed_last_bar(sym, args.preset, ticker=args.symbol)
            if bench is not None:
                bench, _ = D.drop_unconfirmed_last_bar(bench, args.preset, ticker=bt)
    rep = build_report(sym, bench, args.preset, args.symbol, equity=args.equity, risk_pct=args.risk_pct,
                       params=params, as_of=args.as_of, dropped_bar=dropped)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
