"""Crypto exchange public APIs (no key), used to cross-check Yahoo's crypto bars (checklist 4).

Venues, in order: Coinbase Exchange (USD spot) then Kraken (USD spot), both reachable from GitHub's
US runners (Binance answers HTTP 451 there, 2026-10-30). Both publish daily candles on UTC-day
boundaries, the same as Yahoo's 'XXX-USD' bars, so a date compares directly; both quote USD, so
the close is comparable with Yahoo's USD composite to within a venue spread (~1%). Volume is one
venue's and is not compared.

  Coinbase: GET https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start=..&end=..
            -> [[time, low, high, open, close, volume], ...]; unknown product -> 404
  Kraken:   GET https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440&since=<ts>
            -> {"error": [], "result": {"XXBTZUSD": [[time, open, high, low, close, vwap, volume, count], ...]}}
  Upbit:    GET https://api.upbit.com/v1/market/all  (KRW/BTC/USDT markets; listing information only)
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("swing.exchange")

COINBASE = "https://api.exchange.coinbase.com"
KRAKEN = "https://api.kraken.com/0/public"
UPBIT = "https://api.upbit.com/v1"
VENUES = ("coinbase", "kraken")
_YAHOO_RE = re.compile(r"^([A-Za-z_]+?)\d*-USD$")      # UNI7083-USD -> UNI, FIGR_HELOC-USD -> FIGR_HELOC
_KRAKEN_ALIAS = {"BTC": "XBT", "DOGE": "XDG"}


class ExchangeError(Exception):
    pass


def base_symbol(yahoo: str) -> str:
    m = _YAHOO_RE.match(yahoo.strip())
    return (m.group(1) if m else yahoo.split("-")[0]).upper()


def coinbase_product(yahoo: str) -> str:
    return base_symbol(yahoo) + "-USD"


def kraken_pair(yahoo: str) -> str:
    b = base_symbol(yahoo)
    return _KRAKEN_ALIAS.get(b, b) + "USD"


def _get(url: str, timeout: float = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "beomstar-swing/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _get_json(url: str, timeout: float = 30):
    try:
        status, body = _get(url, timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except Exception:                          # noqa: BLE001
            msg = ""
        raise ExchangeError(f"HTTP {e.code} {msg}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExchangeError(f"network: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(body)
    except ValueError:
        raise ExchangeError(f"not JSON (HTTP {status})") from None


def _day_start(day: datetime) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def coinbase_bar(product: str, day: datetime) -> dict | None:
    """The UTC daily candle of a Coinbase product ('BTC-USD') on `day`, or None when the product
    does not exist or the day has no candle. Raises ExchangeError for other failures."""
    t0 = _day_start(day)
    url = (f"{COINBASE}/products/{product}/candles?granularity=86400"
           f"&start={t0.isoformat().replace('+00:00', 'Z')}&end={(t0 + timedelta(days=1)).isoformat().replace('+00:00', 'Z')}")
    try:
        rows = _get_json(url)
    except ExchangeError as e:
        if "HTTP 404" in str(e):
            return None
        raise
    ts = int(t0.timestamp())
    for k in rows or []:
        if int(k[0]) == ts:
            return {"open": float(k[3]), "high": float(k[2]), "low": float(k[1]), "close": float(k[4]), "volume": float(k[5])}
    return None


def kraken_bar(pair: str, day: datetime) -> dict | None:
    """The UTC daily candle of a Kraken pair ('XBTUSD') on `day`, or None when the pair is unknown
    or the day is absent. Raises ExchangeError for other failures."""
    t0 = _day_start(day)
    data = _get_json(f"{KRAKEN}/OHLC?pair={pair}&interval=1440&since={int(t0.timestamp()) - 1}")
    errs = data.get("error") or []
    if errs:
        if any("Unknown asset pair" in e for e in errs):
            return None
        raise ExchangeError("Kraken: " + "; ".join(errs))
    result = data.get("result") or {}
    series = next((v for k, v in result.items() if k != "last"), [])
    ts = int(t0.timestamp())
    for k in series:
        if int(k[0]) == ts:
            return {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[6])}
    return None


def venue_bar(yahoo: str, day: datetime) -> tuple[str | None, dict | None]:
    """(venue, bar) from the first venue that lists the coin; (None, None) when neither does."""
    bar = coinbase_bar(coinbase_product(yahoo), day)
    if bar is not None:
        return "coinbase", bar
    bar = kraken_bar(kraken_pair(yahoo), day)
    if bar is not None:
        return "kraken", bar
    return None, None


def bars_on(symbols, day: datetime, cache_dir=None) -> pd.DataFrame:
    """OHLCV of every Yahoo crypto symbol in `symbols` on `day`, indexed by the Yahoo symbol, with a
    'venue' column; symbols listed on no venue are left out and named in df.attrs['unlisted'].
    Cached per day once fetched (a coin missing on the day is cached as None too)."""
    ds = day.strftime("%Y%m%d")
    p = Path(cache_dir) / "exchange" / f"{ds}.json" if cache_dir else None
    cached = json.loads(p.read_text()) if p is not None and p.exists() else {}
    out, unlisted = {}, []
    for y in symbols:
        if y not in cached:
            venue, bar = venue_bar(y, day)
            cached[y] = None if bar is None else dict(bar, venue=venue)
        if cached[y] is None:
            unlisted.append(y)
        else:
            out[y] = cached[y]
    if p is not None and out:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cached))
    df = pd.DataFrame.from_dict(out, orient="index", columns=["open", "high", "low", "close", "volume", "venue"])
    df.index.name = "symbol"
    df.attrs["unlisted"] = sorted(unlisted)
    return df


def upbit_markets() -> list[str]:
    """Every Upbit market code ('KRW-BTC', 'BTC-ETH', 'USDT-XRP')."""
    rows = _get_json(f"{UPBIT}/market/all?is_details=false")
    return [r["market"] for r in rows if isinstance(r, dict) and "market" in r]


def listing(symbols, day: datetime | None = None) -> dict:
    """Where each Yahoo crypto symbol trades (checklist 4.1): {symbol: {"coinbase": product|None,
    "kraken": pair|None, "upbit": [markets]}}. Upbit failures leave an empty list."""
    day = day or (datetime.now(timezone.utc) - timedelta(days=1))
    try:
        ups = upbit_markets()
    except ExchangeError as e:
        log.warning("Upbit market list failed: %s", e)
        ups = []
    out = {}
    for y in symbols:
        base = base_symbol(y)
        cb, kr = coinbase_product(y), kraken_pair(y)
        out[y] = {"coinbase": cb if coinbase_bar(cb, day) is not None else None,
                  "kraken": kr if kraken_bar(kr, day) is not None else None,
                  "upbit": sorted(m for m in ups if m.split("-", 1)[1] == base)}
    return out
