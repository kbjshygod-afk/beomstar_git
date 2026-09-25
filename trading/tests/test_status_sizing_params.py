"""Status labels (SPEC 6), sizing (SPEC 7) and presets (SPEC 2)."""
import math

import pytest

from swing_engine.params import COMPARE_KEYS, PARAM_KEYS, PRESETS, resolve
from swing_engine.sizing import position_qty, raw_qty, size_position, stop_price, weight_pct
from swing_engine.status import fmt_pct, status_label

nan = float("nan")


# --- fmt_pct ---------------------------------------------------------------------

@pytest.mark.parametrize("x,expected", [
    (16.04, "+16%"), (16.25, "+16.3%"), (16.0, "+16%"), (0.0, "+0%"), (-3.14, "-3.1%"),
    (-3.15, "-3.2%"), (0.05, "+0.1%"), (-0.04, "-0%"), (123.456, "+123.5%"), (nan, "-"), (None, "-"),
])
def test_fmt_pct(x, expected):
    assert fmt_pct(x) == expected


# --- status label ordering ----------------------------------------------------------

BASE = dict(in_pos=False, entry_pending=False, tt_pass=True, tt_count=8, liquidity_ok=True,
            regime_on=True, breakout=False, cap_ok=True, vol_ok=False, breakout_pct=nan,
            to_pivot_pct=5.0, exit_ma_len=50)


def lab(**kw):
    return status_label(**{**BASE, **kw})


def test_status_exact_strings_and_order():
    assert lab(in_pos=True, entry_pending=True, tt_pass=False) == "보유 중 — 50일선 종가 이탈 시 청산"
    assert lab(in_pos=True, exit_ma_len=30) == "보유 중 — 30일선 종가 이탈 시 청산"
    assert lab(entry_pending=True, tt_pass=False, regime_on=False) == "신호 확정 → 다음 시가 진입"
    assert lab(tt_pass=False, tt_count=7, liquidity_ok=False) == "후보 아님 (트렌드 템플릿 7/8)"
    assert lab(tt_pass=False, tt_count=0) == "후보 아님 (트렌드 템플릿 0/8)"
    assert lab(liquidity_ok=False, regime_on=False) == "후보 아님 (거래대금 부족)"
    assert lab(regime_on=False, breakout=True, cap_ok=False, breakout_pct=20) == "레짐 OFF — 신규 진입 금지"
    assert lab(breakout=True, cap_ok=False, breakout_pct=16.25) == "추격 제외 (돌파폭 +16.3%)"
    assert lab(breakout=True, cap_ok=False, breakout_pct=16.04) == "추격 제외 (돌파폭 +16%)"
    assert lab(breakout=True, cap_ok=True, vol_ok=False, to_pivot_pct=-2) == "돌파 · 거래량 부족"
    assert lab(to_pivot_pct=1.0) == "1순위 · 임박 (피벗 1% 이내)"
    assert lab(to_pivot_pct=1.0000001) == "2순위 · 근접 (피벗 3% 이내)"
    assert lab(to_pivot_pct=3.0) == "2순위 · 근접 (피벗 3% 이내)"
    assert lab(to_pivot_pct=3.01) == "3순위 · 관찰"
    assert lab(to_pivot_pct=nan) == "3순위 · 관찰"


def test_status_characters():
    s = lab(in_pos=True)
    assert "—" in s                                     # em dash
    assert "→" in lab(entry_pending=True)               # right arrow
    assert "·" in lab(to_pivot_pct=0.5)                 # middle dot


# --- sizing --------------------------------------------------------------------------

def test_qty_formula_and_weight():
    assert raw_qty(100_000_000, 100.0, 10.0) == 75_000.0
    assert position_qty(100_000_000, 71_500.0, 7.0, integer_shares=True) == 149.0   # 149.85 -> 149
    assert position_qty(100_000_000, 71_500.0, 7.0) == pytest.approx(149.8501498501)
    assert weight_pct(7.0) == pytest.approx(10.714285714)
    assert weight_pct(10.0) == pytest.approx(7.5)
    assert math.isnan(raw_qty(1e6, 0.0, 10.0))
    assert stop_price(200.0, 7.0) == pytest.approx(186.0)


def test_size_position_fields():
    sz = size_position(10_000_000, 50_000.0, 10.0, integer_shares=True)
    assert sz["qty_raw"] == 15.0 and sz["qty"] == 15.0
    assert sz["notional"] == 750_000.0 and sz["weight_pct"] == 7.5
    assert sz["risk_amount"] == 75_000.0 and sz["stop_price"] == 45_000.0


# --- params ---------------------------------------------------------------------------

@pytest.mark.parametrize("preset,bench,regime,stop,cap,yb,whole", [
    ("SP500", "^GSPC", "MA200", 10.0, True, 252, False),
    ("NDX100", "^NDX", "MA200", 7.0, True, 252, False),
    ("KOSPI", "^KS11", "MA200_AND_MA20", 7.0, True, 252, True),
    ("KOSDAQ", "^KQ11", "NONE", 10.0, True, 252, True),
    ("CRYPTO", "BTC-USD", "MA200", 10.0, False, 365, False),
])
def test_presets(preset, bench, regime, stop, cap, yb, whole):
    p = resolve(preset)
    assert (p["benchmark"], p["regime_mode"], p["stop_pct"], p["cap_on"], p["year_bars"], p["integer_shares"]) == \
        (bench, regime, stop, cap, yb, whole)
    assert (p["pivot_len"], p["vol_len"], p["vol_mult"], p["max_breakout_pct"], p["ma200_rise_bars"],
            p["rs_min_diff"], p["exit_ma_len"], p["use_tt"], p["use_value_filter"], p["min_trading_value"]) == \
        (20, 50, 1.4, 15.0, 22, 0.0, 50, True, False, 3e9)


def test_resolve_keys_and_overrides():
    p = resolve("sp500", pivot_len=30, stop_pct=None, regime_mode="무필터")
    assert tuple(p) == PARAM_KEYS and set(COMPARE_KEYS) <= set(p)
    assert p["pivot_len"] == 30 and p["stop_pct"] == 10.0 and p["regime_mode"] == "NONE"
    c = resolve("CUSTOM", benchmark="^N225", cap_on="false", year_bars=250)
    assert c["benchmark"] == "^N225" and c["cap_on"] is False and c["year_bars"] == 250
    assert resolve("코스피")["regime_mode"] == "MA200_AND_MA20"
    with pytest.raises(ValueError):
        resolve("SP500", risk=1)
    with pytest.raises(ValueError):
        resolve("NIKKEI")
    with pytest.raises(ValueError):
        resolve("SP500", regime_mode="MA50")
    assert set(PRESETS) == {"SP500", "NDX100", "KOSPI", "KOSDAQ", "CRYPTO", "CUSTOM"}
