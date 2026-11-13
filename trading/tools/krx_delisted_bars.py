"""Price history for point-in-time index members that Yahoo no longer serves (delisted, merged),
built from the FinanceData/marcap dataset, so the point-in-time backtest (tools/robustness.py,
part `pit`) stops skipping them.

    python tools/krx_delisted_bars.py --data DATA_DIR --market KOSDAQ --marcap-dir MARCAP_DIR \
        --out OUT_DIR [--check 60]

The 2026-09-26 robustness study ran the rules on each day's real index members, but 47 KOSDAQ and
24 KOSPI members had no Yahoo data (delisted since), so their trades were missing and the result
could be flattering. marcap (github.com/FinanceData/marcap, KRX's daily all-stock snapshot,
delisted stocks included) has their unadjusted OHLCV plus the day's change against the reference
price. The reference price of day t is Close_t - Changes_t; on a normal day it equals the previous
close, and on an ex-date (split, reverse split, bonus or rights issue, capital reduction, spin-off)
KRX resets it, so reference_t / Close_{t-1} is the adjustment factor of that day. Prices before
the ex-date are multiplied by the product of the later factors and volume is divided by it, which
gives a continuous series like Yahoo's split-adjusted one (cash dividends are not adjusted in
either).

Halted days (volume 0, open/high/low 0) become flat bars at the last close, as Yahoo shows them,
so a position held into a halt is marked at the last price and exits at the first real open
after it (the liquidation-trading gap of a delisting is then taken in full).

Writes OUT_DIR/<MARKET>.pkl.xz (the snapshot plus the built frames, listed under "filled") and
copies the membership file, so `robustness.py --data OUT_DIR --parts pit` runs unchanged.
--check N compares the same construction with Yahoo on N surviving members and prints how often
the daily returns disagree. Research tooling only: nothing here touches the ledger or the rules.
"""
import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MEMBERSHIP = {"KOSPI": "KOSPI_membership.csv.gz", "KOSDAQ": "KOSDAQ_membership.csv.gz"}
SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
FACTOR_TOLERANCE = 0.002      # |reference / previous close - 1| below this is rounding, not an action
RETURN_TOLERANCE = 0.005      # --check: a day counts as different when the returns differ by more


def adjusted_bars(rows: pd.DataFrame) -> pd.DataFrame:
    """Adjusted OHLCV (index date, columns open/high/low/close/volume) from one code's marcap rows
    (Date, Open, High, Low, Close, Volume, Changes). attrs['actions'] lists (date, factor)."""
    d = rows.sort_values("Date").drop_duplicates("Date", keep="last")
    d = d[pd.to_numeric(d["Close"], errors="coerce") > 0]
    if len(d) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    close = d["Close"].to_numpy(float)
    ref = close - np.nan_to_num(d["Changes"].to_numpy(float))
    step = np.ones(len(d))
    prev = close[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = ref[1:] / prev
    ok = np.isfinite(r) & (r > 0) & (np.abs(r - 1) > FACTOR_TOLERANCE)
    step[1:][ok] = r[ok]
    # factor applied to day t = product of the steps of all later days
    later = np.concatenate([np.cumprod(step[::-1])[::-1][1:], [1.0]])
    o, h, l = (d[c].to_numpy(float) for c in ("Open", "High", "Low"))
    vol = np.nan_to_num(d["Volume"].to_numpy(float))
    flat = ~(o > 0) | ~(h > 0) | ~(l > 0)                    # halted: no trade that day
    o, h, l = (np.where(flat, close, x) for x in (o, h, l))
    out = pd.DataFrame({"open": o * later, "high": h * later, "low": l * later, "close": close * later,
                        "volume": np.where(later > 0, vol / later, vol)},
                       index=pd.DatetimeIndex(pd.to_datetime(d["Date"].to_numpy()), name="date"))
    dates = out.index[1:][ok]
    out.attrs["actions"] = [(t.strftime("%Y-%m-%d"), round(float(f), 6)) for t, f in zip(dates, r[ok])]
    return out


def load_marcap(marcap_dir: Path, codes: set, start: int, end: int) -> pd.DataFrame:
    """Rows of the given 6-digit codes from marcap-<year>.parquet files in marcap_dir."""
    parts = []
    for y in range(start, end + 1):
        p = marcap_dir / f"marcap-{y}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Changes"])
        df["Code"] = df["Code"].astype(str).str.zfill(6).str.upper()
        parts.append(df[df["Code"].isin(codes)])
    if not parts:
        return pd.DataFrame(columns=["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Changes"])
    return pd.concat(parts, ignore_index=True)


