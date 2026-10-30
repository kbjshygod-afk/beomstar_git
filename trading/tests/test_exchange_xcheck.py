"""Crypto cross-check against Binance (checklist 4): symbol mapping, kline parsing, the record."""
import json

import pandas as pd

from swing_engine import exchange as X
from swing_engine import xcheck


def test_yahoo_to_binance_symbols():
    assert X.binance_symbol("BTC-USD") == "BTCUSDT"
    assert X.binance_symbol("UNI7083-USD") == "UNIUSDT"
    assert X.binance_symbol("SUI20947-USD") == "SUIUSDT"
    assert X.binance_symbol("FIGR_HELOC-USD") == "FIGR_HELOCUSDT"
    assert X.base_symbol("TAO22974-USD") == "TAO"


def _kline(day_ms, close):
    return [day_ms, "1", "2", "0.5", str(close), "1234.5", day_ms + 86399999, "0", 0, "0", "0", "0"]


def test_binance_bar_parses_and_treats_unknown_symbol_as_unlisted(monkeypatch):
    day = pd.Timestamp("2026-10-29").to_pydatetime()
    ms = 1793232000000                                   # 2026-10-29 00:00 UTC
    def get(url, timeout=30):
        if "symbol=NOPEUSDT" in url:
            raise X.ExchangeError("HTTP 400 Invalid symbol.")
        assert f"startTime={ms}" in url and "interval=1d" in url
        return [_kline(ms, "81676.3")]
    monkeypatch.setattr(X, "_get_json", get)
    assert X.binance_bar("BTCUSDT", day) == {"open": 1.0, "high": 2.0, "low": 0.5, "close": 81676.3, "volume": 1234.5}
    assert X.binance_bar("NOPEUSDT", day) is None


def test_bars_on_caches_complete_days(tmp_path, monkeypatch):
    day = pd.Timestamp("2026-10-29").to_pydatetime()
    calls = []
    def bar(symbol, d):
        calls.append(symbol)
        return None if symbol == "HYPEUSDT" else {"open": 1, "high": 1, "low": 1, "close": 2.0, "volume": 1}
    monkeypatch.setattr(X, "binance_bar", bar)
    df = X.binance_bars_on(["BTC-USD", "HYPE-USD"], day, tmp_path)
    assert list(df.index) == ["BTC-USD"] and df.attrs["unlisted"] == ["HYPE-USD"]
    df = X.binance_bars_on(["BTC-USD", "HYPE-USD"], day, tmp_path)   # served from the cache
    assert calls == ["BTCUSDT", "HYPEUSDT"] and df.attrs["unlisted"] == ["HYPE-USD"]


def test_run_crypto_compares_close_only_within_one_percent(monkeypatch):
    idx = pd.to_datetime(["2026-10-28", "2026-10-29"])
    frames = {"BTC-USD": pd.DataFrame({"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [80000.0, 81676.3],
                                       "volume": [5e9, 6e9]}, index=idx),
              "XMR-USD": pd.DataFrame({"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [300.0, 310.0],
                                       "volume": [1e6, 1e6]}, index=idx),
              "HYPE-USD": pd.DataFrame({"close": [1.0, 1.0]}, index=idx)}
    bench = frames["BTC-USD"]
    def bars_on(symbols, day, cache_dir=None):
        df = pd.DataFrame({"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [81900.0, 320.0],
                           "volume": [1, 1]}, index=["BTC-USD", "XMR-USD"])
        df.attrs["unlisted"] = ["HYPE-USD"]
        return df
    monkeypatch.setattr(X, "binance_bars_on", bars_on)
    monkeypatch.setattr(X, "binance_bar", lambda s, d: {"open": 1, "high": 1, "low": 1, "close": 81900.0, "volume": 1})
    rec = xcheck.run_crypto(frames, bench, pd.Timestamp("2026-10-29"))
    assert rec["source"] == "Binance" and rec["checked"] == "2026-10-29" and rec["status"] == "mismatch"
    assert rec["index"]["match"] is True                     # 0.27% on BTC is inside 1%
    assert [(m["symbol"], m["field"]) for m in rec["symbols"]["mismatches"]] == [("XMR-USD", "close")]  # 3.2%
    assert rec["symbols"]["missing"] == ["HYPE-USD"]
    line = xcheck.summary_line(rec)
    assert "Binance" in line and "HYPE-USD" in line and "BTC 일치" in line and "XMR-USD close" in line
    json.dumps(rec)


def test_run_crypto_records_network_errors(monkeypatch):
    def boom(symbols, day, cache_dir=None):
        raise X.ExchangeError("HTTP 429 rate limit")
    monkeypatch.setattr(X, "binance_bars_on", boom)
    rec = xcheck.run_crypto({"BTC-USD": pd.DataFrame()}, pd.DataFrame(), pd.Timestamp("2026-10-29"))
    assert rec["status"] == "error" and "429" in rec["error"]
