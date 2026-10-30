"""KIS Open API client and cross-check (checklist 2.4): token caching, headers, parsing, limits."""
import json
import urllib.error

import pandas as pd
import pytest

from swing_engine import kis, xcheck

CRED = {"key": "APPKEY1234", "secret": "S", "env": "vps"}
TOKEN_OK = json.dumps({"access_token": "tok-1", "access_token_token_expired": "2099-01-01 09:00:00"}).encode()


def _stock_body(date="20261030", close="33600"):
    return json.dumps({"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok", "output1": {},
                       "output2": [{"stck_bsop_date": date, "stck_oprc": "33,800", "stck_hgpr": "33900",
                                    "stck_lwpr": "32250", "stck_clpr": close, "acml_vol": "302497"}]}).encode()


def _index_body(date="20261030", close="753.23"):
    return json.dumps({"rt_cd": "0", "output2": [{"stck_bsop_date": date, "bstp_nmix_oprc": "767.78", "bstp_nmix_hgpr": "768.75",
                                                   "bstp_nmix_lwpr": "741.96", "bstp_nmix_prpr": close, "acml_vol": "491936047"}]}).encode()


def test_credentials_from_env(monkeypatch):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    assert kis.credentials() is None
    monkeypatch.setenv("KIS_APP_KEY", "k ")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.delenv("KIS_ENV", raising=False)
    assert kis.credentials() == {"key": "k", "secret": "s", "env": "vps"}
    monkeypatch.setenv("KIS_ENV", "nope")
    with pytest.raises(kis.KISError):
        kis.credentials()


def test_token_is_requested_once_and_cached(tmp_path, monkeypatch):
    seen = []
    def req(method, url, headers, body, timeout):
        seen.append((method, url.split("29443")[1], json.loads(body)["appkey"] if body else None))
        return 200, TOKEN_OK
    monkeypatch.setattr(kis, "_request", req)
    c = kis.Client(CRED, tmp_path, min_interval=0)
    assert c.token() == "tok-1" and c.token() == "tok-1"
    c2 = kis.Client(CRED, tmp_path, min_interval=0)                 # a new process: the file serves it
    assert c2.token() == "tok-1"
    assert seen == [("POST", "/oauth2/tokenP", "APPKEY1234")]
    saved = json.loads((tmp_path / "kis" / "token_vps.json").read_text())
    assert saved["key_tail"] == "1234" and saved["expires"].startswith("2099-01-01T00:00")   # 09:00 KST -> 00:00 UTC


def test_stock_and_index_calls_send_the_documented_headers_and_parse(tmp_path, monkeypatch):
    seen = []
    def req(method, url, headers, body, timeout):
        if url.endswith("/oauth2/tokenP"):
            return 200, TOKEN_OK
        seen.append((headers["tr_id"], headers["custtype"], headers["authorization"], headers["appkey"], url))
        return 200, _stock_body() if "itemchartprice" in url else _index_body()
    monkeypatch.setattr(kis, "_request", req)
    c = kis.Client(CRED, tmp_path, min_interval=0)
    bars = c.stock_bars("096530", "20261030", "20261030")
    assert list(bars.index) == [pd.Timestamp("2026-10-30")]
    assert bars.iloc[0].to_dict() == {"open": 33800.0, "high": 33900.0, "low": 32250.0, "close": 33600.0, "volume": 302497.0}
    idx = c.index_bars("KOSDAQ", "20261030", "20261030")
    assert idx.loc[pd.Timestamp("2026-10-30"), "close"] == 753.23
    assert seen[0][:4] == ("FHKST03010100", "P", "Bearer tok-1", "APPKEY1234")
    assert "FID_ORG_ADJ_PRC=1" in seen[0][4] and "FID_INPUT_ISCD=096530" in seen[0][4]
    assert seen[1][0] == "FHKUP03500100" and "FID_INPUT_ISCD=1001" in seen[1][4] and "FID_COND_MRKT_DIV_CODE=U" in seen[1][4]


def test_rate_limit_is_retried_once_then_raised(tmp_path, monkeypatch):
    n = {"calls": 0}
    def req(method, url, headers, body, timeout):
        if url.endswith("/oauth2/tokenP"):
            return 200, TOKEN_OK
        n["calls"] += 1
        return 200, json.dumps({"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}).encode()
    monkeypatch.setattr(kis, "_request", req)
    monkeypatch.setattr(kis.time, "sleep", lambda s: None)
    c = kis.Client(CRED, tmp_path, min_interval=0)
    with pytest.raises(kis.KISError, match="EGW00201"):
        c.stock_bars("096530", "20261030", "20261030")
    assert n["calls"] == 2


def test_http_error_becomes_kiserror(tmp_path, monkeypatch):
    def req(method, url, headers, body, timeout):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
    monkeypatch.setattr(kis, "_request", req)
    with pytest.raises(kis.KISError, match="token: HTTP 403"):
        kis.Client(CRED, tmp_path).token()


def test_bars_on_maps_symbols_and_caches(tmp_path, monkeypatch):
    calls = []
    class FakeClient:
        calls = 0
        def stock_bars(self, code, start, end):
            calls.append(code)
            if code == "999999":
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [33600.0], "volume": [5.0]},
                                index=pd.to_datetime(["2026-10-30"]))
    d = pd.Timestamp("2026-10-30")
    df = kis.bars_on(FakeClient(), "KOSDAQ", ["096530.KQ", "999999.KQ"], d, tmp_path)
    assert list(df.index) == ["096530.KQ"] and df.loc["096530.KQ", "close"] == 33600.0 and df.attrs["missing"] == ["999999.KQ"]
    df2 = kis.bars_on(FakeClient(), "KOSDAQ", ["096530.KQ", "999999.KQ"], d, tmp_path)
    assert calls == ["096530", "999999"] and df2.attrs["missing"] == ["999999.KQ"]


def test_run_kis_compares_the_signal_day(monkeypatch):
    idx = pd.to_datetime(["2026-10-29", "2026-10-30"])
    frames = {"096530.KQ": pd.DataFrame({"open": [1, 33800.0], "high": [1, 33900.0], "low": [1, 32250.0],
                                         "close": [1, 33600.0], "volume": [1, 302497.0]}, index=idx)}
    bench = pd.DataFrame({"close": [760.0, 753.23]}, index=idx)
    class FakeClient:
        calls = 3
        def __init__(self, cred, cache_dir=None, **kw):
            pass
    def bars_on(client, market, symbols, date, cache_dir=None):
        df = pd.DataFrame({"open": [33800.0], "high": [33900.0], "low": [32250.0], "close": [33600.0], "volume": [310000.0]},
                          index=["096530.KQ"])
        df.attrs["missing"] = []
        return df
    monkeypatch.setattr(kis, "Client", FakeClient)
    monkeypatch.setattr(kis, "bars_on", bars_on)
    monkeypatch.setattr(kis, "index_bar", lambda client, market, date: {"close": 753.23})
    rec = xcheck.run_kis("KOSDAQ", frames, bench, pd.Timestamp("2026-10-30"), CRED)
    assert rec["source"] == "KIS" and rec["checked"] == "2026-10-30" and rec["status"] == "mismatch"
    assert rec["index"]["match"] is True and rec["calls"] == 3
    assert [(m["symbol"], m["field"]) for m in rec["symbols"]["mismatches"]] == [("096530.KQ", "volume")]   # 2.4%
    line = xcheck.summary_line(rec)
    assert line.startswith("- 데이터 대조 (KIS, 2026-10-30 봉)") and "096530.KQ volume" in line and "지수 일치" in line
    json.dumps(rec)