def member_codes(path: Path) -> set:
    m = pd.read_csv(path)
    return set(c for s in m["codes"] for c in str(s).split(","))


def compare_with_yahoo(built: pd.DataFrame, yahoo: pd.DataFrame) -> dict:
    """How the built series' daily returns agree with Yahoo's on the common dates."""
    a = built["close"].pct_change()
    b = yahoo["close"].astype(float).pct_change()
    j = pd.DataFrame({"built": a, "yahoo": b}).dropna()
    if len(j) < 50:
        return {"days": len(j)}
    diff = (j["built"] - j["yahoo"]).abs()
    return {"days": int(len(j)), "differ": int((diff > RETURN_TOLERANCE).sum()),
            "differ_pct": round(float((diff > RETURN_TOLERANCE).mean() * 100), 3),
            "corr": round(float(j["built"].corr(j["yahoo"])), 5)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="snapshot directory (tools/snapshot_data.py output + membership file)")
    ap.add_argument("--market", required=True, choices=sorted(MEMBERSHIP))
    ap.add_argument("--marcap-dir", required=True, help="directory with marcap-<year>.parquet files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=2014)
    ap.add_argument("--end", type=int, default=pd.Timestamp.today().year)
    ap.add_argument("--check", type=int, default=0, help="compare the construction with Yahoo on N surviving members")
    a = ap.parse_args(argv)
    data, out = Path(a.data), Path(a.out)
    snap = pd.read_pickle(data / f"{a.market}.pkl.xz", compression="xz")
    frames = dict(snap["frames"])
    have = {s.split(".")[0] for s in frames}
    members = member_codes(data / MEMBERSHIP[a.market])
    missing = sorted(members - have)
    rows = load_marcap(Path(a.marcap_dir), set(missing), a.start, a.end)
    last = pd.DataFrame(snap["bench"]).index.max()          # keep the snapshot's window: no bars after its last day
    filled, empty, actions = [], [], 0
    for code, g in rows.groupby("Code"):
        bars = adjusted_bars(g[pd.to_datetime(g["Date"]) <= last])
        if len(bars) == 0:
            empty.append(code)
            continue
        frames[code + SUFFIX[a.market]] = bars
        filled.append(code)
        actions += len(bars.attrs.get("actions", []))
    empty += [c for c in missing if c not in set(filled) | set(empty)]
    print(f"{a.market}: members ever {len(members)} · without Yahoo data {len(missing)} · built {len(filled)} "
          f"· still missing {len(empty)} {empty[:10]} · corporate actions adjusted {actions}")
    if a.check:
        pick = sorted(c for c in members & have)[:: max(1, len(members & have) // a.check)][: a.check]
        ref = load_marcap(Path(a.marcap_dir), set(pick), a.start, a.end)
        by_code = {s.split(".")[0]: s for s in snap["frames"]}
        res = []
        for code, g in ref.groupby("Code"):
            c = compare_with_yahoo(adjusted_bars(g[pd.to_datetime(g["Date"]) <= last]), snap["frames"][by_code[code]])
            if c.get("days", 0) >= 50:
                res.append((code, c))
        days = sum(c["days"] for _, c in res)
        differ = sum(c["differ"] for _, c in res)
        worst = sorted(res, key=lambda x: -x[1]["differ_pct"])[:5]
        print(f"check on {len(res)} surviving members: {days:,} common days · returns differ on {differ:,} "
              f"({differ / days * 100:.2f}%) · median correlation {np.median([c['corr'] for _, c in res]):.4f}")
        print("  worst:", [(code, c["differ_pct"], c["corr"]) for code, c in worst])
    out.mkdir(parents=True, exist_ok=True)
    snap = dict(snap, frames=frames, filled=[c + SUFFIX[a.market] for c in filled])
    pd.to_pickle(snap, out / f"{a.market}.pkl.xz", compression="xz")
    shutil.copy(data / MEMBERSHIP[a.market], out / MEMBERSHIP[a.market])
    print(f"wrote {out / (a.market + '.pkl.xz')} ({len(frames)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
