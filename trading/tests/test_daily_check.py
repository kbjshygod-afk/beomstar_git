import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import daily_check as dc  # noqa: E402

TRADES = ("symbol,exit_date,exit_type,pnl_pct,net_pnl\n"
          "AAA,2026-10-07,STOP,-10.36,-700\n"
          "BBB,2026-10-20,EXIT_MA,4.5,300\n"
          "CCC,,,,\n")
EQUITY = "date,equity\n2026-09-25,100000000\n2026-10-21,97000000\n"


def _latest(**over):
    m = {"as_of": "2026-10-21", "regime": {"on": False, "mode": "BREADTH50", "breadth_pct": 29.7},
         "entries_next_open": [{"symbol": "CRL"}], "exits_next_open": [{"symbol": "HUM"}],
         "positions": [{"symbol": "HUM"}, {"symbol": "IFF"}], "stale_positions": []}
    m.update(over)
    return m


def test_summary_reads_the_engine_keys():
    s = dc.market_summary("KOSDAQ_V2", _latest(), {"mismatched": ["2026-10-06"], "late": []},
                          TRADES, EQUITY, recent_days=1)
    assert s["entries"] == ["CRL"] and s["exits"] == ["HUM"]
    assert s["positions"] == ["HUM", "IFF"] and s["stale"] == []
    assert s["breadth_pct"] == 29.7 and s["regime_on"] is False
    assert s["audit"] == {"mismatched": ["2026-10-06"]}
    assert s["closed_total"] == 2 and s["wins"] == 1
    assert [t["symbol"] for t in s["closed_recent"]] == ["BBB"]
    assert s["return_pct"] == -3.0
    assert s["problems"] == []


def test_missing_keys_are_problems_not_zero_signals():
    latest = _latest()
    del latest["entries_next_open"], latest["stale_positions"]
    s = dc.market_summary("SP500", latest, None, None, None)
    assert any("entries_next_open" in p and "stale_positions" in p for p in s["problems"])
    assert any("audit.json" in p for p in s["problems"])
    assert "PROBLEM" in dc.render([s])


def test_stale_positions_are_listed():
    s = dc.market_summary("KOSDAQ", _latest(stale_positions=[{"symbol": "123456.KQ", "last_bar": "2026-10-15"}]),
                          {}, None, None)
    assert s["stale"] == ["123456.KQ"]
    assert "STALE quotes:      123456.KQ" in dc.render([s])
