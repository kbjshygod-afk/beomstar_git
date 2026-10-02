"""60-day warning lines: window returns, excess, in-window drawdown and trade stats."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "paper_thresholds.py"
    spec = importlib.util.spec_from_file_location("paper_thresholds", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_windows_and_trade_stats():
    # equity: flat 100, then a 20% fall and a full recovery; benchmark doubles over the same bars
    eq = [100.0] * 3 + [80.0, 100.0]
    bench = [1.0, 1.0, 1.0, 1.0, 2.0]
    trades = pd.DataFrame({"pnl_pct": [10.0, -4.0, -8.0, np.nan]})
    r = _tool().thresholds(pd.DataFrame({"equity": eq, "bench_close": bench}), trades, window=2)
    # windows of 2 bars: returns 0, -20%, 0; benchmark 0, 0, +100%; drawdowns 0, -20%, -20%
    assert r["samples"] == 3
    assert r["return_median_pct"] == pytest.approx(0.0)
    assert r["return_p5_pct"] == pytest.approx(np.percentile([0, -0.2, 0], 5) * 100)
    assert r["max_dd_p5_pct"] == pytest.approx(-20.0)
    assert r["excess_p5_pp"] == pytest.approx(np.percentile([0, -0.2, -1.0], 5) * 100)
    assert r["avg_loss_pct"] == pytest.approx(-6.0)
    assert r["win_rate_pct"] == pytest.approx(100 / 3)
    assert r["trades_per_window"] == pytest.approx(3 / 4 * 2)
