"""Data access: CSV files, Yahoo Finance prices, index universes, on-disk cache.

All network access goes through four small wrappers (`_http_get`, `_yf_download`,
`_fdr_stock_listing`, `_sleep`) so the unit tests can replace them with mocks.

Prices are split-adjusted but NOT dividend-adjusted (TradingView's default): Yahoo is
called with auto_adjust=False and only Open/High/Low/Close/Volume are used, never
'Adj Close' (SPEC 1).
"""
from __future__ import annotations

import io
import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .indicators import normalize_bars
from .params import BENCHMARKS, normalize_preset

log = logging.getLogger("swing_engine.data")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NDX100 = "https://en.wikipedia.org/wiki/Nasdaq-100"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"

UNIVERSE_SIZES = {"KOSPI": 200, "KOSDAQ": 150, "CRYPTO": 30}


# ---------------------------------------------------------------------------
# network wrappers (mocked in tests)
# ---------------------------------------------------------------------------

def _http_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 30):
    import requests
    h = {"User-Agent": UA}
    h.update(headers or {})
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r


def _yf_download(**kwargs):
    import yfinance as yf
    return yf.download(**kwargs)


def _fdr_stock_listing(market: str) -> pd.DataFrame:
    import FinanceDataReader as fdr
    return fdr.StockListing(market)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> datetime:
    """Current time (UTC). Tests replace it to pin the clock."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

_DATE_COLS = ("time", "date", "datetime", "timestamp", "day")
_ISO_DATE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


def _parse_dates(col: pd.Series, tz: str | None) -> pd.DatetimeIndex:
    """Trading date of each bar.

    * Unix seconds (TradingView 'UNIX timestamp' export) -> date in `tz` (default UTC).
      TradingView stamps a daily bar with its session open (US 09:30 ET = 13:30/14:30 UTC,
      KRX 09:00 KST = 00:00 UTC, crypto 00:00 UTC), so the UTC date is the trading date.
    * Integer YYYYMMDD (20240102, a common Korean export format) -> that date.
    * ISO strings ('2024-01-02', '2024-01-02T14:30:00Z', '2024-01-02T09:00:00+09:00')
      -> the calendar date as written (the exchange-local date when an offset is given).

    Numeric dates that put two rows on the same day are rejected: daily bars have one row
    per day, so a collision means the unit was misread (or the file is intraday).
    """
    num = pd.to_numeric(col, errors="coerce")
    if num.notna().all() and len(num):
        if ((num % 1 == 0) & (num >= 19000101) & (num <= 21001231)).all():
            ymd = pd.to_datetime(num.astype("int64").astype(str), format="%Y%m%d", errors="coerce")
            if ymd.notna().all():
                return pd.DatetimeIndex(ymd)
        unit = "ms" if num.abs().max() > 1e11 else "s"
        ts = pd.to_datetime(num, unit=unit, utc=True)
        if tz:
            ts = ts.dt.tz_convert(ZoneInfo(tz))
        idx = pd.DatetimeIndex(ts.dt.tz_localize(None).dt.normalize())
        if idx.has_duplicates:
            raise ValueError(f"numeric dates put {len(idx)} rows on {idx.nunique()} days; expected one "
                             "daily bar per unix timestamp (s or ms) or YYYYMMDD integers")
        return idx
    s = col.astype(str)
    m = s.str.extract(_ISO_DATE, expand=False)
    if m.notna().all():
        return pd.DatetimeIndex(pd.to_datetime(m, format="%Y-%m-%d"))
    ts = pd.to_datetime(s, format="mixed", utc=True)
    if tz:
        ts = ts.dt.tz_convert(ZoneInfo(tz))
    return pd.DatetimeIndex(ts.dt.tz_localize(None).dt.normalize())


def read_bars_csv(src, require_ohlc: bool = True, tz: str | None = None) -> pd.DataFrame:
    """Load daily bars from a TradingView chart export or a generic OHLCV CSV.

    Column names are matched case-insensitively: time|date|datetime|timestamp, open,
    high, low, close, volume. Extra columns (indicator plots, 'Adj Close') are ignored.
    Returns a normalized frame (DatetimeIndex 'date'; open/high/low/close/volume floats).
    """
    raw = pd.read_csv(src)
    lower = {c: str(c).strip().lower() for c in raw.columns}
    by_lower: dict[str, str] = {}
    for orig, lc in lower.items():
        by_lower.setdefault(lc, orig)       # first occurrence wins (TV can repeat names)
    dcol = next((by_lower[c] for c in _DATE_COLS if c in by_lower), None)
    if dcol is None:
        raise ValueError(f"{src}: no time/date column in {list(raw.columns)}")
    want = ("open", "high", "low", "close", "volume") if require_ohlc else ("close", "volume")
    out = pd.DataFrame(index=range(len(raw)))
    for k in want:
        if k in by_lower:
            out[k] = pd.to_numeric(raw[by_lower[k]], errors="coerce")
        elif k == "volume":
            out[k] = np.nan
        else:
            raise ValueError(f"{src}: missing column {k!r}")
    out.index = _parse_dates(raw[dcol], tz)
    out = out[out["close"].notna()]
    out = clean_bars(out, require_ohlc=require_ohlc, label=str(src))
    return normalize_bars(out, require_ohlc=require_ohlc)


_PRICES = ("open", "high", "low", "close")


def clean_bars(df: pd.DataFrame, require_ohlc: bool = True, label: str = "bars") -> pd.DataFrame:
    """Loader hygiene: keep only rows TradingView would print as a bar.

    Prices <= 0 become NaN (Yahoo sends O=H=L=0 rows for halted days and occasional NaN
    prices). Rows without a valid close are dropped; with `require_ohlc` (symbols) rows
    missing open, high or low are dropped too, and high/low are widened to contain the
    open and close. Benchmarks only need the close. Negative volume becomes NaN.
    This runs in the loaders only; the per-bar core keeps Pine's NaN semantics.
    """
    d = df.copy()
    px = [c for c in _PRICES if c in d.columns]
    d[px] = d[px].where(d[px] > 0)
    if "volume" in d.columns:
        d["volume"] = d["volume"].where(~(d["volume"] < 0))
    need = [c for c in (_PRICES if require_ohlc else ("close",)) if c in d.columns]
    keep = d[need].notna().all(axis=1)
    bad = int((~keep).sum())
    d = d[keep]
    if require_ohlc and len(d) and set(_PRICES) <= set(d.columns):
        d["high"] = d[["high", "open", "close"]].max(axis=1)
        d["low"] = d[["low", "open", "close"]].min(axis=1)
    if bad:
        log.warning("%s: dropped %d row(s) with a missing or non-positive price", label, bad)
    return d


def write_bars_csv(df: pd.DataFrame, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = df.copy()
    d.index = pd.DatetimeIndex(d.index).strftime("%Y-%m-%d")
    d.index.name = "date"
    d.to_csv(path, float_format="%.10g")


def _offline_candidates(ticker: str) -> list[str]:
    t = ticker
    return [t, t.replace("^", ""), t.replace("^", "_"), t.replace("^", "IDX_"), t.replace("^", "INDEX_")]


def find_offline_csv(directory, ticker: str) -> Path | None:
    d = Path(directory)
    files = {p.stem.lower(): p for p in d.glob("*.csv")}
    for cand in _offline_candidates(ticker):
        p = files.get(cand.lower())
        if p is not None:
            return p
    return None


def load_offline_dir(directory, tickers=None, exclude=(), require_ohlc=True):
    """Load `{ticker}.csv` files. Returns (frames, failed). Without `tickers`, every CSV
    in the directory except `exclude` stems (benchmarks) is loaded."""
    d = Path(directory)
    frames, failed = {}, []
    if tickers is None:
        ex = {c.lower() for t in exclude for c in _offline_candidates(t)}
        tickers = sorted(p.stem for p in d.glob("*.csv") if p.stem.lower() not in ex)
    for t in tickers:
        p = find_offline_csv(d, t)
        if p is None:
            failed.append(t)
            log.warning("offline: no CSV for %s", t)
            continue
        try:
            df = read_bars_csv(p, require_ohlc=require_ohlc)
        except Exception as e:  # noqa: BLE001 - logged and skipped
            log.warning("offline: %s unreadable: %s", p, e)
            failed.append(t)
            continue
        if len(df) == 0:
            failed.append(t)
            continue
        frames[t] = df
    return frames, failed


# ---------------------------------------------------------------------------
# confirmed bars (Pine evaluates confirmed bars only, line 163)
# ---------------------------------------------------------------------------

GRACE_MINUTES = 20

_NY = ("America/New_York", 16, 0)
_SEOUL = ("Asia/Seoul", 15, 30)
_SESSIONS = {"SP500": _NY, "NDX100": _NY, "KOSPI": _SEOUL, "KOSDAQ": _SEOUL, "CRYPTO": None}
_US_INDEXES = {"^GSPC", "^SPX", "^NDX", "^IXIC", "^DJI", "^RUT", "^VIX", "^NYA"}
_KR_INDEXES = {"^KS11", "^KQ11", "^KS200"}
_CRYPTO_PAIR = re.compile(r"-(USD|USDT|USDC|EUR|GBP|JPY|KRW|BTC|ETH)$")


def session_for(market: str | None, ticker: str | None = None):
    """Daily close of the market a bar belongs to: (tz, hour, minute), or None for bars
    that span a UTC day (crypto).

    Presets use their own market. CUSTOM (or no market) is inferred from the Yahoo ticker:
    .KS/.KQ and Korean indexes -> KRX 15:30 KST; '-USD'-style pairs -> UTC day; plain US
    tickers and US indexes -> NYSE 16:00 ET. Anything else also uses the UTC day, which ends
    after every stock exchange's close, so a forming bar is never kept (at worst a
    confirmed bar waits until 00:00 UTC).
    """
    mk = normalize_preset(market) if market else "CUSTOM"
    if mk != "CUSTOM":
        return _SESSIONS[mk]
    t = str(ticker or "").strip().upper()
    if t.endswith((".KS", ".KQ")) or t in _KR_INDEXES:
        return _SEOUL
    if _CRYPTO_PAIR.search(t):
        return None
    if t in _US_INDEXES or re.fullmatch(r"[A-Z0-9-]+", t):
        return _NY
    if t:
        log.info("no known session for %r; its bars are treated as UTC days", ticker)
    return None


def _confirmed_at(d: date, sess, grace_minutes: int = GRACE_MINUTES) -> datetime:
    """Moment from which the daily bar dated `d` is final: the session close plus
    `grace_minutes` in exchange time, or the end of its UTC day for crypto."""
    if sess is None:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
    tz, hh, mm = sess
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tz)) + timedelta(minutes=grace_minutes)


def _first_open_date(sess, at: datetime, grace_minutes: int = GRACE_MINUTES) -> date:
    """Earliest bar date that was not yet final at `at` (weekends skipped for stocks)."""
    if sess is None:
        return at.astimezone(timezone.utc).date()
    d = at.astimezone(ZoneInfo(sess[0])).date()
    if at >= _confirmed_at(d, sess, grace_minutes):
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _aware(now: datetime | None) -> datetime:
    now = now or _now()
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


def drop_unconfirmed_last_bar(df: pd.DataFrame, market: str, now: datetime | None = None,
                              grace_minutes: int = GRACE_MINUTES,
                              ticker: str | None = None) -> tuple[pd.DataFrame, bool]:
    """Drop today's still-forming daily bar (Yahoo returns it during the session).

    A bar dated d is final once the session close plus `grace_minutes` (exchange time) has
    passed; a crypto bar once its UTC day has ended. The session comes from
    `session_for(market, ticker)`. Returns (frame, dropped?).
    """
    if len(df) == 0:
        return df, False
    now = _aware(now)
    last = pd.Timestamp(df.index[-1]).date()
    drop = now < _confirmed_at(last, session_for(market, ticker), grace_minutes)
    return (df.iloc[:-1], True) if drop else (df, False)


def confirmed_bars(df: pd.DataFrame, sess, now: datetime, grace_minutes: int = GRACE_MINUTES) -> pd.DataFrame:
    """`df` without trailing bars that were still forming at `now`."""
    n = len(df)
    while n and now < _confirmed_at(pd.Timestamp(df.index[n - 1]).date(), sess, grace_minutes):
        n -= 1
    return df.iloc[:n]


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------

CACHE_VERSION = 2       # v2: the cache holds only bars that were final when fetched


def _safe_name(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", ticker)


def _cache_paths(cache_dir, ticker):
    base = Path(cache_dir) / "yahoo"
    name = _safe_name(str(ticker).upper())             # Yahoo symbols are case-insensitive
    return base / f"{name}.csv", base / f"{name}.json"


def _read_cache(cache_dir, ticker, start: date, end: date, now: datetime, max_age_hours: float, sess):
    """Cached bars for [start, end], or None when the cache may lack a final bar.

    The cache is complete for the window when `end`'s session had already closed at fetch
    time. Otherwise it is reused only while no session has closed since the fetch (and it
    is younger than `max_age_hours`); after that close the bar must be fetched again.
    """
    csv_p, meta_p = _cache_paths(cache_dir, ticker)
    if not (csv_p.exists() and meta_p.exists()):
        return None
    try:
        meta = json.loads(meta_p.read_text())
        if meta.get("v") != CACHE_VERSION:
            return None                                  # older caches may hold a forming bar
        m_start = date.fromisoformat(meta["start"])
        m_end = date.fromisoformat(meta["end"])
        fetched = datetime.fromisoformat(meta["fetched_at"])
    except Exception:  # noqa: BLE001
        return None
    if m_start > start or m_end < end:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    pending = _first_open_date(sess, fetched)            # first bar still forming at fetch time
    complete = pending > end
    unchanged = (now < _confirmed_at(pending, sess)
                 and (now - fetched).total_seconds() < max_age_hours * 3600)
    if not (complete or unchanged):
        return None
    df = _read_cache_csv(csv_p)
    return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]


def _read_cache_csv(path) -> pd.DataFrame:
    raw = pd.read_csv(path, index_col=0)
    raw.index = pd.to_datetime(raw.index, format="%Y-%m-%d")
    return normalize_bars(raw)


def _write_cache(cache_dir, ticker, df, start: date, end: date, now: datetime):
    csv_p, meta_p = _cache_paths(cache_dir, ticker)
    write_bars_csv(df, csv_p)
    meta_p.write_text(json.dumps({"v": CACHE_VERSION, "ticker": ticker, "start": start.isoformat(),
                                  "end": end.isoformat(), "fetched_at": now.isoformat(),
                                  "last_date": pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d"),
                                  "rows": int(len(df))}))


_FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


def _split_download(df: pd.DataFrame | None, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """yf.download result -> {ticker: normalized bars}. Missing/empty tickers are omitted."""
    out: dict[str, pd.DataFrame] = {}
    if df is None or len(df) == 0:
        return out
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):
        lv0 = set(map(str, cols.get_level_values(0)))
        field_first = bool(lv0 & set(_FIELDS)) or "Adj Close" in lv0
        level = 1 if field_first else 0
        # yfinance upper-cases every requested symbol: match the caller's spelling to it
        names = {str(v).upper(): v for v in cols.get_level_values(level)}
        for t in tickers:
            key = names.get(str(t).upper())
            if key is None:
                continue
            out_t = _fields_frame(df.xs(key, axis=1, level=level), label=f"yahoo {t}")
            if out_t is not None:
                out[t] = out_t
    else:
        if len(tickers) == 1:
            out_t = _fields_frame(df, label=f"yahoo {tickers[0]}")
            if out_t is not None:
                out[tickers[0]] = out_t
    return out


def _fields_frame(sub: pd.DataFrame, label: str = "yahoo") -> pd.DataFrame | None:
    if "Close" not in sub.columns:
        return None
    f = pd.DataFrame({v: sub[k] if k in sub.columns else np.nan for k, v in _FIELDS.items()}, index=sub.index)
    f = f[f["close"].notna()]                  # dates of other tickers in a batch download
    f = clean_bars(f, require_ohlc=False, label=label)   # symbols get the OHLC check later
    if len(f) == 0:
        return None
    return normalize_bars(f)


def download_yahoo(tickers, start, end, cache_dir=None, chunk_size: int = 40, retries: int = 3,
                   pause: float = 2.0, max_age_hours: float = 12.0, now: datetime | None = None,
                   timeout: float = 30, market: str | None = None,
                   close_only=()) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Daily bars for `tickers` between `start` and `end` (both inclusive).

    Chunked batch download with retries; tickers still missing after `retries` attempts
    are logged and returned in the failed list.

    A fresh download returns what Yahoo sent, including today's still-forming bar, which
    callers remove with drop_unconfirmed_last_bar. The per-ticker CSV cache stores only
    bars that were final at fetch time (see _read_cache), so a cache hit never serves an
    intraday snapshot as a closed bar. `market` selects the exchange session
    (session_for; inferred per ticker without it).

    Rows without a valid price are dropped (clean_bars). Tickers in `close_only`
    (benchmarks) only need a valid close.
    """
    start = pd.Timestamp(start).date()
    end = pd.Timestamp(end).date()
    now = _aware(now)
    tickers = list(dict.fromkeys(tickers))
    close_only = {str(t).upper() for t in close_only}
    sess = {t: session_for(market, t) for t in tickers}
    frames: dict[str, pd.DataFrame] = {}
    todo = []
    for t in tickers:
        hit = _read_cache(cache_dir, t, start, end, now, max_age_hours, sess[t]) if cache_dir else None
        if hit is not None and len(hit):
            frames[t] = hit
        else:
            todo.append(t)
    failed: list[str] = []
    for i in range(0, len(todo), max(1, chunk_size)):
        chunk = todo[i:i + chunk_size]
        missing = list(chunk)
        for attempt in range(1, retries + 1):
            try:
                raw = _yf_download(tickers=missing if len(missing) > 1 else missing[0],
                                   start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                   auto_adjust=False, actions=False, group_by="ticker",
                                   threads=True, progress=False, multi_level_index=True,
                                   timeout=timeout)
                got = _split_download(raw, missing)
            except Exception as e:  # noqa: BLE001 - network errors are retried
                log.warning("yahoo download attempt %d failed for %d tickers: %s", attempt, len(missing), e)
                got = {}
            for t, df in got.items():
                df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
                if len(df) == 0:
                    continue
                frames[t] = df
                if cache_dir:
                    final = confirmed_bars(df, sess[t], now)
                    if len(final):
                        _write_cache(cache_dir, t, final, start, end, now)
            missing = [t for t in missing if t not in frames]
            if not missing:
                break
            if attempt < retries:
                _sleep(pause * attempt)
        for t in missing:
            log.warning("yahoo: no data for %s after %d attempts - skipped", t, retries)
            failed.append(t)
    out: dict[str, pd.DataFrame] = {}
    for t, df in frames.items():
        if str(t).upper() not in close_only:
            df = clean_bars(df, require_ohlc=True, label=f"yahoo {t}")
        if len(df):
            out[t] = df
        else:
            log.warning("yahoo: no valid bars for %s - skipped", t)
            failed.append(t)
    return out, failed


