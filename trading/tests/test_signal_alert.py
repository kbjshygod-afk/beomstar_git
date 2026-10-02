"""Signal alert (R7): which signal files are new, the message, and the two delivery paths."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def _tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "signal_alert.py"
    spec = importlib.util.spec_from_file_location("signal_alert", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


SIGNAL = {
    "market": "KOSDAQ", "as_of": "2026-10-02",
    "regime": {"benchmark": "^KQ11", "mode": "NONE", "close": 893.29, "ma200": 984.2971, "ma20": 833.26, "on": True},
    "entries_next_open": [{"symbol": "059090.KQ", "signal_close": 23350.0, "rs": 95.14,
                           "desired_qty": 375.0, "est_stop_from_close": 21015.0}],
    "exits_next_open": ["083450.KQ"],
    "positions": ["083450.KQ", "096530.KQ"],
    "watchlist": [{"symbol": "031980.KQ", "label": "1순위 · 임박 (피벗 1% 이내)", "close": 1, "pivot": 1,
                   "to_pivot_pct": 0.4, "rs": 93.8},
                  {"symbol": "327260.KQ", "label": "2순위 · 근접 (피벗 3% 이내)", "close": 1, "pivot": 1,
                   "to_pivot_pct": 1.9, "rs": 97.9}],
    "coverage": {"requested": 150, "loaded": 149, "failed": ["000001.KQ"]},
    "generated_at": "2026-10-02T09:36:27Z",
}
ENTRY = {
    "as_of": "2026-10-02",
    "positions": [{"symbol": "083450.KQ", "entry_date": "2026-09-30", "entry_price": 52600.0, "stop_price": 47340.0,
                   "last_close": 53600.0, "price_pnl_pct": 1.9},
                  {"symbol": "096530.KQ", "entry_date": "2026-09-29", "entry_price": 37300.0, "stop_price": 33570.0,
                   "last_close": 36900.0, "price_pnl_pct": -1.07}],
    "stale_positions": [{"symbol": "096530.KQ", "last_bar": "2026-09-30", "sessions_missing": 2}],
}


@pytest.fixture()
def ledger(tmp_path):
    repo = tmp_path / "ledger"
    sig = repo / "paper" / "KOSDAQ" / "signals"
    sig.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (sig / "2026-10-01.json").write_text(json.dumps(dict(SIGNAL, as_of="2026-10-01", entries_next_open=[])))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "day 1")
    first = _git(repo, "rev-parse", "HEAD")
    (sig / "2026-10-02.json").write_text(json.dumps(SIGNAL))
    (sig / "2026-10-02.rev1.json").write_text(json.dumps(dict(SIGNAL, exits_next_open=[])))
    (repo / "paper" / "latest.json").write_text(json.dumps({"markets": {"KOSDAQ": ENTRY}}))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "day 2")
    return repo, first


def test_new_signal_files_are_those_committed_since_the_previous_head(ledger):
    repo, first = ledger
    t = _tool()
    paper = repo / "paper"
    names = [p.name for p in t.new_signal_files(paper, "KOSDAQ", first)]
    assert names == ["2026-10-02.json", "2026-10-02.rev1.json"]
    assert len(t.new_signal_files(paper, "KOSDAQ", "")) == 3                 # no previous head: everything
    assert t.new_signal_files(paper, "KOSDAQ", _git(repo, "rev-parse", "HEAD")) == []   # rerun: nothing new
    assert t.latest_signal_file(paper, "KOSDAQ").name == "2026-10-02.rev1.json"
    assert t._revision(Path("2026-10-02.rev1.json")) == 1 and t._revision(Path("2026-10-02.json")) is None


def test_message_names_entries_exits_positions_and_stale_warning():
    t = _tool()
    url = "https://example.com/report.md"
    msg = t.render(SIGNAL, ENTRY, "github", url)
    assert msg.startswith("**코스닥 모의투자 신호 · 기준일 2026-10-02 (금)**")
    assert "레짐 ON (필터 없음) — ^KQ11 종가 893.29 · 200일선 984.30" in msg
    assert "- 059090.KQ — 신호 종가 23,350.00 · 예상 손절 21,015.00 (-10%) · 모의 수량 375 · RS 95.1" in msg
    assert "15% 넘게 높으면 추격하지 않습니다" in msg
    assert "**다음 시가 청산 (1)**: 083450.KQ" in msg
    assert "**보유 (2)**" in msg and "- 083450.KQ — 진입 2026-09-30 52,600.00 · 손절 47,340.00" in msg
    assert "⚠ **096530.KQ: 기준일 시세 없음** (마지막 봉 2026-09-30, 2거래일째)" in msg
    assert "관찰 임박 (피벗 1% 이내): 031980.KQ" in msg and "327260.KQ" not in msg
    assert "데이터 실패 1/150종목: 000001.KQ" in msg
    assert "신호 생성 18:36 KST" in msg and f"[보고서]({url})" in msg
    assert msg.rstrip().endswith("매수·매도 결정은 소유자 본인이 합니다._")

    slack = t.render(SIGNAL, ENTRY, "slack", url, revision=1)
    assert slack.startswith("*⚠ 신호 수정본 1 — 코스닥 모의투자 신호")
    assert "• 059090.KQ" in slack and f"<{url}|보고서>" in slack and "**" not in slack

    # without a matching latest.json entry only the symbols of the held positions are known
    bare = t.render(SIGNAL, None, "github")
    assert "**보유 (2)**: 083450.KQ, 096530.KQ" in bare and "시세 없음" not in bare


def test_slack_post_sends_the_text(monkeypatch):
    t = _tool()
    sent = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        sent["url"], sent["body"] = req.full_url, json.loads(req.data)
        return Resp()

    monkeypatch.setattr(t.urllib.request, "urlopen", fake_urlopen)
    t.post_slack("https://hooks.example/abc", "hello")
    assert sent == {"url": "https://hooks.example/abc", "body": {"text": "hello"}}


def test_github_issue_is_created_once_and_then_commented():
    t = _tool()
    calls = []
    issues = []

    def gh(*args):
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(issues)
        if args[:2] == ("issue", "create"):
            issues.append({"number": 7, "title": args[args.index("--title") + 1]})
            return "https://github.com/o/r/issues/7"
        return ""

    assert t.post_github_issue("코스닥 모의투자 신호 알림", "body 1", "코스닥", gh=gh) == 7
    assert t.post_github_issue("코스닥 모의투자 신호 알림", "body 2", "코스닥", gh=gh) == 7
    assert sum(c[:2] == ("issue", "create") for c in calls) == 1
    comments = [c for c in calls if c[:2] == ("issue", "comment")]
    assert [c[2:] for c in comments] == [("7", "--body", "body 1"), ("7", "--body", "body 2")]
    created = next(c for c in calls if c[:2] == ("issue", "create"))
    assert "코스닥 모의투자 신호 알림 스레드" in created[created.index("--body") + 1]


def test_cli_dry_run_prints_without_sending(ledger, monkeypatch, capsys):
    repo, first = ledger
    t = _tool()
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(t, "post_slack", lambda *a: pytest.fail("sent to slack"))
    monkeypatch.setattr(t, "post_github_issue", lambda *a, **k: pytest.fail("posted to github"))
    assert t.main(["--ledger", str(repo / "paper"), "--market", "KOSDAQ", "--since", first, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("----- ") == 2 and "----- 2026-10-02.rev1.json" in out and "신호 수정본 1" in out
    assert t.main(["--ledger", str(repo / "paper"), "--market", "KOSDAQ",
                   "--since", _git(repo, "rev-parse", "HEAD"), "--dry-run"]) == 0
    assert "no new signal file" in capsys.readouterr().out


def test_cli_posts_new_files_to_the_issue_and_latest_on_request(ledger, monkeypatch, capsys):
    repo, first = ledger
    t = _tool()
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    posted = []
    monkeypatch.setattr(t, "post_github_issue", lambda title, body, name: posted.append((title, body)) or 7)
    assert t.main(["--ledger", str(repo / "paper"), "--market", "KOSDAQ", "--since", first]) == 0
    assert [p[0] for p in posted] == ["코스닥 모의투자 신호 알림"] * 2
    assert "[테스트 발송]" not in posted[0][1]
    posted.clear()
    assert t.main(["--ledger", str(repo / "paper"), "--market", "KOSDAQ", "--since", "", "--latest"]) == 0
    assert len(posted) == 1 and posted[0][1].startswith("**[테스트 발송]** ")
    assert "신호 수정본 1" in posted[0][1]

    sent = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setattr(t, "post_slack", lambda url, text: sent.append((url, text)))
    assert t.main(["--ledger", str(repo / "paper"), "--market", "KOSDAQ", "--since", first]) == 0
    assert len(sent) == 2 and sent[0][0] == "https://hooks.example/x" and sent[0][1].startswith("*코스닥")
