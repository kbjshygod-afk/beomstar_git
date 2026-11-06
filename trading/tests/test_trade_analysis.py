"""Trade autopsy: per-trade path figures, backtest reference, and the end-to-end report."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools import trade_analysis as TA


def _bars(n=120, start="2026-01-01"):
    d = pd.bdate_range(start, periods=n)
    c = np.linspace(100, 100, n)
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": np.full(n, 1000.0)},
                      index=pd.DatetimeIndex(d, name="date"))
    return df


def test_trade_path_mfe_mae_and_stop_bar():
    df = _bars()
    e = df.index[60]
    df.loc[df.index[62], "high"] = 112.0      # +12% two bars after entry
    df.loc[df.index[64], "low"] = 89.0        # -11% four bars after entry, through a 90 stop
    out = TA.trade_path(df, e, df.index[65], entry_price=100.0, stop_price=90.0)
    assert out["mfe_pct"] == 12.0 and out["mae_pct"] == -11.0
    assert out["bars_to_mfe"] == 2 and out["bars_to_mae"] == 4 and out["bars_to_stop"] == 4
    assert out["risk_pct"] == 10.0 and out["mfe_r"] == 1.2 and out["mae_r"] == -1.1
    assert out["bars"] == 6
    # open trade: path runs to the last bar
    assert TA.trade_path(df, e, None, 100.0, 90.0)["bars"] == len(df) - 60


def test_signal_features_pivot_excludes_signal_bar():
    df = _bars()
    s = df.index[70]
    df.loc[df.index[55], "high"] = 130.0      # inside the previous 20 bars
    df.loc[s, "high"] = 200.0                 # the signal bar itself is not part of the pivot
    df.loc[s, "close"] = 143.0
    df.loc[s, "volume"] = 2500.0
    f = TA.signal_features(df, s, {"pivot_len": 20, "vol_len": 50})
    assert f["pivot"] == 130.0 and f["breakout_pct"] == 10.0 and f["vol_x"] == 2.5


def test_backtest_reference_and_streak():
    rows = [{"exit_type": "STOP", "pnl_pct": -10, "exit_date": "2025-01-0%d" % i, "days_held": 3} for i in range(1, 5)]
    rows += [{"exit_type": "EXIT_MA", "pnl_pct": 30, "exit_date": "2025-02-01", "days_held": 40},
             {"exit_type": "OPEN", "pnl_pct": None, "exit_date": None, "days_held": None}]
    ref = TA.backtest_reference(rows)
    assert ref["n"] == 5 and ref["win_rate_pct"] == 20.0 and ref["longest_losing_streak"] == 4
    assert ref["stop_share_pct"] == 80.0 and ref["median_days"] == 3.0
    assert TA.backtest_reference(rows, since="2025-02-01")["n"] == 1
    assert TA.chance_of_run(20.0, 4) == pytest.approx(40.96)
    assert TA.longest_losing_streak([-1, -1, 2, -1]) == 2


def test_end_to_end_report(tmp_path):
    offline = tmp_path / "bars"; offline.mkdir()
    df = _bars()
    d = df.index
    sig, ent, ex = d[70], d[71], d[80]
    df.loc[d[55], "high"] = 110.0
    df.loc[sig, "close"] = 112.0
    df.loc[d[71:100], ["open", "high", "low", "close"]] = [113.0, 114.0, 112.0, 113.0]
    df.loc[d[75], "high"] = 125.0
    df.loc[d[80], "low"] = 100.0
    out = df.reset_index().rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    out.to_csv(offline / "ACME.csv", index=False)
    out.to_csv(offline / "GSPC.csv", index=False)
    root = tmp_path / "ledger"; (root / "paper/SP500/signals").mkdir(parents=True)
    (root / "paper/SP500/trades.csv").write_text(
        "symbol,signal_date,signal_close,rs_at_signal,entry_date,entry_price,qty,desired_qty,partial,stop_price,entry_cost,cost_basis,exit_date,exit_price,exit_type,exit_cost,net_pnl,pnl_pct,price_pnl_pct,bars_held,days_held\n"
        f"ACME,{sig.date()},112.0,90.0,{ent.date()},113.0,10,10,False,101.7,1,1,{ex.date()},101.7,STOP,1,-100,-10.4,-10.0,9,13\n")
    (root / "paper/SP500/positions.json").write_text(json.dumps([{"symbol": "ACME", "signal_date": str(d[100].date()),
                                                                 "entry_date": str(d[101].date()), "entry_price": 100.0, "stop_price": 90.0, "qty": 5}]))
    (root / "paper/SP500/signals" / f"{d[100].date()}.json").write_text(json.dumps({"regime": {"on": True}, "entries_next_open": [{"symbol": "ACME", "signal_close": 98.0}]}))
    (root / "paper/SP500/signals" / f"{sig.date()}.json").write_text(json.dumps({"regime": {"on": True}}))
    (root / "paper/SP500/signals" / f"{sig.date()}.rev1.json").write_text(json.dumps({"regime": {"on": False}}))
    res = tmp_path / "results"; (res / "latest/results/SP500").mkdir(parents=True)
    (res / "latest/results/SP500/trades.csv").write_text(
        "symbol,signal_date,entry_date,exit_date,exit_type,pnl_pct,days_held\n"
        + "".join(f"X,2025-01-01,2025-01-02,2025-02-{i:02d},STOP,-9.0,5\n" for i in range(1, 8))
        + "Y,2025-01-01,2025-01-02,2025-03-01,EXIT_MA,40.0,30\nZ,2025-01-01,2025-01-02,2025-03-02,EXIT_MA,25.0,20\n")
    stem = tmp_path / "out" / "ta"
    rc = TA.main(["--ledger-dir", str(root / "paper"), "--results-dir", str(res), "--offline-dir", str(offline),
                  "--markets", "SP500", "--now", str(d[110].date()) + "T00:00:00", "--out", str(stem)])
    assert rc == 0
    j = json.loads(stem.with_suffix(".json").read_text())
    m = j["markets"][0]
    closed, opened = m["trades"]
    assert closed["pivot"] == 110.0 and closed["breakout_pct"] == pytest.approx(1.82, abs=0.01)
    assert closed["regime_on"] is False                      # the revision wins
    assert closed["mfe_pct"] == pytest.approx(10.62, abs=0.01) and closed["bars_to_mfe"] == 4
    assert closed["result_r"] == -1.0 and closed["mfe_r"] == pytest.approx(1.06, abs=0.01)
    assert closed["bars_to_stop"] == 9 and closed["entry_gap_pct"] == pytest.approx(0.89, abs=0.01)
    assert opened["exit_type"] == "OPEN" and opened["bars"] == 10 and opened["price_pnl_pct"] == 0.0
    assert opened["entry_gap_pct"] == pytest.approx(2.04, abs=0.01)      # signal_close taken from the signal file
    s = m["summary"]
    assert s["closed"] == 1 and s["open"] == 1 and s["wins"] == 0 and s["reached_1r"] == 1 and s["losing_streak"] == 1
    assert m["reference"]["win_rate_pct"] == pytest.approx(22.2, abs=0.1) and m["reference"]["longest_losing_streak"] == 7
    assert s["chance_of_streak_pct"] == pytest.approx(77.8, abs=0.1)
    text = stem.with_suffix(".md").read_text()
    assert "| S&P500 | 1 | 0 |" in text and "ACME" in text and "보유 중" in text