# ---------------------------------------------------------------------------
# universes (SPEC 8.1)
# ---------------------------------------------------------------------------

def yahoo_us_symbol(sym: str) -> str:
    """Wikipedia/exchange ticker -> Yahoo: 'BRK.B' -> 'BRK-B', 'BF.B' -> 'BF-B'."""
    return str(sym).strip().upper().replace(".", "-").replace("/", "-").replace(" ", "")


def _wiki_tables(url: str) -> list[pd.DataFrame]:
    html = _http_get(url).text
    return pd.read_html(io.StringIO(html))


def _col_name(c) -> str:
    """Column label as lower-case text; MultiIndex headers are joined with spaces."""
    parts = c if isinstance(c, tuple) else (c,)
    return " ".join(dict.fromkeys(str(x).strip() for x in parts if str(x).strip())).lower()


def _pick_symbol_column(tables, min_rows: int, max_rows: int) -> list[str]:
    """The ticker column of the first table whose row count fits the index size.
    Exact names ('symbol', 'ticker', 'ticker symbol') win; otherwise any column whose
    name contains 'ticker' or 'symbol'. MultiIndex headers are flattened."""
    seen = []
    for exact in (True, False):
        for t in tables:
            cols = {_col_name(c): c for c in t.columns}
            if exact:
                seen.append((len(t), list(cols)[:6]))
            if not (min_rows <= len(t) <= max_rows):
                continue
            if exact:
                hit = next((cols[k] for k in ("symbol", "ticker", "ticker symbol") if k in cols), None)
            else:
                hit = next((c for n, c in cols.items() if "ticker" in n or "symbol" in n), None)
            if hit is not None:
                vals = [str(v) for v in t[hit].dropna()]
                return [yahoo_us_symbol(v) for v in vals if v and v.lower() != "nan"]
    raise ValueError(f"no constituent table with a Symbol/Ticker column found; tables (rows, columns): {seen}")


