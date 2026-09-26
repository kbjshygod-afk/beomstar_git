"""Position state machine for one symbol (SPEC section 5; Pine indicator lines 147-188).

Within bar t the steps run in this exact order:
  1. pending exit fills at open[t]                       -> EXIT_MA
  2. pending entry fills at open[t], stop = open*(1-s)   -> ENTRY
  3. if in a position (including the entry bar itself):
       low <= stop  -> STOP filled at min(open, stop)    (a gap through the stop fills at the open)
       elif close < exit_ma -> exit pending              -> EXIT_SIGNAL
  4. if flat after 1-3 (a stop or an exit fill re-arms the same bar):
       entry_pending = full_signal[t]                    -> SIGNAL

Pine runs this only on confirmed bars (`barstate.isconfirmed`, line 163); every bar fed
here must be a completed daily bar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EVENT_TYPES = ("SIGNAL", "ENTRY", "STOP", "EXIT_SIGNAL", "EXIT_MA")
NAN = float("nan")


def _isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


@dataclass
class Event:
    date: object
    type: str
    price: float | None
    pnl_pct: float | None = None
    bar: int | None = None

    def as_dict(self) -> dict:
        d = self.date
        if isinstance(d, (pd.Timestamp, np.datetime64)):
            d = pd.Timestamp(d).strftime("%Y-%m-%d")
        return {"date": d, "type": self.type,
                "price": None if _isnan(self.price) else float(self.price),
                "pnl_pct": None if _isnan(self.pnl_pct) else float(self.pnl_pct)}


@dataclass
class PositionMachine:
    """The four Pine `var` state variables plus step helpers.

    The helpers are separate so the portfolio can put cash allocation between
    step 1 and step 2 without changing the order of the steps.
    """
    stop_pct: float
    entry_pending: bool = False
    exit_pending: bool = False
    entry_price: float = NAN
    stop_price: float = NAN
    events: list = field(default_factory=list)

    @property
    def in_pos(self) -> bool:
        return not math.isnan(self.entry_price)

    # step 1
    def fill_exit(self, date, o: float, bar=None) -> Event | None:
        if not self.exit_pending:
            return None
        self.exit_pending = False
        pnl = (o / self.entry_price - 1) * 100
        ev = Event(date, "EXIT_MA", o, pnl, bar)
        self.entry_price = NAN
        self.stop_price = NAN
        self.events.append(ev)
        return ev

    # step 2
    def fill_entry(self, date, o: float, bar=None) -> Event | None:
        if not self.entry_pending:
            return None
        self.entry_pending = False
        self.entry_price = o
        self.stop_price = o * (1 - self.stop_pct / 100)
        ev = Event(date, "ENTRY", o, None, bar)
        self.events.append(ev)
        return ev

    def cancel_entry(self) -> None:
        """Portfolio only: pending entry not funded (no cash) -> dropped, stays flat."""
        self.entry_pending = False

    # step 3
    def check_exit(self, date, o: float, l: float, c: float, exit_ma: float, bar=None) -> Event | None:
        if not self.in_pos:
            return None
        if l <= self.stop_price:                       # NaN low -> False
            fill = min(o, self.stop_price)             # gap below the stop fills at the open
            if math.isnan(o):
                fill = NAN                             # Pine math.min(na, x) is na
            ev = Event(date, "STOP", fill, (fill / self.entry_price - 1) * 100, bar)
            self.entry_price = NAN
            self.stop_price = NAN
            self.events.append(ev)
            return ev
        if c < exit_ma:                                # NaN exit_ma -> False
            self.exit_pending = True
            ev = Event(date, "EXIT_SIGNAL", c, None, bar)
            self.events.append(ev)
            return ev
        return None

    # step 4
    def arm_signal(self, date, full_signal: bool, c: float, bar=None) -> Event | None:
        if self.in_pos:
            return None
        self.entry_pending = bool(full_signal)
        if self.entry_pending:
            ev = Event(date, "SIGNAL", c, None, bar)
            self.events.append(ev)
            return ev
        return None

    def step(self, date, o, h, l, c, exit_ma, full_signal, bar=None) -> None:
        self.fill_exit(date, o, bar)
        self.fill_entry(date, o, bar)
        self.check_exit(date, o, l, c, exit_ma, bar)
        self.arm_signal(date, full_signal, c, bar)

    def snapshot(self) -> dict:
        return {"entry_price": self.entry_price, "stop_price": self.stop_price,
                "entry_pending": self.entry_pending, "exit_pending": self.exit_pending}


def run_state_machine(ind: pd.DataFrame, bars: pd.DataFrame, stop_pct: float,
                      start: int = 0) -> tuple[pd.DataFrame, list[Event]]:
    """Run the machine over all bars; returns per-bar state AFTER each bar and events.

    `ind` needs 'exit_ma' and 'full_signal'; `bars` needs open/high/low/close.
    Bars before `start` are skipped (state stays flat).
    """
    m = PositionMachine(stop_pct=float(stop_pct))
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    ema = ind["exit_ma"].to_numpy(float)
    sig = ind["full_signal"].to_numpy(bool)
    dates = bars.index
    n = len(bars)
    ep = np.full(n, np.nan)
    sp = np.full(n, np.nan)
    enp = np.zeros(n, bool)
    exp_ = np.zeros(n, bool)
    for t in range(n):
        if t >= start:
            m.step(dates[t], o[t], h[t], l[t], c[t], ema[t], sig[t], bar=t)
        ep[t], sp[t], enp[t], exp_[t] = m.entry_price, m.stop_price, m.entry_pending, m.exit_pending
    states = pd.DataFrame({"entry_price": ep, "stop_price": sp,
                           "entry_pending": enp, "exit_pending": exp_}, index=dates)
    return states, m.events
