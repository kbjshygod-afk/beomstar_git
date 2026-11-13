"""Probe the KIS Open API (checklist 2.4): a token, one stock's bars, the KOSPI and KOSDAQ index
bars, and the per-second limit, on the paper (vps) or real (prod) server.

    KIS_APP_KEY=... KIS_APP_SECRET=... [KIS_ENV=vps] python tools/kis_probe.py --date 20261030 [--symbol 096530] [--burst 5]

Prints what KIS answered (never the key or token) and, with --cache-dir, the Yahoo bar for the same
day so the two can be eyeballed before the ledger compares them every run.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import kis  # noqa: E402


def yahoo_bar(cache_dir: Path, symbol: str, date_iso: str) -> dict | None:
    for p in cache_dir.rglob(f"{symbol}.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Date", "")[:10] == date_iso:
                    return {k: kis.num(v) for k, v in row.items() if k in ("Open", "High", "Low", "Close", "Volume")}
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="YYYYMMDD KRX trading day (today after the close works)")
    ap.add_argument("--symbol", default="096530")
    ap.add_argument("--burst", type=int, default=5, help="back-to-back calls to observe the per-second limit (0 = skip)")
    ap.add_argument("--cache-dir", default=None)
    a = ap.parse_args(argv)
    try:
        cred = kis.credentials()
    except kis.KISError as e:
        print(e, file=sys.stderr)
        return 2
    if cred is None:
        print("KIS_APP_KEY / KIS_APP_SECRET are not set", file=sys.stderr)
        return 2
    print(f"KIS probe · env {cred['env']} ({kis.BASE[cred['env']]}) · basDd {a.date} · key length {len(cred['key'])} (never printed)")
    client = kis.Client(cred, cache_dir=None)
    t = time.monotonic()
    try:
        tok = client.token()
    except kis.KISError as e:
        print("TOKEN FAILED:", e)
        return 1
    print(f"token ok (length {len(tok)}, {time.monotonic() - t:.1f}s)")
    date = pd.Timestamp(f"{a.date[:4]}-{a.date[4:6]}-{a.date[6:]}")
    ok = True
    for market in ("KOSPI", "KOSDAQ"):
        try:
            bar = kis.index_bar(client, market, date)
            print(f"[{market} index {kis.INDEX_CODE[market]}] {bar if bar else 'no bar for that date'}")
            ok &= bar is not None
        except kis.KISError as e:
            print(f"[{market} index] FAILED {e}")
            ok = False
    try:
        bars = client.stock_bars(a.symbol, a.date, a.date)
        print(f"[stock {a.symbol}] rows {len(bars)}: {bars.to_dict('index') if len(bars) else 'no bar for that date'}")
        ok &= len(bars) > 0
        # which venue does Yahoo's bar come from? KRX regular (J), NXT (NX) or both (UN)
        for mrkt in ("NX", "UN"):
            try:
                b = client.stock_bars(a.symbol, a.date, a.date, mrkt=mrkt)
                print(f"  venue {mrkt}: {b.to_dict('index') if len(b) else 'no bar'}")
            except kis.KISError as e:
                print(f"  venue {mrkt}: FAILED {e}")
        if len(bars) and a.cache_dir:
            suffix = ".KQ" if a.symbol.startswith(("0", "1", "2", "3", "4")) else ".KS"
            for suf in (".KQ", ".KS"):
                yb = yahoo_bar(Path(a.cache_dir), a.symbol + suf, date.strftime("%Y-%m-%d"))
                if yb:
                    print(f"  Yahoo {a.symbol}{suf}: {yb}")
                    break
            else:
                print(f"  (no Yahoo bar for {a.symbol}{suffix} in the cache)")
    except kis.KISError as e:
        print(f"[stock {a.symbol}] FAILED {e}")
        ok = False
    if a.burst > 0:
        fast = kis.Client(cred, cache_dir=None, min_interval=0.0)
        fast._token = tok
        t = time.monotonic()
        hits = 0
        for _ in range(a.burst):
            try:
                fast.stock_bars(a.symbol, a.date, a.date)
                hits += 1
            except kis.KISError as e:
                print(f"burst: call {hits + 1} rejected: {e}")
                break
        print(f"burst: {hits}/{a.burst} back-to-back calls succeeded in {time.monotonic() - t:.2f}s "
              f"(client retries once on {kis.RATE_LIMIT_CODE})")
    print("\nRESULT:", "token, both indexes and the stock answered" if ok else "something needs attention (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
