"""Yahoo vs KRX cross-check of the bars the ledger used (checklist 1.5; grade 1: observation only).

For a Korean market the ledger compares the Yahoo bars it computed with against the exchange's
own daily figures. KRX publishes T-1, so the day being signalled (as_of) is normally not yet
available and the previous session is what gets verified; a difference there is what caught the
2026-10-06 incident (Yahoo revised KOSDAQ volumes during the next session). Results go to
paper/<market>/xcheck/<date>.json and one line of the report. Signals are never changed.
"""
from __future__ import annotations

import logging

import pandas as pd

from . import krx

log = logging.getLogger("swing.xcheck")

# relative tolerance per field: KRX prices are exact KRW integers, Yahoo normally agrees to the won;
# volume differs when one side counts after-hours or revises (10-06: 1.38x -> 1.41x = 2.2%)
TOLERANCE = {"open": 0.001, "high": 0.001, "low": 0.001, "close": 0.001, "volume": 0.01}
FIELDS = ("open", "high", "low", "close", "volume")


def _rel(a, b) -> float | None:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    if a == b:
        return 0.0
    base = max(abs(a), abs(b))
    return abs(a - b) / base if base else None


def compare_bars(yahoo: pd.DataFrame, exchange: pd.DataFrame, date: pd.Timestamp, tolerance=TOLERANCE,
                 fields=FIELDS) -> dict:
    """Compare one date across symbols. `yahoo` is {symbol: bars frame}-like (DataFrame with a
    MultiIndex is not needed: pass the per-symbol rows already selected, see `bars_on`);
    `exchange` is indexed by symbol with the same columns. Returns counts and the mismatches."""
    mism, compared, missing = [], 0, []
    for sym, row in yahoo.iterrows():
        if sym not in exchange.index:
            missing.append(sym)
            continue
        compared += 1
        ex = exchange.loc[sym]
        for f in fields:
            if f not in row or f not in ex or f not in tolerance:
                continue
            r = _rel(row[f], ex[f])
            if r is not None and r > tolerance[f]:
                mism.append({"symbol": sym, "field": f, "yahoo": float(row[f]), "krx": float(ex[f]),
                             "diff_pct": round(r * 100, 3)})
    return {"date": date.strftime("%Y-%m-%d"), "compared": compared, "missing": sorted(missing),
            "mismatches": mism}


def bars_on(frames: dict, date: pd.Timestamp) -> pd.DataFrame:
    """One row per symbol holding `date`'s bar from the ledger's frames."""
    rows = {}
    for sym, df in frames.items():
        if date in df.index:
            rows[sym] = {f: df.loc[date, f] for f in FIELDS if f in df.columns}
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "symbol"
    return out


def run(market: str, frames: dict, bench: pd.DataFrame, as_of: pd.Timestamp, key: str, cache_dir=None) -> dict:
    """The cross-check record for the ledger: as_of when KRX already has it (rare), else the
    previous session. Never raises: a failed call is recorded as status 'error'."""
    dates = [as_of]
    prev = bench.index[bench.index < as_of]
    if len(prev):
        dates.append(prev[-1])
    rec = {"market": market, "as_of": as_of.strftime("%Y-%m-%d"), "source": "KRX Open API",
           "status": "not_published", "checked": None, "index": None, "symbols": None, "error": None}
    for d in dates:
        ds = d.strftime("%Y%m%d")
        try:
            ex = krx.stock_bars(market, ds, key, cache_dir)
            idx = krx.index_bar(market, ds, key, cache_dir)
        except krx.KRXError as e:
            rec.update(status="error", error=str(e))
            log.warning("KRX cross-check %s %s: %s", market, ds, e)
            return rec
        if len(ex) == 0:
            continue                                   # exchange has not published this date
        sym = compare_bars(bars_on(frames, d), ex, d)
        rec["checked"] = d.strftime("%Y-%m-%d")
        rec["symbols"] = sym
        if idx is not None and d in bench.index:
            yc = float(bench.loc[d, "close"])
            r = _rel(yc, idx["close"])
            rec["index"] = {"yahoo_close": yc, "krx_close": idx["close"],
                            "match": r is not None and r <= TOLERANCE["close"]}
        bad = bool(sym["mismatches"]) or (rec["index"] is not None and not rec["index"]["match"])
        rec["status"] = "mismatch" if bad else "ok"
        return rec
    return rec


