"""tools/breadth_sensitivity.py: the plateau criteria fixed in the pre-registration document."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import breadth_sensitivity as B  # noqa: E402

BASE = {"trades": 1122, "cagr_pct": 10.0, "excess_cagr_pp": 7.9, "profit_factor": 1.20, "win_rate_pct": 26.1,
        "max_drawdown_pct": -41.0, "exposure_pct": 74.6, "h1_excess_pp": 7.6, "h2_excess_pp": 8.1}


def _r(**kw):
    return {**BASE, "cagr_pct": 13.5, "profit_factor": 1.40, "max_drawdown_pct": -35.0, **kw}


def test_similar_thresholds_are_a_plateau():
    res = B.plateau(BASE, {"40": _r(), "45": _r(cagr_pct=13.0), "50": _r(cagr_pct=13.8), "55": _r(cagr_pct=12.4)})
    assert res["plateau"] and all(res["checks"].values())
    assert abs(res["cagr_spread_pp"] - 1.4) < 1e-9


def test_each_criterion_can_fail_alone():
    ok = {"40": _r(), "45": _r(), "50": _r(), "55": _r()}
    cases = {
        "P1_cagr_above_baseline": {"40": _r(cagr_pct=12.0), "45": _r(cagr_pct=12.0), "50": _r(cagr_pct=12.0),
                                   "55": _r(cagr_pct=10.0)},                # equal is not higher
        "P2_drawdown_not_deeper": {"45": _r(max_drawdown_pct=-41.1)},
        "P3_profit_factor": {"45": _r(profit_factor=1.29), "55": _r(profit_factor=1.25)},
        "P4_both_halves": {"50": _r(h1_excess_pp=5.5)},                      # baseline 7.6 - 2 = 5.6
        "P5_cagr_spread": {"40": _r(cagr_pct=16.6)},                         # 16.6 - 13.5 = 3.1 > 3.0
    }
    for name, change in cases.items():
        res = B.plateau(BASE, {**ok, **change})
        assert not res["plateau"], name
        assert [k for k, v in res["checks"].items() if not v] == [name], name


def test_one_weak_profit_factor_is_allowed_and_boundaries_pass():
    res = B.plateau(BASE, {"40": _r(profit_factor=1.29), "45": _r(profit_factor=1.30), "50": _r(),
                           "55": _r(cagr_pct=10.5, h1_excess_pp=5.6, h2_excess_pp=6.1, max_drawdown_pct=-41.0)})
    assert res["plateau"] and res["profit_factor_ok"] == 3
    assert abs(res["cagr_spread_pp"] - 3.0) < 1e-9


def test_a_single_threshold_cannot_be_a_plateau():
    assert not B.plateau(BASE, {"50": _r()})["plateau"]


def test_table_lists_the_baseline_and_every_threshold():
    t = B.table({"baseline": BASE, "thresholds": {"40": _r(), "50": _r()}})
    assert t.count("\n") == 5 and "기준 (필터 없음)" in t and "폭 ≥ 40%" in t and "폭 ≥ 50%" in t


def test_missing_metrics_are_not_a_plateau_and_do_not_raise():
    res = B.plateau(BASE, {"40": _r(), "50": _r(profit_factor=None)})
    assert not res["plateau"] and "missing" in res["reason"]
    res = B.plateau({**BASE, "h1_excess_pp": float("nan")}, {"40": _r(), "50": _r()})
    assert not res["plateau"]
    text = B.table({"baseline": BASE, "thresholds": {"50": _r(profit_factor=None, trades=None, exposure_pct=None)}})
    assert text.count("n/a") == 3


def test_main_runs_end_to_end_on_a_small_snapshot(tmp_path, capsys):
    """Loading, point-in-time preparation, the gate at each threshold and the output together."""
    import json
    from test_path_noise import _snapshot
    _snapshot(tmp_path)
    out = tmp_path / "out"
    assert B.main(["--data", str(tmp_path), "--out", str(out), "--thresholds", "40", "50"]) == 0
    d = json.loads((out / "KOSDAQ" / "breadth_sensitivity.json").read_text())
    assert list(d["thresholds"]) == ["40", "50"] and "plateau" in d["result"]
    # a gate can only remove entries
    assert all((r["trades"] or 0) <= (d["baseline"]["trades"] or 0) for r in d["thresholds"].values())
    assert "기준 (필터 없음)" in capsys.readouterr().out
