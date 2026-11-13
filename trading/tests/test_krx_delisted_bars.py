import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import krx_delisted_bars as K  # noqa: E402


def _rows(recs):
    cols = ["Date", "Open", "High", "Low", "Close", "Volume", "Changes"]
    return pd.DataFrame([dict(zip(cols, r)) for r in recs]).assign(Date=lambda d: pd.to_datetime(d["Date"]))


def test_split_is_back_adjusted_from_the_reference_price():
    """A 2-for-1 split: the reference price of the ex-date (close - change) is half the previous
    close, so earlier prices are halved and earlier volume doubled."""
    b = K.adjusted_bars(_rows([
        ("2020-01-02", 1000, 1020, 990, 1000, 100, 0),
        ("2020-01-03", 1000, 1050, 1000, 1040, 200, 40),
        ("2020-01-06", 525, 530, 515, 530, 500, 10),      # reference 520 = 1040 / 2
        ("2020-01-07", 530, 540, 528, 535, 300, 5),
    ]))
    assert b.attrs["actions"] == [("2020-01-06", 0.5)]
    assert b["close"].tolist() == [500.0, 520.0, 530.0, 535.0]
    assert b["volume"].tolist() == [200.0, 400.0, 500.0, 300.0]
    assert round(b["close"].pct_change().iloc[2], 4) == round(530 / 520 - 1, 4)     # no artificial -49% day


def test_normal_days_and_rounding_are_not_treated_as_actions():
    b = K.adjusted_bars(_rows([
        ("2020-01-02", 10000, 10100, 9900, 10000, 10, 0),
        ("2020-01-03", 10000, 10300, 9990, 10250, 10, 250),
        ("2020-01-06", 10200, 10200, 9000, 9010, 10, -1240),          # reference 10250, a real -12% day
        ("2020-01-07", 9000, 9100, 8990, 9020, 10, 0),                # reference 9020 vs 9010: 0.1% rounding
    ]))
    assert b.attrs["actions"] == [] and b["close"].tolist() == [10000.0, 10250.0, 9010.0, 9020.0]


def test_halt_days_are_left_out_and_the_gap_after_is_kept():
    """A halted day gets no bar (so nothing can fill on it); the liquidation gap is not adjusted away."""
    b = K.adjusted_bars(_rows([
        ("2021-03-02", 5000, 5100, 4950, 5000, 1000, 0),
        ("2021-03-03", 0, 0, 0, 5000, 0, 0),              # halted
        ("2021-03-04", 0, 0, 0, 5000, 0, 0),
        ("2021-03-05", 900, 950, 500, 600, 99999, -4400),   # liquidation trading: reference still 5000
    ]))
    assert [d.strftime("%m-%d") for d in b.index] == ["03-02", "03-05"] and b.attrs["halted_days"] == 2
    assert b.attrs["actions"] == [] and b.loc["2021-03-05", "open"] == 900.0
    assert round(b["close"].pct_change().iloc[-1], 2) == -0.88


def test_a_split_during_a_halt_is_still_adjusted():
    """The factor comes from the halted rows too: a reverse split that takes effect while halted."""
    b = K.adjusted_bars(_rows([
        ("2021-03-02", 500, 510, 495, 500, 1000, 0),
        ("2021-03-03", 0, 0, 0, 500, 0, 0),               # halted
        ("2021-03-04", 0, 0, 0, 5000, 0, 0),              # 10-for-1 reverse split, reference 5000, still halted
        ("2021-03-05", 5100, 5200, 5000, 5100, 10, 100),
    ]))
    assert b.attrs["actions"] == [("2021-03-04", 10.0)] and b["close"].tolist() == [5000.0, 5100.0]


