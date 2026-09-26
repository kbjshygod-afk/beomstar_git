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
