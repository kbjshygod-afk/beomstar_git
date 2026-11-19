"""DART (금융감독원 전자공시) OpenAPI for a Korean stock code -> fundamentals periods.

  corp codes : GET https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=KEY  (zip holding CORPCODE.xml:
               <list><corp_code/><corp_name/><stock_code/>...) — cached, ~10 MB
  statements : GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key&corp_code&bsns_year
               &reprt_code&fs_div=CFS  -> {"status": "000", "list": [{sj_div, account_id, account_nm,
               thstrm_amount, thstrm_add_amount, ...}]}  reprt_code 11013 1Q, 11012 반기, 11014 3Q, 11011 사업보고서
Income-statement rows of a quarterly report carry the quarter in thstrm_amount and the year-to-date in
thstrm_add_amount; cash-flow rows carry only the year-to-date (differenced here); balance-sheet rows
are period-end balances. The fourth quarter is the annual report minus the third quarter's year-to-date.
Status 013 = no data for that report (not filed yet). Limit 20,000 calls/day per key.
Environment: DART_API_KEY. Reference material only; nothing here changes signals.
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .fundamentals import Company

BASE = "https://opendart.fss.or.kr/api"
REPORTS = {"Q1": "11013", "H1": "11012", "Q3": "11014", "FY": "11011"}
# account_id first, then account_nm fallbacks (IFRS taxonomies differ between filers)
ACCOUNTS = {
    "revenue": (["ifrs-full_Revenue", "ifrs_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"]),
    "op_income": (["dart_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)"]),
    "net_income": (["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)", "반기순이익", "반기순이익(손실)"]),
    "ocf": (["ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"], ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로 인한 현금흐름"]),
    "assets": (["ifrs-full_Assets", "ifrs_Assets"], ["자산총계"]),
    "liabilities": (["ifrs-full_Liabilities", "ifrs_Liabilities"], ["부채총계"]),
    "equity": (["ifrs-full_Equity", "ifrs_Equity"], ["자본총계"]),
    "inventory": (["ifrs-full_Inventories", "ifrs_Inventories"], ["재고자산"]),
    "receivables": (["dart_ShortTermTradeReceivable", "ifrs-full_TradeAndOtherCurrentReceivables", "ifrs_TradeAndOtherCurrentReceivables"], ["매출채권", "매출채권 및 기타유동채권", "매출채권및기타채권"]),
    "eps": (["ifrs-full_DilutedEarningsLossPerShare", "ifrs-full_BasicEarningsLossPerShare", "ifrs_DilutedEarningsLossPerShare", "ifrs_BasicEarningsLossPerShare"], ["희석주당이익", "기본주당이익", "주당이익"]),
}
FLOW_IS = ("revenue", "op_income", "net_income", "eps")      # income statement: quarter in thstrm_amount
FLOW_CF = ("ocf",)                                             # cash flow: year-to-date only


class DARTError(Exception):
    pass


def api_key() -> str | None:
    k = os.environ.get("DART_API_KEY", "").strip()
    return k or None


def _get(url: str, timeout: float = 60) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "beomstar-swing/1"}), timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise DARTError(f"DART HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DARTError(f"DART network {getattr(e, 'reason', e)}") from None


def corp_codes(key: str, cache_dir=None) -> dict[str, tuple[str, str]]:
    """{stock_code: (corp_code, corp_name)} for listed companies."""
    p = Path(cache_dir) / "dart" / "corp_codes.json" if cache_dir else None
    if p is not None and p.exists():
        return {k: tuple(v) for k, v in json.loads(p.read_text()).items()}
    raw = _get(f"{BASE}/corpCode.xml?crtfc_key={urllib.parse.quote(key)}")
    out = parse_corp_codes(raw)
    if p is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False))
    return out


def parse_corp_codes(raw: bytes) -> dict[str, tuple[str, str]]:
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read(next(n for n in z.namelist() if n.lower().endswith(".xml")))
    else:
        xml = raw
    if b"<status>" in xml[:300] and b"<status>000" not in xml[:300]:
        raise DARTError(f"corpCode: {xml[:200].decode('utf-8', 'replace')}")
    out = {}
    for el in ET.fromstring(xml).iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            out[sc] = ((el.findtext("corp_code") or "").strip(), (el.findtext("corp_name") or "").strip())
    return out


def statements(key: str, corp_code: str, year: int, reprt_code: str, fs_div: str = "CFS", cache_dir=None) -> list[dict]:
    """Rows of fnlttSinglAcntAll, [] when the report is not filed (status 013). Cached once non-empty."""
    p = Path(cache_dir) / "dart" / f"{corp_code}_{year}_{reprt_code}_{fs_div}.json" if cache_dir else None
    if p is not None and p.exists():
        return json.loads(p.read_text())
    qs = urllib.parse.urlencode({"crtfc_key": key, "corp_code": corp_code, "bsns_year": year, "reprt_code": reprt_code, "fs_div": fs_div})
    data = json.loads(_get(f"{BASE}/fnlttSinglAcntAll.json?{qs}"))
    st = str(data.get("status"))
    if st == "013":
        return []
    if st != "000":
        raise DARTError(f"fnlttSinglAcntAll {year}/{reprt_code}: {st} {data.get('message', '')}")
    rows = data.get("list") or []
    if p is not None and rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def _amount(s) -> float | None:
    t = str(s or "").replace(",", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _find(rows: list[dict], fig: str, sj: tuple[str, ...]) -> dict | None:
    ids, names = ACCOUNTS[fig]
    cand = [r for r in rows if r.get("sj_div") in sj]
    for i in ids:
        for r in cand:
            if r.get("account_id") == i:
                return r
    for n in names:
        for r in cand:
            if (r.get("account_nm") or "").replace(" ", "") == n.replace(" ", ""):
                return r
    return None


def figures(rows: list[dict], quarterly: bool) -> dict:
    """{fig: (period value, year-to-date value)} from one report's rows."""
    out = {}
    for fig in ACCOUNTS:
        sj = ("BS",) if fig in ("assets", "liabilities", "equity", "inventory", "receivables") else ("CF",) if fig in FLOW_CF else ("IS", "CIS")
        r = _find(rows, fig, sj)
        if r is None:
            out[fig] = (None, None)
            continue
        cur = _amount(r.get("thstrm_amount"))
        ytd = _amount(r.get("thstrm_add_amount")) if quarterly and fig in FLOW_IS else cur
        out[fig] = (cur, ytd if ytd is not None else cur)
    return out


