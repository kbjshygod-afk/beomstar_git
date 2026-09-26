"""Signal-level study for pattern analysis of the backtest.

Every rule signal of every symbol is traded on its own (the single-symbol state machine,
no cash limit), so the sample is not shaped by which signals the portfolio could afford.
Each row carries the signal bar's indicator values and the trade's outcome.

    python -m swing_engine.signal_study --market SP500 --start 2014-09-25 --end 2026-09-25 \
        --test-start 2016-09-25 --cache-dir .cache --out results/SP500/signals.csv
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import load_inputs
from .indicators import align_asof, sma, true_range
from .params import COST_PCT, normalize_preset, resolve
from .portfolio import PortfolioConfig, prepare_frames
from .state import run_state_machine

log = logging.getLogger("swing_engine.signal_study")

SIGNAL_COLS = ["close", "rs_pct", "vol_x", "breakout_pct", "from_high52", "contraction", "dry_up", "regime_on"]


def _ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return a / b - 1


def study(frames: dict, bench: pd.DataFrame, params: dict, test_start, cost_pct: float = COST_PCT) -> pd.DataFrame:
    cfg = PortfolioConfig(params=params, rs_mode="percentile", test_start=test_start)
    prepared = prepare_frames(frames, bench, cfg)
    ts = pd.Timestamp(test_start)
    c_rate = float(cost_pct) / 100.0

    b = bench["close"].astype("float64")
    bext = pd.DataFrame({"b_ret20": _ratio(b, b.shift(20)), "b_ret60": _ratio(b, b.shift(60))}, index=bench.index)
    # breadth: share of symbols (with a 200-day MA) that pass the full trend template that day
    tt = pd.DataFrame({s: f["tt_pass"].where(f["ma200"].notna()) for s, f in prepared.items()})
    breadth = tt.astype("float64").mean(axis=1) * 100

    rows = []
    for s, f in prepared.items():
        start = int(f.index.searchsorted(ts))
        if start >= len(f):
            continue
        _, events = run_state_machine(f, f, params["stop_pct"], start=start)
        o, h, l, c = (f[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr_pct = (sma(true_range(f["high"], f["low"], f["close"]), 20) / f["close"] * 100).to_numpy(float)
        tv50 = sma(f["close"] * f["volume"], 50).to_numpy(float)
        ret20 = (_ratio(f["close"], f["close"].shift(20)) * 100).to_numpy(float)
        sig = trade = None
        for ev in events:
            if ev.type == "SIGNAL":
                sig = ev
            elif ev.type == "ENTRY":
                i = sig.bar
                trade = {"symbol": s, "signal_date": f.index[i], "entry_date": ev.date, "entry_price": ev.price,
                         "entry_bar": ev.bar, "exit_signal_date": None,
                         **{k: f[k].iat[i] for k in SIGNAL_COLS},
                         "ext50_pct": _ratio(c[i], f["ma50"].iat[i]) * 100,
                         "ma50_over_ma200_pct": _ratio(f["ma50"].iat[i], f["ma200"].iat[i]) * 100,
                         "above_lo52_pct": _ratio(c[i], f["lo52"].iat[i]) * 100,
                         "atr20_pct": atr_pct[i], "trading_value50": tv50[i], "ret20_pct": ret20[i],
                         "b_dist200_pct": _ratio(f["b_close"].iat[i], f["b_ma200"].iat[i]) * 100,
                         "b_dist20_pct": _ratio(f["b_close"].iat[i], f["b_ma20"].iat[i]) * 100,
                         "entry_gap_pct": _ratio(ev.price, c[i]) * 100}
                sig = None
            elif ev.type == "EXIT_SIGNAL" and trade is not None:
                trade["exit_signal_date"] = ev.date
            elif ev.type in ("STOP", "EXIT_MA") and trade is not None:
                rows.append(_close(trade, ev.date, ev.bar, ev.price, ev.type, h, l, c_rate))
                trade = None
        if trade is not None:                              # still open: marked at the last close
            rows.append(_close(trade, f.index[-1], len(f) - 1, c[-1], "OPEN", h, l, c_rate))
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    out["n_same_day"] = out.groupby("signal_date")["symbol"].transform("count")
    out["breadth_tt_pct"] = breadth.reindex(pd.DatetimeIndex(out["signal_date"])).to_numpy()
    sd = pd.DatetimeIndex(out["signal_date"])
    out[["b_ret20_pct", "b_ret60_pct"]] = align_asof(bext, sd)[["b_ret20", "b_ret60"]].to_numpy() * 100
    for k in ("signal_date", "entry_date", "exit_date", "exit_signal_date"):
        out[k] = pd.to_datetime(out[k]).dt.strftime("%Y-%m-%d")
    return out.sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def _close(t: dict, date, bar: int, price: float, kind: str, h, l, c_rate: float) -> dict:
    e, x = t["entry_bar"], bar
    ep = t["entry_price"]
    t = dict(t, exit_date=date, exit_price=price, exit_type=kind, bars_held=x - e,
             pnl_pct=_ratio(price, ep) * 100,
             net_pnl_pct=(price * (1 - c_rate) / (ep * (1 + c_rate)) - 1) * 100,
             mfe_pct=_ratio(np.nanmax(h[e:x + 1]), ep) * 100,
             mae_pct=_ratio(np.nanmin(l[e:x + 1]), ep) * 100)
    t.pop("entry_bar")
    return t


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--market", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--test-start", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir", default=".cache")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--offline-dir", default=None)
    p.add_argument("--universe-file", default=None)
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--chunk-size", type=int, default=40)
    p.add_argument("--cost-pct", type=float, default=COST_PCT)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    market = normalize_preset(args.market)
    params = resolve(market)
    frames, bench, cov = load_inputs(args, market, params["benchmark"])
    if bench is None or len(bench) == 0:
        raise SystemExit(f"benchmark {params['benchmark']} could not be loaded")
    df = study(frames, bench, params, args.test_start, args.cost_pct)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"{market}: {len(df)} signal trades from {cov['loaded']} symbols -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
