"""compute() output contract (COMPARE_API.md)."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import bench_rows_from, rising_bench, rows_from, uptrend_with_breakout
from swing_engine.compare_api import compute

BAR_KEYS = {"date", "ma50", "ma150", "ma200", "exit_ma", "hi52", "lo52", "rs_diff", "tt", "tt_count",
            "tt_pass", "pivot", "vol_x", "breakout", "vol_ok", "cap_ok", "regime_on", "candidate",
            "full_signal", "entry_price", "stop_price", "entry_pending", "exit_pending"}


@pytest.fixture
def breakout():
    df = uptrend_with_breakout()
    return df, rising_bench(df.index)


def test_contract_and_signal_on_last_bar(breakout, sp500):
    df, b = breakout
    out = compute(rows_from(df), bench_rows_from(b), sp500)
    json.dumps(out, allow_nan=False)                       # None, never NaN; plain Python types
    assert set(out) == {"bars", "events", "status"}
    assert len(out["bars"]) == len(df)
    first, last = out["bars"][0], out["bars"][-1]
    assert set(first) == BAR_KEYS
    assert first["ma50"] is None and first["pivot"] is None and first["entry_price"] is None
    assert last["tt"] == [True] * 8 and last["tt_count"] == 8 and last["full_signal"]
    assert last["entry_pending"] and not last["exit_pending"] and last["entry_price"] is None
    assert out["events"][-1] == {"date": last["date"], "type": "SIGNAL", "price": float(df["close"].iloc[-1]),
                                 "pnl_pct": None}
    assert out["status"] == "신호 확정 → 다음 시가 진입"


def test_entry_next_open_then_in_position(breakout, sp500):
    df, b = breakout
    nxt = df.index[-1] + pd.offsets.BDay(1)
    c = float(df["close"].iloc[-1])
    df2 = pd.concat([df, pd.DataFrame({"open": [c * 1.01], "high": [c * 1.03], "low": [c * 1.0],
                                       "close": [c * 1.02], "volume": [1e6]}, index=[nxt])])
    b2 = rising_bench(df2.index)
    out = compute(rows_from(df2), bench_rows_from(b2), sp500)
    last = out["bars"][-1]
    assert last["entry_price"] == pytest.approx(c * 1.01)
    assert last["stop_price"] == pytest.approx(c * 1.01 * 0.9)
    assert out["events"][-1]["type"] == "ENTRY"
    assert out["status"] == "보유 중 — 50일선 종가 이탈 시 청산"


def test_missing_volume_means_no_confirmation(sp500):
    df = uptrend_with_breakout()
    rows = rows_from(df)
    rows[-1]["volume"] = None                              # no volume -> no confirmation
    out = compute(rows, bench_rows_from(rising_bench(df.index)), sp500)
    last = out["bars"][-1]
    assert last["vol_x"] is None and not last["vol_ok"] and not last["full_signal"]
    assert last["breakout"] and last["tt_pass"]
    assert out["status"] == "돌파 · 거래량 부족"


def test_benchmark_on_its_own_sparse_calendar(sp500):
    df = uptrend_with_breakout()                           # 420 symbol bars
    brow = bench_rows_from(rising_bench(df.index))[::2]    # 210 benchmark bars
    out = compute(rows_from(df), brow, sp500)
    last = out["bars"][-1]
    assert last["regime_on"]                               # b_ma200 from 200 benchmark bars exists
    assert last["rs_diff"] is None                         # b_perf needs 253 benchmark bars
    assert last["tt"][7] is False and out["status"] == "후보 아님 (트렌드 템플릿 7/8)"


def test_empty_benchmark_gives_no_regime_and_no_rs(sp500):
    df = uptrend_with_breakout()
    out = compute(rows_from(df), [], sp500)
    last = out["bars"][-1]
    assert last["rs_diff"] is None and not last["regime_on"] and last["tt_count"] == 7
    assert out["status"] == "후보 아님 (트렌드 템플릿 7/8)"
