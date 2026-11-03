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
from pathlib import Path

from .fundamentals import Company

# SEC's edge rejects (403) any User-Agent without a contact address, so the project name
# plus an e-mail is required: set EDGAR_USER_AGENT ("beomstar-swing you@example.com").
UA_ENV = "EDGAR_USER_AGENT"
UA_DEFAULT = "beomstar-swing research"


def user_agent() -> str:
    return os.environ.get(UA_ENV, "").strip() or UA_DEFAULT


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
        hint = f" (User-Agent has no contact address; set {UA_ENV}='project you@example.com')" if e.code == 403 and "@" not in ua else ""
        raise EdgarError(f"EDGAR HTTP {e.code} for {url}{hint}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise EdgarError(f"EDGAR network {getattr(e, 'reason', e)}") from None


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


def periods_from_facts(facts: dict) -> list[dict]:
    """Quarterly and annual periods keyed by XBRL frame."""
    q: dict[str, dict] = {}
    y: dict[str, dict] = {}
    for fig, concepts in CONCEPTS.items():
        for concept in concepts:
            rows = _series(facts, concept)
            if not rows:
                continue
            used = False
            for r in rows:
                fr = r.get("frame")
                if not fr:
                    continue
                m = re.fullmatch(r"CY(\d{4})(?:Q([1-4]))?(I?)", fr)
                if not m:
                    continue
                year, qn, inst = m.group(1), m.group(2), m.group(3)
                if fig in INSTANT:
                    if not inst or not qn:
                        continue
                    key = f"{year}Q{qn}"
                    q.setdefault(key, {"label": key, "kind": "Q", "end": r["end"]})
                    q[key].setdefault(fig, float(r["val"]))
                    used = True
                    # the year's balance sheet is the Q4 (or fiscal year-end) balance
                else:
                    if inst:
                        continue
                    if qn:
                        key = f"{year}Q{qn}"
                        q.setdefault(key, {"label": key, "kind": "Q", "end": r["end"]})
                        q[key].setdefault(fig, float(r["val"]))
                    else:
                        key = f"FY{year}"
                        y.setdefault(key, {"label": key, "kind": "FY", "end": r["end"]})
                        y[key].setdefault(fig, float(r["val"]))
                    used = True
            if used:
                break
    # derive a missing Q4 flow as FY - (Q1+Q2+Q3) of the same calendar year
    for key, fy in y.items():
        year = key[2:]
        q4 = f"{year}Q4"
        for fig in ("revenue", "op_income", "net_income", "ocf"):
            if fy.get(fig) is None:
                continue
            parts = [q.get(f"{year}Q{i}", {}).get(fig) for i in (1, 2, 3)]
            if q.get(q4, {}).get(fig) is None and all(p is not None for p in parts):
                q.setdefault(q4, {"label": q4, "kind": "Q", "end": fy["end"]})
                q[q4][fig] = fy[fig] - sum(parts)
        # the year's balances are the Q4 balances
        for fig in INSTANT:
            if fy.get(fig) is None and q.get(q4, {}).get(fig) is not None:
                fy[fig] = q[q4][fig]
    out = list(q.values()) + list(y.values())
    for p in out:
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
    c.notes.append(f"EDGAR CIK {cik:010d} · us-gaap 개념: 매출 {'/'.join(CONCEPTS['revenue'][:2])} 등 첫 번째로 값이 있는 개념 사용 · 4분기 = 연간 − 1~3분기")
    return c