KIS_SOURCE = "KIS"


def run_kis(market: str, frames: dict, bench: pd.DataFrame, as_of: pd.Timestamp, cred: dict, cache_dir=None) -> dict:
    """The cross-check record against Korea Investment & Securities for the signal day itself
    (checklist 2.4): KIS serves the day's bar after the close, which KRX cannot (T-1). Same
    tolerances as KRX (exchange figures). Never raises."""
    from . import kis
    rec = {"market": market, "as_of": as_of.strftime("%Y-%m-%d"), "source": KIS_SOURCE,
           "status": "not_published", "checked": None, "index": None, "symbols": None, "error": None}
    try:
        client = kis.Client(cred, cache_dir)
        ex = kis.bars_on(client, market, sorted(frames), as_of, cache_dir)
        idx = kis.index_bar(client, market, as_of)
        rec["calls"] = client.calls
    except kis.KISError as e:
        rec.update(status="error", error=str(e))
        log.warning("KIS cross-check %s %s: %s", market, rec["as_of"], e)
        return rec
    if len(ex) == 0:
        return rec
    sym = compare_bars(bars_on(frames, as_of), ex, as_of)
    sym["missing"] = sorted(set(sym["missing"]) | set(ex.attrs.get("missing", [])))
    rec["checked"] = rec["as_of"]
    rec["symbols"] = sym
    if idx is not None and as_of in bench.index:
        yc = float(bench.loc[as_of, "close"])
        r = _rel(yc, idx["close"])
        rec["index"] = {"yahoo_close": yc, "krx_close": idx["close"], "match": r is not None and r <= TOLERANCE["close"]}
    bad = bool(sym["mismatches"]) or (rec["index"] is not None and not rec["index"]["match"])
    rec["status"] = "mismatch" if bad else "ok"
    return rec


# One venue's USD price vs Yahoo's USD composite across venues: 1% on the close is a sanity
# bound (a wrong bar, a stale day), not a tick-level check; volume is not comparable.
CRYPTO_TOLERANCE = {"close": 0.01}
CRYPTO_SOURCE = "Coinbase/Kraken"


def run_crypto(frames: dict, bench: pd.DataFrame, as_of: pd.Timestamp, cache_dir=None) -> dict:
    """The cross-check record for the crypto ledger against Coinbase, then Kraken (checklist 4).
    Yahoo's crypto as_of is the last complete UTC day and the venues have that candle at once, so
    as_of itself is compared. Coins on neither venue are listed as missing. Never raises."""
    from . import exchange
    rec = {"market": "CRYPTO", "as_of": as_of.strftime("%Y-%m-%d"), "source": CRYPTO_SOURCE,
           "status": "not_published", "checked": None, "index": None, "symbols": None, "error": None}
    syms = sorted(frames)
    try:
        ex = exchange.bars_on(syms, as_of.to_pydatetime(), cache_dir)
        _, bidx = exchange.venue_bar("BTC-USD", as_of.to_pydatetime())
    except exchange.ExchangeError as e:
        rec.update(status="error", error=str(e))
        log.warning("crypto cross-check %s: %s", rec["as_of"], e)
        return rec
    if len(ex) == 0:
        return rec
    sym = compare_bars(bars_on(frames, as_of), ex, as_of, CRYPTO_TOLERANCE, ("close",))
    sym["missing"] = sorted(set(sym["missing"]) | set(ex.attrs.get("unlisted", [])))
    sym["venues"] = {v: int(n) for v, n in ex["venue"].value_counts().items()} if "venue" in ex else {}
    rec["checked"] = rec["as_of"]
    rec["symbols"] = sym
    if bidx is not None and as_of in bench.index:
        yc = float(bench.loc[as_of, "close"])
        r = _rel(yc, bidx["close"])
        rec["index"] = {"yahoo_close": yc, "krx_close": bidx["close"], "match": r is not None and r <= CRYPTO_TOLERANCE["close"]}
    bad = bool(sym["mismatches"]) or (rec["index"] is not None and not rec["index"]["match"])
    rec["status"] = "mismatch" if bad else "ok"
    return rec


TIINGO_SOURCE = "Tiingo"


