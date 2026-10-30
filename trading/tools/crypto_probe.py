"""Probe the crypto exchange public APIs (checklist 4.1-4.3): where each coin of the paper
universe trades, one Binance daily bar per coin, and the Yahoo-vs-Binance close difference for
the coins the Yahoo cache holds.

    python tools/crypto_probe.py --date 2026-10-29 [--universe ../ledger/paper/CRYPTO/config.json] [--cache-dir .cache]

No key is needed. Binance klines are UTC days like Yahoo's crypto bars; Upbit is listed for
information only (KRW prices are not compared).
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import exchange as X                      # noqa: E402

DEFAULT_UNIVERSE = ["BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "SOL-USD", "TRX-USD", "ZEC-USD", "FIGR_HELOC-USD",
                    "HYPE-USD", "DOGE-USD", "XMR-USD", "LINK-USD", "WBT-USD", "ADA-USD", "LEO-USD", "RAIN-USD",
                    "XLM-USD", "BCH-USD", "NEAR-USD", "UNI7083-USD", "LTC-USD", "CC-USD", "SUI20947-USD", "AVAX-USD",
                    "HBAR-USD", "GRAM-USD", "BTW-USD", "TAO22974-USD", "SHIB-USD", "CRO-USD"]


def yahoo_close(cache_dir: Path, symbol: str, date_iso: str) -> float | None:
    for p in cache_dir.rglob(f"{symbol}.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Date", "")[:10] == date_iso:
                    try:
                        return float(row["Close"])
                    except (KeyError, ValueError):
                        return None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="UTC day, YYYY-MM-DD (yesterday or earlier)")
    ap.add_argument("--universe", default=None, help="paper CRYPTO config.json; default: the 2026-10 universe")
    ap.add_argument("--cache-dir", default=None)
    a = ap.parse_args(argv)
    day = datetime.strptime(a.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    syms = json.loads(Path(a.universe).read_text())["universe"] if a.universe else DEFAULT_UNIVERSE
    print(f"crypto probe · {a.date} · {len(syms)} coins")
    try:
        where = X.listing(syms, day)
    except X.ExchangeError as e:
        print("Binance unreachable:", e)
        return 1
    missing = [s for s, w in where.items() if w["binance"] is None]
    print(f"\nBinance USDT pair: {len(syms) - len(missing)}/{len(syms)} listed")
    for s in missing:
        print(f"  NOT on Binance: {s} · Upbit markets: {where[s]['upbit'] or 'none'}")
    print("\nsample bars (Binance 1d, UTC) and Yahoo close from the cache:")
    worst = []
    for s in syms:
        if where[s]["binance"] is None:
            continue
        bar = X.binance_bar(where[s]["binance"], day)
        yc = yahoo_close(Path(a.cache_dir), s, a.date) if a.cache_dir else None
        diff = (bar["close"] / yc - 1) * 100 if (bar and yc) else None
        if diff is not None:
            worst.append((abs(diff), s, yc, bar["close"], diff))
        if s in ("BTC-USD", "ETH-USD") or (diff is not None and abs(diff) > 1):
            print(f"  {s:14s} binance close {bar['close']:,.6g} vol {bar['volume']:,.0f}"
                  + (f" · yahoo {yc:,.6g} · diff {diff:+.2f}%" if diff is not None else " · yahoo: not in cache"))
    if worst:
        worst.sort(reverse=True)
        print(f"\ncompared {len(worst)} coins with the Yahoo cache · largest |diff| {worst[0][0]:.2f}% ({worst[0][1]})"
              f" · over 1%: {sum(1 for w in worst if w[0] > 1)}")
    print("\nRESULT:", "ok" if not missing else f"{len(missing)} coins have no Binance pair (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
