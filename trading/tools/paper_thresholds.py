"""60-trading-day warning lines for the paper-trading verdict (docs/paper-trading-plan.md, item D).

    python tools/paper_thresholds.py --market SP500 --equity equity.csv --trades trades.csv [--window 60]

Every overlapping window of `window` bars in a backtest equity curve gives one sample:
  * return  = equity[i + window] / equity[i] - 1
  * excess  = return - benchmark return over the same bars
  * max DD  = worst drawdown inside the window, from its own running peak
The warning lines are the 5th percentiles; the medians are shown for scale. From the trades:
the average loss of losing trades (net pnl_pct), the win rate and the trades per window.

Run on the 2026-09-25 backtest it reproduces the fixed table of the plan exactly
(S&P 500: -10.9% / +2.2% / -16.8% / -13.0%p).
"""
import argparse
import json

import numpy as np
import pandas as pd


def thresholds(equity: pd.DataFrame, trades: pd.DataFrame, window: int = 60) -> dict:
    eq = equity["equity"].to_numpy(float)
    bench = equity["bench_close"].to_numpy(float)
    n = window
    ret = eq[n:] / eq[:-n] - 1
    excess = ret - (bench[n:] / bench[:-n] - 1)
    dd = np.array([(w / np.maximum.accumulate(w) - 1).min()
                   for w in (eq[i:i + n + 1] for i in range(len(eq) - n))])
    pnl = trades["pnl_pct"].dropna().to_numpy(float)
    losses = pnl[pnl < 0]
    pct = lambda a, q: float(np.percentile(a, q) * 100)   # noqa: E731
    return {
        "window": n,
        "samples": int(len(ret)),
        "return_p5_pct": pct(ret, 5),
        "return_median_pct": pct(ret, 50),
        "max_dd_p5_pct": pct(dd, 5),
        "excess_p5_pp": pct(excess, 5),
        "avg_loss_pct": float(losses.mean()) if len(losses) else None,
        "trades_per_window": float(len(pnl) / (len(eq) - 1) * n),
        "win_rate_pct": float((pnl > 0).mean() * 100) if len(pnl) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True)
    ap.add_argument("--equity", required=True, help="backtest equity CSV (date, equity, bench_close, ...)")
    ap.add_argument("--trades", required=True, help="backtest trades CSV (pnl_pct, ...)")
    ap.add_argument("--window", type=int, default=60)
    a = ap.parse_args()
    res = thresholds(pd.read_csv(a.equity), pd.read_csv(a.trades), a.window)
    print(json.dumps({"market": a.market, **res}, ensure_ascii=False))


if __name__ == "__main__":
    main()