def test_a_pending_exit_waits_for_the_first_real_open_after_a_halt():
    """Through the simulator: exit signalled the day before a halt fills at the reopening gap,
    not at the last close (cross-review of 2026-11-13)."""
    import numpy as np
    from swing_engine.params import resolve
    from swing_engine.portfolio import PortfolioConfig, simulate
    b = K.adjusted_bars(_rows([
        ("2021-03-01", 10, 10, 10, 10, 100, 0),
        ("2021-03-02", 10, 10, 10, 10, 100, 0),           # entry at this open (signal the day before)
        ("2021-03-03", 10, 10, 9.5, 9.5, 100, -0.5),      # close below the exit MA: exit pending
        ("2021-03-04", 0, 0, 0, 9.5, 0, 0),               # halted
        ("2021-03-05", 0, 0, 0, 9.5, 0, 0),               # halted
        ("2021-03-08", 3, 3.2, 2.5, 3, 5000, -6.5),       # liquidation trading
    ]))
    f = b.assign(exit_ma=np.where(b.index == pd.Timestamp("2021-03-03"), 11.0, 0.0),
                 full_signal=b.index == pd.Timestamp("2021-03-01"), rs_key=50.0)
    cfg = PortfolioConfig(params=resolve("CUSTOM", stop_pct=50.0), initial_equity=1000.0, risk_pct=4.0, cost_pct=0.0)
    r = simulate({"X.KQ": f}, cfg)
    assert len(r.trades) == 1
    t = r.trades.iloc[0]
    assert t["exit_date"] == "2021-03-08" and t["exit_price"] == 3.0 and t["exit_type"] == "EXIT_MA"


def test_a_stop_through_a_halt_fills_at_the_reopening_open():
    """Held into a halt with no exit signal: the stop is taken at the first real open, far below it."""
    from swing_engine.params import resolve
    from swing_engine.portfolio import PortfolioConfig, simulate
    b = K.adjusted_bars(_rows([
        ("2021-03-01", 10, 10, 10, 10, 100, 0),
        ("2021-03-02", 10, 10, 10, 10, 100, 0),           # entry at this open, stop 9
        ("2021-03-03", 0, 0, 0, 10, 0, 0),                # halted
        ("2021-03-04", 0, 0, 0, 10, 0, 0),                # halted
        ("2021-03-05", 2, 2.2, 1.5, 2, 5000, -8),         # liquidation trading opens at 2
    ]))
    f = b.assign(exit_ma=0.0, full_signal=b.index == pd.Timestamp("2021-03-01"), rs_key=50.0)
    cfg = PortfolioConfig(params=resolve("CUSTOM", stop_pct=10.0), initial_equity=1000.0, risk_pct=4.0, cost_pct=0.0)
    t = simulate({"X.KQ": f}, cfg).trades.iloc[0]
    assert t["exit_type"] == "STOP" and t["exit_date"] == "2021-03-05" and t["exit_price"] == 2.0
    assert round(t["price_pnl_pct"]) == -80


def test_missing_year_file_is_an_error_not_a_fake_action(tmp_path):
    pytest.importorskip("pyarrow")
    rows = pd.DataFrame({"Code": ["000020"], "Date": pd.to_datetime(["2020-01-02"]), "Open": [5.0], "High": [6.0],
                         "Low": [4.0], "Close": [5.0], "Volume": [9.0], "Changes": [0.0]})
    rows.to_parquet(tmp_path / "marcap-2020.parquet")
    rows.to_parquet(tmp_path / "marcap-2022.parquet")
    with pytest.raises(FileNotFoundError, match="2021"):
        K.load_marcap(tmp_path, {"000020"}, 2020, 2022)


