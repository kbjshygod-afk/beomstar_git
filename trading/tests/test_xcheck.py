"""Yahoo vs KRX cross-check (checklist 1.5): parsing, comparison, the ledger record, no network."""
import json

import pandas as pd
import pytest

from swing_engine import krx, xcheck


def _bars(close, vol, dates=("2026-10-28", "2026-10-29")):
    idx = pd.to_datetime(list(dates))
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": vol}, index=idx)


def _krx_rows(symbol_code, close, vol):
    return [{"BAS_DD": "20261028", "ISU_CD": symbol_code, "ISU_NM": "x", "TDD_OPNPRC": f"{close:,}",
             "TDD_HGPRC": f"{close:,}", "TDD_LWPRC": f"{close:,}", "TDD_CLSPRC": f"{close:,}", "ACC_TRDVOL": f"{vol:,}"}]


def test_krx_parsing_and_symbol_mapping(monkeypatch):
    monkeypatch.setattr(krx, "fetch_rows", lambda service, date, key, **kw: _krx_rows("KR7096530003", 36250, 1234567))
    df = krx.stock_bars("KOSDAQ", "20261028", "k")
    assert list(df.index) == ["096530.KQ"] and df.loc["096530.KQ", "close"] == 36250 and df.loc["096530.KQ", "volume"] == 1234567
    monkeypatch.setattr(krx, "fetch_rows", lambda service, date, key, **kw: [{"IDX_NM": "코스닥 150", "CLSPRC_IDX": "1,000.5"},
                                                                             {"IDX_NM": "코스닥", "CLSPRC_IDX": "753.23", "ACC_TRDVOL": "-"}])
    bar = krx.index_bar("KOSDAQ", "20261028", "k")
    assert bar["close"] == 753.23 and bar["volume"] is None


def test_cache_keeps_non_empty_answers_only(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(krx, "fetch_rows", lambda service, date, key, **kw: calls.append(date) or
                        (_krx_rows("096530", 1, 1) if date == "20261028" else []))
    krx.stock_bars("KOSDAQ", "20261028", "k", tmp_path)
    krx.stock_bars("KOSDAQ", "20261028", "k", tmp_path)      # cached
    krx.stock_bars("KOSDAQ", "20261029", "k", tmp_path)      # empty: asked again next time
    krx.stock_bars("KOSDAQ", "20261029", "k", tmp_path)
    assert calls == ["20261028", "20261029", "20261029"]
    assert (tmp_path / "krx" / "sto_ksq_bydd_trd_20261028.json").exists()


def test_compare_flags_only_differences_over_tolerance():
    y = pd.DataFrame({"close": [36250.0, 10000.0], "volume": [1000.0, 2000.0]}, index=["A.KQ", "B.KQ"])
    ex = pd.DataFrame({"close": [36250.0, 10000.0], "volume": [1005.0, 2100.0]}, index=["A.KQ", "C.KQ"])
    r = xcheck.compare_bars(y, ex, pd.Timestamp("2026-10-28"))
    assert r["compared"] == 1 and r["missing"] == ["B.KQ"]
    assert r["mismatches"] == []                               # 0.5% volume is within 1%
    ex.loc["A.KQ", "volume"] = 1022                            # 2.2%: the 10-06 kind of revision
    r = xcheck.compare_bars(y, ex, pd.Timestamp("2026-10-28"))
    assert [(m["symbol"], m["field"]) for m in r["mismatches"]] == [("A.KQ", "volume")]


def test_run_checks_the_previous_session_when_as_of_is_unpublished(monkeypatch):
    frames = {"096530.KQ": _bars([36000.0, 36250.0], [1000.0, 1100.0])}
    bench = _bars([750.0, 753.23], [0.0, 0.0])
    def rows(service, date, key, **kw):
        if date != "20261028":
            return []                                           # T-1 rule: 10-29 not published yet
        if service.startswith("sto"):
            return _krx_rows("096530", 36000, 1030)             # volume revised +3%
        return [{"IDX_NM": "코스닥", "CLSPRC_IDX": "750", "ACC_TRDVOL": "1"}]
    monkeypatch.setattr(krx, "fetch_rows", rows)
    rec = xcheck.run("KOSDAQ", frames, bench, pd.Timestamp("2026-10-29"), "k")
    assert rec["status"] == "mismatch" and rec["checked"] == "2026-10-28"
    assert rec["index"]["match"] is True
    assert rec["symbols"]["mismatches"][0]["field"] == "volume"
    line = xcheck.summary_line(rec)
    assert "2026-10-28 봉" in line and "096530.KQ volume" in line and "지수 일치" in line
    json.dumps(rec)                                             # serialisable as written


def test_run_records_errors_instead_of_raising(monkeypatch):
    def boom(service, date, key, **kw):
        raise krx.KRXError("HTTP 401 (key rejected or service not approved)")
    monkeypatch.setattr(krx, "fetch_rows", boom)
    rec = xcheck.run("KOSPI", {}, _bars([1.0, 2.0], [0.0, 0.0]), pd.Timestamp("2026-10-29"), "k")
    assert rec["status"] == "error" and "401" in rec["error"]
    assert "실패" in xcheck.summary_line(rec)


def test_fetch_rows_falls_back_to_query_auth_on_401(monkeypatch):
    import urllib.error
    seen = []
    def req(url, headers, timeout):
        seen.append((url.split("?")[1], "AUTH_KEY" in headers))
        if "AUTH_KEY" in headers:
            raise urllib.error.HTTPError(url, 401, "no", {}, None)
        return 200, b'{"OutBlock_1": [{"a": 1}]}'
    monkeypatch.setattr(krx, "_request", req)
    assert krx.fetch_rows("sto/ksq_bydd_trd", "20261028", "k k") == [{"a": 1}]
    assert seen == [("basDd=20261028", True), ("basDd=20261028&AUTH_KEY=k%20k", False)]
    def deny(url, headers, timeout):
        raise urllib.error.HTTPError(url, 401, "no", {}, None)
    monkeypatch.setattr(krx, "_request", deny)
    with pytest.raises(krx.KRXError, match="401"):
        krx.fetch_rows("sto/ksq_bydd_trd", "20261028", "k")
