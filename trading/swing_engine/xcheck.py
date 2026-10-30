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


def compare_bars(yahoo: pd.DataFrame, exchange: pd.DataFrame, date: pd.Timestamp, tolerance=TOLERANCE) -> dict:
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
        for f in FIELDS:
            if f not in row or f not in ex:
                continue
            r = _rel(row[f], ex[f])
            if r is not None and r > tolerance[f]:
                mism.append({"symbol": sym, "field": f, "yahoo": float(row[f]), "krx": float(ex[f]),
                             "diff_pct": round(r * 100, 3)})
    return {"date": date.strftime("%Y-%m-%d"), "compared": compared, "missing_in_krx": sorted(missing),
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


def summary_line(rec: dict | None) -> str:
    """One Korean line for report.md and the signal alert."""
    if not rec:
        return "- 데이터 대조: 없음 (KRX 키 미설정)"
    if rec["status"] == "error":
        return f"- 데이터 대조 (KRX): 실패 — {rec['error']}"
    if rec["status"] == "not_published":
        return f"- 데이터 대조 (KRX): {rec['as_of']} 봉은 거래소 미공개(T-1 규칙), 전일 봉도 없음"
    s = rec["symbols"]
    n_bad = len({m["symbol"] for m in s["mismatches"]})
    idx = rec["index"]
    idx_txt = ("지수 일치" if idx and idx["match"] else
               f"지수 불일치 Yahoo {idx['yahoo_close']:,.2f} vs KRX {idx['krx_close']:,.2f}" if idx else "지수 비교 불가")
    line = (f"- 데이터 대조 (KRX, {rec['checked']} 봉): 종목 {s['compared']}개 비교, 불일치 {n_bad}개"
            f"{', KRX에 없음 ' + str(len(s['missing_in_krx'])) + '개' if s['missing_in_krx'] else ''} · {idx_txt}")
    for m in s["mismatches"][:8]:
        line += f"\n  - {m['symbol']} {m['field']}: Yahoo {m['yahoo']:,.0f} vs KRX {m['krx']:,.0f} ({m['diff_pct']:+.2f}%)"
    if len(s["mismatches"]) > 8:
        line += f"\n  - … 외 {len(s['mismatches']) - 8}건 (xcheck/{rec['checked']}.json)"
    return line
