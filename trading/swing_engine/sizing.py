"""Position sizing (SPEC section 7; Pine indicator lines 245-248).

qty = equity * risk_pct / 100 / (ref_price * stop_pct / 100)   (same operation order as Pine)
ref_price = entry price when in a position, else the signal bar's close.
Weight = risk_pct / stop_pct: 10.7% at a 7% stop, 7.5% at a 10% stop.
"""
from __future__ import annotations

import math

from .params import RISK_PCT


def weight_pct(stop_pct: float, risk_pct: float = RISK_PCT) -> float:
    return risk_pct / stop_pct * 100


def stop_price(entry_price: float, stop_pct: float) -> float:
    return entry_price * (1 - stop_pct / 100)


def raw_qty(equity: float, ref_price: float, stop_pct: float, risk_pct: float = RISK_PCT) -> float:
    if not (ref_price is not None and ref_price > 0):   # Pine: refPrice > 0 ? ... : na
        return float("nan")
    return equity * risk_pct / 100 / (ref_price * stop_pct / 100)


def position_qty(equity: float, ref_price: float, stop_pct: float, risk_pct: float = RISK_PCT,
                 integer_shares: bool = False) -> float:
    q = raw_qty(equity, ref_price, stop_pct, risk_pct)
    if math.isnan(q):
        return q
    return float(math.floor(q)) if integer_shares else q


def size_position(equity: float, ref_price: float, stop_pct: float, risk_pct: float = RISK_PCT,
                  integer_shares: bool = False) -> dict:
    """Everything a report needs about one suggested position."""
    q_raw = raw_qty(equity, ref_price, stop_pct, risk_pct)
    q = position_qty(equity, ref_price, stop_pct, risk_pct, integer_shares)
    notional = q * ref_price if not math.isnan(q) else float("nan")
    return {
        "qty_raw": q_raw,
        "qty": q,
        "whole_shares": float(math.floor(q_raw)) if not math.isnan(q_raw) else float("nan"),
        "integer_shares": bool(integer_shares),
        "ref_price": ref_price,
        "notional": notional,
        "weight_pct": weight_pct(stop_pct, risk_pct),
        "actual_weight_pct": notional / equity * 100 if equity and not math.isnan(notional) else float("nan"),
        "risk_amount": equity * risk_pct / 100,
        "stop_price": stop_price(ref_price, stop_pct) if ref_price else float("nan"),
    }