def periods(key: str, corp_code: str, years: list[int], cache_dir=None) -> tuple[list[dict], list[str]]:
    """Quarterly and annual periods for `years`; notes list the reports not filed yet."""
    out, notes = [], []
    for year in years:
        reps = {k: statements(key, corp_code, year, code, "CFS", cache_dir) for k, code in REPORTS.items()}
        if not any(reps.values()):
            reps = {k: statements(key, corp_code, year, code, "OFS", cache_dir) for k, code in REPORTS.items()}
            if any(reps.values()):
                notes.append(f"{year}: 연결재무제표 없음, 개별(OFS) 사용")
        fig = {k: figures(rows, k != "FY") if rows else None for k, rows in reps.items()}
        ends = {"Q1": f"{year}-03-31", "H1": f"{year}-06-30", "Q3": f"{year}-09-30", "FY": f"{year}-12-31"}
        labels = {"Q1": f"{year}Q1", "H1": f"{year}Q2", "Q3": f"{year}Q3", "FY": f"{year}Q4"}
        prev_ytd: dict = {}
        for k in ("Q1", "H1", "Q3", "FY"):
            f = fig.get(k)
            if f is None:
                notes.append(f"{labels[k]} 보고서 미공시")
                prev_ytd = {}
                continue
            p = {"label": labels[k], "kind": "Q", "end": ends[k]}
            for name, (cur, ytd) in f.items():
                if name in FLOW_IS:
                    p[name] = cur if k != "FY" else (None if ytd is None or prev_ytd.get(name) is None else ytd - prev_ytd[name])
                elif name in FLOW_CF:
                    p[name] = None if ytd is None else (ytd - prev_ytd[name] if prev_ytd.get(name) is not None else (ytd if k == "Q1" else None))
                else:
                    p[name] = cur
            for name, (cur, ytd) in f.items():
                if name in FLOW_IS or name in FLOW_CF:
                    prev_ytd[name] = ytd
            out.append(p)
            if k == "FY":
                fy = {"label": f"FY{year}", "kind": "FY", "end": ends[k]}
                for name, (cur, ytd) in f.items():
                    fy[name] = cur
                out.append(fy)
    return out, notes


def company(stock_code: str, key: str, years: list[int], cache_dir=None, price: float | None = None, shares: float | None = None) -> Company:
    code = stock_code.split(".")[0]
    codes = corp_codes(key, cache_dir)
    if code not in codes:
        raise DARTError(f"{stock_code}: DART 고유번호를 찾지 못함 (상장 종목코드 6자리인지 확인)")
    corp_code, name = codes[code]
    pers, notes = periods(key, corp_code, years, cache_dir)
    c = Company(symbol=stock_code, name=name, source="DART", currency="KRW", periods=pers, price=price, shares=shares)
    c.notes.append(f"DART 고유번호 {corp_code} · 연결재무제표(CFS) 우선 · 분기 손익 = 보고서의 3개월 값, 4분기 = 사업보고서 − 3분기 누적 · 현금흐름은 누적 차감")
    c.notes += notes
    return c


def shares_outstanding(key: str, corp_code: str, year: int, cache_dir=None) -> float | None:
    """유통주식수 (발행주식 − 자기주식, 보통주) from stockTotqySttus of the latest annual report; None when absent."""
    for y in (year, year - 1):
        qs = urllib.parse.urlencode({"crtfc_key": key, "corp_code": corp_code, "bsns_year": y, "reprt_code": "11011"})
        try:
            data = json.loads(_get(f"{BASE}/stockTotqySttus.json?{qs}"))
        except DARTError:
            return None
        if str(data.get("status")) != "000":
            continue
        for r in data.get("list") or []:
            if "보통주" in (r.get("se") or ""):
                v = _amount(r.get("distb_stock_co")) or _amount(r.get("istc_totqy"))
                if v:
                    return v
    return None
