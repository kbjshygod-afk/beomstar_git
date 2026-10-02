"""Regime BREADTH50 (docs/swing-upgrade-study-2026-10.md U11) and the KOSDAQ_V2 study preset."""
import numpy as np
import pandas as pd
from conftest import bdays, make_bars

from swing_engine import data as D
from swing_engine import paper as P
from swing_engine.indicators import compute_indicators
from swing_engine.params import BREADTH_MIN_PCT, data_market, normalize_regime, resolve
from swing_engine.portfolio import PortfolioConfig, breadth_series, prepare_frames


def test_preset_shares_kosdaq_data_and_adds_the_breadth_regime():
    p = resolve("KOSDAQ_V2")
    assert (p["regime_mode"], p["benchmark"], p["stop_pct"], p["cap_on"], p["integer_shares"]) == \
        ("BREADTH50", "^KQ11", 10.0, True, True)
    assert resolve("코스닥 v2") == p
    assert {k: v for k, v in p.items() if k != "regime_mode"} == \
        {k: v for k, v in resolve("KOSDAQ").items() if k != "regime_mode"}
    assert normalize_regime("폭50") == "BREADTH50" and BREADTH_MIN_PCT == 50.0
    assert data_market("KOSDAQ_V2") == "KOSDAQ" and data_market("KOSDAQ") == "KOSDAQ"
    assert D.session_for("KOSDAQ_V2") == D.session_for("KOSDAQ") == ("Asia/Seoul", 15, 30)
    assert D.benchmark_ticker("KOSDAQ_V2") == "^KQ11"
    assert P.MARKET_KO["KOSDAQ_V2"] == "코스닥 v2"
    assert P.next_open_deadline("KOSDAQ_V2", "2024-06-28") == P.next_open_deadline("KOSDAQ", "2024-06-28")


def test_a_single_symbol_leaves_the_gate_open():
    dates = bdays(260)
    bench = pd.DataFrame({"close": np.linspace(100, 120, 260)}, index=dates)
    ind = compute_indicators(make_bars(np.full(260, 10.0), dates=dates), bench, resolve("KOSDAQ_V2"))
    assert ind["regime_on"].all() and ind["b_breadth"].isna().all()


def _universe(lasts, dates):
    out = {}
    for name, last in zip("ABCDEFGH", lasts):
        c = np.full(len(dates), 100.0)
        c[-1] = last
        out[name] = make_bars(c, dates=dates)
    return out


def test_breadth_gates_the_whole_universe():
    dates = bdays(260)
    bench = pd.DataFrame({"close": np.full(260, 100.0)}, index=dates)
    cfg = PortfolioConfig(params=resolve("KOSDAQ_V2"), rs_mode="percentile", test_start=dates[0])
    last = dates[-1]
    # two of four above their 200-day MA on the last bar: 50% -> open
    frames = prepare_frames(_universe([101, 101, 99, 99], dates), bench, cfg)
    assert frames["A"].loc[last, "b_breadth"] == 50.0
    assert all(bool(f.loc[last, "regime_on"]) for f in frames.values())
    # one of four: 25% -> closed, and the signal column follows
    frames = prepare_frames(_universe([101, 99, 99, 99], dates), bench, cfg)
    assert frames["A"].loc[last, "b_breadth"] == 25.0
    assert not any(bool(f.loc[last, "regime_on"]) for f in frames.values())
    assert not frames["A"]["full_signal"].iloc[-1]
    # flat closes equal their MA (not above): 0%; before any 200-day MA exists: NaN and closed
    assert frames["A"]["b_breadth"].iloc[-2] == 0.0 and not bool(frames["A"]["regime_on"].iloc[-2])
    assert np.isnan(frames["A"]["b_breadth"].iloc[0]) and not bool(frames["A"]["regime_on"].iloc[0])
    # the proxy mode re-finalizes the signals too
    cfg2 = PortfolioConfig(params=resolve("KOSDAQ_V2"), rs_mode="proxy", test_start=dates[0])
    frames2 = prepare_frames(_universe([101, 99, 99, 99], dates), bench, cfg2)
    assert not bool(frames2["A"].loc[last, "regime_on"]) and not frames2["A"]["full_signal"].iloc[-1]


def test_breadth_series_counts_only_members_of_the_day():
    dates = bdays(260)
    bars = _universe([101, 101, 99, 99], dates)
    inds = {s: compute_indicators(b, None, resolve("KOSDAQ_V2")) for s, b in bars.items()}
    member = pd.DataFrame(True, index=dates, columns=list(bars))
    member.loc[dates[-1], ["C", "D"]] = False          # only the two leaders are members that day
    assert breadth_series(bars, inds).iloc[-1] == 50.0
    assert breadth_series(bars, inds, member).iloc[-1] == 100.0


def test_report_and_alert_show_the_breadth():
    rg = {"benchmark": "^KQ11", "mode": "BREADTH50", "close": 900.0, "ma200": 950.0, "ma20": 880.0,
          "on": False, "breadth_pct": 43.3}
    snap = {"market": "KOSDAQ_V2", "as_of": "2026-10-02", "regime": rg, "entries_next_open": [],
            "exits_next_open": [], "positions": [], "watchlist": [],
            "coverage": {"requested": 150, "loaded": 150, "failed": []}}
    cfg = {"start_date": "2026-10-06", "rs_mode": "percentile", "risk_pct": 0.75, "cost_pct": 0.2}
    perf = {"equity": 1e8, "return_pct": 0.0, "bench_return_pct": 0.0, "mdd_pct": 0.0, "closed_trades": 0,
            "win_rate_pct": None, "avg_win_pct": None, "avg_loss_pct": None}
    aud = {"days": 1, "signal_files": 1, "missing_days": [], "late": [], "uncommitted": [], "mismatched": [],
           "revised": [], "rows": [{"on_time": True}]}

    class Res:
        open_positions = []
    report = P.render_report("KOSDAQ_V2", cfg, snap, perf, aud, Res(), resolve("KOSDAQ_V2"))
    assert "코스닥 v2" in report and "레짐 (BREADTH50): **OFF**" in report
    assert "유니버스 중 200일선 위 43.3% (기준 50%)" in report
