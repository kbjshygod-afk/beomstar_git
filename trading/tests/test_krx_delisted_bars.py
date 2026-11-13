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


def test_halt_days_become_flat_bars_and_the_gap_after_is_kept():
    """A halted stock keeps its last close with no trades; the liquidation gap is not adjusted away."""
    b = K.adjusted_bars(_rows([
        ("2021-03-02", 5000, 5100, 4950, 5000, 1000, 0),
        ("2021-03-03", 0, 0, 0, 5000, 0, 0),              # halted
        ("2021-03-04", 0, 0, 0, 5000, 0, 0),
        ("2021-03-05", 900, 950, 500, 600, 99999, -4400),   # liquidation trading: reference still 5000
    ]))
    assert b.loc["2021-03-03", ["open", "high", "low", "close"]].tolist() == [5000.0] * 4
    assert b.attrs["actions"] == [] and b.loc["2021-03-05", "open"] == 900.0
    assert round(b["close"].pct_change().iloc[-1], 2) == -0.88


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