def fetch_sp500() -> list[str]:
    return list(dict.fromkeys(_pick_symbol_column(_wiki_tables(WIKI_SP500), 400, 600)))


def fetch_ndx100() -> list[str]:
    return list(dict.fromkeys(_pick_symbol_column(_wiki_tables(WIKI_NDX100), 90, 110)))


def fetch_krx_top(market: str, n: int | None = None) -> list[str]:
    """Top-n common stocks by market cap from FinanceDataReader's KRX listing.

    fdr.StockListing('KOSPI'|'KOSDAQ') returns KRX's 'all stocks' snapshot with columns
    Code, Name, Market, Dept, Close, ..., Marcap, Stocks, MarketId (see
    FinanceDataReader/krx/listing.py KrxMarcapListingCache). Preferred shares (code not
    ending in '0') and SPACs ('스팩') are dropped, as KOSPI 200 / KOSDAQ 150 do. Newer
    listings have short codes with letters (0126Z0 삼성에피스홀딩스); common stocks still end
    in '0', letter-coded preferreds in K/L/M.
    """
    mk = normalize_preset(market)
    if mk not in ("KOSPI", "KOSDAQ"):
        raise ValueError(market)
    n = n or UNIVERSE_SIZES[mk]
    df = _fdr_stock_listing(mk).copy()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Marcap"] = pd.to_numeric(df["Marcap"], errors="coerce")
    df["Code"] = df["Code"].str.upper()
    ok = df["Code"].str.fullmatch(r"[0-9A-Z]{5}0") & ~df["Name"].astype(str).str.contains("스팩")
    if "Dept" in df.columns:
        ok &= ~df["Dept"].astype(str).str.contains("SPAC", case=False, na=False)
    df = df[ok & df["Marcap"].notna()].sort_values("Marcap", ascending=False, kind="stable")
    suffix = ".KS" if mk == "KOSPI" else ".KQ"
    return [c + suffix for c in df["Code"].head(n)]


