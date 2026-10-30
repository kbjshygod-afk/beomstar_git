"""Crypto exchange public APIs (no key), used to cross-check Yahoo's crypto bars (checklist 4).

Binance spot klines: GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&
startTime=<ms>&endTime=<ms>&limit=1 -> [[openTime, open, high, low, close, volume, closeTime, ...]].
Daily klines close at 00:00 UTC, the same boundary as Yahoo's 'XXX-USD' bars, so a date compares
directly. Prices are in USDT on one venue while Yahoo publishes a USD composite across venues, so
only the close is compared and with a looser tolerance; volume is not comparable at all.

Upbit: GET https://api.upbit.com/v1/market/all lists KRW/BTC/USDT markets; used only to say
whether a coin Yahoo lacks is listed somewhere Korean. Its prices are in KRW and are not compared.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("swing.exchange")

BINANCE = "https://api.binance.com/api/v3"
UPBIT = "https://api.upbit.com/v1"
_YAHOO_RE = re.compile(r"^([A-Za-z_]+?)\d*-USD$")      # UNI7083-USD -> UNI, FIGR_HELOC-USD -> FIGR_HELOC


class ExchangeError(Exception):
    pass


def base_symbol(yahoo: str) -> str:
    m = _YAHOO_RE.match(yahoo.strip())
    return (m.group(1) if m else yahoo.split("-")[0]).upper()


def binance_symbol(yahoo: str) -> str:
    return base_symbol(yahoo) + "USDT"


def _get(url: str, timeout: float = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "beomstar-swing/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _get_json(url: str, timeout: float = 30):
    try:
        status, body = _get(url, timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("msg", "")
        except Exception:                          # noqa: BLE001
            msg = ""
        raise ExchangeError(f"HTTP {e.code} {msg}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExchangeError(f"network: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(body)
    except ValueError:
        raise ExchangeError(f"not JSON (HTTP {status})") from None


def binance_bar(symbol: str, day: datetime) -> dict | None:
    """The 1d kline opening at 00:00 UTC on `day` for a Binance pair ('BTCUSDT'): {open, high,
    low, close, volume} or None when the pair is not listed or the day has no kline. Raises
    ExchangeError for network or rate-limit trouble (not for an unknown symbol)."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    end = start + 24 * 3600 * 1000 - 1
    url = (f"{BINANCE}/klines?symbol={symbol}&interval=1d&startTime={start}&endTime={end}&limit=1")
    try:
        rows = _get_json(url)
    except ExchangeError as e:
        if "HTTP 400" in str(e):                   # -1121 Invalid symbol
            return None
        raise
    if not rows:
        return None
    k = rows[0]
    if int(k[0]) != start:
        return None
    return {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}


def binance_bars_on(symbols, day: datetime, cache_dir=None) -> pd.DataFrame:
    """Close (and OHLCV) of every Yahoo crypto symbol in `symbols` on `day` from Binance, indexed by
    the Yahoo symbol; symbols without a Binance pair are left out. Cached per day once complete."""
    ds = day.strftime("%Y%m%d")
    p = Path(cache_dir) / "binance" / f"{ds}.json" if cache_dir else None
    cached = json.loads(p.read_text()) if p is not None and p.exists() else {}
    out, unlisted = {}, []
    for y in symbols:
        if y in cached:
            if cached[y] is not None:
                out[y] = cached[y]
            else:
                unlisted.append(y)
            continue
        bar = binance_bar(binance_symbol(y), day)
        cached[y] = bar
        if bar is None:
            unlisted.append(y)
        else:
            out[y] = bar
    if p is not None and out:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cached))
    df = pd.DataFrame.from_dict(out, orient="index", columns=["open", "high", "low", "close", "volume"])
    df.index.name = "symbol"
    df.attrs["unlisted"] = sorted(unlisted)
    return df


def upbit_markets() -> list[str]:
    """Every Upbit market code ('KRW-BTC', 'BTC-ETH', 'USDT-XRP')."""
    rows = _get_json(f"{UPBIT}/market/all?is_details=false")
    return [r["market"] for r in rows if isinstance(r, dict) and "market" in r]


def listing(symbols, day: datetime | None = None) -> dict:
    """Where each Yahoo crypto symbol trades: {symbol: {"binance": "BTCUSDT"|None,
    "upbit": ["KRW-BTC", ...]}} (checklist 4.1). Upbit failures leave an empty list."""
    day = day or (datetime.now(timezone.utc) - timedelta(days=1))
    try:
        ups = upbit_markets()
    except ExchangeError as e:
        log.warning("Upbit market list failed: %s", e)
        ups = []
    out = {}
    for y in symbols:
        base = base_symbol(y)
        bsym = binance_symbol(y)
        out[y] = {"binance": bsym if binance_bar(bsym, day) is not None else None,
                  "upbit": sorted(m for m in ups if m.split("-", 1)[1] == base)}
    return out
