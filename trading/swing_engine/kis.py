"""Korea Investment & Securities (KIS) Open API daily bars, the second Korean source for the
cross-check (checklist 2.4). Unlike KRX Open API (T-1 only), KIS serves the day's bar right after
the close, so the signal day itself can be verified at commit time.

Request shape (koreainvestment/open-trading-api, examples_llm, 2026-10-30):
  token : POST {base}/oauth2/tokenP  {"grant_type":"client_credentials","appkey","appsecret"}
          -> {"access_token", "access_token_token_expired"}; valid one day; KIS throttles issuance,
          so the token is cached under cache_dir/kis/ and reused until it expires.
  stock : GET {base}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
          tr_id FHKST03010100 (same on the paper server), FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD=code,
          FID_INPUT_DATE_1/2=YYYYMMDD, FID_PERIOD_DIV_CODE=D, FID_ORG_ADJ_PRC=1 (unadjusted, like KRX)
          -> body.rt_cd "0", body.output2 [{stck_bsop_date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol}]
  index : GET .../inquire-daily-indexchartprice, tr_id FHKUP03500100, FID_COND_MRKT_DIV_CODE=U,
          FID_INPUT_ISCD 0001 (KOSPI) / 1001 (KOSDAQ) -> output2 [{stck_bsop_date, bstp_nmix_prpr, _oprc, _hgpr, _lwpr, acml_vol}]
Headers: authorization Bearer, appkey, appsecret, tr_id, custtype P. EGW00201 = calls per second
exceeded (the paper server allows fewer); calls are spaced and retried once on it.

Environment: KIS_APP_KEY, KIS_APP_SECRET, KIS_ENV = "vps" (paper server, default) or "prod".
Quotations need no account number. Nothing here changes signals: it only reads.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("swing.kis")

BASE = {"prod": "https://openapi.koreainvestment.com:9443", "vps": "https://openapivts.koreainvestment.com:29443"}
STOCK_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
INDEX_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
STOCK_TR, INDEX_TR = "FHKST03010100", "FHKUP03500100"
INDEX_CODE = {"KOSPI": "0001", "KOSDAQ": "1001"}
SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
STOCK_COLS = {"stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "stck_clpr": "close", "acml_vol": "volume"}
INDEX_COLS = {"bstp_nmix_oprc": "open", "bstp_nmix_hgpr": "high", "bstp_nmix_lwpr": "low", "bstp_nmix_prpr": "close",
              "acml_vol": "volume"}
RATE_LIMIT_CODE = "EGW00201"
MIN_INTERVAL = 0.6          # seconds between calls: the paper server rejects bursts above ~2/s


class KISError(Exception):
    pass


def credentials() -> dict | None:
    """{"key", "secret", "env"} from the environment, or None when the key or secret is unset."""
    k, s = os.environ.get("KIS_APP_KEY", "").strip(), os.environ.get("KIS_APP_SECRET", "").strip()
    env = os.environ.get("KIS_ENV", "vps").strip() or "vps"
    if not k or not s:
        return None
    if env not in BASE:
        raise KISError(f"KIS_ENV must be prod or vps, not {env!r}")
    return {"key": k, "secret": s, "env": env}


def num(s) -> float | None:
    t = str(s).replace(",", "").strip() if s is not None else ""
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _request(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


class Client:
    """One session: a cached token and spaced calls. `cache_dir` holds the token file; it must not
    be committed anywhere (the ledger checkout is a different directory)."""

    def __init__(self, cred: dict, cache_dir=None, timeout: float = 30, min_interval: float = MIN_INTERVAL):
        self.cred, self.base = cred, BASE[cred["env"]]
        self.cache_dir, self.timeout, self.min_interval = cache_dir, timeout, min_interval
        self._token, self._last_call = None, 0.0
        self.calls = 0

    # -- token --------------------------------------------------------------------------------
    def _token_path(self) -> Path | None:
        return Path(self.cache_dir) / "kis" / f"token_{self.cred['env']}.json" if self.cache_dir else None

    def token(self) -> str:
        if self._token:
            return self._token
        p = self._token_path()
        if p is not None and p.exists():
            try:
                saved = json.loads(p.read_text())
                if saved.get("key_tail") == self.cred["key"][-4:] and \
                        datetime.fromisoformat(saved["expires"]) - timedelta(minutes=10) > datetime.now(timezone.utc):
                    self._token = saved["token"]
                    return self._token
            except (ValueError, KeyError):
                pass
        body = json.dumps({"grant_type": "client_credentials", "appkey": self.cred["key"],
                           "appsecret": self.cred["secret"]}).encode()
        try:
            status, raw = _request("POST", f"{self.base}/oauth2/tokenP",
                                   {"content-type": "application/json; charset=utf-8", "User-Agent": "beomstar-swing/1"},
                                   body, self.timeout)
        except urllib.error.HTTPError as e:
            raise KISError(f"token: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise KISError(f"token: network {getattr(e, 'reason', e)}") from None
        data = json.loads(raw)
        tok = data.get("access_token")
        if not tok:
            raise KISError(f"token: no access_token in {str(data)[:200]}")
        # "2026-10-31 09:12:33" in KST; store as UTC
        exp_txt = data.get("access_token_token_expired", "")
        try:
            exp = datetime.strptime(exp_txt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
        except ValueError:
            exp = datetime.now(timezone.utc) + timedelta(hours=23)
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"token": tok, "expires": exp.astimezone(timezone.utc).isoformat(),
                                     "key_tail": self.cred["key"][-4:]}))
        self._token = tok
        return tok

    # -- quotations ---------------------------------------------------------------------------
    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        headers = {"authorization": f"Bearer {self.token()}", "appkey": self.cred["key"], "appsecret": self.cred["secret"],
                   "tr_id": tr_id, "custtype": "P", "content-type": "application/json; charset=utf-8",
                   "User-Agent": "beomstar-swing/1"}
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        for attempt in (1, 2):
            self._last_call = time.monotonic()
            self.calls += 1
            try:
                status, raw = _request("GET", url, headers, None, self.timeout)
            except urllib.error.HTTPError as e:
                detail = e.read()[:200].decode("utf-8", "replace")
                if e.code == 500 and RATE_LIMIT_CODE in detail and attempt == 1:
                    time.sleep(1.2)
                    continue
                raise KISError(f"{tr_id}: HTTP {e.code} {detail}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise KISError(f"{tr_id}: network {getattr(e, 'reason', e)}") from None
            data = json.loads(raw)
            if data.get("rt_cd") != "0":
                if data.get("msg_cd") == RATE_LIMIT_CODE and attempt == 1:
                    time.sleep(1.2)
                    continue
                raise KISError(f"{tr_id}: {data.get('msg_cd')} {str(data.get('msg1', '')).strip()}")
            return data
        raise KISError(f"{tr_id}: rate limited twice")

    def stock_bars(self, code: str, start: str, end: str, mrkt: str = "J") -> pd.DataFrame:
        """Unadjusted daily bars of one 6-digit code between start and end (YYYYMMDD, max 100 rows),
        indexed by date, columns open/high/low/close/volume. `mrkt`: J = KRX regular session,
        NX = NXT (the alternative venue, 08:00-20:00 KST), UN = both combined."""
        data = self._get(STOCK_PATH, STOCK_TR, {"FID_COND_MRKT_DIV_CODE": mrkt, "FID_INPUT_ISCD": code,
                                               "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": end,
                                               "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "1"})
        return _frame(data.get("output2") or [], STOCK_COLS)

    def index_bars(self, market: str, start: str, end: str) -> pd.DataFrame:
        data = self._get(INDEX_PATH, INDEX_TR, {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": INDEX_CODE[market],
                                               "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": end,
                                               "FID_PERIOD_DIV_CODE": "D"})
        return _frame(data.get("output2") or [], INDEX_COLS)


def _frame(rows: list[dict], cols: dict) -> pd.DataFrame:
    out = {}
    for r in rows:
        d = str(r.get("stck_bsop_date", "")).strip()
        if len(d) == 8:
            out[pd.Timestamp(f"{d[:4]}-{d[4:6]}-{d[6:]}")] = {c: num(r.get(src)) for src, c in cols.items()}
    df = pd.DataFrame.from_dict(out, orient="index", columns=list(cols.values())).sort_index()
    df.index.name = "date"
    return df


def bars_on(client: Client, market: str, symbols, date: pd.Timestamp, cache_dir=None) -> pd.DataFrame:
    """One row per Yahoo symbol ('096530.KQ') with that date's KIS bar; symbols KIS has no bar for
    on that date are left out and listed in df.attrs['missing']. Cached per market and date once
    complete, so the 2-hourly reruns do not repeat the calls."""
    ds = date.strftime("%Y%m%d")
    p = Path(cache_dir) / "kis" / f"{market}_{ds}.json" if cache_dir else None
    if p is not None and p.exists():
        cached = json.loads(p.read_text())
        df = pd.DataFrame.from_dict(cached["rows"], orient="index", columns=list(STOCK_COLS.values()))
        df.index.name = "symbol"
        df.attrs["missing"] = cached["missing"]
        return df
    rows, missing = {}, []
    for y in symbols:
        code = y.split(".")[0]
        bars = client.stock_bars(code, ds, ds)
        if date in bars.index and bars.loc[date, "close"] is not None and not pd.isna(bars.loc[date, "close"]):
            rows[y] = {c: (None if pd.isna(v) else float(v)) for c, v in bars.loc[date].items()}
        else:
            missing.append(y)
    if p is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"rows": rows, "missing": missing}))
    df = pd.DataFrame.from_dict(rows, orient="index", columns=list(STOCK_COLS.values()))
    df.index.name = "symbol"
    df.attrs["missing"] = missing
    return df


def index_bar(client: Client, market: str, date: pd.Timestamp) -> dict | None:
    ds = date.strftime("%Y%m%d")
    bars = client.index_bars(market, ds, ds)
    if date not in bars.index:
        return None
    return {c: (None if pd.isna(v) else float(v)) for c, v in bars.loc[date].items()}
