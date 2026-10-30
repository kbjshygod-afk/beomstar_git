"""KRX Open API (openapi.krx.co.kr) daily bars, used to cross-check Yahoo (checklist 1.5).

GET https://data-dbg.krx.co.kr/svc/apis/<group>/<service>?basDd=YYYYMMDD with the key in the
AUTH_KEY header (a query-string form exists; tried only when the header form is rejected).
The body is {"OutBlock_1": [rows]} with numbers as strings ("1,234"). The exchange publishes
T-1 and earlier: asking for today returns an empty block until the next day, so a same-day
cross-check is never possible and the ledger compares the previous session instead.

Every service must be approved separately on the portal after the key is issued; an
unapproved one answers 401 like a bad key. Nothing here changes signals: it only reads.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

log = logging.getLogger("swing.krx")

BASE = "https://data-dbg.krx.co.kr/svc/apis"
STOCK_SERVICE = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd"}
INDEX_SERVICE = {"KOSPI": "idx/kospi_dd_trd", "KOSDAQ": "idx/kosdaq_dd_trd"}
SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
INDEX_NAMES = {"KOSPI": ("코스피", "KOSPI"), "KOSDAQ": ("코스닥", "KOSDAQ")}
STOCK_COLS = {"TDD_OPNPRC": "open", "TDD_HGPRC": "high", "TDD_LWPRC": "low", "TDD_CLSPRC": "close", "ACC_TRDVOL": "volume"}
INDEX_COLS = {"OPNPRC_IDX": "open", "HGPRC_IDX": "high", "LWPRC_IDX": "low", "CLSPRC_IDX": "close", "ACC_TRDVOL": "volume"}


class KRXError(Exception):
    pass


def api_key() -> str | None:
    k = os.environ.get("KRX_API_KEY", "").strip()
    return k or None


def num(s) -> float | None:
    """'1,234.5' -> 1234.5; '-', '' and junk -> None."""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def short_code(isu_cd) -> str:
    """6-digit code from either the short code or the 12-character ISIN (KR7005930003 -> 005930)."""
    s = str(isu_cd).strip()
    return s[3:9] if len(s) == 12 and s.startswith("KR") else s


def _request(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def fetch_rows(service: str, date: str, key: str, timeout: float = 30, auth: str = "header") -> list[dict]:
    """Rows of OutBlock_1 for `service` ("sto/ksq_bydd_trd") on `date` (YYYYMMDD). Raises KRXError
    with a short reason (http status, not approved, not json) so callers can record it."""
    k = key.strip()
    url = f"{BASE}/{service}?basDd={date}"
    headers = {"User-Agent": "beomstar-swing/1"}
    if auth == "query":
        url += "&AUTH_KEY=" + urllib.parse.quote(k, safe="")
    else:
        headers["AUTH_KEY"] = k
    try:
        status, body = _request(url, headers, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401 and auth == "header":
            return fetch_rows(service, date, key, timeout, auth="query")
        raise KRXError(f"HTTP {e.code}" + (" (key rejected or service not approved)" if e.code == 401 else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KRXError(f"network: {getattr(e, 'reason', e)}") from None
    try:
        data = json.loads(body)
    except ValueError:
        raise KRXError(f"not JSON (HTTP {status}); service probably not approved") from None
    if not isinstance(data, dict) or "OutBlock_1" not in data:
        raise KRXError("no OutBlock_1 in the answer")
    return list(data["OutBlock_1"])


def _cached(cache_dir, name: str, date: str, loader):
    """Rows for (name, date) from cache_dir/krx when present, else fetched and cached when non-empty
    (an empty answer for a date the exchange has not published yet must be asked again later)."""
    p = Path(cache_dir) / "krx" / f"{name}_{date}.json" if cache_dir else None
    if p is not None and p.exists():
        return json.loads(p.read_text())
    rows = loader()
    if p is not None and rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def stock_bars(market: str, date: str, key: str, cache_dir=None) -> pd.DataFrame:
    """Daily bars of every listed stock for one date, indexed by Yahoo symbol ('096530.KQ'):
    columns open/high/low/close/volume as floats. Empty when the date is not published."""
    service = STOCK_SERVICE[market]
    rows = _cached(cache_dir, service.replace("/", "_"), date, lambda: fetch_rows(service, date, key))
    out = {}
    for r in rows:
        sym = short_code(r.get("ISU_CD", "")) + SUFFIX[market]
        out[sym] = {col: num(r.get(src)) for src, col in STOCK_COLS.items()}
    df = pd.DataFrame.from_dict(out, orient="index", columns=list(STOCK_COLS.values()))
    df.index.name = "symbol"
    return df


def index_bar(market: str, date: str, key: str, cache_dir=None) -> dict | None:
    """The headline index (코스피 / 코스닥) bar for one date as {open, high, low, close, volume},
    or None when the date is not published or the series is not in the answer."""
    service = INDEX_SERVICE[market]
    rows = _cached(cache_dir, service.replace("/", "_"), date, lambda: fetch_rows(service, date, key))
    want = INDEX_NAMES[market]
    for r in rows:
        if str(r.get("IDX_NM", "")).strip() in want:
            return {col: num(r.get(src)) for src, col in INDEX_COLS.items()}
    if rows:
        log.warning("KRX %s %s: index %s not among %s", market, date, want, [r.get("IDX_NM") for r in rows[:6]])
    return None
