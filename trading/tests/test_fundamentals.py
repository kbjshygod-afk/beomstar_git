"""Fundamentals: EDGAR frames -> periods, DART rows -> periods, ratios and the page."""
import json
import zipfile
import io

import pytest

from swing_engine import dart, edgar, fundamentals as F


def _facts():
    def flow(concept, vals, unit="USD"):
        rows = []
        for (frame, end, v) in vals:
            y, q = frame[2:6], frame[7:8]
            start = f"{y}-{int(q) * 3 - 2:02d}-01" if q and q.isdigit() else f"{y}-01-01"
            rows.append({"start": start, "end": end, "val": v, "fy": int(end[:4]), "fp": "Q", "form": "10-Q", "frame": frame})
        return {"units": {unit: rows}}
    gaap = {
        "Revenues": flow("Revenues", [("CY2025Q1", "2025-03-31", 100), ("CY2025Q2", "2025-06-30", 110), ("CY2025Q3", "2025-09-30", 120),
                                      ("CY2025", "2025-12-31", 460), ("CY2026Q1", "2026-03-31", 140), ("CY2026Q2", "2026-06-30", 150)]),
        "OperatingIncomeLoss": flow("op", [("CY2025Q1", "2025-03-31", 10), ("CY2025Q2", "2025-06-30", 11), ("CY2025Q3", "2025-09-30", 12),
                                           ("CY2025", "2025-12-31", 50), ("CY2026Q1", "2026-03-31", 16), ("CY2026Q2", "2026-06-30", 18)]),
        "NetIncomeLoss": flow("ni", [("CY2025Q1", "2025-03-31", 8), ("CY2025Q2", "2025-06-30", 9), ("CY2025Q3", "2025-09-30", 9),
                                     ("CY2025", "2025-12-31", 40), ("CY2026Q1", "2026-03-31", 12), ("CY2026Q2", "2026-06-30", 14)]),
        "NetCashProvidedByUsedInOperatingActivities": flow("ocf", [("CY2025Q1", "2025-03-31", 9), ("CY2025Q2", "2025-06-30", 10), ("CY2025Q3", "2025-09-30", 11),
                                                                   ("CY2025", "2025-12-31", 44), ("CY2026Q1", "2026-03-31", 13), ("CY2026Q2", "2026-06-30", 15)]),
        "Assets": flow("a", [("CY2025Q4I", "2025-12-31", 400), ("CY2026Q2I", "2026-06-30", 420)]),
        "Liabilities": flow("l", [("CY2025Q4I", "2025-12-31", 200), ("CY2026Q2I", "2026-06-30", 210)]),
        "StockholdersEquity": flow("e", [("CY2025Q4I", "2025-12-31", 200), ("CY2026Q2I", "2026-06-30", 210)]),
        "EarningsPerShareDiluted": flow("eps", [("CY2026Q2", "2026-06-30", 1.4)], unit="USD/shares"),
    }
    return {"facts": {"us-gaap": gaap, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-07-15", "val": 10}]}}}}}


def test_edgar_periods_derive_q4_and_year_balances():
    ps = edgar.periods_from_facts(_facts())
    by = {p["label"]: p for p in ps}
    assert by["2025Q4"]["revenue"] == 460 - 330 and by["2025Q4"]["net_income"] == 40 - 26 and by["2025Q4"]["ocf"] == 44 - 30
    assert by["FY2025"]["equity"] == 200 and by["2026Q2"]["eps"] == 1.4 and by["2026Q2"]["assets"] == 420
    assert edgar.shares_outstanding(_facts()) == 10
    t = F.ttm(ps)
    assert t["revenue"] == 130 + 140 + 150 + 120 and t["label"] == "TTM 2026Q2"
    r = F.ratios(ps)
    assert round(r["op_margin_ttm_pct"], 2) == round((12 + 17 + 16 + 18) / 540 * 100, 2)
    assert r["revenue_yoy_pct"] == pytest.approx((150 / 110 - 1) * 100) and r["debt_ratio_pct"] == 100.0


def test_edgar_september_fiscal_year_and_concept_merge():
    """Apple-like: fiscal year ends late September, Revenues only in old years, the newer
    concept carries the recent quarters; the 10-K balance sheet is the fiscal year-end one."""
    def rows(vals, unit="USD"):
        return {"units": {unit: [{"start": s, "end": e, "val": v, "frame": f} for (f, s, e, v) in vals]}}
    gaap = {
        "Revenues": rows([("CY2018", "2017-10-01", "2018-09-29", 265.0)]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": rows([
            ("CY2024Q4", "2024-09-29", "2024-12-28", 124.0), ("CY2025Q1", "2024-12-29", "2025-03-29", 95.0),
            ("CY2025Q2", "2025-03-30", "2025-06-28", 94.0), ("CY2025", "2024-09-29", "2025-09-27", 416.0),
            ("CY2025Q4", "2025-09-28", "2025-12-27", 140.0)]),
        "OperatingIncomeLoss": rows([
            ("CY2024Q4", "2024-09-29", "2024-12-28", 42.8), ("CY2025Q1", "2024-12-29", "2025-03-29", 29.6),
            ("CY2025Q2", "2025-03-30", "2025-06-28", 28.2), ("CY2025", "2024-09-29", "2025-09-27", 133.0)]),
        "NetCashProvidedByUsedInOperatingActivities": rows([
            ("CY2024Q4", "2024-09-29", "2024-12-28", 29.9), (None, "2024-09-29", "2025-03-29", 54.0),
            (None, "2024-09-29", "2025-06-28", 81.8), ("CY2025", "2024-09-29", "2025-09-27", 111.5)]),
        "StockholdersEquity": rows([("CY2024Q4I", None, "2024-12-28", 66.8), ("CY2025Q3I", None, "2025-09-27", 73.7),
                                    ("CY2025Q4I", None, "2025-12-27", 88.2)]),
        "Assets": rows([("CY2025Q3I", None, "2025-09-27", 359.0)]),
    }
    ps = edgar.periods_from_facts({"facts": {"us-gaap": gaap}})
    by = {p["label"]: p for p in ps}
    assert by["2025Q1"]["revenue"] == 95.0 and by["FY2018"]["revenue"] == 265.0        # concepts merged
    q4 = by["2025Q3"]                                                                  # fiscal Q4 derived
    assert q4["start"] == "2025-06-29" and q4["end"] == "2025-09-27"
    assert q4["revenue"] == pytest.approx(416.0 - 124.0 - 95.0 - 94.0)
    assert q4["op_income"] == pytest.approx(133.0 - 42.8 - 29.6 - 28.2)
    assert q4["equity"] == 73.7 and by["FY2025"]["equity"] == 73.7 and by["FY2025"]["assets"] == 359.0
    assert by["2025Q1"]["ocf"] == pytest.approx(54.0 - 29.9) and by["2025Q2"]["ocf"] == pytest.approx(81.8 - 54.0)
    assert q4["ocf"] == pytest.approx(111.5 - 81.8)                                   # YTD-differenced quarters feed the Q4
    assert by["2025Q4"]["equity"] == 88.2 and by["2025Q4"]["revenue"] == 140.0
    assert edgar._quarter_label(edgar.date(2025, 9, 28), edgar.date(2026, 1, 2)) == "2025Q4"


def test_edgar_january_fiscal_year_labels_the_fourth_quarter_q4():
    """NVIDIA-like: fiscal year Jan 27 2025 - Jan 25 2026; SEC frames its quarters CY2025Q1..Q3.
    The derived Oct 27 - Jan 25 quarter is CY2025Q4, not 2026Q1 (which the next year's Q1 uses)."""
    def rows(vals):
        return {"units": {"USD": [{"start": s, "end": e, "val": v, "frame": f} for (f, s, e, v) in vals]}}
    gaap = {"Revenues": rows([
        ("CY2025Q1", "2025-01-27", "2025-04-27", 44.0), ("CY2025Q2", "2025-04-28", "2025-07-27", 46.7),
        ("CY2025Q3", "2025-07-28", "2025-10-26", 57.0), ("CY2025", "2025-01-27", "2026-01-25", 210.0),
        ("CY2026Q1", "2026-01-26", "2026-04-26", 70.0)])}
    by = {p["label"]: p for p in edgar.periods_from_facts({"facts": {"us-gaap": gaap}})}
    assert by["2025Q4"]["revenue"] == pytest.approx(210.0 - 44.0 - 46.7 - 57.0)
    assert by["2025Q4"]["start"] == "2025-10-27" and by["2026Q1"]["revenue"] == 70.0
    assert edgar._quarter_label(edgar.date(2025, 10, 27), edgar.date(2026, 1, 25)) == "2025Q4"


def test_edgar_cik_lookup_and_company(monkeypatch, tmp_path):
    tickers = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"}}
    def get(url, timeout=30):
        return json.dumps(tickers if "company_tickers" in url else _facts()).encode()
    monkeypatch.setattr(edgar, "_get", get)
    assert edgar.cik_for("brk.b", tmp_path) == (1067983, "Berkshire")
    c = edgar.company("AAPL", tmp_path, price=200.0)
    assert c.name == "Apple Inc." and c.currency == "USD" and c.shares == 10
    v = c.valuation()
    assert v["market_cap"] == 2000 and v["per_ttm"] == pytest.approx(2000 / (14 + 12 + 14 + 9))
    md = F.render(c)
    assert "재무제표 요약 — Apple Inc. (AAPL)" in md and "| 2026Q2 |" in md and "PER (TTM)" in md
    with pytest.raises(edgar.EdgarError):
        edgar.cik_for("ZZZZ", tmp_path)


def _dart_rows(q, ytd, bs, cf_ytd, quarterly=True):
    rows = [{"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": f"{q[0]:,}", "thstrm_add_amount": f"{ytd[0]:,}"},
            {"sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "thstrm_amount": f"{q[1]:,}", "thstrm_add_amount": f"{ytd[1]:,}"},
            {"sj_div": "IS", "account_id": "-", "account_nm": "분기순이익", "thstrm_amount": f"{q[2]:,}", "thstrm_add_amount": f"{ytd[2]:,}"},
            {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": f"{bs[0]:,}"},
            {"sj_div": "BS", "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계", "thstrm_amount": f"{bs[1]:,}"},
            {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "thstrm_amount": f"{bs[2]:,}"},
            {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "account_nm": "영업활동현금흐름", "thstrm_amount": f"{cf_ytd:,}"}]
    if not quarterly:
        for r in rows:
            r.pop("thstrm_add_amount", None)
    return rows


def test_dart_periods_split_quarters_from_year_to_date(monkeypatch, tmp_path):
    reports = {
        "11013": _dart_rows((100, 10, 8), (100, 10, 8), (400, 200, 200), 9),
        "11012": _dart_rows((110, 11, 9), (210, 21, 17), (405, 202, 203), 19),
        "11014": _dart_rows((120, 12, 9), (330, 33, 26), (410, 205, 205), 30),
        "11011": _dart_rows((460, 50, 40), (460, 50, 40), (420, 210, 210), 44, quarterly=False),
    }
    def statements(key, corp_code, year, reprt_code, fs_div="CFS", cache_dir=None):
        return reports[reprt_code] if year == 2025 else []
    monkeypatch.setattr(dart, "statements", statements)
    ps, notes = dart.periods("k", "00126380", [2025, 2026], tmp_path)
    by = {p["label"]: p for p in ps}
    assert by["2025Q2"]["revenue"] == 110 and by["2025Q2"]["ocf"] == 10 and by["2025Q3"]["ocf"] == 11
    assert by["2025Q4"]["revenue"] == 130 and by["2025Q4"]["net_income"] == 14 and by["2025Q4"]["ocf"] == 14 and by["2025Q4"]["equity"] == 210
    assert by["FY2025"]["revenue"] == 460 and by["FY2025"]["kind"] == "FY"
    assert any("2026Q1 보고서 미공시" in n for n in notes)


def test_dart_corp_codes_zip_and_missing_key(monkeypatch, tmp_path):
    xml = ('<?xml version="1.0"?><result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code></list>'
           '<list><corp_code>1</corp_code><corp_name>x</corp_name><stock_code> </stock_code></list></result>').encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml)
    assert dart.parse_corp_codes(buf.getvalue()) == {"005930": ("00126380", "삼성전자")}
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert dart.api_key() is None
    with pytest.raises(dart.DARTError):
        dart.parse_corp_codes(b'<?xml version="1.0"?><result><status>010</status><message>bad key</message></result>')


def test_edgar_user_agent_from_env(monkeypatch):
    from swing_engine import edgar
    monkeypatch.delenv(edgar.UA_ENV, raising=False)
    assert edgar.user_agent() == edgar.UA_DEFAULT
    monkeypatch.setenv(edgar.UA_ENV, " beomstar-swing a@b.c ")
    assert edgar.user_agent() == "beomstar-swing a@b.c"


def test_edgar_403_hint_names_the_block(monkeypatch):
    import gzip
    import io
    import urllib.error
    from swing_engine import edgar

    def raise_403(req, timeout=None):
        body = gzip.compress(b"<html>Your Request Originates from an Undeclared Automated Tool</html>")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(edgar.urllib.request, "urlopen", raise_403)
    monkeypatch.setenv(edgar.UA_ENV, "beomstar-swing a@b.c")
    with pytest.raises(edgar.EdgarError) as ei:
        edgar._get("https://www.sec.gov/files/company_tickers.json")
    msg = str(ei.value)
    assert "403" in msg and "Undeclared Automated Tool" in msg and "home network" in msg

    monkeypatch.setenv(edgar.UA_ENV, "no-contact")
    with pytest.raises(edgar.EdgarError) as ei:
        edgar._get("https://www.sec.gov/files/company_tickers.json")
    assert "no contact address" in str(ei.value)


def test_edgar_user_agent_rejects_non_ascii(monkeypatch):
    from swing_engine import edgar
    monkeypatch.setenv(edgar.UA_ENV, "beomstar-swing 대표님이메일@도메인")
    with pytest.raises(edgar.EdgarError, match="ASCII"):
        edgar.user_agent()


def test_edgar_current_fiscal_year_quarter_from_ytd():
    """NVIDIA-like current year: Q1 framed, Q2 only as a 6-month YTD fact, no 10-K yet."""
    def rows(vals):
        return {"units": {"USD": [{"start": s, "end": e, "val": v, "frame": f} for (f, s, e, v) in vals]}}
    gaap = {"Revenues": rows([("CY2026Q1", "2026-01-26", "2026-04-26", 81.6), ("CY2026Q2", "2026-04-27", "2026-07-26", 96.2)]),
            "NetCashProvidedByUsedInOperatingActivities": rows([("CY2026Q1", "2026-01-26", "2026-04-26", 50.3),
                                                                (None, "2026-01-26", "2026-07-26", 88.0)])}
    by = {p["label"]: p for p in edgar.periods_from_facts({"facts": {"us-gaap": gaap}})}
    assert by["2026Q2"]["ocf"] == pytest.approx(88.0 - 50.3) and by["2026Q1"]["ocf"] == 50.3
