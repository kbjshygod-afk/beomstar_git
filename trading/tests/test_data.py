"""CSV loader and network fetchers (all network calls mocked)."""
import io
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from swing_engine import data as D


# --- CSV -----------------------------------------------------------------------------

TV_UNIX = """time,open,high,low,close,Volume,Volume MA
1704205800,187.15,188.44,183.89,185.64,82488700,
1704292200,184.22,185.88,183.43,184.25,58414500,70000000
1704378600,182.15,183.09,180.88,181.91,71983600,70100000
"""


def test_tradingview_unix_export():
    df = D.read_bars_csv(io.StringIO(TV_UNIX))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert [d.strftime("%Y-%m-%d") for d in df.index] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert df["close"].iloc[0] == 185.64 and df["volume"].iloc[1] == 58414500


def test_tradingview_krx_unix_and_iso_exports():
    krx = "time,open,high,low,close,Volume\n1704153600,78200,79800,78200,79600,17142847\n"
    assert D.read_bars_csv(io.StringIO(krx)).index[0] == pd.Timestamp("2024-01-02")   # 09:00 KST
    iso = ("time,open,high,low,close,Volume\n2024-01-03T09:00:00+09:00,1,2,0.5,1.5,10\n"
           "2024-01-02T14:30:00Z,1,2,0.5,1.5,10\n")
    df = D.read_bars_csv(io.StringIO(iso))
    assert [d.strftime("%Y-%m-%d") for d in df.index] == ["2024-01-02", "2024-01-03"]   # sorted


def test_generic_csv_case_insensitive_uses_close_not_adj_close():
    csv = ("DATE,OPEN,HIGH,LOW,CLOSE,ADJ CLOSE,VOLUME\n"
           "2024-01-03,10,11,9,10.5,9.9,100\n2024-01-02,9,10,8,9.5,8.9,\n2024-01-03,10,11,9,10.6,9.9,120\n")
    df = D.read_bars_csv(io.StringIO(csv))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03"]
    assert df["close"].tolist() == [9.5, 10.6]                   # duplicate date keeps the last row
    assert np.isnan(df["volume"].iloc[0])
    b = D.read_bars_csv(io.StringIO("Date,Close\n2024-01-02,4700.5\n"), require_ohlc=False)
    assert list(b.columns) == ["close"] and b["close"].iloc[0] == 4700.5


def test_csv_without_volume_column_and_roundtrip(tmp_path):
    df = D.read_bars_csv(io.StringIO("date,open,high,low,close\n2024-01-02,1,2,0.5,1.5\n"))
    assert np.isnan(df["volume"].iloc[0])
    D.write_bars_csv(df, tmp_path / "X.csv")
    back = D.read_bars_csv(tmp_path / "X.csv")
    pd.testing.assert_frame_equal(df, back)


def test_offline_dir_and_benchmark_name(tmp_path):
    (tmp_path / "AAPL.csv").write_text(TV_UNIX)
    (tmp_path / "GSPC.csv").write_text("date,close\n2024-01-02,4700\n")
    (tmp_path / "BAD.csv").write_text("foo,bar\n1,2\n")
    frames, failed = D.load_offline_dir(tmp_path, exclude=["^GSPC"])
    assert set(frames) == {"AAPL"} and failed == ["BAD"]
    assert D.find_offline_csv(tmp_path, "^GSPC").name == "GSPC.csv"


# --- Yahoo download ------------------------------------------------------------------

def _yf_frame(tickers, dates):
    cols = pd.MultiIndex.from_product([tickers, ["Adj Close", "Close", "High", "Low", "Open", "Volume"]],
                                      names=["Ticker", "Price"])
    df = pd.DataFrame(index=pd.DatetimeIndex(dates, name="Date"), columns=cols, dtype=float)
    for k, t in enumerate(tickers):
        base = 100.0 + k
        df[(t, "Open")] = base
        df[(t, "High")] = base + 2
        df[(t, "Low")] = base - 2
        df[(t, "Close")] = base + 1
        df[(t, "Adj Close")] = base - 50          # must never be used
        df[(t, "Volume")] = 1000.0
    return df


