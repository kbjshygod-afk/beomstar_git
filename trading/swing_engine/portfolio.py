"""Multi-symbol portfolio simulation (SPEC section 8) and performance metrics.

Assumptions (SPEC 8 says these approximate the scanner, whose code is not available):
* Universe = current constituents (survivorship bias, like the scanner).
* RS: rs_mode 'proxy' uses tt8 of SPEC 4.3; 'percentile' sets tt8 = the symbol's
  weighted_perf percentile across the universe that day (rank(pct=True)*100) >= 70.
* Signal at close t -> fill at open t+1. Desired qty = equity_t x risk% / (close_t x stop%),
  equity marked to market at close t. Fills are limited by cash (no leverage); when cash
  is short, pending entries are filled in descending RS order and the last one partially,
  after which allocation stops for that open. Integer-share markets floor quantities and
  skip a fill below 1 share (then the next signal is tried); fractional markets skip a fill
  below 1% of the desired size (cash residue would otherwise open dust positions).
* Costs: cost_pct of traded value per side (0.2%).
* Within one day: (1) pending exits fill at the open, (2) pending entries fill at the open
  (cash from (1) is available), (3) stops / 50-day-MA checks, (4) mark to market at the
  close, (5) new signals for flat symbols. Steps 1-3 and 5 are exactly state.py's steps;
  each symbol is only processed on its own bars.
* No re-entry while a position (or a pending exit) is open: signals arm only when flat.
* A bar whose open, low or close is missing or <= 0 counts as no bar for that symbol
  (TradingView prints none; the loaders drop such rows too). A pending exit or a stop
  then waits for the next valid bar instead of filling at 0 or NaN, which would book a
  -100% trade or turn cash into NaN for the rest of the run.
* `as_of` truncates every input before any computation (no lookahead); `test_start`
  data only warms the indicators - no signal before test_start is acted on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import truncate
from .indicators import align_asof, compute_indicators, finalize_signals, normalize_bars
from .params import COST_PCT, RISK_PCT, RS_PERCENTILE_MIN
from .sizing import position_qty
from .state import PositionMachine

RS_MODES = ("proxy", "percentile")


@dataclass
class PortfolioConfig:
    params: dict
    rs_mode: str = "percentile"
    rs_percentile_min: float = RS_PERCENTILE_MIN
    initial_equity: float = 100_000_000.0
    risk_pct: float = RISK_PCT
    cost_pct: float = COST_PCT
    integer_shares: bool | None = None       # None -> params["integer_shares"]
    test_start: object = None
    as_of: object = None
    min_fill_value: float = 0.0              # fractional markets: skip fills worth less than this
    min_fill_frac: float = 0.01              # fractional markets: skip fills < 1% of the desired size
                                             # (the analogue of "< 1 share"; avoids dust from cash residue)

    @property
    def whole_shares(self) -> bool:
        return bool(self.params.get("integer_shares", False) if self.integer_shares is None
                    else self.integer_shares)


@dataclass
class PortfolioResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    skipped: pd.DataFrame
    open_positions: list = field(default_factory=list)
    pending_entries: list = field(default_factory=list)
    pending_exits: list = field(default_factory=list)
    config: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# preparation: indicators + RS per symbol
# ---------------------------------------------------------------------------

def prepare_frames(symbols: dict, bench: pd.DataFrame | None, cfg: PortfolioConfig) -> dict:
    """Truncate to as_of, compute indicators, apply the RS mode. Returns per-symbol frames
    with open/high/low/close/exit_ma/full_signal/rs_key (+ all indicator columns)."""
    if cfg.rs_mode not in RS_MODES:
        raise ValueError(f"rs_mode must be one of {RS_MODES}")
    p = cfg.params
    b = truncate(normalize_bars(bench, require_ohlc=False), cfg.as_of) if bench is not None else None
    inds, bars = {}, {}
    for s, df in symbols.items():
        d = truncate(normalize_bars(df), cfg.as_of)
        if len(d) == 0:
            continue
        bars[s] = d
        inds[s] = compute_indicators(d, b, p)
    if cfg.rs_mode == "percentile" and inds:
        # Universe percentile of weighted_perf per day, among symbols with a value that day.
        panel = pd.DataFrame({s: ind["wp"] for s, ind in inds.items()})
        pct = panel.rank(axis=1, pct=True) * 100
        for s, ind in inds.items():
            pr = pct[s].reindex(ind.index)
            finalize_signals(ind, p, tt8_override=pr >= cfg.rs_percentile_min)
            ind["rs_pct"] = pr
            ind["rs_key"] = pr
    else:
        for ind in inds.values():
            ind["rs_key"] = ind["rs_diff"]
    frames = {}
    for s, ind in inds.items():
        f = pd.concat([bars[s][["open", "high", "low", "close", "volume"]], ind], axis=1)
        frames[s] = f
    return frames


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------

def _d(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def simulate(frames: dict, cfg: PortfolioConfig) -> PortfolioResult:
    """Run the day loop on prepared frames (each needs open, high, low, close, exit_ma,
    full_signal, rs_key). Frames are used as given; call prepare_frames for as_of."""
    p = cfg.params
    stop_pct = float(p["stop_pct"])
    c_rate = float(cfg.cost_pct) / 100.0
    whole = cfg.whole_shares
    syms = sorted(frames)
    S = len(syms)
    empty = PortfolioResult(pd.DataFrame(columns=["cash", "positions_value", "equity", "exposure_pct", "n_positions"]),
                            pd.DataFrame(), pd.DataFrame(), config=_cfg_dict(cfg))
    if S == 0:
        return empty

    frames = {s: (truncate(frames[s], cfg.as_of)) for s in syms}
    cal = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
    if cfg.test_start is not None:
        cal = cal[cal >= pd.Timestamp(cfg.test_start)]
    if len(cal) == 0:
        return empty

    def panel(col, fill=np.nan, dtype=float):
        arr = np.full((len(cal), S), fill, dtype=dtype)
        for j, s in enumerate(syms):
            ser = frames[s][col].reindex(cal)
            v = ser.to_numpy()
            if dtype is bool:
                arr[:, j] = pd.Series(v).fillna(False).astype(bool).to_numpy()
            else:
                arr[:, j] = v.astype(float)
        return arr

    O, H, L, C = panel("open"), panel("high"), panel("low"), panel("close")
    EMA, RS = panel("exit_ma"), panel("rs_key")
    SIG = panel("full_signal", False, bool)
    HAS = (C > 0) & (O > 0) & (L > 0)          # NaN compares False: a bad row is no bar

    # last close before the test window (for marking, never for trading)
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

    def close_trade(j, d, price, kind):
        nonlocal cash
        tr = open_tr.pop(j)
        q = qty[j]
        proceeds = q * price * (1 - c_rate)
        cash += proceeds
        cost_basis = tr["cost_basis"]
        net = proceeds - cost_basis
        tr.update(exit_date=_d(d), exit_price=float(price), exit_type=kind,
                  exit_cost=q * price * c_rate, net_pnl=net,
                  pnl_pct=net / cost_basis * 100 if cost_basis else np.nan,
                  price_pnl_pct=(price / tr["entry_price"] - 1) * 100,
                  bars_held=int(tr.pop("_bars", 0)),
                  days_held=(pd.Timestamp(d) - pd.Timestamp(tr["entry_date"])).days)
        trades.append(tr)
        qty[j] = 0.0

    for i, d in enumerate(cal):
        has = HAS[i]
        # (1) pending exits at the open  (state.py step 1)
        for j in [j for j in open_tr if has[j] and machines[j].exit_pending]:
            ev = machines[j].fill_exit(d, O[i, j], bar=i)
            close_trade(j, d, ev.price, "EXIT_MA")
        # (2) pending entries at the open, descending RS, cash-limited  (state.py step 2)
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
                          "cost_basis": cost_basis, "_bars": 0}
            if partial:
                alloc_done = True     # "the last one partially"
        # (3) stop / exit-MA check for open positions with a bar today (state.py step 3)
        for j in list(open_tr):
            if not has[j]:
                continue
            m = machines[j]
            open_tr[j]["_bars"] += 1
            ev = m.check_exit(d, O[i, j], L[i, j], C[i, j], EMA[i, j], bar=i)
            if ev is not None and ev.type == "STOP":
                close_trade(j, d, ev.price, "STOP")
            elif ev is not None and ev.type == "EXIT_SIGNAL":
                open_tr[j]["exit_signal_date"] = _d(d)
        # (4) mark to market at the close
        last_close[has] = C[i, has]
        pos_value = float(sum(qty[j] * last_close[j] for j in open_tr))
        equity = cash + pos_value
        # (5) new signals for flat symbols (state.py step 4)
        for j in np.flatnonzero(has & SIG[i]):
            m = machines[j]
            if m.in_pos:
                continue           # no re-entry while a position is open
            ev = m.arm_signal(d, True, C[i, j], bar=i)
            if ev is not None:
                pending[j] = {"signal_date": _d(d), "signal_close": float(C[i, j]), "rs": float(RS[i, j]),
                              "equity": equity,
                              "desired_qty": position_qty(equity, C[i, j], stop_pct, cfg.risk_pct, whole)}
        rows.append((d, cash, pos_value, equity, len(open_tr)))

    eq = pd.DataFrame(rows, columns=["date", "cash", "positions_value", "equity", "n_positions"]).set_index("date")
    eq["exposure_pct"] = eq["positions_value"] / eq["equity"] * 100

    last_i = len(cal) - 1
    open_positions = []
    for j, tr in open_tr.items():
        m = machines[j]
        mark = last_close[j]
        open_positions.append({
            "symbol": syms[j], "entry_date": tr["entry_date"], "entry_price": tr["entry_price"],
            "qty": qty[j], "stop_price": m.stop_price, "last_close": float(mark),
            "exit_ma": float(frames[syms[j]]["exit_ma"].iloc[-1]),
            "unrealized_pnl": qty[j] * mark * (1 - c_rate) - tr["cost_basis"],
            "price_pnl_pct": (mark / tr["entry_price"] - 1) * 100,
            "exit_pending": bool(m.exit_pending),
        })
    pending_entries = [{"symbol": syms[j], **pe, "est_stop_from_close": pe["signal_close"] * (1 - stop_pct / 100)}
                       for j, pe in sorted(pending.items(), key=lambda kv: -kv[1]["rs"] if not math.isnan(kv[1]["rs"]) else np.inf)]
    pending_exits = [x["symbol"] for x in open_positions if x["exit_pending"]]
    tdf = pd.DataFrame(trades)
    if len(tdf):
        tdf = tdf.drop(columns=[c for c in tdf.columns if c.startswith("_")])
    return PortfolioResult(eq, tdf, pd.DataFrame(skipped), open_positions, pending_entries,
                           pending_exits, _cfg_dict(cfg) | {"last_date": _d(cal[last_i]),
                                                            "first_date": _d(cal[0])})


def _cfg_dict(cfg: PortfolioConfig) -> dict:
    return {"rs_mode": cfg.rs_mode, "rs_percentile_min": cfg.rs_percentile_min,
            "initial_equity": cfg.initial_equity, "risk_pct": cfg.risk_pct, "cost_pct": cfg.cost_pct,
            "integer_shares": cfg.whole_shares,
            "test_start": None if cfg.test_start is None else _d(cfg.test_start),
            "as_of": None if cfg.as_of is None else _d(cfg.as_of), "params": dict(cfg.params)}


def run_portfolio(symbols: dict, bench: pd.DataFrame | None, cfg: PortfolioConfig) -> PortfolioResult:
    return simulate(prepare_frames(symbols, bench, cfg), cfg)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

BIG_WIN_PCT = 20.0


def _cagr(v0, v1, days):
    if v0 is None or v1 is None or not (v0 > 0) or not (v1 > 0) or days <= 0:
        return None
    return ((v1 / v0) ** (365.25 / days) - 1) * 100


def _none(x):
    if x is None:
        return None
    try:
        return None if math.isnan(x) or math.isinf(x) else float(x)
    except TypeError:
        return x


def trade_stats(trades: pd.DataFrame) -> dict:
    """Closed-trade statistics. Win = net P&L > 0. Percentages use net pnl_pct."""
    n = int(len(trades))
    if n == 0:
        return {"trades": 0, "win_rate_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
                "profit_factor": None, "big_win_profit_share_pct": None, "big_win_trade_share_pct": None,
                "gross_profit": 0.0, "gross_loss": 0.0}
    pnl = trades["net_pnl"].astype(float)
    pct = trades["pnl_pct"].astype(float)
    wins = pnl > 0
    gp = float(pnl[wins].sum())
    gl = float(-pnl[~wins].sum())
    big = pct > BIG_WIN_PCT
    return {
        "trades": n,
        "win_rate_pct": wins.mean() * 100,
        "avg_win_pct": float(pct[wins].mean()) if wins.any() else None,
        "avg_loss_pct": float(pct[~wins].mean()) if (~wins).any() else None,
        "profit_factor": gp / gl if gl > 0 else None,
        # share of gross profit that came from trades above +20%, and share of such trades
        "big_win_profit_share_pct": float(pnl[big & wins].sum()) / gp * 100 if gp > 0 else None,
        "big_win_trade_share_pct": big.mean() * 100,
        "gross_profit": gp, "gross_loss": gl,
    }


def period_metrics(equity: pd.DataFrame, trades: pd.DataFrame, bench_close: pd.Series | None,
                   start=None, end=None) -> dict | None:
    """Metrics for [start, end]. Returns are measured from the last close BEFORE start
    (the previous period's end) when one exists, else from the first close in the window."""
    eq = equity["equity"]
    idx = eq.index
    end_ts = pd.Timestamp(end) if end is not None else idx[-1]
    start_ts = pd.Timestamp(start) if start is not None else idx[0]
    in_win = (idx >= start_ts) & (idx <= end_ts)
    if not in_win.any():
        return None
    win_idx = idx[in_win]
    prior = idx[idx < start_ts]
    base = prior[-1] if len(prior) else win_idx[0]
    last = win_idx[-1]
    v0, v1 = float(eq.loc[base]), float(eq.loc[last])
    days = (last - base).days
    seg = eq.loc[(idx >= base) & (idx <= last)]
    dd = (seg / seg.cummax() - 1) * 100
    out = {
        "start": _d(win_idx[0]), "end": _d(last), "base_date": _d(base), "days": int(days),
        "start_equity": v0, "end_equity": v1,
        "return_pct": (v1 / v0 - 1) * 100, "cagr_pct": _cagr(v0, v1, days),
        "max_drawdown_pct": float(dd.min()),
        "exposure_pct": float(equity.loc[win_idx, "exposure_pct"].mean()),
    }
    if bench_close is not None and len(bench_close):
        b = align_asof(bench_close.to_frame("close"), [base, last])["close"].to_numpy()
        b0, b1 = float(b[0]), float(b[1])
        out["bench_return_pct"] = (b1 / b0 - 1) * 100 if b0 > 0 else None
        out["bench_cagr_pct"] = _cagr(b0, b1, days)
    else:
        out["bench_return_pct"] = out["bench_cagr_pct"] = None
    out["excess_cagr_pp"] = (out["cagr_pct"] - out["bench_cagr_pct"]
                             if out["cagr_pct"] is not None and out["bench_cagr_pct"] is not None else None)
    out["excess_return_pp"] = (out["return_pct"] - out["bench_return_pct"]
                               if out["bench_return_pct"] is not None else None)
    tsel = trades
    if len(trades):
        # trades closed inside the requested period [start, end]
        ex = pd.to_datetime(trades["exit_date"])
        tsel = trades[(ex >= start_ts) & (ex <= min(end_ts, last))]
    out.update(trade_stats(tsel))
    return {k: _none(v) if isinstance(v, float) else v for k, v in out.items()}


def compute_metrics(result: PortfolioResult, bench: pd.DataFrame | None, oos_start=None) -> dict:
    """Full test window, last 1 year, each calendar year (and OOS when given)."""
    eq = result.equity
    if len(eq) == 0:
        return {"full": None, "last_1y": None, "years": {}, "oos": None}
    bclose = None
    if bench is not None and len(bench):
        bclose = normalize_bars(bench, require_ohlc=False)["close"]
    first, last = eq.index[0], eq.index[-1]
    out = {"full": period_metrics(eq, result.trades, bclose, first, last)}
    one_year_start = last - pd.DateOffset(years=1) + pd.Timedelta(days=1)
    out["last_1y"] = period_metrics(eq, result.trades, bclose, one_year_start, last)
    years = {}
    for y in range(first.year, last.year + 1):
        m = period_metrics(eq, result.trades, bclose, pd.Timestamp(y, 1, 1), pd.Timestamp(y, 12, 31))
        if m is not None:
            # a full calendar year starts from the previous year's last close and ends in late December
            m["full_year"] = (pd.Timestamp(m["base_date"]).year == y - 1
                              and pd.Timestamp(m["end"]) >= pd.Timestamp(y, 12, 24))
            years[str(y)] = m
    out["years"] = years
    out["oos"] = period_metrics(eq, result.trades, bclose, pd.Timestamp(oos_start), last) if oos_start else None
    out["open_positions"] = len(result.open_positions)
    return out
