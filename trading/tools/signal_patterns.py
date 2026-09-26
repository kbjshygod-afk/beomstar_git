"""Pattern tests on the signal study (signals.csv from the backtest workflow).

    python tools/signal_patterns.py RESULTS_DIR OUT_CSV

RESULTS_DIR holds <MARKET>/signals.csv (swing-results branch, runs/<run>/results).
For each market and signal-bar feature, compares the top and bottom thirds of signals by
net P&L and by the share of trades above +20%, with a permutation p-value and the sign in
each half of the period (split 2021-09-25) and in each year. Closed trades only.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO"]
FEATURES = {
    "rs_pct": "RS 백분위", "vol_x": "거래량 배수", "breakout_pct": "돌파폭(피벗 대비)", "from_high52": "52주 고점 대비",
    "contraction": "변동성 수축비", "dry_up": "거래량 마름(10/50)", "ext50_pct": "50일선 이격",
    "ma50_over_ma200_pct": "50/200일선 간격", "above_lo52_pct": "52주 저점 대비 상승", "atr20_pct": "변동성(ATR%)",
    "log_tv": "거래대금(로그)", "ret20_pct": "직전 20일 수익", "b_dist200_pct": "지수 200일선 이격",
    "b_dist20_pct": "지수 20일선 이격", "b_ret20_pct": "지수 20일 수익", "b_ret60_pct": "지수 60일 수익",
    "entry_gap_pct": "진입 갭", "n_same_day": "같은 날 신호 수", "breadth_tt_pct": "템플릿 통과 종목 비율",
}
SPLIT = "2021-09-25"
BIG = 20.0


def _diffs(y_hi, y_lo):
    if len(y_hi) <= 5 or len(y_lo) <= 5:
        return np.nan, np.nan
    return y_hi.mean() - y_lo.mean(), ((y_hi > BIG).mean() - (y_lo > BIG).mean()) * 100


def test_market(d: pd.DataFrame, market: str, rng, nperm: int = 2000) -> list[dict]:
    d = d[d.exit_type != "OPEN"].copy()
    d["log_tv"] = np.log10(d.trading_value50.clip(lower=1))
    y = d.net_pnl_pct.to_numpy()
    h1 = (d.signal_date < SPLIT).to_numpy()
    year = d.signal_date.str[:4].to_numpy()
    rows = []
    for f, name in FEATURES.items():
        x = d[f].to_numpy(float)
        ok = ~np.isnan(x)
        if ok.sum() < 60 or np.nanstd(x) == 0:
            continue
        q1, q2 = np.nanquantile(x, [1 / 3, 2 / 3])
        lo, hi = ok & (x <= q1), ok & (x > q2)
        if lo.sum() < 20 or hi.sum() < 20:
            continue
        diff, dbig = _diffs(y[hi], y[lo])
        xs, ys = x[ok], y[ok]
        n_big = n_mean = 0
        for _ in range(nperm):
            p = rng.permutation(ys)
            a, b = p[xs > q2], p[xs <= q1]
            n_big += abs(((a > BIG).mean() - (b > BIG).mean()) * 100) >= abs(dbig)
            n_mean += abs(a.mean() - b.mean()) >= abs(diff)
        h1d, h1b = _diffs(y[hi & h1], y[lo & h1])
        h2d, h2b = _diffs(y[hi & ~h1], y[lo & ~h1])
        same = [np.sign(y[hi & (year == yr)].mean() - y[lo & (year == yr)].mean()) == np.sign(diff)
                for yr in sorted(set(year)) if (hi & (year == yr)).sum() >= 8 and (lo & (year == yr)).sum() >= 8]
        rows.append({
            "market": market, "feature": f, "name": name, "q1": q1, "q2": q2,
            "n_lo": int(lo.sum()), "n_hi": int(hi.sum()),
            "mean_lo": y[lo].mean(), "mean_hi": y[hi].mean(), "diff": diff,
            "big_lo": (y[lo] > BIG).mean() * 100, "big_hi": (y[hi] > BIG).mean() * 100, "dbig": dbig,
            "win_lo": (y[lo] > 0).mean() * 100, "win_hi": (y[hi] > 0).mean() * 100,
            "p_big": (n_big + 1) / (nperm + 1), "p_mean": (n_mean + 1) / (nperm + 1),
            "h1_diff": h1d, "h2_diff": h2d, "h1_dbig": h1b, "h2_dbig": h2b,
            "years_same": f"{sum(same)}/{len(same)}",
            "consistent": bool(np.sign(h1d) == np.sign(diff) == np.sign(h2d)
                               and np.sign(h1b) == np.sign(dbig) == np.sign(h2b)),
        })
    return rows


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    rng = np.random.default_rng(0)
    rows = []
    for m in MARKETS:
        p = src / m / "signals.csv"
        if p.exists():
            rows += test_market(pd.read_csv(p), m, rng)
    r = pd.DataFrame(rows)
    r.to_csv(out, index=False)
    strict = r[(r[["p_big", "p_mean"]].min(axis=1) < 0.005) & r.consistent]
    print(f"{len(r)} tests; p<0.05 on either measure: {int(((r.p_big < 0.05) | (r.p_mean < 0.05)).sum())}; "
          f"p<0.005 and same sign in both halves: {len(strict)}")
    print(strict[["market", "name", "mean_lo", "mean_hi", "big_lo", "big_hi", "years_same"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
