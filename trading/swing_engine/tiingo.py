"""Tiingo end-of-day bars, the US cross-check source (checklist 3.3-3.4; grade 1: observation only).

Request shape (api.tiingo.com/documentation/end-of-day, as known 2026-10; the portal is not
reachable from the build container, so tiingo_probe confirms it):
  GET https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&format=json
  header Authorization: Token <TIINGO_TOKEN>
  -> [{"date": "2026-10-29T00:00:00.000Z", "open", "high", "low", "close", "volume",
       "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume", "divCash", "splitFactor"}]
  404 = ticker unknown to Tiingo; 429 = rate limited.
The ledger's Yahoo prices are split-adjusted but not dividend-adjusted (data.py), so the raw
open/high/low/close/volume are compared, not the adj* columns. Class shares are written with a
hyphen on both sides (BRK-B), so Yahoo tickers are passed through unchanged.

Free tier (third-party figures, 2026-10, [확인 필요]): 50 requests/hour, 1,000/day, 500 unique
symbols/month. S&P 500 + Nasdaq 100 is ~600 symbols, so the cross-check samples: the held and
pending symbols every run plus a rotating slice of the universe (SAMPLE per market per day),
about 25 requests a day and under 500 symbols a month.

Environment: TIINGO_TOKEN. Nothing here changes signals: it only reads.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

log = logging.getLogger("swing.tiingo")

BASE = "https://api.tiingo.com"
COLS = ("open", "high", "low", "close", "volume")
SAMPLE = 10                 # universe symbols per market per day besides the held/pending ones
MIN_INTERVAL = 0.3          # seconds between calls (the hourly cap is what matters, not the burst)
MARKETS = ("SP500", "NDX100")


class TiingoError(Exception):
    pass


def token() -> str | None:
    t = os.environ.get("TIINGO_TOKEN", "").strip()
    return t or None


def _request(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


_last_call = 0.0


def fetch_bars(ticker: str, start: str, end: str, tok: str, timeout: float = 30) -> pd.DataFrame | None:
    """Raw daily bars of `ticker` between start and end (YYYY-MM-DD), indexed by date, columns
    open/high/low/close/volume. None when Tiingo does not know the ticker (404). Raises TiingoError
    on other failures (401 bad token, 429 rate limit, network)."""
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    url = f"{BASE}/tiingo/daily/{ticker}/prices?startDate={start}&endDate={end}&format=json"
    headers = {"Authorization": f"Token {tok}", "Content-Type": "application/json", "User-Agent": "beomstar-swing/1"}
    try:
        status, raw = _request(url, headers, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read()[:200].decode("utf-8", "replace")
        raise TiingoError(f"{ticker}: HTTP {e.code} {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TiingoError(f"{ticker}: network {getattr(e, 'reason', e)}") from None
    try:
        rows = json.loads(raw)
    except ValueError:
        raise TiingoError(f"{ticker}: not json {raw[:80]!r}") from None
    if isinstance(rows, dict):                       # {"detail": "..."} on an error body with 200
        raise TiingoError(f"{ticker}: {str(rows)[:200]}")
    return frame(rows)


def frame(rows: list[dict]) -> pd.DataFrame:
    out = {}
    for r in rows:
        d = str(r.get("date", ""))[:10]
        if len(d) == 10:
            out[pd.Timestamp(d)] = {c: (None if r.get(c) is None else float(r[c])) for c in COLS}
    df = pd.DataFrame.from_dict(out, orient="index", columns=list(COLS)).sort_index()
    df.index.name = "date"
    return df


def sample(symbols, date: pd.Timestamp, n: int = SAMPLE, always=()) -> list[str]:
    """`always` (held and pending symbols) plus a slice of `n` universe symbols that rotates one
    slice per calendar day, so every symbol comes up about once a quarter and the monthly unique
    count stays under the free cap. Deterministic given the date."""
    pool = sorted(set(symbols) - set(always))
    picked = sorted(set(always) & set(symbols))
    if pool and n > 0:
        start = (int(pd.Timestamp(date).toordinal()) * n) % len(pool)
        picked += [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]
    return sorted(set(picked))


def bars_on(market: str, symbols, date: pd.Timestamp, tok: str, cache_dir=None) -> pd.DataFrame:
    """One row per symbol with that date's Tiingo bar; symbols without the bar are listed in
    df.attrs['missing'], tickers Tiingo does not know in df.attrs['unlisted']. Cached per market
    and date once at least one bar came back (an unpublished day must be asked again later)."""
    ds = date.strftime("%Y-%m-%d")
    p = Path(cache_dir) / "tiingo" / f"{market}_{ds}.json" if cache_dir else None
    cached = json.loads(p.read_text()) if p is not None and p.exists() else {"rows": {}, "missing": [], "unlisted": []}
    rows, missing, unlisted = dict(cached["rows"]), set(cached["missing"]), set(cached["unlisted"])
    known = set(rows) | missing | unlisted
    fetched = 0
    for y in symbols:
        if y in known:
            continue
        bars = fetch_bars(y, ds, ds, tok)
        fetched += 1
        if bars is None:
            unlisted.add(y)
        elif date in bars.index and not pd.isna(bars.loc[date, "close"]):
            rows[y] = {c: (None if pd.isna(v) else float(v)) for c, v in bars.loc[date].items()}
        else:
            missing.add(y)
    if p is not None and fetched and rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"rows": rows, "missing": sorted(missing), "unlisted": sorted(unlisted)}))
    want = set(symbols)
    df = pd.DataFrame.from_dict({k: v for k, v in rows.items() if k in want}, orient="index", columns=list(COLS))
    df.index.name = "symbol"
    df.attrs["missing"] = sorted(missing & want)
    df.attrs["unlisted"] = sorted(unlisted & want)
    df.attrs["calls"] = fetched
    return df
