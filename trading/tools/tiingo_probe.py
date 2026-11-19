"""Probe the Tiingo end-of-day API (checklist 3.1, 3.3): the token, one date's bars for a few
tickers (class shares such as BRK-B and the ones Yahoo fails on, e.g. WBD), and how many
requests the free tier allows.

    TIINGO_TOKEN=... python tools/tiingo_probe.py --date 2026-10-29 [--symbols AAPL,BRK-B,BF-B,WBD] [--cache-dir .cache]

Prints what Tiingo answered (never the token) and, with --cache-dir, the Yahoo bar for the same
day so the two can be eyeballed before the ledger compares them every run.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import tiingo  # noqa: E402


def yahoo_bar(cache_dir: Path, symbol: str, date_iso: str) -> dict | None:
    for p in cache_dir.rglob(f"{symbol}.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Date", "")[:10] == date_iso:
                    return {k: row[k] for k in ("Open", "High", "Low", "Close", "Volume") if k in row}
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD US trading day")
    ap.add_argument("--symbols", default="AAPL,BRK-B,BF-B,WBD,GOOGL")
    ap.add_argument("--cache-dir", default=None)
    a = ap.parse_args(argv)
    tok = tiingo.token()
    if tok is None:
        print("TIINGO_TOKEN is not set", file=sys.stderr)
        return 2
    print(f"Tiingo probe · date {a.date} · token length {len(tok)} (never printed)")
    ok, unlisted = True, []
    for sym in [s.strip() for s in a.symbols.split(",") if s.strip()]:
        try:
            bars = tiingo.fetch_bars(sym, a.date, a.date, tok)
        except tiingo.TiingoError as e:
            print(f"[{sym}] FAILED {e}")
            ok = False
            if "HTTP 401" in str(e) or "HTTP 429" in str(e):
                break
            continue
        if bars is None:
            print(f"[{sym}] unknown to Tiingo (404)")
            unlisted.append(sym)
            continue
        print(f"[{sym}] rows {len(bars)}: {bars.to_dict('index') if len(bars) else 'no bar for that date (not published yet?)'}")
        if a.cache_dir:
            yb = yahoo_bar(Path(a.cache_dir), sym, a.date)
            print(f"  Yahoo {sym}: {yb}" if yb else f"  (no Yahoo bar for {sym} in the cache)")
    print("\nRESULT:", ("token and bars answered" if ok else "something needs attention (see above)")
          + (f"; unknown tickers: {', '.join(unlisted)}" if unlisted else ""))
    print("Free-tier caps to confirm on tiingo.com/pricing: requests/hour, requests/day, unique symbols/month "
          f"(the ledger uses ~{2 * (tiingo.SAMPLE + 5)} requests a day, see swing_engine/tiingo.py).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
