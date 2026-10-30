"""Tiingo end-of-day cross-check (checklist 3.3-3.4): parsing, the rotating sample, caching and the record."""
import json
import urllib.error

import pandas as pd
import pytest

from swing_engine import tiingo, xcheck

ROWS = [{"date": "2026-10-29T00:00:00.000Z", "open": 100.5, "high": 102.0, "low": 99.75, "close": 101.25,
         "volume": 1234567, "adjClose": 101.25, "divCash": 0.0, "splitFactor": 1.0}]


def test_frame_keeps_raw_columns_only():
    df = tiingo.frame(ROWS)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.loc[pd.Timestamp("2026-10-29"), "close"] == 101.25 and len(tiingo.frame([])) == 0


def test_fetch_bars_sends_the_token_header_and_maps_404_to_none(monkeypatch):
    seen = {}
    def req(url, headers, timeout):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        return 200, json.dumps(ROWS).encode()
    monkeypatch.setattr(tiingo, "_request", req)
    monkeypatch.setattr(tiingo.time, "sleep", lambda s: None)
    df = tiingo.fetch_bars("BRK-B", "2026-10-29", "2026-10-29", "tok123")
    assert seen["auth"] == "Token tok123" and "/tiingo/daily/BRK-B/prices?startDate=2026-10-29" in seen["url"]
    assert "tok123" not in seen["url"] and len(df) == 1
    def nf(url, headers, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(tiingo, "_request", nf)
    assert tiingo.fetch_bars("NOPE", "2026-10-29", "2026-10-29", "t") is None
    def rl(url, headers, timeout):
        raise urllib.error.HTTPError(url, 429, "Too Many", {}, None)
    monkeypatch.setattr(tiingo, "_request", rl)
    with pytest.raises(tiingo.TiingoError, match="HTTP 429"):
        tiingo.fetch_bars("AAPL", "2026-10-29", "2026-10-29", "t")


def test_sample_rotates_daily_and_always_includes_the_focus():
    syms = [f"S{i:02d}" for i in range(50)]
    a = tiingo.sample(syms, pd.Timestamp("2026-10-29"), 10, always=["S07", "ZZZ"])
    b = tiingo.sample(syms, pd.Timestamp("2026-10-30"), 10, always=["S07"])
    assert "S07" in a and "ZZZ" not in a and len(a) in (10, 11) and a == sorted(set(a))
    assert a != b and a == tiingo.sample(syms, pd.Timestamp("2026-10-29"), 10, always=["S07", "ZZZ"])
    # five consecutive days cover the whole 50-symbol pool
    seen = set()
    for i in range(5):
        seen |= set(tiingo.sample(syms, pd.Timestamp("2026-11-01") + pd.Timedelta(days=i), 10))
    assert seen == set(syms)


def test_bars_on_caches_published_days_and_records_unlisted(tmp_path, monkeypatch):
    calls = []
    def fetch(sym, start, end, tok, timeout=30):
        calls.append(sym)
        if sym == "GONE":
            return None
        if sym == "LATE":
            return tiingo.frame([])
        return tiingo.frame(ROWS)
    monkeypatch.setattr(tiingo, "fetch_bars", fetch)
    d = pd.Timestamp("2026-10-29")
    df = tiingo.bars_on("SP500", ["AAPL", "GONE", "LATE"], d, "t", tmp_path)
    assert list(df.index) == ["AAPL"] and df.attrs["unlisted"] == ["GONE"] and df.attrs["missing"] == ["LATE"]
    assert df.attrs["calls"] == 3 and (tmp_path / "tiingo" / "SP500_2026-10-29.json").exists()
    df2 = tiingo.bars_on("SP500", ["AAPL", "GONE", "MSFT"], d, "t", tmp_path)    # only MSFT is new
    assert calls == ["AAPL", "GONE", "LATE", "MSFT"] and sorted(df2.index) == ["AAPL", "MSFT"] and df2.attrs["calls"] == 1
    # an unpublished day (no bar at all) is not cached, so it is asked again later
    monkeypatch.setattr(tiingo, "fetch_bars", lambda *a, **k: tiingo.frame([]))
    e = tiingo.bars_on("SP500", ["AAPL"], pd.Timestamp("2026-10-30"), "t", tmp_path)
    assert len(e) == 0 and not (tmp_path / "tiingo" / "SP500_2026-10-30.json").exists()


def test_run_tiingo_falls_back_to_the_previous_session_and_compares(monkeypatch):
    idx = pd.to_datetime(["2026-10-28", "2026-10-29"])
    frames = {"AAPL": pd.DataFrame({"open": [1, 100.5], "high": [1, 102.0], "low": [1, 99.75], "close": [1, 101.25],
                                    "volume": [1, 1250000.0]}, index=idx),
              "MSFT": pd.DataFrame({"open": [1, 1.0], "high": [1, 1.0], "low": [1, 1.0], "close": [1, 1.0],
                                    "volume": [1, 1.0]}, index=idx)}
    bench = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    asked = []
    def bars_on(market, symbols, date, tok, cache_dir=None):
        asked.append((date.strftime("%Y-%m-%d"), sorted(symbols)))
        df = pd.DataFrame.from_dict({"AAPL": {"open": 100.5, "high": 102.0, "low": 99.75, "close": 101.25, "volume": 1234567.0}},
                                    orient="index") if date == idx[1] else pd.DataFrame(columns=list(tiingo.COLS))
        df.attrs.update(missing=[], unlisted=["MSFT"] if len(df) else [], calls=len(symbols))
        return df
    monkeypatch.setattr(tiingo, "bars_on", bars_on)
    rec = xcheck.run_tiingo("SP500", frames, bench, pd.Timestamp("2026-10-30"), "t", focus=["AAPL"])
    assert asked[0][0] == "2026-10-30" and asked[1][0] == "2026-10-29" and asked[1][1] == ["AAPL", "MSFT"]
    assert rec["source"] == "Tiingo" and rec["checked"] == "2026-10-29" and rec["status"] == "mismatch"
    assert [(m["symbol"], m["field"]) for m in rec["symbols"]["mismatches"]] == [("AAPL", "volume")]   # 1.25%
    assert rec["symbols"]["unlisted"] == ["MSFT"] and rec["symbols"]["focus"] == ["AAPL"] and rec["index"] is None
    line = xcheck.summary_line(rec)
    assert line.startswith("- 데이터 대조 (Tiingo, 2026-10-29 봉): 종목 1개 비교 (표본 2: 보유·대기 1 + 순환)") and "지수 비교 안 함" in line
    json.dumps(rec)
    def boom(*a, **k):
        raise tiingo.TiingoError("AAPL: HTTP 429 rate limited")
    monkeypatch.setattr(tiingo, "bars_on", boom)
    err = xcheck.run_tiingo("SP500", frames, bench, pd.Timestamp("2026-10-30"), "t")
    assert err["status"] == "error" and "429" in err["error"]
