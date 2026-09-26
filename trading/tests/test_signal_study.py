"""Signal study: every signal traded alone, with the signal bar's features."""
import numpy as np
import pandas as pd

from swing_engine import signal_study as SS
from swing_engine.params import resolve
from swing_engine.portfolio import PortfolioConfig, prepare_frames
from swing_engine.state import run_state_machine


def _market(n_sym=25, seed=5):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2019-01-02", "2024-06-28")
    n = len(d)

    def series(mu, sig):
        c = 100 * np.exp(np.cumsum(rng.normal(mu, sig, n)))
        o = c * np.exp(rng.normal(0, 0.004, n))
        h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.01, n)))
        lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.01, n)))
        v = rng.lognormal(13, 0.5, n) * np.where(rng.random(n) < 0.08, 3.0, 1.0)
        return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v}, index=d)

    bench = series(0.0006, 0.008)
    syms = {f"T{i:02d}": series(rng.uniform(0.0008, 0.0025), rng.uniform(0.012, 0.025)) for i in range(n_sym)}
    return syms, bench


def test_study_matches_state_machine():
    syms, bench = _market()
    params = resolve("SP500")
    start = "2020-06-01"
    df = SS.study(syms, bench, params, start)
    assert len(df) > 20
    prepared = prepare_frames(syms, bench, PortfolioConfig(params=params, rs_mode="percentile"))
    for s, f in prepared.items():
        _, ev = run_state_machine(f, f, params["stop_pct"], start=int(f.index.searchsorted(pd.Timestamp(start))))
        exits = [e for e in ev if e.type in ("STOP", "EXIT_MA")]
        rows = df[(df.symbol == s) & (df.exit_type != "OPEN")]
        assert len(rows) == len(exits)
        assert np.allclose(rows["pnl_pct"].to_numpy(), [e.pnl_pct for e in exits])
    assert (df["signal_date"] < df["entry_date"]).all()
    assert (df["signal_date"] >= start).all()
    assert (df["exit_type"] == "OPEN").sum() <= len(syms)
    # every signal passed the rules on its signal bar
    assert (df["rs_pct"] >= 70).all() and (df["vol_x"] >= 1.4).all()
    assert ((df["breakout_pct"] > 0) & (df["breakout_pct"] <= 15)).all()
    # net = price return after 0.2% cost on each side; MFE/MAE bracket the result
    net = (df["exit_price"] * 0.998 / (df["entry_price"] * 1.002) - 1) * 100
    assert np.allclose(df["net_pnl_pct"], net)
    assert (df["mfe_pct"] >= df["pnl_pct"] - 1e-9).all() and (df["mae_pct"] <= df["pnl_pct"] + 1e-9).all()
    stops = df[df.exit_type == "STOP"]
    assert (stops["pnl_pct"] <= -params["stop_pct"] + 1e-9).all()
    assert df["n_same_day"].min() >= 1 and df["breadth_tt_pct"].between(0, 100).all()
