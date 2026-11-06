"""Paper verdict: criteria A-D from ledger files, regime reference, verdict wording."""
import json

from tools import paper_verdict as V


def test_a_excludes_only_the_explained_days():
    a = V.check_a({"late": ["2026-11-04"], "uncommitted": [], "mismatched": ["2026-10-06", "2026-10-20"]}, "KOSDAQ")
    assert not a["pass"] and a["explained"] == ["2026-10-06"]
    assert a["issues"] == ["늦은 커밋 2026-11-04", "설명 안 된 불일치 2026-10-20"]
    assert V.check_a({"mismatched": ["2026-10-06"]}, "KOSDAQ")["pass"]
    assert not V.check_a({"mismatched": ["2026-10-06"]}, "SP500")["pass"]


def test_b_and_c():
    b = V.check_b({"missing_days": ["d1"]}, [{"requested": 30, "failed": ["x"] * 5}, {"requested": 30, "failed": []}])
    assert not b["pass"] and b["worst_fail_share"] == round(5 / 30, 4)
    assert V.check_b({"missing_days": ["a", "b"]}, [{"requested": 100, "failed": ["x"] * 5}])["pass"]
    trades = [{"symbol": "GAP", "exit_type": "STOP", "price_pnl_pct": "-13.9", "exit_price": "45", "stop_price": "47"},
              {"symbol": "BAD", "exit_type": "STOP", "price_pnl_pct": "-12.0", "exit_price": "47", "stop_price": "47"},
              {"symbol": "TGT", "exit_type": "TARGET", "price_pnl_pct": "20", "exit_price": "60", "stop_price": "40"},
              {"symbol": "OK", "exit_type": "EXIT_MA", "price_pnl_pct": "-3", "exit_price": "48", "stop_price": "45"}]
    c = V.check_c(trades, "KOSDAQ")
    assert c["gaps"] == ["GAP -13.9% (시가 갭, 허용)"]
    assert c["issues"] == ["BAD 손절폭 초과 -12.0%", "TGT 청산 유형 TARGET"]


def test_d_and_verdict():
    stats = V.equity_stats([{"equity": "100"}, {"equity": "110"}, {"equity": "85"}, {"equity": "86"}])
    assert stats == {"days": 4, "return_pct": -14.0, "mdd_pct": round((85 / 110 - 1) * 100, 2)}
    d = V.check_d(stats, [{"exit_date": "x", "pnl_pct": "-13"}, {"exit_date": "x", "pnl_pct": "-12"}], "KOSDAQ")
    assert d["warn"] and len(d["warnings"]) == 3 and d["avg_loss_pct"] == -12.5
    ok = {"pass": True}
    assert V.verdict({"pass": False}, ok, ok, {"warn": False}, 30) == "중간(30/60일): A 실패 → 원인 수정 후 새 기간"
    assert V.verdict(ok, ok, ok, {"warn": False}, 30) == "중간(30/60일): 현재까지 기준 충족"
    assert V.verdict(ok, ok, ok, {"warn": False}, 60) == "통과 → 실전 소액(계획 비중 1/4) 가능"
    assert V.verdict(ok, ok, ok, {"warn": True}, 61) == "D 경고 → 대표님 검토(룰 vs 국면)"


def test_regime_reference_and_end_to_end(tmp_path):
    sig = ("symbol,exit_type,net_pnl_pct,b_dist200_pct\n"
           "A,STOP,-9,-20\nB,EXIT_MA,30,-18\nC,STOP,-9,-16\nD,EXIT_MA,5,3\nE,OPEN,,-1\n")
    ref = V.regime_reference(sig, -33.0)
    assert ref["band"] == "< -15%" and ref["band_stats"]["n"] == 3 and ref["band_stats"]["win_rate_pct"] == 33.3
    assert ref["deepest_in_backtest_pct"] == -20.0 and ref["all_stats"]["n"] == 4
    led = tmp_path / "ledger" / "paper"
    (led / "KOSDAQ" / "signals").mkdir(parents=True)
    (led / "latest.json").write_text(json.dumps({"markets": {"KOSDAQ": {"regime": {"close": 660.0, "ma200": 1000.0}}}}))
    (led / "KOSDAQ" / "audit.json").write_text(json.dumps({"start_date": "2026-09-29", "as_of": "2026-11-06", "late": ["2026-11-04"],
                                                          "mismatched": ["2026-10-06"], "missing_days": []}))
    (led / "KOSDAQ" / "trades.csv").write_text("symbol,exit_date,exit_type,pnl_pct,price_pnl_pct,exit_price,stop_price\nX,2026-10-10,STOP,-10.4,-10.0,90,90\n")
    (led / "KOSDAQ" / "equity.csv").write_text("date,equity\n2026-09-29,100\n2026-10-10,99\n")
    (led / "KOSDAQ" / "signals" / "2026-11-06.json").write_text(json.dumps({"coverage": {"requested": 150, "failed": []}}))
    res = tmp_path / "results" / "latest" / "results" / "KOSDAQ"
    res.mkdir(parents=True)
    (res / "signals.csv").write_text(sig)
    stem = tmp_path / "out" / "v"
    assert V.main(["--ledger-dir", str(led), "--results-dir", str(tmp_path / "results"), "--markets", "KOSDAQ", "--out", str(stem)]) == 0
    row = json.loads(stem.with_suffix(".json").read_text())["markets"][0]
    assert row["verdict"] == "중간(2/60일): A 실패 → 원인 수정 후 새 기간" and row["regime"]["dist_now_pct"] == -34.0
    text = stem.with_suffix(".md").read_text()
    assert "| 코스닥 | 2/60 | **실패** |" in text and "비교할 과거가 없음" in text