class FakeYF:
    def __init__(self, missing=(), fail_first=False):
        self.calls = []
        self.missing = set(missing)
        self.fail_first = fail_first

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail_first and len(self.calls) == 1:
            raise ConnectionError("boom")
        t = kw["tickers"]
        tickers = [t] if isinstance(t, str) else list(t)
        dates = pd.bdate_range(kw["start"], pd.Timestamp(kw["end"]) - pd.Timedelta(days=1))
        present = [x for x in tickers if x not in self.missing]
        df = _yf_frame(present, dates)
        for x in tickers:
            if x in self.missing:                  # yfinance leaves all-NaN columns for failures
                for f in ["Adj Close", "Close", "High", "Low", "Open", "Volume"]:
                    df[(x, f)] = np.nan
        return df


def test_download_chunks_retries_failures_and_cache(tmp_path, monkeypatch):
    fake = FakeYF(missing={"DEAD"}, fail_first=True)
    monkeypatch.setattr(D, "_yf_download", fake)
    monkeypatch.setattr(D, "_sleep", lambda s: None)
    now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    frames, failed = D.download_yahoo(["AAA", "BBB", "DEAD"], "2024-01-02", "2024-01-31",
                                      cache_dir=tmp_path, chunk_size=2, retries=3, now=now)
    assert failed == ["DEAD"] and set(frames) == {"AAA", "BBB"}
    a = frames["AAA"]
    assert a["close"].iloc[0] == 101.0 and a["open"].iloc[0] == 100.0     # Close, not Adj Close
    assert a.index[-1] == pd.Timestamp("2024-01-31")                     # end inclusive
    assert fake.calls[0]["auto_adjust"] is False and fake.calls[0]["end"] == "2024-02-01"
    # chunk 1 (AAA, BBB): attempt 1 raises, attempt 2 ok; chunk 2 (DEAD): 3 attempts
    assert len(fake.calls) == 2 + 3
    # second run is served from the cache (fetched after the window closed)
    fake2 = FakeYF()
    monkeypatch.setattr(D, "_yf_download", fake2)
    frames2, failed2 = D.download_yahoo(["AAA", "BBB"], "2024-01-05", "2024-01-20", cache_dir=tmp_path, now=now)
    assert fake2.calls == [] and failed2 == []
    assert frames2["AAA"].index[0] == pd.Timestamp("2024-01-05")
    # a wider window is not covered -> refetch
    D.download_yahoo(["AAA"], "2023-12-01", "2024-01-20", cache_dir=tmp_path, now=now)
    assert len(fake2.calls) == 1


def test_download_single_ticker_and_stale_cache(tmp_path, monkeypatch):
    fake = FakeYF()
    monkeypatch.setattr(D, "_yf_download", fake)
    t0 = datetime(2024, 1, 31, 12, tzinfo=timezone.utc)                  # same day as `end`
    D.download_yahoo(["^GSPC"], "2024-01-02", "2024-01-31", cache_dir=tmp_path, now=t0)
    assert fake.calls[0]["tickers"] == "^GSPC"
    D.download_yahoo(["^GSPC"], "2024-01-02", "2024-01-31", cache_dir=tmp_path,
                     now=datetime(2024, 1, 31, 15, tzinfo=timezone.utc))
    assert len(fake.calls) == 1                                           # fresh (< 12h)
    D.download_yahoo(["^GSPC"], "2024-01-02", "2024-01-31", cache_dir=tmp_path,
                     now=datetime(2024, 2, 1, 6, tzinfo=timezone.utc))
    assert len(fake.calls) == 2                                           # stale, window was open


# --- unconfirmed bar guard -----------------------------------------------------------

