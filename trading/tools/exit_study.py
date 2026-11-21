"""Can an exit change raise the win rate without costing the return?

    python tools/exit_study.py --data DATA_DIR --out OUT_DIR \
        [--market KOSDAQ] [--other KOSPI] [--reps 40] [--drop-pct 10] [--jobs 4]

The rules have no profit target: about one trade in four wins and the winners pay for the rest.
Every upgrade tested so far changed the ENTRY (tools/upgrade_study.py) and moved the win rate by
1-2pp. This tool tests the other side, the exits that are known to raise a win rate - a profit
target, a partial sale, a stop moved to the entry price, a faster exit line - one at a time, on the
point-in-time universe (tools/robustness.py, prepare_pit). Entry signals are never changed.

Research tooling only: it has its own day loop (simulate_exits) and touches neither the engine,
the ledger nor the rules. With an empty rule the loop is the engine's loop: the tests and every
real run compare it with swing_engine.portfolio.simulate trade by trade before anything is read.

R is the stop distance of the market (KOSDAQ 10%, KOSPI 7%): "+2R" is entry x (1 + 2 x stop%).

Hypotheses, fixed on 2026-11-21 before the first run (docs/swing-exit-study-prereg-2026-11.md):

  E1  sell everything at +1R            E6  stop to the entry price after +1R
  E2  sell everything at +2R            E7  stop to the entry price after +2R
  E3  sell everything at +3R            E8  E7 and sell half at +3R
  E4  sell half at +2R                  E9  exit on a close below the 20-day MA (not the 50-day)
  E5  sell half at +3R                  E10 exit on a close below the 10-day MA

Inside one daily bar the order of the high and the low is unknown. The order is fixed against the
variant: the stop in force at the start of the bar is checked first, then the target; a stop moved
to the entry price counts from the next bar. A target is a resting limit order: it fills at the
target, or at the open when the open is already above it. A position is one trade whatever the
number of sales, and it is a win when its total net result is above zero (the engine's definition).

Every hypothesis is run on the unperturbed data and on the paired paths of tools/path_noise.py
(same seed, so the baseline paths are those of 2026-11-13): each repetition applies one
perturbation and runs the baseline and all ten variants on it.

Criteria, fixed with the hypotheses (KOSDAQ decides; `verdict` below is the only reading):

  S1  win rate >= baseline + 5.0pp on the unperturbed data
  P1  in BOTH perturbations: the paired win-rate difference is above 0 in >= 95% of the paths
      and its median is >= +5.0pp
  P2  in BOTH perturbations: the median paired CAGR difference is >= -1.0pp
  P3  in BOTH perturbations: the median paired max-drawdown difference is >= -3.0pp
  P4  unperturbed: the win rate is above the baseline's in both halves, and the excess return
      over the index is >= baseline - 2.0pp in both halves
  P5  the other market (KOSPI), unperturbed: CAGR >= its baseline - 3.0pp

  "win rate up, return kept"      S1 and P1..P5
  "win rate up, return damaged"   S1 and P1, but one of P2..P5 fails
  "win rate not raised"           S1 or P1 fails
  and, for reading, "return up as well" when the 5th percentile of the paired CAGR difference is
  above 0 in both perturbations (the rule of 2026-11-13).

Writes OUT_DIR/exit_study.json and prints the tables.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import path_noise as P                                          # noqa: E402

BASE_COLS = ["open", "high", "low", "close", "exit_ma", "full_signal", "rs_key"]
EXIT_LENS = (20, 10)                                            # E9, E10
WIN_GAIN_PP, WIN_AHEAD_PCT = 5.0, 95.0
CAGR_SLACK_PP, MDD_SLACK_PP, HALF_SLACK_PP, OTHER_SLACK_PP = 1.0, 3.0, 2.0, 3.0
EPS = 1e-9
METRICS = ("win_rate_pct", "cagr_pct", "max_drawdown_pct", "profit_factor", "excess_cagr_pp")
_W: dict = {}


@dataclass(frozen=True)
class ExitRule:
    """One exit variant. All fields off is the current rule."""
    target_r: float | None = None        # sell at entry x (1 + target_r x stop%)
    target_frac: float = 1.0             # share of the position sold at the target (1.0 = all)
    breakeven_r: float | None = None     # after a bar whose high reached this, stop = entry price
    exit_col: str = "exit_ma"            # the exit line: a close below it sells at the next open


RULES = {
    "E0_base": ("기준 (현재 룰)", ExitRule()),
    "E1_target1R": ("+1R 전량 익절", ExitRule(target_r=1.0)),
    "E2_target2R": ("+2R 전량 익절", ExitRule(target_r=2.0)),
    "E3_target3R": ("+3R 전량 익절", ExitRule(target_r=3.0)),
    "E4_half2R": ("+2R 절반 익절", ExitRule(target_r=2.0, target_frac=0.5)),
    "E5_half3R": ("+3R 절반 익절", ExitRule(target_r=3.0, target_frac=0.5)),
    "E6_be1R": ("+1R 뒤 본전 손절", ExitRule(breakeven_r=1.0)),
    "E7_be2R": ("+2R 뒤 본전 손절", ExitRule(breakeven_r=2.0)),
    "E8_be2R_half3R": ("+2R 뒤 본전 손절 + +3R 절반 익절", ExitRule(target_r=3.0, target_frac=0.5, breakeven_r=2.0)),
    "E9_exit20": ("청산 20일선", ExitRule(exit_col="exit_ma_20")),
    "E10_exit10": ("청산 10일선", ExitRule(exit_col="exit_ma_10")),
}
BASE = "E0_base"


def simulate_exits(frames: dict, cfg, rule: ExitRule = ExitRule()):
    """swing_engine.portfolio.simulate with the exit variants of `rule`. With an empty rule every
    step is the engine's (pending exits at the open, entries by RS within cash, stop then exit
    line, mark, new signals); paper-trading overrides are left out."""
    from swing_engine.portfolio import PortfolioResult, _cfg_dict, _d
    from swing_engine.data import truncate
    from swing_engine.sizing import position_qty
    from swing_engine.state import NAN, PositionMachine
    p = cfg.params
    stop_pct = float(p["stop_pct"])
    c_rate = float(cfg.cost_pct) / 100.0
    whole = cfg.whole_shares
    frac = float(rule.target_frac)
    if not 0.0 < frac <= 1.0:
        raise ValueError("target_frac must be in (0, 1]")
    syms = sorted(frames)
    S = len(syms)
    empty = PortfolioResult(pd.DataFrame(columns=["cash", "positions_value", "equity", "exposure_pct", "n_positions"]),
                            pd.DataFrame(), pd.DataFrame(), config=_cfg_dict(cfg))
    if S == 0:
        return empty
    frames = {s: truncate(frames[s], cfg.as_of) for s in syms}
    cal = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
    if cfg.test_start is not None:
        cal = cal[cal >= pd.Timestamp(cfg.test_start)]
    if len(cal) == 0:
        return empty

    def panel(col, fill=np.nan, dtype=float):
        arr = np.full((len(cal), S), fill, dtype=dtype)
        for j, s in enumerate(syms):
            v = frames[s][col].reindex(cal).to_numpy()
            arr[:, j] = pd.Series(v).fillna(False).astype(bool).to_numpy() if dtype is bool else v.astype(float)
        return arr

    O, H, L, C = panel("open"), panel("high"), panel("low"), panel("close")
    EMA, RS = panel(rule.exit_col), panel("rs_key")
    SIG = panel("full_signal", False, bool)
    HAS = (C > 0) & (O > 0) & (L > 0)

    last_close = np.full(S, np.nan)
    for j, s in enumerate(syms):
        pre = frames[s]["close"]
        pre = pre[pre.index < cal[0]].dropna()
        if len(pre):
            last_close[j] = pre.iloc[-1]

    machines = [PositionMachine(stop_pct=stop_pct) for _ in syms]
    qty = np.zeros(S)
    pending: dict[int, dict] = {}
    open_tr: dict[int, dict] = {}
    trades, skipped, rows = [], [], []
    cash = float(cfg.initial_equity)

    def sell(j, q, price):
        """Sell q shares of position j: cash in, proceeds and costs booked on the trade."""
        nonlocal cash
        tr = open_tr[j]
        proceeds = q * price * (1 - c_rate)
        cash += proceeds
        tr["_proceeds"] += proceeds
        tr["_exit_cost"] += q * price * c_rate
        qty[j] -= q

    def close_trade(j, d, price, kind):
        sell(j, qty[j], price)
        tr = open_tr.pop(j)
        cost_basis = tr["cost_basis"]
        net = tr.pop("_proceeds") - cost_basis
        tr.update(exit_date=_d(d), exit_price=float(price), exit_type=kind,
                  exit_cost=tr.pop("_exit_cost"), net_pnl=net,
                  pnl_pct=net / cost_basis * 100 if cost_basis else np.nan,
                  price_pnl_pct=(price / tr["entry_price"] - 1) * 100,
                  bars_held=int(tr.pop("_bars", 0)),
                  days_held=(pd.Timestamp(d) - pd.Timestamp(tr["entry_date"])).days)
        tr.pop("_target", None)
        trades.append(tr)
        qty[j] = 0.0

    for i, d in enumerate(cal):
        has = HAS[i]
        for j in [j for j in open_tr if has[j] and machines[j].exit_pending]:
            ev = machines[j].fill_exit(d, O[i, j], bar=i)
            close_trade(j, d, ev.price, "EXIT_MA")
        cands = [j for j in pending if has[j]]
        cands.sort(key=lambda j: (-(pending[j]["rs"] if not math.isnan(pending[j]["rs"]) else -np.inf), syms[j]))
        alloc_done = False
        for j in cands:
            m = machines[j]
            pe = pending.pop(j)
            o = O[i, j]
            reason = None
            q = 0.0
            if alloc_done:
                reason = "cash"
            elif not (o > 0) or not (pe["desired_qty"] > 0):
                reason = "size"
            else:
                afford = cash / (o * (1 + c_rate))
                q = min(pe["desired_qty"], afford)
                if whole:
                    q = float(math.floor(q))
                too_small = (q < 1) if whole else (q * o < cfg.min_fill_value
                                                   or q < cfg.min_fill_frac * pe["desired_qty"])
                if q <= 0 or too_small:
                    reason = "cash"
            if reason:
                m.cancel_entry()
                skipped.append({"symbol": syms[j], "signal_date": pe["signal_date"], "date": _d(d),
                                "reason": reason, "rs": pe["rs"], "desired_qty": pe["desired_qty"],
                                "cash": cash})
                continue
            partial = q < pe["desired_qty"]
            m.fill_entry(d, o, bar=i)
            qty[j] = q
            cost_basis = q * o * (1 + c_rate)
            cash -= cost_basis
            open_tr[j] = {"symbol": syms[j], "signal_date": pe["signal_date"], "signal_close": pe["signal_close"],
                          "rs_at_signal": pe["rs"], "entry_date": _d(d), "entry_price": float(o),
                          "qty": q, "desired_qty": pe["desired_qty"], "partial": bool(partial),
                          "stop_price": m.stop_price, "entry_cost": q * o * c_rate,
                          "cost_basis": cost_basis, "_bars": 0, "_proceeds": 0.0, "_exit_cost": 0.0,
                          "_target": rule.target_r is not None, "target_sold": 0.0}
            if partial:
                alloc_done = True
        for j in list(open_tr):
            if not has[j]:
                continue
            m = machines[j]
            tr = open_tr[j]
            tr["_bars"] += 1
            entry = m.entry_price
            # the variant's target, only when the stop in force at the start of the bar holds
            if tr["_target"] and not (L[i, j] <= m.stop_price):
                tgt = entry * (1 + rule.target_r * stop_pct / 100)
                if H[i, j] >= tgt:
                    fill = max(O[i, j], tgt)                       # a limit order: the open if it gaps above
                    tr["_target"] = False
                    q = qty[j] * frac
                    if whole:
                        q = float(math.floor(q))
                    if frac >= 1.0 or q >= qty[j]:
                        m.entry_price = m.stop_price = NAN
                        m.exit_pending = False
                        close_trade(j, d, fill, "TARGET")
                        continue
                    if q > 0:
                        sell(j, q, fill)
                        tr["target_sold"] = q
            ev = m.check_exit(d, O[i, j], L[i, j], C[i, j], EMA[i, j], bar=i)
            if ev is not None and ev.type == "STOP":
                close_trade(j, d, ev.price, "STOP")
                continue
            if ev is not None and ev.type == "EXIT_SIGNAL":
                tr["exit_signal_date"] = _d(d)
            if rule.breakeven_r is not None and H[i, j] >= entry * (1 + rule.breakeven_r * stop_pct / 100):
                m.stop_price = max(m.stop_price, entry)             # in force from the next bar
        last_close[has] = C[i, has]
        pos_value = float(sum(qty[j] * last_close[j] for j in open_tr))
        equity = cash + pos_value
        for j in np.flatnonzero(has & SIG[i]):
            m = machines[j]
            if m.in_pos:
                continue
            ev = m.arm_signal(d, True, C[i, j], bar=i)
            if ev is not None:
                pending[j] = {"signal_date": _d(d), "signal_close": float(C[i, j]), "rs": float(RS[i, j]),
                              "equity": equity,
                              "desired_qty": position_qty(equity, C[i, j], stop_pct, cfg.risk_pct, whole)}
        rows.append((d, cash, pos_value, equity, len(open_tr)))

    eq = pd.DataFrame(rows, columns=["date", "cash", "positions_value", "equity", "n_positions"]).set_index("date")
    eq["exposure_pct"] = eq["positions_value"] / eq["equity"] * 100
    tdf = pd.DataFrame(trades)
    if len(tdf):
        tdf = tdf.drop(columns=[c for c in tdf.columns if c.startswith("_")])
    return PortfolioResult(eq, tdf, pd.DataFrame(skipped), config=_cfg_dict(cfg))


def same_as_engine(frames: dict, cfg) -> tuple[bool, str]:
    """The empty rule against the engine: the same trades and the same equity, exactly."""
    from swing_engine.portfolio import simulate
    a, b = simulate(frames, cfg), simulate_exits(frames, cfg)
    if len(a.trades) != len(b.trades):
        return False, f"trades {len(a.trades)} vs {len(b.trades)}"
    if len(a.trades):
        cols = list(a.trades.columns)
        x, y = a.trades[cols].reset_index(drop=True), b.trades[cols].reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(x, y, check_exact=False, rtol=1e-12, atol=1e-9)
        except AssertionError as e:
            return False, str(e).splitlines()[0]
    if not np.allclose(a.equity["equity"].to_numpy(), b.equity["equity"].to_numpy(), rtol=1e-12, atol=1e-6):
        return False, "equity differs"
    return True, f"{len(a.trades)} trades"


def add_exit_lines(frames: dict) -> dict:
    """Slim frames (the columns the loop reads) plus the faster exit lines of E9 and E10."""
    from swing_engine.indicators import sma
    out = {}
    for s, f in frames.items():
        g = f[BASE_COLS].copy()
        for n in EXIT_LENS:
            g[f"exit_ma_{n}"] = sma(f["close"], n)
        out[s] = g
    return out


def prepare(data_dir: str, market: str):
    import robustness as R
    from swing_engine.indicators import normalize_bars
    from swing_engine.params import resolve
    snap, _, bench = R.load(data_dir, market)
    frames = dict(snap["frames"])
    cfg = R._cfg(resolve(market))
    dates = normalize_bars(bench, require_ohlc=False).index
    rdates, sets = R.membership_rows(market, Path(data_dir) / R.MEMBERSHIP_FILES[market], sorted(frames))
    member = R.membership_mask(rdates, sets, dates, sorted(frames))
    return add_exit_lines(R.prepare_pit(frames, bench, cfg, member)), cfg, bench


def row(res, bench, market: str) -> dict:
    """The numbers compared, from robustness.summarize, plus what the exits did."""
    import robustness as R
    s = R.summarize(res, bench, market)
    f = (s or {}).get("full") or {}
    t = res.trades
    out = {k: f.get(k) for k in ("trades", "cagr_pct", "excess_cagr_pp", "profit_factor", "win_rate_pct",
                                 "avg_win_pct", "avg_loss_pct", "max_drawdown_pct", "exposure_pct")}
    for h in ("h1", "h2"):
        x = (s or {}).get(h) or {}
        out[f"{h}_win_rate_pct"] = x.get("win_rate_pct")
        out[f"{h}_excess_pp"] = x.get("excess_cagr_pp")
    if len(t):
        out["scratch_pct"] = float((t["pnl_pct"].abs() <= 1.0).mean() * 100)      # within +-1% of flat
        out["exit_types"] = {k: int(v) for k, v in t["exit_type"].value_counts().items()}
        out["median_bars_held"] = float(t["bars_held"].median())
    return out


def _job(job):
    mode, rep = job
    w = _W
    frames = P.perturb(w["frames"], mode, rep, w["drop_pct"], w["seed"])
    return {"mode": mode, "rep": rep,
            "rows": {k: row(simulate_exits(frames, w["cfg"], r), w["bench"], w["market"]) for k, (_, r) in RULES.items()}}


def paired(runs: list) -> dict:
    """Per perturbation and variant: the distribution of the paired difference variant - baseline."""
    out = {}
    for mode in P.MODES:
        rs = [r for r in runs if r["mode"] == mode]
        if not rs:
            continue
        m = {}
        for key in RULES:
            if key == BASE:
                continue
            d = {}
            for k in METRICS:
                diffs = [r["rows"][key][k] - r["rows"][BASE][k] for r in rs
                         if r["rows"][key].get(k) is not None and r["rows"][BASE].get(k) is not None]
                d[k] = P.dist(diffs) | {"ahead_pct": float(np.mean([v > 0 for v in diffs]) * 100) if diffs else None}
            m[key] = d
        out[mode] = {"reps": len(rs), "diff": m,
                     "baseline": {k: P.dist([r["rows"][BASE].get(k) for r in rs]) for k in METRICS}}
    return out


def _ge(a, b) -> bool:
    return a is not None and b is not None and a == a and b == b and a >= b - EPS


def verdict(key: str, rows: dict, pairs: dict, other: dict | None) -> dict:
    """The fixed criteria for one variant. Any missing number fails its check."""
    b, v = rows[BASE], rows[key]
    modes = [pairs.get(m, {}).get("diff", {}).get(key) for m in P.MODES]
    complete = all(x is not None for x in modes)
    def every(f):
        return complete and all(f(x) for x in modes)
    checks = {
        "S1_win_rate": _ge(v.get("win_rate_pct"), (b.get("win_rate_pct") or math.nan) + WIN_GAIN_PP),
        "P1_win_paired": every(lambda x: _ge(x["win_rate_pct"].get("ahead_pct"), WIN_AHEAD_PCT)
                               and _ge(x["win_rate_pct"].get("p50"), WIN_GAIN_PP)),
        "P2_cagr": every(lambda x: _ge(x["cagr_pct"].get("p50"), -CAGR_SLACK_PP)),
        "P3_drawdown": every(lambda x: _ge(x["max_drawdown_pct"].get("p50"), -MDD_SLACK_PP)),
        "P4_halves": all(v.get(f"{h}_win_rate_pct") is not None and b.get(f"{h}_win_rate_pct") is not None
                         and v[f"{h}_win_rate_pct"] > b[f"{h}_win_rate_pct"]
                         and _ge(v.get(f"{h}_excess_pp"), (b.get(f"{h}_excess_pp") or math.nan) - HALF_SLACK_PP)
                         for h in ("h1", "h2")),
        "P5_other_market": other is not None and _ge((other.get(key) or {}).get("cagr_pct"),
                                                     ((other.get(BASE) or {}).get("cagr_pct") or math.nan) - OTHER_SLACK_PP),
    }
    raised = checks["S1_win_rate"] and checks["P1_win_paired"]
    kept = all(checks[k] for k in ("P2_cagr", "P3_drawdown", "P4_halves", "P5_other_market"))
    text = "win rate not raised" if not raised else ("win rate up, return kept" if kept else "win rate up, return damaged")
    return {"verdict": text, "checks": checks,
            "return_up_as_well": every(lambda x: x["cagr_pct"].get("p05") is not None and x["cagr_pct"]["p05"] > 0)}


def _n(v, spec=".1f", unit="") -> str:
    return "n/a" if v is None or v != v else format(v, spec) + unit


def table(rows: dict) -> str:
    head = ("| # | 변형 | 거래 | 승률 | CAGR | 지수 초과 | PF | 평균 이익 | 평균 손실 | 최대 낙폭 | 본전권 | 전반 승률 | 후반 승률 |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    return head + "".join(
        f"| {k.split('_')[0]} | {RULES[k][0]} | {_n(r.get('trades'), ',')} | {_n(r.get('win_rate_pct'), '.1f', '%')} | "
        f"{_n(r.get('cagr_pct'), '.1f', '%')} | {_n(r.get('excess_cagr_pp'), '+.1f', '%p')} | {_n(r.get('profit_factor'), '.2f')} | "
        f"{_n(r.get('avg_win_pct'), '+.1f', '%')} | {_n(r.get('avg_loss_pct'), '.1f', '%')} | {_n(r.get('max_drawdown_pct'), '.1f', '%')} | "
        f"{_n(r.get('scratch_pct'), '.1f', '%')} | {_n(r.get('h1_win_rate_pct'), '.1f', '%')} | {_n(r.get('h2_win_rate_pct'), '.1f', '%')} |\n"
        for k, r in rows.items())


def paired_table(pairs: dict) -> str:
    lines = []
    for mode, s in pairs.items():
        lines.append(f"\n[{mode}] {s['reps']} paired paths: variant - baseline (p05 / median / p95, share of paths ahead)")
        for key, d in s["diff"].items():
            w, c, m = d["win_rate_pct"], d["cagr_pct"], d["max_drawdown_pct"]
            lines.append(f"  {key:16s} win {_n(w.get('p05'), '+.1f')} / {_n(w.get('p50'), '+.1f')} / {_n(w.get('p95'), '+.1f')}pp "
                         f"({_n(w.get('ahead_pct'), '.0f')}%) · CAGR {_n(c.get('p05'), '+.1f')} / {_n(c.get('p50'), '+.1f')} / "
                         f"{_n(c.get('p95'), '+.1f')}pp ({_n(c.get('ahead_pct'), '.0f')}%) · MDD {_n(m.get('p05'), '+.1f')} / "
                         f"{_n(m.get('p50'), '+.1f')} / {_n(m.get('p95'), '+.1f')}pp")
    return "\n".join(lines)


def run_plain(frames: dict, cfg, bench, market: str) -> dict:
    return {k: row(simulate_exits(frames, cfg, r), bench, market) for k, (_, r) in RULES.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="snapshot directory with the membership files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--market", default="KOSDAQ", help="the market that decides")
    ap.add_argument("--other", default="KOSPI", help="second market for P5; '' to skip")
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--drop-pct", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=P.SEED)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--check-only", action="store_true",
                    help="stop after comparing the empty rule with the engine (no variant is run)")
    a = ap.parse_args(argv)

    frames, cfg, bench = prepare(a.data, a.market)
    ok, why = same_as_engine(frames, cfg)
    print(f"{a.market}: empty rule vs engine: {'identical' if ok else 'DIFFERENT'} ({why})", flush=True)
    if not ok:
        return 2
    if a.check_only:
        return 0
    rows = run_plain(frames, cfg, bench, a.market)
    print(table(rows), flush=True)

    other = None
    if a.other:
        fo, cfg_o, bench_o = prepare(a.data, a.other)
        ok, why = same_as_engine(fo, cfg_o)
        print(f"{a.other}: empty rule vs engine: {'identical' if ok else 'DIFFERENT'} ({why})", flush=True)
        if not ok:
            return 2
        other = run_plain(fo, cfg_o, bench_o, a.other)
        print(table(other), flush=True)
        del fo

    _W.update(frames=frames, cfg=cfg, bench=bench, market=a.market, drop_pct=a.drop_pct, seed=a.seed)
    jobs = [(mode, rep) for mode in P.MODES for rep in range(a.reps)]
    runs = []
    with get_context("fork").Pool(max(1, a.jobs)) as pool:
        for r in pool.imap_unordered(_job, jobs):
            runs.append(r)
            print(f"{r['mode']} {r['rep']:02d} done ({len(runs)}/{len(jobs)})", flush=True)
    runs.sort(key=lambda r: (P.MODES.index(r["mode"]), r["rep"]))
    pairs = paired(runs)
    verdicts = {k: verdict(k, rows, pairs, other) for k in RULES if k != BASE}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "exit_study.json").write_text(json.dumps(
        {"market": a.market, "other_market": a.other or None, "reps": a.reps, "drop_pct": a.drop_pct, "seed": a.seed,
         "rows": rows, "other_rows": other, "paired": pairs, "verdicts": verdicts, "runs": runs},
        ensure_ascii=False, indent=1))
    print(paired_table(pairs))
    print()
    for k, v in verdicts.items():
        failed = [c for c, ok in v["checks"].items() if not ok]
        print(f"VERDICT {k:16s} {v['verdict']}" + (f" · failed {', '.join(failed)}" if failed else "")
              + (" · return up as well" if v["return_up_as_well"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