def run_tiingo(market: str, frames: dict, bench: pd.DataFrame, as_of: pd.Timestamp, tok: str, cache_dir=None,
               focus=(), sample_n: int | None = None) -> dict:
    """The cross-check record for a US market against Tiingo end-of-day bars (checklist 3.4):
    as_of when Tiingo already has it, else the previous session. Only a sample of the universe is
    compared (free-tier caps, see tiingo.py): `focus` (held and pending symbols) plus a rotating
    slice. No index comparison (Tiingo serves no index on the free tier). Never raises."""
    from . import tiingo
    rec = {"market": market, "as_of": as_of.strftime("%Y-%m-%d"), "source": TIINGO_SOURCE,
           "status": "not_published", "checked": None, "index": None, "symbols": None, "error": None, "calls": 0}
    n = tiingo.SAMPLE if sample_n is None else sample_n
    dates = [as_of]
    prev = bench.index[bench.index < as_of]
    if len(prev):
        dates.append(prev[-1])
    for d in dates:
        syms = tiingo.sample(frames, d, n, focus)
        try:
            ex = tiingo.bars_on(market, syms, d, tok, cache_dir)
        except tiingo.TiingoError as e:
            rec.update(status="error", error=str(e))
            log.warning("Tiingo cross-check %s %s: %s", market, d.date(), e)
            return rec
        rec["calls"] += ex.attrs.get("calls", 0)
        if len(ex) == 0:
            continue                                   # Tiingo has not published this date yet
        sym = compare_bars(bars_on(frames, d), ex, d)
        sym["missing"] = sorted(set(sym["missing"]) | set(ex.attrs.get("missing", [])))
        sym["unlisted"] = ex.attrs.get("unlisted", [])
        sym["sampled"] = len(syms)
        sym["focus"] = sorted(set(focus) & set(frames))
        rec["checked"] = d.strftime("%Y-%m-%d")
        rec["symbols"] = sym
        rec["status"] = "mismatch" if sym["mismatches"] else "ok"
        return rec
    return rec


def summary_line(rec: dict | None) -> str:
    """One Korean line for report.md and the signal alert."""
    if not rec:
        return "- 데이터 대조: 없음 (KRX 키 미설정)"
    crypto = rec.get("market") == "CRYPTO"
    src = rec.get("source", "KRX") if (crypto or rec.get("source") in (KIS_SOURCE, TIINGO_SOURCE)) else "KRX"
    bench_word = "BTC" if crypto else "지수"
    if rec["status"] == "error":
        return f"- 데이터 대조 ({src}): 실패 — {rec['error']}"
    if rec["status"] == "not_published":
        return (f"- 데이터 대조 ({src}): {rec['as_of']} 봉 없음"
                + (" (거래소 미공개, T-1 규칙; 전일 봉도 없음)" if src == "KRX" else ""))
    s = rec["symbols"]
    n_bad = len({m["symbol"] for m in s["mismatches"]})
    idx = rec["index"]
    idx_txt = (f"{bench_word} 일치" if idx and idx["match"] else
               f"{bench_word} 불일치 Yahoo {idx['yahoo_close']:,.2f} vs {src} {idx['krx_close']:,.2f}" if idx
               else f"{bench_word} 비교 불가")
    missing = s.get("missing", [])
    sampled = f" (표본 {s['sampled']}: 보유·대기 {len(s.get('focus', []))} + 순환)" if s.get("sampled") is not None else ""
    idx_txt = idx_txt if src != TIINGO_SOURCE else "지수 비교 안 함"
    line = (f"- 데이터 대조 ({src}, {rec['checked']} 봉" + (", 종가 ±1%" if crypto else "") + "): "
            f"종목 {s['compared']}개 비교{sampled}, 불일치 {n_bad}개"
            f"{', ' + src + '에 없음 ' + str(len(missing)) + '개 (' + ', '.join(missing) + ')' if missing else ''} · {idx_txt}")
    fmt = "{:,.4g}" if crypto else "{:,.0f}"
    for m in s["mismatches"][:8]:
        line += (f"\n  - {m['symbol']} {m['field']}: Yahoo {fmt.format(m['yahoo'])} vs {src} {fmt.format(m['krx'])}"
                 f" ({m['diff_pct']:+.2f}%)")
    if len(s["mismatches"]) > 8:
        line += f"\n  - … 외 {len(s['mismatches']) - 8}건 (xcheck/{rec['checked']}.json)"
    return line