@pytest.mark.parametrize("market,now,dropped", [
    ("SP500", datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc), True),    # 15:00 ET
    ("SP500", datetime(2026, 9, 25, 20, 30, tzinfo=timezone.utc), False),  # 16:30 ET
    ("KOSPI", datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc), True),     # 14:00 KST
    ("KOSDAQ", datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc), False),   # 16:00 KST
    ("CRYPTO", datetime(2026, 9, 25, 23, 0, tzinfo=timezone.utc), True),
    ("CRYPTO", datetime(2026, 9, 26, 0, 5, tzinfo=timezone.utc), False),
])
def test_drop_unconfirmed_last_bar(market, now, dropped):
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-24", "2026-09-25"]))
    out, flag = D.drop_unconfirmed_last_bar(df, market, now=now)
    assert flag is dropped and len(out) == (1 if dropped else 2)


# --- universes -------------------------------------------------------------------------

class Resp:
    def __init__(self, text=None, js=None):
        self.text = text
        self._js = js

    def json(self):
        return self._js


def _html_table(col, symbols):
    rows = "".join(f"<tr><td>{s}</td><td>Co {s}</td></tr>" for s in symbols)
    return f"<html><body><table><tr><th>{col}</th><th>Security</th></tr>{rows}</table></body></html>"


def test_fetch_sp500_normalizes_tickers(monkeypatch):
    syms = ["AAPL", "BRK.B", "BF.B"] + [f"T{i}" for i in range(500)]
    seen = []
    monkeypatch.setattr(D, "_http_get", lambda url, **kw: seen.append(url) or Resp(_html_table("Symbol", syms)))
    got = D.fetch_sp500()
    assert seen == [D.WIKI_SP500]
    assert got[:3] == ["AAPL", "BRK-B", "BF-B"] and len(got) == 503


def test_fetch_ndx100_ticker_column(monkeypatch):
    small = "<table><tr><th>Ticker</th></tr><tr><td>X</td></tr></table>"   # wrong-size table is skipped
    syms = [f"N{i}" for i in range(101)]
    monkeypatch.setattr(D, "_http_get", lambda url, **kw: Resp(small + _html_table("Ticker", syms)))
    got = D.fetch_ndx100()
    assert len(got) == 101 and got[0] == "N0"


def test_fetch_krx_top_by_marcap(monkeypatch):
    listing = pd.DataFrame({
        "Code": [5930, "005935", "000660", "373220", "123450", "999990"],
        "Name": ["삼성전자", "삼성전자우", "SK하이닉스", "LG에너지솔루션", "미래스팩1호", "작은회사"],
        "Marcap": [400e12, 50e12, 100e12, 90e12, 1e11, 5e10],
        "Dept": ["", "", "", "", "", ""], "MarketId": ["STK"] * 6,
    })
    calls = []
    monkeypatch.setattr(D, "_fdr_stock_listing", lambda m: calls.append(m) or listing)
    assert D.fetch_krx_top("KOSPI", 3) == ["005930.KS", "000660.KS", "373220.KS"]
    assert calls == ["KOSPI"]
    got = D.fetch_krx_top("KOSDAQ", 10)
    assert got == ["005930.KQ", "000660.KQ", "373220.KQ", "999990.KQ"]     # preferred + SPAC dropped


def test_fetch_crypto_top_excludes_stablecoins(monkeypatch):
    coins = [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1},
        {"id": "tether", "symbol": "usdt", "name": "Tether", "market_cap_rank": 3},
        {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "market_cap_rank": 2},
        {"id": "usd-coin", "symbol": "usdc", "name": "USDC", "market_cap_rank": 5},
        {"id": "staked-ether", "symbol": "steth", "name": "Lido Staked Ether", "market_cap_rank": 6},
        {"id": "sui", "symbol": "sui", "name": "Sui", "market_cap_rank": 7},
        {"id": "ethena-usde", "symbol": "usde", "name": "Ethena USDe", "market_cap_rank": 8},
        {"id": "wrapped-bitcoin", "symbol": "wbtc", "name": "Wrapped Bitcoin", "market_cap_rank": 9},
        {"id": "solana", "symbol": "sol", "name": "Solana", "market_cap_rank": 4},
        {"id": "tether-gold", "symbol": "xaut", "name": "Tether Gold", "market_cap_rank": 10},
        {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin", "market_cap_rank": 11},
    ]
    seen = {}
    monkeypatch.setattr(D, "_http_get", lambda url, params=None, **kw: seen.update(url=url, params=params) or Resp(js=coins))
    assert D.fetch_crypto_top(4) == ["BTC-USD", "ETH-USD", "SOL-USD", "SUI20947-USD"]
    assert seen["url"] == D.COINGECKO_MARKETS and seen["params"]["order"] == "market_cap_desc"
    assert D.fetch_crypto_top(10, exclude_wrapped=False) == ["BTC-USD", "ETH-USD", "SOL-USD", "STETH-USD",
                                                             "SUI20947-USD", "WBTC-USD", "DOGE-USD"]