STABLECOIN_SYMBOLS = {
    "usdt", "usdc", "dai", "fdusd", "tusd", "usde", "usdd", "pyusd", "usds", "busd", "frax",
    "lusd", "gusd", "usdp", "usd0", "usdb", "rlusd", "usdx", "usdy", "usdg", "usd1", "usdf",
    "crvusd", "gho", "susde", "susds", "bfusd", "usdtb", "eurc", "eurs", "eurt", "xaut", "paxg",
    "ustc", "usdl", "buidl", "syrupusdc", "usdc.e", "usdt0", "dola", "mim", "alusd", "susd",
}
_WRAPPED_RE = re.compile(r"\b(wrapped|staked|bridged|restaked|liquid staking)\b", re.I)
WRAPPED_SYMBOLS = {"weth", "wbtc", "steth", "wsteth", "weeth", "reth", "cbbtc", "cbeth", "meth",
                   "bnsol", "jitosol", "msol", "lbtc", "solvbtc", "tbtc", "wbeth", "ezeth", "rseth",
                   "wbnb", "btcb", "stsol", "oseth", "sweth"}
# CoinGecko symbol -> Yahoo ticker where Yahoo disambiguates with a numeric id.
YAHOO_CRYPTO_OVERRIDES = {
    "SUI": "SUI20947-USD", "TON": "TON11419-USD", "UNI": "UNI7083-USD", "APT": "APT21794-USD",
    "PEPE": "PEPE24478-USD", "TAO": "TAO22974-USD",
}


