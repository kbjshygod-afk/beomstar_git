import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def bdays(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


def make_bars(close, dates=None, volume=1_000_000.0, spread=0.005, open_=None):
    """OHLCV frame from a close array: open = previous close (or given), high/low = +-spread."""
    close = np.asarray(close, float)
    n = len(close)
    dates = bdays(n) if dates is None else pd.DatetimeIndex(dates)
    o = np.r_[close[0], close[:-1]] if open_ is None else np.asarray(open_, float)
    h = np.maximum(o, close) * (1 + spread)
    l = np.minimum(o, close) * (1 - spread)
    v = np.full(n, float(volume)) if np.isscalar(volume) else np.asarray(volume, float)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": close, "volume": v}, index=dates)


def uptrend_with_breakout(n=420, growth=0.003, base_len=25, vol_mult=2.0, breakout=1.02, seed=None):
    """Smooth uptrend, a flat base of `base_len` bars, then a breakout on the last bar
    with `vol_mult` x volume. With SP500 params the last bar is a full signal."""
    t = np.arange(n - base_len - 1)
    up = 50 * np.exp(growth * t)
    peak = up[-1]
    base = peak * (0.97 + 0.004 * np.sin(np.arange(base_len)))
    last = peak * breakout
    close = np.r_[up, base, last]
    vol = np.full(n, 1_000_000.0)
    vol[-1] = 1_000_000.0 * vol_mult
    df = make_bars(close, volume=vol, spread=0.003)
    # keep base highs below the peak's close so the pivot is well defined
    df.iloc[-base_len - 1:-1, df.columns.get_loc("high")] = np.minimum(
        df["high"].iloc[-base_len - 1:-1], peak * 0.99)
    return df


def rising_bench(dates, start=1000.0, growth=0.0005):
    return pd.DataFrame({"close": start * np.exp(growth * np.arange(len(dates)))}, index=pd.DatetimeIndex(dates))


def rows_from(df):
    return [{"date": d.strftime("%Y-%m-%d"), "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "volume": (None if np.isnan(r.volume) else r.volume)}
            for d, r in df.iterrows()]


def bench_rows_from(df):
    return [{"date": d.strftime("%Y-%m-%d"), "close": float(c)} for d, c in df["close"].items()]


@pytest.fixture
def sp500():
    from swing_engine.params import resolve
    return resolve("SP500")