def test_fetch_universe_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(D, "fetch_ndx100", lambda: calls.append(1) or ["AAPL", "MSFT"])
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    assert D.fetch_universe("NDX100", cache_dir=tmp_path, now=now) == ["AAPL", "MSFT"]
    assert D.fetch_universe("NDX", cache_dir=tmp_path, now=now) == ["AAPL", "MSFT"]
    assert len(calls) == 1
    later = datetime(2026, 10, 5, tzinfo=timezone.utc)
    D.fetch_universe("NDX100", cache_dir=tmp_path, now=later)
    assert len(calls) == 2
    assert json.loads((tmp_path / "universe" / "NDX100.json").read_text())["tickers"] == ["AAPL", "MSFT"]


def test_universe_file_and_benchmarks(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("AAPL, MSFT\n# comment\nNVDA # trailing\nAAPL\n")
    assert D.read_universe_file(p) == ["AAPL", "MSFT", "NVDA"]
    assert [D.benchmark_ticker(m) for m in ("SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO")] == \
        ["^GSPC", "^NDX", "^KS11", "^KQ11", "BTC-USD"]


# --- review regressions: confirmed bars, cache, bad rows, dates, tickers, KRX codes -----

class FormingYF:
    """Yahoo mock: bars up to `upto`; the bar dated `forming` carries `last` = (close, volume)."""

    def __init__(self, upto, forming=None, last=(100.5, 1e5), upper=False):
        self.upto, self.forming, self.last, self.upper, self.calls = pd.Timestamp(upto), forming, last, upper, 0

    def __call__(self, **kw):
        self.calls += 1
        t = kw["tickers"]
        tickers = [t] if isinstance(t, str) else list(t)
        if self.upper:                                   # yfinance upper-cases every symbol
            tickers = [x.upper() for x in tickers]
        stop = min(self.upto, pd.Timestamp(kw["end"]) - pd.Timedelta(days=1))
        df = _yf_frame(tickers, pd.bdate_range(kw["start"], stop))
        if self.forming is not None and pd.Timestamp(self.forming) in df.index:
            for x in tickers:
                df.loc[pd.Timestamp(self.forming), (x, "Close")] = self.last[0]
                df.loc[pd.Timestamp(self.forming), (x, "Volume")] = self.last[1]
        return df


def test_cache_never_serves_an_intraday_bar_as_the_close(tmp_path, monkeypatch):
    # 10:00 ET: Yahoo returns the forming 9/25 bar (close 100.5). It must not be cached.
    fake = FormingYF("2026-09-25", forming="2026-09-25", last=(100.5, 1e5))
    monkeypatch.setattr(D, "_yf_download", fake)
    morning = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
    fr, _ = D.download_yahoo(["AAA"], "2026-09-01", "2026-09-25", cache_dir=tmp_path, now=morning, market="SP500")
    assert fr["AAA"]["close"].iloc[-1] == 100.5                       # raw result; callers drop it
    assert D.drop_unconfirmed_last_bar(fr["AAA"], "SP500", now=morning)[1] is True
    meta = json.loads((tmp_path / "yahoo" / "AAA.json").read_text())
    assert meta["last_date"] == "2026-09-24" and meta["v"] == D.CACHE_VERSION
    # 16:45 ET, same day: the session has closed since the fetch -> refetch the final bar
    fake.last = (110.0, 5e6)
    evening = datetime(2026, 9, 25, 20, 45, tzinfo=timezone.utc)
    fr, _ = D.download_yahoo(["AAA"], "2026-09-01", "2026-09-25", cache_dir=tmp_path, now=evening, market="SP500")
    assert fake.calls == 2
    bars, dropped = D.drop_unconfirmed_last_bar(fr["AAA"], "SP500", now=evening)
    assert not dropped and bars.index[-1] == pd.Timestamp("2026-09-25")
    assert (bars["close"].iloc[-1], bars["volume"].iloc[-1]) == (110.0, 5e6)
    # fetched after the close: the cache is complete for this window and is reused
    fr, _ = D.download_yahoo(["AAA"], "2026-09-01", "2026-09-25", cache_dir=tmp_path,
                             now=datetime(2026, 9, 25, 23, 0, tzinfo=timezone.utc), market="SP500")
    assert fake.calls == 2 and fr["AAA"]["close"].iloc[-1] == 110.0


def test_cache_from_before_the_open_is_refetched_after_the_close(tmp_path, monkeypatch):
    # KOSPI: fetch at 08:00 KST 9/25 (no 9/25 bar yet), rerun at 17:05 KST the same day
    fake = FormingYF("2026-09-24")
    monkeypatch.setattr(D, "_yf_download", fake)
    D.download_yahoo(["005930.KS"], "2026-09-01", "2026-09-25", cache_dir=tmp_path,
                     now=datetime(2026, 9, 24, 23, 0, tzinfo=timezone.utc), market="KOSPI")
    fake.upto = pd.Timestamp("2026-09-25")
    fr, _ = D.download_yahoo(["005930.KS"], "2026-09-01", "2026-09-25", cache_dir=tmp_path,
                             now=datetime(2026, 9, 25, 8, 5, tzinfo=timezone.utc), market="KOSPI")
    assert fake.calls == 2 and fr["005930.KS"].index[-1] == pd.Timestamp("2026-09-25")


def test_legacy_cache_without_version_is_ignored(tmp_path, monkeypatch):
    fake = FormingYF("2026-09-24")
    monkeypatch.setattr(D, "_yf_download", fake)
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    D.download_yahoo(["AAA"], "2026-09-01", "2026-09-24", cache_dir=tmp_path, now=now)
    meta_p = tmp_path / "yahoo" / "AAA.json"
    meta = json.loads(meta_p.read_text())
    del meta["v"]                                     # written by the old code (may hold a forming bar)
    meta_p.write_text(json.dumps(meta))
    D.download_yahoo(["AAA"], "2026-09-01", "2026-09-24", cache_dir=tmp_path, now=now)
    assert fake.calls == 2


def test_zero_and_nan_price_rows_are_dropped_for_symbols_not_benchmarks(monkeypatch):
    dates = pd.bdate_range("2026-09-21", "2026-09-25")

    def fake(**kw):
        df = _yf_frame(["AAA", "^GSPC"], dates)
        for t in ("AAA", "^GSPC"):
            df.loc[dates[2], [(t, "Open"), (t, "High"), (t, "Low"), (t, "Volume")]] = 0.0   # halted day
            df.loc[dates[3], (t, "Open")] = np.nan
        df.loc[dates[4], ("AAA", "High")] = 100.5          # below the close (101): widened
        return df
    monkeypatch.setattr(D, "_yf_download", fake)
    fr, failed = D.download_yahoo(["AAA", "^GSPC"], dates[0], dates[-1], close_only=["^GSPC"],
                                  now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert failed == []
    a, b = fr["AAA"], fr["^GSPC"]
    assert list(a.index) == [dates[0], dates[1], dates[4]]           # TradingView prints no bar there
    assert a["high"].iloc[-1] == 101.0 and (a[["open", "high", "low", "close"]] > 0).all().all()
    assert list(b.index) == list(dates) and b["close"].notna().all()  # benchmark only needs the close
    assert np.isnan(b.loc[dates[2], "open"])                          # zero price -> NaN, row kept
    # a zero low would otherwise trigger a -100% stop in the state machine
    from swing_engine.state import PositionMachine
    m = PositionMachine(stop_pct=7.0)
    m.entry_price, m.stop_price = 100.0, 93.0
    for d, r in a.iterrows():
        assert m.check_exit(d, r.open, r.low, r.close, 0.0) is None


def test_csv_loader_drops_zero_and_nan_price_rows():
    csv = ("date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,100\n2024-01-03,0,0,0,10.5,0\n"
           "2024-01-04,,11,9,10.4,100\n2024-01-05,10,10.2,9,10.6,100\n2024-01-08,10,11,9,-1,100\n")
    df = D.read_bars_csv(io.StringIO(csv))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-05"]
    assert df["high"].iloc[-1] == 10.6                                # widened to the close
    b = D.read_bars_csv(io.StringIO(csv), require_ohlc=False)
    assert list(b.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]


def test_csv_integer_yyyymmdd_dates():
    csv = ("Date,Open,High,Low,Close,Volume\n20240102,1,2,0.5,1.5,10\n20240103,1,2,0.5,1.6,10\n"
           "20240104,1,2,0.5,1.7,10\n")
    df = D.read_bars_csv(io.StringIO(csv))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert df["close"].tolist() == [1.5, 1.6, 1.7]
    with pytest.raises(ValueError, match="same day|days"):         # Excel serials read as seconds collide
        D.read_bars_csv(io.StringIO("Date,Open,High,Low,Close\n45293,1,2,0.5,1.5\n45294,1,2,0.5,1.6\n"))


def test_lowercase_tickers_match_yfinance_uppercased_columns(monkeypatch):
    dates = pd.bdate_range("2024-01-02", "2024-01-05")
    got = D._split_download(_yf_frame(["AAPL", "^GSPC"], dates), ["aapl", "^gspc"])
    assert set(got) == {"aapl", "^gspc"} and got["aapl"]["close"].iloc[0] == 101.0
    fake = FormingYF("2024-01-05", upper=True)
    monkeypatch.setattr(D, "_yf_download", fake)
    monkeypatch.setattr(D, "_sleep", lambda s: None)
    fr, failed = D.download_yahoo(["aapl", "^GSPC"], "2024-01-02", "2024-01-05",
                                  now=datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert failed == [] and set(fr) == {"aapl", "^GSPC"} and fake.calls == 1
    fr, failed = D.download_yahoo(["msft"], "2024-01-02", "2024-01-05", now=datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert failed == [] and set(fr) == {"msft"}


@pytest.mark.parametrize("ticker,now,dropped", [
    ("BTC-USD", datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc), True),     # UTC day not over
    ("BTC-USD", datetime(2026, 9, 26, 0, 5, tzinfo=timezone.utc), False),
    ("005930.KS", datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc), False),   # 16:00 KST, closed
    ("005930.KS", datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc), True),    # 14:00 KST
    ("AAPL", datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc), True),        # 15:00 ET
    ("AAPL", datetime(2026, 9, 25, 20, 30, tzinfo=timezone.utc), False),      # 16:30 ET
    ("7203.T", datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc), True),      # unknown: UTC day
    ("7203.T", datetime(2026, 9, 26, 0, 5, tzinfo=timezone.utc), False),
    (None, datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc), True),
])
def test_custom_preset_session_follows_the_ticker(ticker, now, dropped):
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-24", "2026-09-25"]))
    out, flag = D.drop_unconfirmed_last_bar(df, "CUSTOM", now=now, ticker=ticker)
    assert flag is dropped and len(out) == (1 if dropped else 2)


def test_fetch_krx_top_keeps_letter_coded_common_stocks(monkeypatch):
    listing = pd.DataFrame({
        "Code": ["005930", "0126Z0", "00680K", "0220WL", "0015G0", "000660"],
        "Name": ["삼성전자", "삼성에피스홀딩스", "미래에셋증권2우B", "어떤회사우", "하나스팩40호", "SK하이닉스"],
        "Marcap": [400e12, 8.21e12, 3e12, 2e12, 1e11, 100e12],
        "Dept": [""] * 6, "MarketId": ["STK"] * 6,
    })
    monkeypatch.setattr(D, "_fdr_stock_listing", lambda m: listing)
    assert D.fetch_krx_top("KOSPI", 10) == ["005930.KS", "000660.KS", "0126Z0.KS"]
