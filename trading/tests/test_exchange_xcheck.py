"""Crypto cross-check against Coinbase / Kraken (checklist 4): symbol mapping, candle parsing, the record."""
import json

import pandas as pd

from swing_engine import exchange as X
from swing_engine import xcheck

TS = 1793232000                                      # 2026-10-29 00:00 UTC
DAY = pd.Timestamp("2026-10-29").to_pydatetime()


def test_yahoo_to_venue_symbols():
    assert X.coinbase_product("BTC-USD") == "BTC-USD" and X.kraken_pair("BTC-USD") == "XBTUSD"
    assert X.coinbase_product("UNI7083-USD") == "UNI-USD" and X.kraken_pair("DOGE-USD") == "XDGUSD"
    assert X.coinbase_product("SUI20947-USD") == "SUI-USD"
    assert X.base_symbol("FIGR_HELOC-USD") == "FIGR_HELOC" and X.base_symbol("TAO22974-USD") == "TAO"


def test_coinbase_and_kraken_candles_parse_and_unknown_is_none(monkeypatch):
    def get(url, timeout=30):
        if "/products/NOPE-USD/" in url:
            raise X.ExchangeError("HTTP 404 NotFound")
        if "/products/BTC-USD/" in url:
            assert "granularity=86400" in url and "start=2026-10-29T00:00:00Z" in url
            return [[TS, "80000", "82000", "81000", "81676.3", "12345.6"]]          # time, low, high, open, close, vol
        if "pair=NOPEUSD" in url:
            return {"error": ["EQuery:Unknown asset pair"], "result": {}}
        if "pair=XMRUSD" in url:
            return {"error": [], "result": {"XXMRZUSD": [[TS - 86400, "1", "1", "1", "1", "1", "1", 1],
                                                          [TS, "300", "320", "295", "310.5", "305", "9999", 10]], "last": TS}}
        raise AssertionError(url)
    monkeypatch.setattr(X, "_get_json", get)
    assert X.coinbase_bar("BTC-USD", DAY) == {"open": 81000.0, "high": 82000.0, "low": 80000.0, "close": 81676.3, "volume": 12345.6}
    assert X.coinbase_bar("NOPE-USD", DAY) is None
    assert X.kraken_bar("XMRUSD", DAY)["close"] == 310.5 and X.kraken_bar("XMRUSD", DAY)["volume"] == 9999.0
    assert X.kraken_bar("NOPEUSD", DAY) is None


def test_venue_bar_falls_back_to_kraken(monkeypatch):
    monkeypatch.setattr(X, "coinbase_bar", lambda p, d: {"close": 1.0} if p == "BTC-USD" else None)
    monkeypatch.setattr(X, "kraken_bar", lambda p, d: {"close": 2.0} if p == "XMRUSD" else None)
    assert X.venue_bar("BTC-USD", DAY) == ("coinbase", {"close": 1.0})
    assert X.venue_bar("XMR-USD", DAY) == ("kraken", {"close": 2.0})
    assert X.venue_bar("HYPE-USD", DAY) == (None, None)


def test_bars_on_caches_the_day(tmp_path, monkeypatch):
    calls = []
    def vb(y, d):
        calls.append(y)
        return (None, None) if y == "HYPE-USD" else ("coinbase", {"open": 1, "high": 1, "low": 1, "close": 2.0, "volume": 1})
    monkeypatch.setattr(X, "venue_bar", vb)
    df = X.bars_on(["BTC-USD", "HYPE-USD"], DAY, tmp_path)
    assert list(df.index) == ["BTC-USD"] and df.loc["BTC-USD", "venue"] == "coinbase" and df.attrs["unlisted"] == ["HYPE-USD"]
    df = X.bars_on(["BTC-USD", "HYPE-USD"], DAY, tmp_path)   # served from the cache
    assert calls == ["BTC-USD", "HYPE-USD"] and df.attrs["unlisted"] == ["HYPE-USD"]


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
                           "volume": [1, 1], "venue": ["coinbase", "kraken"]}, index=["BTC-USD", "XMR-USD"])
        df.attrs["unlisted"] = ["HYPE-USD"]
        return df
    monkeypatch.setattr(X, "bars_on", bars_on)
    monkeypatch.setattr(X, "venue_bar", lambda y, d: ("coinbase", {"open": 1, "high": 1, "low": 1, "close": 81900.0, "volume": 1}))
    rec = xcheck.run_crypto(frames, bench, pd.Timestamp("2026-10-29"))
    assert rec["source"] == "Coinbase/Kraken" and rec["checked"] == "2026-10-29" and rec["status"] == "mismatch"
    assert rec["index"]["match"] is True                     # 0.27% on BTC is inside 1%
    assert [(m["symbol"], m["field"]) for m in rec["symbols"]["mismatches"]] == [("XMR-USD", "close")]  # 3.2%
    assert rec["symbols"]["missing"] == ["HYPE-USD"] and rec["symbols"]["venues"] == {"coinbase": 1, "kraken": 1}
    line = xcheck.summary_line(rec)
    assert "Coinbase/Kraken" in line and "HYPE-USD" in line and "BTC 일치" in line and "XMR-USD close" in line
    json.dumps(rec)


def test_run_crypto_records_network_errors(monkeypatch):
    def boom(symbols, day, cache_dir=None):
        raise X.ExchangeError("HTTP 451 restricted location")
    monkeypatch.setattr(X, "bars_on", boom)
    rec = xcheck.run_crypto({"BTC-USD": pd.DataFrame()}, pd.DataFrame(), pd.Timestamp("2026-10-29"))
    assert rec["status"] == "error" and "451" in rec["error"]
