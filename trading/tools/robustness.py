"""Robustness study of the swing rules on a data snapshot (tools/snapshot_data.py output).

    python tools/robustness.py --data DATA_DIR --out OUT_DIR [--markets SP500 ...] [--jobs 4]
                               [--random-reps 30] [--parts baseline,variants,edge,random,pit]

Per market, in OUT_DIR/<MARKET>/:
  baseline.json, trades.csv, equity.csv   the rules as they are (RS percentile >= 70)
  variants/<n>.json                        one parameter (or the cost) changed at a time
  edge.json                                signal-level test against date-matched random entries
  random/<pool>_<i>.json                   portfolio runs with random entries on the signal dates
  pit.json                                 S&P 500 only: point-in-time index members
Every run covers the same test window as the published backtest (TEST_START to the last bar).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine.indicators import align_asof, compute_indicators, finalize_signals, normalize_bars  # noqa: E402
from swing_engine.params import COST_PCT, resolve  # noqa: E402
from swing_engine.portfolio import PortfolioConfig, period_metrics, prepare_frames, simulate  # noqa: E402

MARKETS = ["SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO"]
TEST_START = "2016-09-25"
SPLIT = "2021-09-25"            # halves: TEST_START..SPLIT-1, SPLIT..end
BIG = 20.0
_DATA: dict = {}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load(data_dir: str, market: str):
    key = (data_dir, market)
    if key not in _DATA:
        snap = pd.read_pickle(Path(data_dir) / f"{market}.pkl.xz", compression="xz")
        cur = {t: snap["frames"][t] for t in snap["universe"] if t in snap["frames"]}
        _DATA[key] = (snap, cur, snap["bench"])
    return _DATA[key]


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return o


def _write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(obj), ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------
# portfolio runs and their summary
# ---------------------------------------------------------------------------

def _cfg(params, rs_min=70.0, cost=COST_PCT):
    return PortfolioConfig(params=params, rs_mode="percentile", rs_percentile_min=rs_min,
                           cost_pct=cost, test_start=TEST_START)


def summarize(res, bench: pd.DataFrame, market: str) -> dict:
    eq = res.equity
    if len(eq) == 0:
        return {}
    bclose = normalize_bars(bench, require_ohlc=False)["close"]
    first, last = eq.index[0], eq.index[-1]
    split = pd.Timestamp(SPLIT)
    out = {"full": period_metrics(eq, res.trades, bclose, first, last),
           "h1": period_metrics(eq, res.trades, bclose, first, split - pd.Timedelta(days=1)),
           "h2": period_metrics(eq, res.trades, bclose, split, last)}
    ann = 365 if market == "CRYPTO" else 252
    r = eq["equity"].pct_change().dropna()
    b = align_asof(bclose.to_frame("close"), eq.index)["close"]
    br = b.pct_change().dropna()
    bdd = (b / b.cummax() - 1).min() * 100
    out["risk"] = {
        "sharpe": float(r.mean() / r.std() * math.sqrt(ann)) if r.std() > 0 else None,
        "bench_sharpe": float(br.mean() / br.std() * math.sqrt(ann)) if br.std() > 0 else None,
        "vol_pct": float(r.std() * math.sqrt(ann) * 100),
        "bench_vol_pct": float(br.std() * math.sqrt(ann) * 100),
        "bench_mdd_pct": float(bdd),
    }
    f = out["full"]
    out["risk"]["calmar"] = (f["cagr_pct"] / -f["max_drawdown_pct"]) if f["max_drawdown_pct"] else None
    bench_cagr = f["bench_cagr_pct"]
    out["risk"]["bench_calmar"] = bench_cagr / -bdd if bdd else None
    t = res.trades
    if len(t):
        out["trades"] = {"n": int(len(t)), "per_year": len(t) / ((last - first).days / 365.25),
                         "avg_bars_held": float(t["bars_held"].mean()),
                         "median_bars_held": float(t["bars_held"].median()),
                         "big_win_rate_pct": float((t["pnl_pct"] > BIG).mean() * 100),
                         "top10_profit_share_pct": float(t["net_pnl"].nlargest(10).sum() / t["net_pnl"].sum() * 100)
                         if t["net_pnl"].sum() > 0 else None}
    return out


def run_variant(job):
    data_dir, out_dir, market, n, label, overrides, rs_min, cost = job[:8]
    pit = len(job) > 8 and job[8]
    path = Path(out_dir) / market / ("variants_pit" if pit else "variants") / f"{n:02d}.json"
    if path.exists():
        return str(path)
    snap, frames, bench = load(data_dir, market)
    params = resolve(market, **overrides)
    cfg = _cfg(params, rs_min, cost)
    if pit:
        frames = dict(snap["frames"])
        dates = normalize_bars(bench, require_ohlc=False).index
        rdates, sets = membership_rows(market, Path(data_dir) / MEMBERSHIP_FILES[market], sorted(frames))
        prep = prepare_pit(frames, bench, cfg, membership_mask(rdates, sets, dates, sorted(frames)))
    else:
        prep = prepare_frames(frames, bench, cfg)
    res = simulate(prep, cfg)
    s = summarize(res, bench, market)
    _write(path, {"label": label, "overrides": overrides, "rs_min": rs_min, "cost_pct": cost, "pit": bool(pit), **s})
    if n == 0:
        root = Path(out_dir) / market
        sfx = "_pit" if pit else ""
        if not pit:
            _write(root / "baseline.json", {"label": label, **s})
        res.trades.to_csv(root / f"trades{sfx}.csv", index=False)
        e = res.equity.copy()
        e["bench_close"] = align_asof(normalize_bars(bench, require_ohlc=False)[["close"]], e.index)["close"].to_numpy()
        e.index = pd.DatetimeIndex(e.index).strftime("%Y-%m-%d")
        e.to_csv(root / f"equity{sfx}.csv", index_label="date")
    return str(path)


def variant_jobs(data_dir, out_dir, market) -> list:
    base = resolve(market)
    V = [("기준 (현재 룰)", {}, 70.0, COST_PCT)]
    for s in (5.0, 7.0, 10.0, 15.0):
        if s != base["stop_pct"]:
            V.append((f"손절 −{s:g}%", {"stop_pct": s}, 70.0, COST_PCT))
    for r in (50.0, 60.0, 80.0, 90.0):
        V.append((f"RS 백분위 ≥ {r:g}", {}, r, COST_PCT))
    for v in (1.0, 1.2, 1.7, 2.0):
        V.append((f"거래량 {v:g}배", {"vol_mult": v}, 70.0, COST_PCT))
    for p in (10, 40):
        V.append((f"피벗 {p}봉", {"pivot_len": p}, 70.0, COST_PCT))
    for m in (20, 100):
        V.append((f"청산 {m}일선", {"exit_ma_len": m}, 70.0, COST_PCT))
    V.append(("추격 제한 없음", {"cap_on": False}, 70.0, COST_PCT) if base["cap_on"]
             else ("추격 제한 15%", {"cap_on": True}, 70.0, COST_PCT))
    V.append(("레짐 필터 없음", {"regime_mode": "NONE"}, 70.0, COST_PCT) if base["regime_mode"] != "NONE"
             else ("레짐 필터 (지수 > 200일선)", {"regime_mode": "MA200"}, 70.0, COST_PCT))
    V.append(("템플릿·RS 조건 없음 (돌파만)", {"use_tt": False}, 70.0, COST_PCT))
    for c in (0.1, 0.4, 0.6):
        V.append((f"비용 편도 {c:g}%", {}, 70.0, c))
    return [(data_dir, out_dir, market, i, *v) for i, v in enumerate(V)]


# ---------------------------------------------------------------------------
# signal-level edge test
# ---------------------------------------------------------------------------

def trade_outcomes(f: pd.DataFrame, stop_pct: float, cost_pct: float, start: int):
    """Net return and bars held of a trade signalled at the close of every bar t >= start
    (entry at open[t+1]; stop intraday; close below the exit MA -> exit at the next open).
    Same order of steps as the state machine."""
    o, lo, c, ema = (f[k].to_numpy(float) for k in ("open", "low", "close", "exit_ma"))
    n = len(f)
    below = c < ema                                   # NaN -> False
    nb = np.full(n, n, dtype=np.int64)
    nxt = n
    for j in range(n - 1, -1, -1):
        if below[j]:
            nxt = j
        nb[j] = nxt
    cr = cost_pct / 100.0
    s = stop_pct / 100.0
    ret = np.full(n, np.nan)
    held = np.full(n, np.nan)
    for t in range(max(start, 0), n - 1):
        e = t + 1
        ep = o[e]
        if not ep > 0:
            continue
        stop = ep * (1 - s)
        end = nb[e]
        last = min(end, n - 1)
        hit = np.flatnonzero(lo[e:last + 1] <= stop)
        if hit.size:
            j = e + int(hit[0])
            px = min(o[j], stop) if o[j] == o[j] else stop
            h = j - e
        elif end < n - 1:
            px, h = o[end + 1], end + 1 - e
        else:
            px, h = c[n - 1], n - 1 - e
        if px > 0:
            ret[t] = (px * (1 - cr) / (ep * (1 + cr)) - 1) * 100
            held[t] = h
    return ret, held


def _stats(r: np.ndarray, h: np.ndarray) -> dict:
    pos, neg = r[r > 0].sum(), -r[r <= 0].sum()
    return {"n": int(len(r)), "mean_pct": float(r.mean()), "median_pct": float(np.median(r)),
            "win_rate_pct": float((r > 0).mean() * 100), "big_rate_pct": float((r > BIG).mean() * 100),
            "profit_factor": float(pos / neg) if neg > 0 else None,
            "mean_bars": float(h.mean()), "ret_per_100_bars_pct": float(r.sum() / h.sum() * 100) if h.sum() else None}


def edge_test(data_dir, out_dir, market, reps=2000, seed=7):
    path = Path(out_dir) / market / "edge.json"
    if path.exists():
        return str(path)
    _, frames, bench = load(data_dir, market)
    params = resolve(market)
    prep = prepare_frames(frames, bench, _cfg(params))
    ts = pd.Timestamp(TEST_START)
    rows = []
    for sym, f in prep.items():
        start = int(f.index.searchsorted(ts))
        if start >= len(f) - 1:
            continue
        ret, held = trade_outcomes(f, params["stop_pct"], COST_PCT, start)
        ok = ~np.isnan(ret)
        ok[:start] = False
        idx = np.flatnonzero(ok)
        above = (f["close"] > f["exit_ma"]).to_numpy()
        rows.append(pd.DataFrame({
            "date": f.index[idx], "ret": ret[idx], "held": held[idx],
            "rule": f["full_signal"].to_numpy(bool)[idx],
            "cand": (f["candidate"] & f["regime_on"]).to_numpy(bool)[idx],
            "p0": (f["regime_on"].to_numpy(bool) & above)[idx]}))
    d = pd.concat(rows, ignore_index=True)
    rule = d[d["rule"]]
    out = {"market": market, "rule": _stats(rule["ret"].to_numpy(), rule["held"].to_numpy()), "pools": {}}
    rng = np.random.default_rng(seed)
    need = rule.groupby("date").size()
    for pool_name, col in (("candidates", "cand"), ("above_ma_regime_on", "p0")):
        p = d[d[col]].sort_values("date")
        pdates = p["date"].to_numpy()
        pret, pheld = p["ret"].to_numpy(), p["held"].to_numpy()
        # start/size of each date's block in the sorted pool
        uniq, first = np.unique(pdates, return_index=True)
        size = np.diff(np.append(first, len(pdates)))
        pos = {dt: (a, b) for dt, a, b in zip(uniq, first, size)}
        starts, sizes = [], []
        for dt, k in need.items():
            a, b = pos.get(np.datetime64(dt), (None, 0))
            if b == 0:
                continue
            starts += [a] * int(k)
            sizes += [b] * int(k)
        starts, sizes = np.array(starts), np.array(sizes)
        pick = starts[None, :] + (rng.random((reps, len(starts))) * sizes[None, :]).astype(np.int64)
        R, H = pret[pick], pheld[pick]
        means = R.mean(axis=1)
        bigs = (R > BIG).mean(axis=1) * 100
        wins = (R > 0).mean(axis=1) * 100
        pf = np.where((-np.where(R <= 0, R, 0).sum(axis=1)) > 0,
                      np.where(R > 0, R, 0).sum(axis=1) / (-np.where(R <= 0, R, 0).sum(axis=1)), np.nan)
        rpb = R.sum(axis=1) / H.sum(axis=1) * 100
        r = out["rule"]

        def dist(x, v):
            return {"mean": float(np.nanmean(x)), "p05": float(np.nanpercentile(x, 5)),
                    "p50": float(np.nanpercentile(x, 50)), "p95": float(np.nanpercentile(x, 95)),
                    "rule": v, "rule_percentile": float((x < v).mean() * 100) if v is not None else None}

        out["pools"][pool_name] = {
            "pool_size": int(len(p)), "matched": int(len(starts)),
            "pool_all": _stats(pret, pheld),
            "mean_pct": dist(means, r["mean_pct"]), "big_rate_pct": dist(bigs, r["big_rate_pct"]),
            "win_rate_pct": dist(wins, r["win_rate_pct"]), "profit_factor": dist(pf, r["profit_factor"]),
            "ret_per_100_bars_pct": dist(rpb, r["ret_per_100_bars_pct"])}
    # halves: is the rule's edge over date-matched candidates present in both halves?
    halves = {}
    for name, sel in (("h1", d["date"] < pd.Timestamp(SPLIT)), ("h2", d["date"] >= pd.Timestamp(SPLIT))):
        dd = d[sel]
        halves[name] = {"rule": _stats(dd[dd["rule"]]["ret"].to_numpy(), dd[dd["rule"]]["held"].to_numpy()),
                        "candidates": _stats(dd[dd["cand"]]["ret"].to_numpy(), dd[dd["cand"]]["held"].to_numpy()),
                        "above_ma_regime_on": _stats(dd[dd["p0"]]["ret"].to_numpy(), dd[dd["p0"]]["held"].to_numpy())}
    out["halves"] = halves
    _write(path, out)
    return str(path)


# ---------------------------------------------------------------------------
# portfolio runs with random entries
# ---------------------------------------------------------------------------

def run_random(job):
    """Portfolio runs whose entries are drawn at random from `pool` on each signal date, as many
    per date as the rules had. Everything else (sizing, cash, RS-ordered fills, stops, exits,
    costs) is unchanged, so the gap to the rules is the value of their stock selection."""
    data_dir, out_dir, market, pool, reps = job[:5]
    pit = len(job) > 5 and job[5]
    root = Path(out_dir) / market / "random"
    tag = f"pit_{pool}" if pit else pool
    todo = [i for i in reps if not (root / f"{tag}_{i:03d}.json").exists()]
    if not todo:
        return f"{market} {tag} cached"
    snap, frames, bench = load(data_dir, market)
    params = resolve(market)
    cfg = _cfg(params)
    member = None
    if pit:
        frames = dict(snap["frames"])
        dates = normalize_bars(bench, require_ohlc=False).index
        rdates, sets = membership_rows(market, Path(data_dir) / MEMBERSHIP_FILES[market], sorted(frames))
        member = membership_mask(rdates, sets, dates, sorted(frames))
        prep = prepare_pit(frames, bench, cfg, member)
    else:
        prep = prepare_frames(frames, bench, cfg)
    syms = sorted(prep)
    cal = pd.DatetimeIndex(sorted(set().union(*[f.index for f in prep.values()])))
    cal = cal[cal >= pd.Timestamp(TEST_START)]

    def panel(values):
        return pd.DataFrame({s: values(prep[s]).reindex(cal) for s in syms}).fillna(False).astype(bool)

    K = panel(lambda f: f["full_signal"]).to_numpy().sum(axis=1)
    if pool == "candidates":
        E = panel(lambda f: f["candidate"] & f["regime_on"]).to_numpy()
    else:
        E = panel(lambda f: f["regime_on"] & (f["close"] > f["exit_ma"])).to_numpy()
    if member is not None:
        E = E & member.reindex(index=cal, columns=syms).fillna(False).to_numpy(bool)
    pos = {s: prep[s].index.get_indexer(cal) for s in syms}
    for i in todo:
        rng = np.random.default_rng(1000 + i)
        new = np.zeros_like(E)
        for r in np.flatnonzero(K):
            cand = np.flatnonzero(E[r])
            if len(cand):
                new[r, rng.choice(cand, size=min(int(K[r]), len(cand)), replace=False)] = True
        for j, s in enumerate(syms):
            sig = np.zeros(len(prep[s]), dtype=bool)
            ok = pos[s] >= 0
            sig[pos[s][ok]] = new[ok, j]
            prep[s]["full_signal"] = sig
        res = simulate(prep, cfg)
        _write(root / f"{tag}_{i:03d}.json", {"pool": pool, "pit": bool(pit), "rep": i,
                                              **summarize(res, bench, market)})
    return f"{market} {tag} {len(todo)} runs"


# ---------------------------------------------------------------------------
# S&P 500 point-in-time membership (survivorship bias)
# ---------------------------------------------------------------------------

def membership_rows(market: str, path: Path, symbols) -> tuple[pd.Series, list]:
    """(dates, [set of symbols]) of the index membership file, mapped to snapshot tickers.
    S&P 500 (fja05680/sp500): columns date,tickers with '.' class separators.
    KOSPI/KOSDAQ (tools/krx_membership.py): columns date,codes with 6-digit codes."""
    m = pd.read_csv(path)
    m["date"] = pd.to_datetime(m["date"])
    m = m.sort_values("date").reset_index(drop=True)
    if market == "SP500":
        sets = [set(x.strip().upper().replace(".", "-") for x in s.split(",")) for s in m["tickers"]]
    else:
        by_code = {}
        for s in symbols:
            by_code.setdefault(s.split(".")[0], s)
        sets = [set(by_code[c] if c in by_code else c for c in s.split(",")) for s in m["codes"]]
    return m["date"], sets


def membership_mask(rows_dates: pd.Series, sets: list, dates: pd.DatetimeIndex, symbols) -> pd.DataFrame:
    pos = np.searchsorted(rows_dates.to_numpy(), dates.to_numpy(), side="right") - 1
    out = np.zeros((len(dates), len(symbols)), dtype=bool)
    col = {s: j for j, s in enumerate(symbols)}
    for i, p in enumerate(pos):
        if p < 0:
            continue
        for s in sets[p]:
            j = col.get(s)
            if j is not None:
                out[i, j] = True
    return pd.DataFrame(out, index=dates, columns=list(symbols))


def prepare_pit(frames: dict, bench, cfg, member: pd.DataFrame) -> dict:
    """prepare_frames with the RS percentile ranked among index members of the day and
    entries allowed only while the symbol is a member."""
    p = cfg.params
    b = normalize_bars(bench, require_ohlc=False)
    inds, bars = {}, {}
    for s, df in frames.items():
        d = normalize_bars(df)
        if len(d) == 0:
            continue
        bars[s] = d
        inds[s] = compute_indicators(d, b, p)
    panel = pd.DataFrame({s: ind["wp"] for s, ind in inds.items()})
    mem = member.reindex(index=panel.index, columns=panel.columns).fillna(False).astype(bool)
    pct = panel.where(mem).rank(axis=1, pct=True) * 100
    out = {}
    for s, ind in inds.items():
        pr = pct[s].reindex(ind.index)
        finalize_signals(ind, p, tt8_override=pr >= cfg.rs_percentile_min)
        ind["full_signal"] = ind["full_signal"] & mem[s].reindex(ind.index).fillna(False).to_numpy()
        ind["rs_pct"] = pr
        ind["rs_key"] = pr
        out[s] = pd.concat([bars[s][["open", "high", "low", "close", "volume"]], ind], axis=1)
    return out


MEMBERSHIP_FILES = {"SP500": "sp500_membership.csv", "KOSPI": "KOSPI_membership.csv.gz",
                    "KOSDAQ": "KOSDAQ_membership.csv.gz"}


def pit_study(data_dir, out_dir, market):
    """The rules on the index universe of each day (point in time) instead of today's members."""
    path = Path(out_dir) / market / "pit.json"
    mfile = Path(data_dir) / MEMBERSHIP_FILES[market]
    if path.exists() or not mfile.exists():
        return str(path) if path.exists() else f"{market}: no membership file"
    snap, cur, bench = load(data_dir, market)
    frames_all = dict(snap["frames"])
    params = resolve(market)
    cfg = _cfg(params)
    dates = normalize_bars(bench, require_ohlc=False).index
    rdates, sets = membership_rows(market, mfile, sorted(frames_all))
    member = membership_mask(rdates, sets, dates, sorted(frames_all))
    cov = {}
    in_test = rdates >= pd.Timestamp(TEST_START)
    for y in sorted(set(rdates[in_test].dt.year)):
        idx = np.flatnonzero(in_test.to_numpy() & (rdates.dt.year == y).to_numpy())
        names = set().union(*[sets[i] for i in idx])
        have = sum(1 for s in names if s in frames_all)
        cov[str(y)] = {"members_during_year": len(names), "with_data": have,
                       "coverage_pct": have / len(names) * 100}
    ever = set().union(*[sets[i] for i in np.flatnonzero(in_test.to_numpy())])
    missing = sorted(s for s in ever if s not in frames_all)
    res_pit = simulate(prepare_pit(frames_all, bench, cfg, member), cfg)
    cur_only = {s: f for s, f in frames_all.items() if s in cur}
    res_cur_pit = simulate(prepare_pit(cur_only, bench, cfg, member), cfg)
    _write(path, {"market": market, "coverage_by_year": cov, "members_since_test_start": len(ever),
                  "members_without_data": len(missing), "missing_sample": missing[:80],
                  "pit": summarize(res_pit, bench, market),
                  "current_members_pit_rule": summarize(res_cur_pit, bench, market)})
    res_pit.trades.to_csv(Path(out_dir) / market / "pit_trades.csv", index=False)
    return str(path)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--markets", nargs="*", default=MARKETS)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--random-reps", type=int, default=30)
    ap.add_argument("--parts", default="baseline,variants,edge,random,pit")
    a = ap.parse_args()
    parts = set(a.parts.split(","))
    jobs = []
    for mk in a.markets:
        vj = variant_jobs(a.data, a.out, mk)
        if "variants" in parts:
            jobs += vj
        elif "baseline" in parts:
            jobs += vj[:1]
    with Pool(a.jobs) as pool:
        for p in pool.imap_unordered(run_variant, jobs):
            print("done", p, flush=True)
        if "edge" in parts:
            for p in pool.starmap(edge_test, [(a.data, a.out, mk) for mk in a.markets]):
                print("done", p, flush=True)
        if "random" in parts:
            # chunks of 25 runs per job: one indicator pass per chunk
            rj = [(a.data, a.out, mk, pl, list(range(k, min(k + 25, a.random_reps))))
                  for mk in a.markets for pl in ("candidates", "above_ma") for k in range(0, a.random_reps, 25)]
            for p in pool.imap_unordered(run_random, rj):
                print("done", p, flush=True)
    if "pit" in parts:
        for mk in a.markets:
            if mk in MEMBERSHIP_FILES:
                print("done", pit_study(a.data, a.out, mk), flush=True)
    if "pit_variants" in parts:
        vj = [(*j, True) for mk in a.markets if mk in MEMBERSHIP_FILES and (Path(a.data) / MEMBERSHIP_FILES[mk]).exists()
              for j in variant_jobs(a.data, a.out, mk)]
        with Pool(a.jobs) as pool:
            for p in pool.imap_unordered(run_variant, vj):
                print("done", p, flush=True)
    if "pit_random" in parts:
        rj = [(a.data, a.out, mk, pl, list(range(k, min(k + 25, a.random_reps))), True)
              for mk in a.markets if mk in MEMBERSHIP_FILES and (Path(a.data) / MEMBERSHIP_FILES[mk]).exists()
              for pl in ("candidates", "above_ma") for k in range(0, a.random_reps, 25)]
        with Pool(a.jobs) as pool:
            for p in pool.imap_unordered(run_random, rj):
                print("done", p, flush=True)


if __name__ == "__main__":
    main()