def is_stablecoin(coin: dict) -> bool:
    sym = str(coin.get("symbol", "")).lower()
    name = str(coin.get("name", "")).lower()
    if sym in STABLECOIN_SYMBOLS:
        return True
    if "usd" in sym or "stablecoin" in name or re.search(r"\b(usd|dollar|euro)\b", name):
        return True
    return False


def is_wrapped(coin: dict) -> bool:
    sym = str(coin.get("symbol", "")).lower()
    return sym in WRAPPED_SYMBOLS or bool(_WRAPPED_RE.search(str(coin.get("name", ""))))


def fetch_crypto_top(n: int = 30, exclude_wrapped: bool = True) -> list[str]:
    """Top-n coins by market cap from CoinGecko, stablecoins excluded, as 'SYMBOL-USD'.

    `exclude_wrapped` (default on, beyond SPEC 8.1) also drops wrapped/staked copies of
    another coin (WBTC, stETH, ...), which would duplicate BTC/ETH positions.
    """
    r = _http_get(COINGECKO_MARKETS, params={"vs_currency": "usd", "order": "market_cap_desc",
                                             "per_page": 250, "page": 1, "sparkline": "false"})
    coins = r.json()
    coins = sorted(coins, key=lambda c: (c.get("market_cap_rank") or 10**9))
    out = []
    for c in coins:
        if is_stablecoin(c) or (exclude_wrapped and is_wrapped(c)):
            continue
        sym = str(c.get("symbol", "")).upper()
        ticker = YAHOO_CRYPTO_OVERRIDES.get(sym, f"{sym}-USD")
        if ticker not in out:
            out.append(ticker)
        if len(out) >= n:
            break
    return out