def test_member_codes_ignores_blanks_and_check_without_data_does_not_crash(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    pd.DataFrame({"date": ["2020-01-02", "2020-01-03"], "codes": ["000010, 000020,", None]}).to_csv(tmp_path / "m.csv.gz", index=False)
    assert K.member_codes(tmp_path / "m.csv.gz") == {"000010", "000020"}
    data, marcap, out = tmp_path / "data", tmp_path / "marcap", tmp_path / "out"
    data.mkdir()
    marcap.mkdir()
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    yahoo = pd.DataFrame({"open": [10.0, 11], "high": [10.0, 11], "low": [10.0, 11], "close": [10.0, 11], "volume": [1.0, 1]}, index=idx)
    pd.to_pickle({"market": "KOSDAQ", "frames": {"000010.KQ": yahoo, "000020.KQ": yahoo.iloc[:0]}, "universe": ["000010.KQ"],
                  "bench": pd.DataFrame({"close": [1.0, 2.0]}, index=idx)}, data / "KOSDAQ.pkl.xz", compression="xz")
    pd.DataFrame({"date": ["2020-01-02"], "codes": ["000010,000020"]}).to_csv(data / "KOSDAQ_membership.csv.gz", index=False)
    pd.DataFrame({"Code": ["000020", "000020", "000010", "000010"], "Date": list(idx) * 2, "Open": [5.0] * 4, "High": [6.0] * 4,
                  "Low": [4.0] * 4, "Close": [5.0] * 4, "Volume": [9.0] * 4, "Changes": [0.0] * 4}).to_parquet(marcap / "marcap-2020.parquet")
    assert K.main(["--data", str(data), "--market", "KOSDAQ", "--marcap-dir", str(marcap), "--out", str(out),
                   "--start", "2020", "--end", "2020", "--check", "5"]) == 0
    text = capsys.readouterr().out
    assert "not validated" in text and "built 1" in text                    # the empty Yahoo frame counted as missing
    snap = pd.read_pickle(out / "KOSDAQ.pkl.xz", compression="xz")
    assert len(snap["frames"]["000020.KQ"]) == 2 and snap["universe"] == ["000010.KQ"]


def test_reverse_split_and_two_actions_compound():
    b = K.adjusted_bars(_rows([
        ("2019-01-02", 100, 100, 100, 100, 1000, 0),
        ("2019-01-03", 1000, 1100, 1000, 1100, 100, 100),        # 10-for-1 reverse split: reference 1000
        ("2019-01-04", 550, 560, 540, 560, 300, 10),             # then 2-for-1 split: reference 550
    ]))
    assert [f for _, f in b.attrs["actions"]] == [10.0, 0.5]
    assert b["close"].tolist() == [500.0, 550.0, 560.0]          # 100 * 10 * 0.5, 1100 * 0.5
    assert K.adjusted_bars(_rows([("2019-01-02", 0, 0, 0, 0, 0, 0)])).empty


def test_main_fills_only_members_without_yahoo_data(tmp_path, capsys):
    pytest.importorskip("pyarrow")                      # marcap files are parquet; not in requirements.txt
    data, marcap, out = tmp_path / "data", tmp_path / "marcap", tmp_path / "out"
    data.mkdir()
    marcap.mkdir()
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    yahoo = pd.DataFrame({"open": [10.0, 11, 12], "high": [10.0, 11, 12], "low": [10.0, 11, 12],
                          "close": [10.0, 11, 12], "volume": [1.0, 1, 1]}, index=idx)
    bench = pd.DataFrame({"close": [1.0, 2.0]}, index=idx[:2])                    # snapshot ends 01-03
    pd.to_pickle({"market": "KOSDAQ", "frames": {"000010.KQ": yahoo}, "universe": ["000010.KQ"], "bench": bench},
                 data / "KOSDAQ.pkl.xz", compression="xz")
    pd.DataFrame({"date": ["2020-01-02"], "codes": ["000010,000020"]}).to_csv(data / "KOSDAQ_membership.csv.gz", index=False)
    rows = pd.DataFrame({"Code": ["000020"] * 3 + ["000010"] * 3, "Date": list(idx) * 2,
                         "Open": [5.0] * 6, "High": [6.0] * 6, "Low": [4.0] * 6, "Close": [5.0] * 6,
                         "Volume": [9.0] * 6, "Changes": [0.0] * 6})
    rows.to_parquet(marcap / "marcap-2020.parquet")
    assert K.main(["--data", str(data), "--market", "KOSDAQ", "--marcap-dir", str(marcap), "--out", str(out),
                   "--start", "2020", "--end", "2020"]) == 0
    snap = pd.read_pickle(out / "KOSDAQ.pkl.xz", compression="xz")
    assert snap["filled"] == ["000020.KQ"] and snap["frames"]["000010.KQ"].equals(yahoo)   # Yahoo frame untouched
    assert len(snap["frames"]["000020.KQ"]) == 2                                          # clipped to the snapshot window
    assert (out / "KOSDAQ_membership.csv.gz").exists() and "built 1" in capsys.readouterr().out
