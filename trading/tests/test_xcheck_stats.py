"""Cross-check statistics tool (checklist 1.6 / 5.3)."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import xcheck_stats as xs  # noqa: E402


def _rec(market, source, status, checked, mismatches=(), index_match=True, guard=None, compared=150):
    r = {"market": market, "as_of": checked, "source": source, "status": status, "checked": checked,
         "index": {"yahoo_close": 1, "krx_close": 1, "match": index_match} if source != "Tiingo" else None,
         "symbols": {"date": checked, "compared": compared, "missing": [], "mismatches": list(mismatches)}, "error": None}
    if guard:
        r["guard"] = guard
    return r


def test_summary_groups_by_market_and_source_and_lists_mismatches():
    recs = [
        {**_rec("KOSDAQ", "KRX Open API", "ok", "2026-10-29"), "ledger_market": "KOSDAQ"},
        {**_rec("KOSDAQ", "KIS", "mismatch", "2026-10-30",
                [{"symbol": "086520.KQ", "field": "close", "yahoo": 72200.0, "krx": 70800.0, "diff_pct": 1.939},
                 {"symbol": "086520.KQ", "field": "low", "yahoo": 70900.0, "krx": 70800.0, "diff_pct": 0.141}],
                guard={"blocked": True, "late": False}), "ledger_market": "KOSDAQ"},
        {**_rec("CRYPTO", "Coinbase/Kraken", "mismatch", "2026-10-29",
                [{"symbol": "SHIB-USD", "field": "close", "yahoo": 5e-06, "krx": 5.38e-06, "diff_pct": 7.6}], compared=23),
         "ledger_market": "CRYPTO"},
        {"market": "KOSPI", "source": "KRX Open API", "status": "error", "checked": None, "as_of": "2026-10-28",
         "index": None, "symbols": None, "error": "HTTP 401", "ledger_market": "KOSPI"},
    ]
    rows = xs.summarize(recs)
    assert [(r["market"], r["source"]) for r in rows] == [("CRYPTO", "Coinbase/Kraken"), ("KOSDAQ", "KIS"),
                                                          ("KOSDAQ", "KRX Open API"), ("KOSPI", "KRX Open API")]
    kis = rows[1]
    assert kis["records"] == 1 and kis["mismatch"] == 1 and kis["mismatched_symbols"] == 1 and kis["by_field"] == {"close": 1, "low": 1}
    assert kis["guard_blocked"] == 1 and kis["mismatches"][0]["source"] == 70800.0
    assert rows[3]["error"] == 1 and rows[3]["compared"] == 0
    md = xs.render(rows)
    assert "| 코스닥 | KIS | 1 | 0 | 1 | 0 | 0 | 150 | 1 | close 1, low 1 | 0 | 보류 1 · 해제 0 |" in md
    assert "| 2026-10-29 | 크립토 | Coinbase/Kraken | SHIB-USD | close | 5e-06 | 5.38e-06 | +7.60% |" in md
    assert xs.summarize(recs, since="2026-10-30")[0]["source"] == "KIS" and "기록 없음" in xs.render([])
    json.dumps(rows)


def test_records_are_read_from_a_git_ref(tmp_path):
    repo = tmp_path / "ledger"
    (repo / "paper" / "KOSDAQ" / "xcheck").mkdir(parents=True)
    (repo / "paper" / "KOSDAQ" / "xcheck" / "2026-10-29.json").write_text(json.dumps(_rec("KOSDAQ", "KRX Open API", "ok", "2026-10-29")))
    (repo / "paper" / "KOSDAQ" / "xcheck" / "2026-10-30.kis.json").write_text(json.dumps(_rec("KOSDAQ", "KIS", "ok", "2026-10-30")))
    for a in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"], ["add", "-A"],
              ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    recs = xs.load_records(repo, "HEAD")
    assert [r["source"] for r in recs] == ["KRX Open API", "KIS"] and recs[0]["ledger_market"] == "KOSDAQ"
    out = subprocess.run([sys.executable, str(Path(xs.__file__)), "--repo", str(repo), "--ref", "HEAD"],
                         capture_output=True, text=True, check=True).stdout
    assert "| 코스닥 | KIS | 1 | 1 |" in out and "| 코스닥 | KRX Open API | 1 | 1 |" in out