def fetch_universe(market: str, cache_dir=None, max_age_days: float = 7.0,
                   now: datetime | None = None) -> list[str]:
    """Current constituents for a preset (survivorship bias as in the scanner, SPEC 8.1)."""
    mk = normalize_preset(market)
    now = now or datetime.now(timezone.utc)
    cache_p = Path(cache_dir) / "universe" / f"{mk}.json" if cache_dir else None
    if cache_p and cache_p.exists():
        try:
            meta = json.loads(cache_p.read_text())
            fetched = datetime.fromisoformat(meta["fetched_at"])
            if (now - fetched).total_seconds() < max_age_days * 86400 and meta["tickers"]:
                return list(meta["tickers"])
        except Exception:  # noqa: BLE001
            pass
    if mk == "SP500":
        tickers = fetch_sp500()
    elif mk == "NDX100":
        tickers = fetch_ndx100()
    elif mk in ("KOSPI", "KOSDAQ"):
        tickers = fetch_krx_top(mk)
    elif mk == "CRYPTO":
        tickers = fetch_crypto_top(UNIVERSE_SIZES["CRYPTO"])
    else:
        raise ValueError("CUSTOM has no universe; pass --universe-file or --offline-dir")
    if cache_p:
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps({"market": mk, "fetched_at": now.isoformat(), "tickers": tickers}))
    return tickers


def benchmark_ticker(market: str) -> str:
    return BENCHMARKS[normalize_preset(market)]


def read_universe_file(path) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.extend(x.strip() for x in s.split(",") if x.strip())
    return list(dict.fromkeys(out))


def truncate(df: pd.DataFrame, as_of=None, start=None) -> pd.DataFrame:
    """Rows with start <= date <= as_of (inclusive). Used everywhere to rule out lookahead."""
    if df is None:
        return df
    m = np.ones(len(df), bool)
    if as_of is not None:
        m &= df.index <= pd.Timestamp(as_of)
    if start is not None:
        m &= df.index >= pd.Timestamp(start)
    return df.loc[m]


def is_nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))
