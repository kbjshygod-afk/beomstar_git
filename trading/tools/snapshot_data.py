"""Download one market's daily bars once and save them for offline research.

    python tools/snapshot_data.py --market SP500 --start 2014-01-01 --out data/SP500.pkl.xz \
        [--extra-tickers extra.txt]

The file holds {"market", "fetched_at", "universe", "extra", "frames": {ticker: bars},
"bench": bars, "failed": [...]}, compressed with xz. Only bars that were final at download
time are kept. --extra-tickers adds symbols outside the current universe (e.g. former index
members) to measure survivorship bias.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import data as D  # noqa: E402
from swing_engine.params import normalize_preset, resolve  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--extra-tickers", default=None)
    p.add_argument("--fallback-universe", default=None, help="tickers to use if the live universe fetch fails")
    a = p.parse_args()
    market = normalize_preset(a.market)
    params = resolve(market)
    now = datetime.now(timezone.utc)
    start, end = pd.Timestamp(a.start).date(), (now + timedelta(days=1)).date()
    try:
        universe = D.fetch_universe(market, cache_dir=None, now=now)
    except Exception as e:  # noqa: BLE001 - KRX's listing endpoint fails now and then
        if not a.fallback_universe:
            raise
        print(f"universe fetch failed ({e}); using {a.fallback_universe}", flush=True)
        universe = [t.strip() for t in Path(a.fallback_universe).read_text().split() if t.strip()]
    extra = []
    if a.extra_tickers:
        extra = [t.strip() for t in Path(a.extra_tickers).read_text().split() if t.strip()]
        extra = sorted(set(extra) - set(universe))
    frames, failed = D.download_yahoo(universe + extra, start, end, cache_dir=None, market=market, now=now)
    frames = {t: D.drop_unconfirmed_last_bar(df, market, now=now, ticker=t)[0] for t, df in frames.items()}
    bf, _ = D.download_yahoo([params["benchmark"]], start, end, cache_dir=None, market=market, now=now,
                             close_only=[params["benchmark"]])
    bench = D.drop_unconfirmed_last_bar(bf[params["benchmark"]], market, now=now,
                                        ticker=params["benchmark"])[0]
    out = {"market": market, "fetched_at": now.isoformat(timespec="seconds"), "universe": universe,
           "extra": extra, "frames": frames, "bench": bench, "failed": sorted(failed)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, a.out, compression="xz")
    got_extra = sum(1 for t in extra if t in frames)
    print(f"{market}: universe {len(universe)}, loaded {sum(1 for t in universe if t in frames)}; "
          f"extra {len(extra)}, loaded {got_extra}; bench rows {len(bench)} -> {a.out} "
          f"({Path(a.out).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
