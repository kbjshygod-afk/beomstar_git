"""Korean status label (SPEC section 6; Pine `statusTxt`, lines 230-239).

Strings are copied character for character from the Pine indicator:
em dash U+2014 ("—"), right arrow U+2192 ("→"), middle dot U+00B7 ("·").
"""
from __future__ import annotations

import math

from .indicators import pine_round_int

LABEL_IN_POS = "보유 중 — {n}일선 종가 이탈 시 청산"
LABEL_ENTRY_PENDING = "신호 확정 → 다음 시가 진입"
LABEL_NOT_TT = "후보 아님 (트렌드 템플릿 {n}/8)"
LABEL_NOT_LIQUID = "후보 아님 (거래대금 부족)"
LABEL_REGIME_OFF = "레짐 OFF — 신규 진입 금지"
LABEL_CHASE = "추격 제외 (돌파폭 {pct})"
LABEL_LOW_VOL = "돌파 · 거래량 부족"
LABEL_P1 = "1순위 · 임박 (피벗 1% 이내)"
LABEL_P2 = "2순위 · 근접 (피벗 3% 이내)"
LABEL_P3 = "3순위 · 관찰"


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def fmt_num1(x) -> str:
    """Pine "#.#" without sign: one optional decimal, ties rounded up on |x|."""
    tenths = pine_round_int(abs(float(x)) * 10)
    whole, frac = divmod(tenths, 10)
    return f"{whole}" if frac == 0 else f"{whole}.{frac}"


def fmt_pct(x) -> str:
    """Pine f_pct (line 224): "+#.#;-#.#" + "%", "-" for na.

    1. round |x| to one decimal as pine_round(|x| * 10) / 10 (integer tenths, no float
       formatting), 2. drop a trailing ".0", 3. "+" for x >= 0 else "-", then "%".
    16.04 -> "+16%", 16.25 -> "+16.3%".
    """
    if _nan(x):
        return "-"
    x = float(x)
    return ("+" if x >= 0 else "-") + fmt_num1(x) + "%"


def fmt_pp(x) -> str:
    """Same as fmt_pct but with the %p unit (RS proxy row, Pine line 260)."""
    if _nan(x):
        return "-"
    x = float(x)
    return ("+" if x >= 0 else "-") + fmt_num1(x) + "%p"


def status_label(*, in_pos: bool, entry_pending: bool, tt_pass: bool, tt_count: int,
                 liquidity_ok: bool, regime_on: bool, breakout: bool, cap_ok: bool,
                 vol_ok: bool, breakout_pct: float, to_pivot_pct: float, exit_ma_len: int) -> str:
    """First matching rule wins, in the Pine order. NaN comparisons are False."""
    if in_pos:
        return LABEL_IN_POS.format(n=int(exit_ma_len))
    if entry_pending:
        return LABEL_ENTRY_PENDING
    if not tt_pass:
        return LABEL_NOT_TT.format(n=int(tt_count))
    if not liquidity_ok:
        return LABEL_NOT_LIQUID
    if not regime_on:
        return LABEL_REGIME_OFF
    if breakout and not cap_ok:
        return LABEL_CHASE.format(pct=fmt_pct(breakout_pct))
    if breakout and not vol_ok:
        return LABEL_LOW_VOL
    if not _nan(to_pivot_pct) and to_pivot_pct <= 1:
        return LABEL_P1
    if not _nan(to_pivot_pct) and to_pivot_pct <= 3:
        return LABEL_P2
    return LABEL_P3


def status_from(ind_row, state: dict, exit_ma_len: int) -> str:
    """Label from one indicator row (Series/dict) and the machine state after that bar."""
    in_pos = not _nan(state.get("entry_price"))
    return status_label(
        in_pos=in_pos, entry_pending=bool(state.get("entry_pending")),
        tt_pass=bool(ind_row["tt_pass"]), tt_count=int(ind_row["tt_count"]),
        liquidity_ok=bool(ind_row["liquidity_ok"]), regime_on=bool(ind_row["regime_on"]),
        breakout=bool(ind_row["breakout"]), cap_ok=bool(ind_row["cap_ok"]),
        vol_ok=bool(ind_row["vol_ok"]), breakout_pct=float(ind_row["breakout_pct"]),
        to_pivot_pct=float(ind_row["to_pivot_pct"]), exit_ma_len=exit_ma_len,
    )
