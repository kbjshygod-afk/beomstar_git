"""SEC EDGAR XBRL "company facts" for a US ticker -> fundamentals periods.

  tickers : https://www.sec.gov/files/company_tickers.json  {"0": {"cik_str", "ticker", "title"}, ...}
  facts   : https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
            facts.us-gaap.<Concept>.units.USD -> [{start, end, val, fy, fp, form, frame}]
Rules: a User-Agent naming the project and a contact is required, about 10 requests/second.
Frames ("CY2026Q2" for a quarter's flow, "CY2025" for a year, "...I" for an instant) identify
one reported value per period and avoid the duplicates of restated filings. A fourth quarter is
derived as the year minus the first three quarters when it has no frame of its own.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .fundamentals import Company

# SEC's edge rejects (403) any User-Agent without a contact address, so the project name
# plus an e-mail is required: set EDGAR_USER_AGENT ("beomstar-swing you@example.com").
UA_ENV = "EDGAR_USER_AGENT"
UA_DEFAULT = "beomstar-swing research"


def user_agent() -> str:
    """EDGAR_USER_AGENT, or the default without a contact. HTTP headers are Latin-1, so a value
    with other characters (2026-11-04: a Korean placeholder left in place of the e-mail) is
    refused here with a clear message instead of failing inside urllib."""
    ua = os.environ.get(UA_ENV, "").strip() or UA_DEFAULT
    try:
        ua.encode("latin-1")
    except UnicodeEncodeError:
        raise EdgarError(f"{UA_ENV} must be ASCII, e.g. 'beomstar-swing you@example.com' (got {ua!r})") from None
    return ua


TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# first concept with data wins
CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities", "LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
}
INSTANT = {"assets", "liabilities", "equity", "inventory", "receivables"}


class EdgarError(Exception):
    pass


def _get(url: str, timeout: float = 30) -> bytes:
    ua = user_agent()
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Host": url.split("/")[2]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return raw
    except urllib.error.HTTPError as e:
        raise EdgarError(f"EDGAR HTTP {e.code} for {url}{_http_error_hint(e, ua)}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise EdgarError(f"EDGAR network {getattr(e, 'reason', e)}") from None


BLOCKED_MARKERS = ("Undeclared Automated Tool", "Request Rate Threshold", "Access Denied")


def _http_error_hint(e, ua: str) -> str:
    """Why SEC said no: a User-Agent without a contact, or a network it refuses outright
    (GitHub-hosted runners get 403 on every sec.gov host even with a proper User-Agent)."""
    if e.code != 403:
        return ""
    if "@" not in ua:
        return f" (User-Agent has no contact address; set {UA_ENV}='project you@example.com')"
    try:
        body = e.read()
        if body[:2] == b"\x1f\x8b":
            import gzip
            body = gzip.decompress(body)
        text = body.decode("utf-8", "replace")
    except Exception:
        text = ""
    marker = next((m for m in BLOCKED_MARKERS if m in text), None)
    where = f" ({marker})" if marker else ""
    return f"{where}: SEC refuses this network; run tools/fundamentals_report.py from a home network (Mac)"


def cik_for(ticker: str, cache_dir=None) -> tuple[int, str]:
    """(CIK, company title) for a Yahoo-style ticker (BRK-B -> BRK-B in SEC's list too)."""
    p = Path(cache_dir) / "edgar" / "company_tickers.json" if cache_dir else None
    if p is not None and p.exists():
        data = json.loads(p.read_text())
    else:
        data = json.loads(_get(TICKERS_URL))
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data))
    t = ticker.upper().replace(".", "-")
    for row in data.values():
        if str(row.get("ticker", "")).upper() == t:
            return int(row["cik_str"]), str(row.get("title", t))
    raise EdgarError(f"{ticker}: not in SEC's ticker list")


def company_facts(cik: int, cache_dir=None) -> dict:
    p = Path(cache_dir) / "edgar" / f"CIK{cik:010d}.json" if cache_dir else None
    if p is not None and p.exists():
        return json.loads(p.read_text())
    data = json.loads(_get(FACTS_URL.format(cik=cik)))
    if p is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
    return data


def _series(facts: dict, concept: str) -> list[dict]:
    units = ((facts.get("facts") or {}).get("us-gaap") or {}).get(concept, {}).get("units") or {}
    for unit in ("USD", "USD/shares", "shares"):
        if unit in units:
            return units[unit]
    return next(iter(units.values()), [])


_FRAME = re.compile(r"CY(\d{4})(?:Q([1-4]))?(I?)")
DERIVED = ("revenue", "op_income", "net_income", "ocf")      # additive flows; EPS is not


def _date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _quarter_label(start: date, end: date) -> str:
    """Calendar quarter holding most of the period, as SEC frames do: the quarter of its
    midpoint (Apple Jun 29 - Sep 27 -> Q3; NVIDIA Oct 27 - Jan 25 -> Q4 of the earlier year)."""
    mid = start + (end - start) / 2
    return f"{mid.year}Q{(mid.month - 1) // 3 + 1}"


def _balance_at(bal: dict[str, dict], end: str, fig: str):
    """Balance of `fig` at `end`, or at the nearest reported instant within ten days."""
    if end in bal and fig in bal[end]:
        return bal[end][fig]
    e = _date(end)
    if e is None:
        return None
    best = None
    for k, v in bal.items():
        if fig not in v:
            continue
        d = _date(k)
        if d is None:
            continue
        gap = abs((d - e).days)
        if gap <= 10 and (best is None or gap < best[0]):
            best = (gap, v[fig])
    return best[1] if best else None


