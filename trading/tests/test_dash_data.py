"""Dashboard data files: latest rows, csv rows with a market column, backtest metric rows."""
import json

from tools import dash_data as DD


def test_latest_rows_flatten_each_market():
    latest = {"updated_at": "2026-11-03T09:10:00Z", "markets": {
        "KOSDAQ": {"as_of": "2026-11-03", "start_date": "2026-09-29",
                   "regime": {"on": False, "mode": "NONE", "benchmark": "^KQ11", "close": 704.39, "ma200": 970.5, "breadth_pct": 19.5},
                   "performance": {"equity": 95e6, "return_pct": -5.0, "bench_return_pct": -12.5, "closed_trades": 7, "win_rate_pct": 0.0},
                   "entries_next_open": [{"symbol": "A"}], "positions": [{"symbol": "B"}, {"symbol": "C"}],
                   "audit": {"days": 25, "signal_files": 30, "late": [], "mismatched": [], "revised": ["2026-10-22"]},
                   "xcheck": {"source": "KRX Open API", "status": "ok", "checked": 150, "mismatched_symbols": []},
                   "xcheck_kis": {"status": "mismatch", "checked": 150, "mismatched_symbols": ["086520.KQ"], "guard": {"enforced": False, "blocked": True}}}}}
    rows = DD.latest_rows(latest)
    assert len(rows) == 1
    r = rows[0]
    assert r["market"] == "KOSDAQ" and r["regime_on"] == 0 and r["excess_pp"] == 7.5
    assert r["n_entries"] == 1 and json.loads(r["positions_json"]) == [{"symbol": "B"}, {"symbol": "C"}]
    assert r["audit_revised"] == "2026-10-22" and r["xcheck_bad"] == 0 and r["kis_bad"] == 1
    assert r["kis_guard"] == "blocked"       # same order as daily_check: late > blocked > ok|observe


def test_csv_rows_and_backtest_rows():
    rows = DD.csv_rows("date,cash,equity\n2026-09-29,1.0,1.5\n2026-09-30,,2\n", "SP500", DD.EQUITY_NUM)
    assert rows == [{"market": "SP500", "date": "2026-09-29", "cash": 1.0, "equity": 1.5},
                    {"market": "SP500", "date": "2026-09-30", "cash": None, "equity": 2.0}]
    res = {"generated_at": "2026-11-03T00:00:00Z", "test_first_date": "2016-11-03", "data_last_date": "2026-11-03",
           "modes": {"percentile": {"metrics": {"full": {"start": "2016-11-03", "end": "2026-11-03", "return_pct": 837.6, "max_drawdown_pct": -37.1, "trades": 885},
                                                "last_1y": {"return_pct": 10.0, "trades": 90},
                                                "years": {"2025": {"return_pct": 3.0}}}}}}
    bt = DD.backtest_rows("KOSDAQ", res)
    assert [r["period"] for r in bt] == ["full", "last_1y", "2025"]
    assert bt[0]["mdd_pct"] == -37.1 and bt[0]["trades"] == 885 and bt[0]["test"] == "2016-11-03 ~ 2026-11-03"
    assert bt[2]["return_pct"] == 3.0 and bt[2]["win_rate_pct"] is None
