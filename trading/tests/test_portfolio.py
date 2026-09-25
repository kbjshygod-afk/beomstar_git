"""Portfolio simulation (SPEC 8) on hand-built frames, and metrics on a tiny equity curve."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import bdays, make_bars
from swing_engine.params import resolve
from swing_engine.portfolio import (PortfolioConfig, PortfolioResult, compute_metrics, period_metrics,
                                    prepare_frames, run_portfolio, simulate, trade_stats)


def frame(dates, closes, opens=None, lows=None, signals=(), rs=50.0, exit_ma=0.0):
    closes = np.asarray(closes, float)
    opens = closes.copy() if opens is None else np.asarray(opens, float)
    lows = np.minimum(opens, closes) if lows is None else np.asarray(lows, float)
    sig = np.zeros(len(dates), bool)
    sig[list(signals)] = True
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, closes), "low": lows, "close": closes,
                         "exit_ma": exit_ma, "full_signal": sig, "rs_key": rs}, index=dates)


def cfg(**kw):
    base = dict(params=resolve("CUSTOM", stop_pct=10.0), initial_equity=1000.0, risk_pct=4.0, cost_pct=0.0)
    base.update(kw)
    return PortfolioConfig(**base)


def test_cash_limited_allocation_in_rs_order_with_partial_fill():
    d = bdays(3)
    # desired qty = 1000 * 4% / (10 * 10%) = 40 shares = 400 per signal; cash covers 2.5 of them
    frames = {"C": frame(d, [10, 10, 10], signals=[0], rs=70.0),
              "A": frame(d, [10, 10, 10], signals=[0], rs=90.0),
              "D": frame(d, [10, 10, 10], signals=[0], rs=60.0),
              "B": frame(d, [10, 10, 10], signals=[0], rs=80.0)}
    r = simulate(frames, cfg())
    t = {x["symbol"]: x for x in r.open_positions}
    assert set(t) == {"A", "B", "C"}
    assert (t["A"]["qty"], t["B"]["qty"], t["C"]["qty"]) == (40.0, 40.0, 20.0)
    assert list(r.skipped["symbol"]) == ["D"] and r.skipped["reason"].iloc[0] == "cash"
    assert r.equity["cash"].iloc[1] == pytest.approx(0.0)
    assert r.equity["equity"].iloc[1] == pytest.approx(1000.0)
    assert r.equity["exposure_pct"].iloc[1] == pytest.approx(100.0)


def test_integer_shares_floor_skip_below_one_share_then_partial():
    d = bdays(3)
    frames = {"A": frame(d, [30, 30, 30], signals=[0], rs=90.0),   # floor(13.33) = 13 -> 390
              "B": frame(d, [30, 30, 30], signals=[0], rs=85.0),   # 13 -> 390, cash 220
              "X": frame(d, [300, 300, 300], signals=[0], rs=80.0),  # wants 1, affords 0.73 -> skip
              "C": frame(d, [30, 30, 30], signals=[0], rs=70.0),   # wants 13, affords 7.33 -> 7 (partial)
              "E": frame(d, [5, 5, 5], signals=[0], rs=60.0)}      # after the partial: not filled
    r = simulate(frames, cfg(integer_shares=True))
    q = {x["symbol"]: x["qty"] for x in r.open_positions}
    assert q == {"A": 13.0, "B": 13.0, "C": 7.0}
    sk = dict(zip(r.skipped["symbol"], r.skipped["reason"]))
    assert sk == {"X": "cash", "E": "cash"}
    assert r.equity["cash"].iloc[1] == pytest.approx(1000 - 33 * 30)


def test_costs_on_both_sides():
    d = bdays(5)
    # entry at open 10 on day 1; close < exit_ma on day 2 -> exit at open 12 on day 3
    f = frame(d, [10, 10, 11, 12, 12], opens=[10, 10, 10, 12, 12], signals=[0],
              exit_ma=np.array([0, 0, 11.5, 0, 0]))
    c = cfg(initial_equity=10_000.0, risk_pct=0.75, cost_pct=0.2)
    r = simulate({"A": f}, c)
    tr = r.trades.iloc[0]
    assert tr["qty"] == pytest.approx(75.0)                            # 10000*0.75%/(10*10%)
    assert tr["cost_basis"] == pytest.approx(75 * 10 * 1.002)
    assert (tr["exit_type"], tr["exit_date"], tr["exit_price"]) == ("EXIT_MA", d[3].strftime("%Y-%m-%d"), 12.0)
    assert tr["net_pnl"] == pytest.approx(75 * 12 * 0.998 - 751.5)       # 146.7
    assert tr["pnl_pct"] == pytest.approx(146.7 / 751.5 * 100)
    assert tr["price_pnl_pct"] == pytest.approx(20.0)
    assert r.equity["equity"].iloc[-1] == pytest.approx(10_000 + 146.7)
    # mark to market on day 1: 9248.5 cash + 75 * 10
    assert r.equity["equity"].iloc[1] == pytest.approx(9248.5 + 750)


def test_stop_fill_and_cost():
    d = bdays(3)
    f = frame(d, [10, 10, 8.5], opens=[10, 10, 8.8], lows=[10, 10, 8.4], signals=[0])
    r = simulate({"A": f}, cfg(cost_pct=0.2))
    tr = r.trades.iloc[0]
    assert tr["exit_type"] == "STOP" and tr["exit_price"] == pytest.approx(8.8)   # gap below 9 -> open
    assert tr["net_pnl"] == pytest.approx(40 * 8.8 * 0.998 - 40 * 10 * 1.002)


def test_no_reentry_while_open_and_reentry_after_exit():
    d = bdays(6)
    f = frame(d, [10, 10, 10, 10, 10, 10], signals=[0, 2, 4], exit_ma=np.array([0, 0, 0, 11, 0, 0]))
    r = simulate({"A": f}, cfg(risk_pct=0.75, initial_equity=100_000.0))
    # day0 signal -> day1 entry; day2 signal ignored (in position); day3 close<exit_ma -> day4 exit at open;
    # day4 signal (flat again after the exit fill) -> day5 entry
    assert len(r.trades) == 1 and r.trades.iloc[0]["entry_date"] == d[1].strftime("%Y-%m-%d")
    assert r.trades.iloc[0]["exit_date"] == d[4].strftime("%Y-%m-%d")
    assert [x["entry_date"] for x in r.open_positions] == [d[5].strftime("%Y-%m-%d")]
    assert len(r.skipped) == 0


def test_test_start_ignores_earlier_signals():
    d = bdays(6)
    f = frame(d, [10] * 6, signals=[1, 3])
    r = simulate({"A": f}, cfg(test_start=d[2]))
    assert r.equity.index[0] == d[2]
    assert r.equity["equity"].iloc[0] == 1000.0
    assert [x["entry_date"] for x in r.open_positions] == [d[4].strftime("%Y-%m-%d")]


def test_pending_entry_reported_at_as_of():
    d = bdays(4)
    f = frame(d, [10, 10, 10, 12], signals=[3], rs=77.0)
    r = simulate({"A": f}, cfg())
    assert r.open_positions == []
    pe = r.pending_entries[0]
    assert pe["symbol"] == "A" and pe["signal_close"] == 12 and pe["desired_qty"] == pytest.approx(1000 * 0.04 / 1.2)
    assert pe["est_stop_from_close"] == pytest.approx(10.8)


def _random_universe(n_sym=6, n=700, seed=7):
    rng = np.random.default_rng(seed)
    d = bdays(n, "2018-01-01")
    out = {}
    for k in range(n_sym):
        c = 40 * np.exp(np.cumsum(rng.normal(0.0012, 0.018, n)))
        o = c * (1 + rng.normal(0, 0.004, n))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
        v = rng.lognormal(13, 0.5, n)
        out[f"S{k}"] = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=d)
    bench = pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))}, index=d)
    return out, bench


@pytest.mark.parametrize("mode", ["proxy", "percentile"])
def test_as_of_truncation_has_no_lookahead(mode):
    syms, bench = _random_universe()
    as_of = syms["S0"].index[600]
    p = resolve("SP500")
    c = PortfolioConfig(params=p, rs_mode=mode, test_start="2019-01-01", as_of=as_of)
    full = run_portfolio(syms, bench, c)
    assert len(full.trades) > 0
    assert full.equity.index[-1] == as_of
    # wreck everything after as_of: results must not change
    wrecked = {s: df.copy() for s, df in syms.items()}
    for df in wrecked.values():
        df.loc[df.index > as_of, ["open", "high", "low", "close"]] *= 5
    wb = bench.copy()
    wb.loc[wb.index > as_of, "close"] = 1.0
    other = run_portfolio(wrecked, wb, c)
    pd.testing.assert_frame_equal(full.equity, other.equity)
    pd.testing.assert_frame_equal(full.trades, other.trades)
    # and it equals a run on pre-truncated data
    trunc = {s: df.loc[:as_of] for s, df in syms.items()}
    pre = run_portfolio(trunc, bench.loc[:as_of], PortfolioConfig(params=p, rs_mode=mode, test_start="2019-01-01"))
    pd.testing.assert_frame_equal(full.equity, pre.equity)


def test_percentile_mode_sets_tt8_from_universe_rank():
    syms, bench = _random_universe(n_sym=5)
    c = PortfolioConfig(params=resolve("SP500"), rs_mode="percentile")
    fr = prepare_frames(syms, bench, c)
    day = fr["S0"].index[-1]
    wps = pd.Series({s: f.loc[day, "wp"] for s, f in fr.items()})
    pct = wps.rank(pct=True) * 100                          # 5 symbols -> 20, 40, 60, 80, 100
    for s, f in fr.items():
        assert f.loc[day, "rs_key"] == pytest.approx(pct[s])
        assert bool(f.loc[day, "tt8"]) is bool(pct[s] >= 70)
    assert sorted(pct.round(6)) == [20, 40, 60, 80, 100]


def test_prepare_then_simulate_equals_run():
    syms, bench = _random_universe(n_sym=3, n=500)
    c = PortfolioConfig(params=resolve("SP500"), rs_mode="proxy")
    a = run_portfolio(syms, bench, c)
    b = simulate(prepare_frames(syms, bench, c), c)
    pd.testing.assert_frame_equal(a.equity, b.equity)


# --- metrics -------------------------------------------------------------------------

def tiny_result():
    idx = pd.to_datetime(["2020-01-01", "2020-12-31", "2021-06-30", "2021-12-31"])
    eq = pd.DataFrame({"cash": [100, 50, 50, 60], "positions_value": [0, 60, 49, 61],
                       "equity": [100.0, 110.0, 99.0, 121.0], "n_positions": [0, 1, 1, 1]}, index=idx)
    eq["exposure_pct"] = eq["positions_value"] / eq["equity"] * 100
    trades = pd.DataFrame({"exit_date": ["2020-06-01", "2020-09-01", "2021-03-01", "2021-11-01"],
                           "net_pnl": [50.0, -10.0, -20.0, 5.0], "pnl_pct": [25.0, -5.0, -10.0, 2.5]})
    bench = pd.DataFrame({"close": [50.0, 55.0, 60.5]}, index=pd.to_datetime(["2020-01-01", "2020-12-31", "2021-12-31"]))
    return PortfolioResult(eq, trades, pd.DataFrame()), bench


def test_metrics_on_tiny_equity_curve():
    r, bench = tiny_result()
    m = compute_metrics(r, bench)
    f = m["full"]
    assert f["days"] == 730 and f["return_pct"] == pytest.approx(21.0)
    assert f["cagr_pct"] == pytest.approx((1.21 ** (365.25 / 730) - 1) * 100)
    assert f["bench_cagr_pct"] == pytest.approx(f["cagr_pct"]) and f["excess_cagr_pp"] == pytest.approx(0.0)
    assert f["max_drawdown_pct"] == pytest.approx(-10.0)
    assert f["trades"] == 4 and f["win_rate_pct"] == 50.0
    assert f["avg_win_pct"] == pytest.approx(13.75) and f["avg_loss_pct"] == pytest.approx(-7.5)
    assert f["profit_factor"] == pytest.approx(55 / 30)
    assert f["big_win_profit_share_pct"] == pytest.approx(50 / 55 * 100)
    assert f["big_win_trade_share_pct"] == 25.0
    assert f["exposure_pct"] == pytest.approx(np.mean([0, 60 / 110, 49 / 99, 61 / 121]) * 100)
    y20, y21 = m["years"]["2020"], m["years"]["2021"]
    assert y20["base_date"] == "2020-01-01" and y20["return_pct"] == pytest.approx(10.0)
    assert y21["base_date"] == "2020-12-31" and y21["return_pct"] == pytest.approx(10.0)
    assert y21["max_drawdown_pct"] == pytest.approx(-10.0) and y21["trades"] == 2
    assert y21["bench_return_pct"] == pytest.approx(10.0) and y21["excess_return_pp"] == pytest.approx(0.0)
    assert y21["full_year"] and not y20["full_year"]
    assert m["last_1y"]["base_date"] == "2020-12-31" and m["last_1y"]["end"] == "2021-12-31"
    oos = compute_metrics(r, bench, oos_start="2021-01-01")["oos"]
    assert oos["return_pct"] == pytest.approx(10.0)


def test_trade_stats_edge_cases():
    assert trade_stats(pd.DataFrame())["trades"] == 0
    s = trade_stats(pd.DataFrame({"net_pnl": [5.0, 7.0], "pnl_pct": [1.0, 30.0]}))
    assert s["profit_factor"] is None and s["win_rate_pct"] == 100.0 and s["avg_loss_pct"] is None
    assert s["big_win_profit_share_pct"] == pytest.approx(7 / 12 * 100)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_single_symbol_portfolio_matches_state_machine(seed):
    """With one symbol and ample cash, every portfolio trade is exactly a state.py round trip."""
    from swing_engine.compare_api import analyze_frames
    syms, bench = _random_universe(n_sym=1, n=600, seed=seed)
    p = resolve("SP500", use_tt=False, regime_mode="NONE", vol_mult=1.1)
    df = syms["S0"]
    _, _, events, _ = analyze_frames(df, bench, p)
    trips, cur = [], None
    for e in events:
        if e.type == "ENTRY":
            cur = (e.date.strftime("%Y-%m-%d"), e.price)
        elif e.type in ("STOP", "EXIT_MA"):
            trips.append(cur + (e.date.strftime("%Y-%m-%d"), e.price, e.type))
    assert len(trips) >= 5
    r = run_portfolio(syms, bench, PortfolioConfig(params=p, rs_mode="proxy", cost_pct=0.0))
    got = [(t.entry_date, t.entry_price, t.exit_date, t.exit_price, t.exit_type) for t in r.trades.itertuples()]
    assert got == trips
    assert len(r.skipped) == 0


def test_fractional_dust_fill_is_skipped():
    d = bdays(4)
    # risk 9.95% / stop 10% -> desired = 99.5% of equity. A fills 995 at 10 -> cash 5.
    # D's desired is ~995 too; 5 of cash buys 0.5% of it -> skipped instead of a dust position.
    frames = {"A": frame(d, [10] * 4, signals=[0], rs=90.0), "D": frame(d, [10] * 4, signals=[2], rs=95.0)}
    r = simulate(frames, cfg(risk_pct=9.95))
    assert [x["symbol"] for x in r.open_positions] == ["A"]
    assert r.equity["cash"].iloc[-1] == pytest.approx(5.0)
    assert list(r.skipped["symbol"]) == ["D"]
    # with the guard off, the same run opens a 0.5-share D position
    r2 = simulate(frames, cfg(risk_pct=9.95, min_fill_frac=0.0))
    assert sorted(x["symbol"] for x in r2.open_positions) == ["A", "D"]


# --- review regression: a bar with a zero / NaN open or low is no bar ------------------

def test_zero_open_does_not_fill_a_pending_exit_at_zero():
    d = bdays(6)
    # entry d1 at 10 (stop 9); d2 close 9.5 < exit_ma 11 -> exit pending; d3 is a halted row
    # (open = low = 0); the exit fills at the next valid open 9.7, not at 0 (-100%)
    f = frame(d, [10, 10, 9.5, 9.6, 9.7, 9.7], opens=[10, 10, 9.5, 0, 9.7, 9.7], signals=[0],
              exit_ma=np.array([0, 0, 11, 0, 0, 0]))
    r = simulate({"A": f}, cfg())
    tr = r.trades.iloc[0]
    assert (tr["exit_type"], tr["exit_date"], tr["exit_price"]) == ("EXIT_MA", d[4].strftime("%Y-%m-%d"), 9.7)
    assert tr["pnl_pct"] == pytest.approx(-3.0)
    assert np.isfinite(r.equity["equity"]).all()


@pytest.mark.parametrize("bad_open,bad_low", [(np.nan, 8.4), (10.0, 0.0), (0.0, 0.0)])
def test_nan_or_zero_price_bar_neither_stops_nor_poisons_cash(bad_open, bad_low):
    d = bdays(6)
    opens = [10, 10, bad_open, 9.6, 9.7, 9.7]
    lows = [10, 10, bad_low, 9.6, 9.7, 9.7]
    f = frame(d, [10, 10, 9.5, 9.6, 9.7, 9.7], opens=opens, lows=lows, signals=[0])
    r = simulate({"A": f}, cfg())
    assert len(r.trades) == 0 and [x["symbol"] for x in r.open_positions] == ["A"]
    assert np.isfinite(r.equity["cash"]).all() and np.isfinite(r.equity["equity"]).all()
    assert r.equity["equity"].iloc[2] == pytest.approx(1000.0)          # marked at the last valid close