def periods_from_facts(facts: dict) -> list[dict]:
    """Quarterly and annual periods keyed by XBRL frame.

    * Flows: concepts are merged per period in CONCEPTS order, so a company that reports
      Revenues for some years and RevenueFromContractWithCustomer... for others (Apple) still
      gets every period.
    * Balances: taken at the period's end date, whatever frame SEC gave the instant, so a
      September fiscal year-end reads its own balance sheet, not December's.
    * The quarter a company never files a 10-Q for (its fiscal Q4) is derived as the fiscal
      year minus the three quarters that fall inside that year's start..end, and labelled by
      the calendar quarter its end aligns with.
    * Cash flow is filed year-to-date, so SEC frames only the first quarter; the second and
      third are YTD minus the previous YTD (same fiscal-year start).
    """
    flows: dict[str, dict] = {}
    bal: dict[str, dict] = {}
    ytd: dict[tuple, dict] = {}            # (start, end) -> {fig: val}: every duration fact, framed or not
    for fig, concepts in CONCEPTS.items():
        for concept in concepts:
            rows = sorted(_series(facts, concept), key=lambda r: 0 if r.get("frame") else 1)
            for r in rows:
                if r.get("val") is None or not r.get("end"):
                    continue
                if fig in INSTANT:
                    bal.setdefault(r["end"], {}).setdefault(fig, float(r["val"]))
                    continue
                if r.get("start") and fig in DERIVED:
                    ytd.setdefault((r["start"], r["end"]), {}).setdefault(fig, float(r["val"]))
                m = _FRAME.fullmatch(r.get("frame") or "")
                if not m or m.group(3):
                    continue
                year, qn = m.group(1), m.group(2)
                key = f"{year}Q{qn}" if qn else f"FY{year}"
                p = flows.setdefault(key, {"label": key, "kind": "Q" if qn else "FY",
                                           "start": r.get("start"), "end": r["end"]})
                p.setdefault(fig, float(r["val"]))
    # the fiscal fourth quarter: year minus the three quarters inside it
    for fy in [p for p in list(flows.values()) if p["kind"] == "FY"]:
        s, e = _date(fy.get("start")), _date(fy["end"])
        if s is None or e is None:
            continue
        inside = sorted((q for q in flows.values() if q["kind"] == "Q" and _date(q.get("start")) is not None
                         and _date(q["start"]) >= s - timedelta(days=7) and _date(q["end"]) <= e + timedelta(days=7)),
                        key=lambda q: q["end"])
        if len(inside) != 3:
            continue
        # cash flow (and anything else) a 10-Q reports only year-to-date: quarter = YTD − previous YTD
        for i, q in enumerate(inside):
            cur = ytd.get((fy["start"], q["end"]), {})
            prev = ytd.get((fy["start"], inside[i - 1]["end"]), {}) if i else {}
            for fig in DERIVED:
                if q.get(fig) is None and cur.get(fig) is not None and (i == 0 or prev.get(fig) is not None):
                    q[fig] = cur[fig] - (prev[fig] if i else 0.0)
        starts = [_date(q["start"]) for q in inside]
        ends = [_date(q["end"]) for q in inside]
        if (starts[0] - s).days > 20:
            gap = (s, starts[0] - timedelta(days=1))
        elif (e - ends[-1]).days > 20:
            gap = (ends[-1] + timedelta(days=1), e)
        else:
            gap = next(((ends[i] + timedelta(days=1), starts[i + 1] - timedelta(days=1))
                        for i in range(2) if (starts[i + 1] - ends[i]).days > 20), None)
            if gap is None:
                continue
        key = _quarter_label(gap[0], gap[1])
        if key in flows and any(flows[key].get(f) is not None for f in DERIVED):
            continue                                     # a filed quarter already holds that label
        p = flows.setdefault(key, {"label": key, "kind": "Q", "start": gap[0].isoformat(), "end": gap[1].isoformat()})
        for fig in DERIVED:
            if p.get(fig) is None and fy.get(fig) is not None and all(q.get(fig) is not None for q in inside):
                p[fig] = fy[fig] - sum(q[fig] for q in inside)
    out = list(flows.values())
    for p in out:
        for fig in INSTANT:
            p[fig] = _balance_at(bal, p["end"], fig)
        for fig in CONCEPTS:
            p.setdefault(fig, None)
    return sorted(out, key=lambda p: (p["end"], p["kind"]))


def shares_outstanding(facts: dict) -> float | None:
    dei = (facts.get("facts") or {}).get("dei") or {}
    rows = (dei.get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []
    rows = [r for r in rows if r.get("val")]
    return float(max(rows, key=lambda r: r["end"])["val"]) if rows else None


def company(ticker: str, cache_dir=None, price: float | None = None) -> Company:
    cik, title = cik_for(ticker, cache_dir)
    facts = company_facts(cik, cache_dir)
    c = Company(symbol=ticker.upper(), name=title, source="SEC EDGAR", currency="USD",
                periods=periods_from_facts(facts), price=price, shares=shares_outstanding(facts))
    c.notes.append(f"EDGAR CIK {cik:010d} · us-gaap 개념: 매출 {'/'.join(CONCEPTS['revenue'][:2])} 등을 분기마다 순서대로 채움 · 잔액은 각 기간 말일 기준 · 4분기 = 회계연도 − 그 안의 3분기")
    return c
