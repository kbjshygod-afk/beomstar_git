"""Print the raw tail of Yahoo daily bars as yfinance returns them and as the engine loads them."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import data as D  # noqa: E402

now = datetime.now(timezone.utc)
print("now", now.isoformat(), "yfinance", yf.__version__)
start = (now - timedelta(days=20)).date().isoformat()
end = (now + timedelta(days=2)).date().isoformat()
cases = [("single", "^GSPC"), ("single", "AAPL"), ("batch", ["AAPL", "MSFT", "NVDA", "^GSPC"]),
         ("single", "BTC-USD"), ("batch", ["BTC-USD", "ETH-USD", "SOL-USD"]), ("single", "005930.KS")]
for kind, t in cases:
    raw = yf.download(tickers=t, start=start, end=end, auto_adjust=False, actions=False, group_by="ticker",
                      threads=True, progress=False, multi_level_index=True)
    print(f"\n=== raw {kind} {t}: index tz={getattr(raw.index, 'tz', None)} rows={len(raw)}")
    print(raw.tail(4).to_string()[:2000])
for market, tickers in (("SP500", ["AAPL", "MSFT", "NVDA"]), ("CRYPTO", ["BTC-USD", "ETH-USD"])):
    frames, failed = D.download_yahoo(tickers, (now - timedelta(days=20)).date(), (now + timedelta(days=1)).date(),
                                      market=market, now=now)
    for t, df in frames.items():
        kept, dropped = D.drop_unconfirmed_last_bar(df, market, now=now, ticker=t)
        print(f"engine {market} {t}: last rows {[d.strftime('%Y-%m-%d') for d in df.index[-3:]]} "
              f"-> after drop {kept.index[-1].strftime('%Y-%m-%d')} (dropped={dropped})")

# replicate paper.load_bars for the full universe
from collections import Counter  # noqa: E402

from swing_engine import paper as P  # noqa: E402
from swing_engine.backtest import warmup_bars  # noqa: E402
from swing_engine.params import resolve  # noqa: E402


class _A:
    offline_dir = None
    cache_dir = None
    chunk_size = 40
    max_symbols = 0


for market in ("SP500", "CRYPTO"):
    params = resolve(market)
    uni = D.fetch_universe(market, cache_dir=None, now=now)
    wb = warmup_bars(params)
    cal_days = wb + 30 if market == "CRYPTO" else int(wb * 1.5) + 45
    start = now.date() - timedelta(days=cal_days)
    frames, bench, failed = P.load_bars(market, params, uni, start, now, _A())
    last = Counter(df.index[-1].strftime("%Y-%m-%d") for df in frames.values())
    print(f"\npaper.load_bars {market}: {len(frames)} frames, failed {len(failed)}, bench last "
          f"{bench.index[-1].strftime('%Y-%m-%d')}, frame last-date counts {dict(last)}")
