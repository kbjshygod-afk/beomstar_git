"""Paper trading: pre-committed signals, deterministic ledger, integrity audit."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_engine import paper as P


def _write_market(dirpath: Path, n_sym=40, seed=11, end="2024-06-28"):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2020-01-02", end)
    n = len(d)

    def series(mu, sig):
        r = rng.normal(mu, sig, n)
        c = 100 * np.exp(np.cumsum(r))
        o = c * np.exp(rng.normal(0, 0.004, n))
        h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.01, n)))
        lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.01, n)))
        v = rng.lognormal(13, 0.5, n) * np.where(rng.random(n) < 0.08, 3.0, 1.0)
        return pd.DataFrame({"Date": d.strftime("%Y-%m-%d"), "Open": o, "High": h, "Low": lo, "Close": c, "Volume": v})

    series(0.0006, 0.008).to_csv(dirpath / "GSPC.csv", index=False)
    tick = [f"T{i:02d}" for i in range(n_sym)]
    for t in tick:
        series(rng.uniform(0.0008, 0.0025), rng.uniform(0.012, 0.025)).to_csv(dirpath / f"{t}.csv", index=False)
    return d


def _git(repo, *a, env=None):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)


@pytest.fixture()
def ledger_repo(tmp_path):
    repo = tmp_path / "ledger"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    return repo


def _run(offline, repo, now, monkeypatch, commit_time=None):
    ct = (commit_time or now).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", ct)
    monkeypatch.setenv("GIT_AUTHOR_DATE", ct)
    args = P.build_parser().parse_args([
        "--market", "SP500", "--ledger-dir", str(repo / "paper"), "--offline-dir", str(offline),
        "--now", now.strftime("%Y-%m-%dT%H:%M:%S")])
    return P.run(args)


def _after_close(day):          # 22:35 UTC, after the 16:00 ET close
    return datetime(day.year, day.month, day.day, 22, 35, tzinfo=timezone.utc)


def test_next_open_deadline():
    # Friday 2024-06-28 -> Monday 09:30 ET (EDT) = 13:30 UTC
    assert P.next_open_deadline("SP500", "2024-06-28") == datetime(2024, 7, 1, 13, 30, tzinfo=timezone.utc)
    # KRX: Friday -> Monday 09:00 KST = 00:00 UTC
    assert P.next_open_deadline("KOSPI", "2024-06-28") == datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
    # crypto: 3 hours after the 00:00 UTC close
    assert P.next_open_deadline("CRYPTO", "2024-06-28") == datetime(2024, 6, 29, 3, 0, tzinfo=timezone.utc)


def test_daily_runs_commit_on_time_and_match(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    run_days = list(days[-25:])
    results = []
    for i, day in enumerate(run_days):
        if i == 10:
            continue                                        # a missed run
        results.append(_run(offline, ledger_repo, _after_close(day), monkeypatch))
    root = ledger_repo / "paper" / "SP500"
    cfg = json.loads((root / "config.json").read_text())
    assert cfg["start_date"] == run_days[0].strftime("%Y-%m-%d")      # frozen at the first run
    aud = results[-1]["audit"]
    assert aud["days"] == 25
    assert aud["signal_files"] == 24
    assert aud["missing_days"] == [run_days[10].strftime("%Y-%m-%d")]
    assert aud["late"] == [] and aud["uncommitted"] == []
    assert aud["mismatched"] == []
    # the simulation actually traded, so the audit compared non-empty sets
    n_events = sum(len(r["snapshot"]["entries_next_open"]) + len(r["snapshot"]["exits_next_open"]) for r in results)
    assert n_events > 0
    # outputs exist
    for f in ("report.md", "trades.csv", "equity.csv", "positions.json", "audit.json", "status.csv"):
        assert (root / f).exists()
    st = pd.read_csv(root / "status.csv")
    assert len(st) == 40 and set(st["as_of"]) == {run_days[-1].strftime("%Y-%m-%d")}
    held = set(json.loads((root / "positions.json").read_text()) and
               [p["symbol"] for p in json.loads((root / "positions.json").read_text())])
    assert set(st.loc[st["in_position"], "symbol"]) == held
    assert st.loc[st["in_position"], "status"].str.startswith("보유 중").all()
    assert (st.loc[~st["tt_pass"] & ~st["in_position"] & ~st["entry_pending"], "status"].str.startswith("후보 아님")).all()
    latest = json.loads((ledger_repo / "paper" / "latest.json").read_text())
    assert latest["markets"]["SP500"]["as_of"] == run_days[-1].strftime("%Y-%m-%d")
    report = (root / "report.md").read_text()
    assert "목표가는 두지 않습니다" in report and "미확인 추정값" in report


def test_rerun_same_day_is_unchanged(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    now = _after_close(days[-1])
    r1 = _run(offline, ledger_repo, now, monkeypatch)
    r2 = _run(offline, ledger_repo, now, monkeypatch)
    assert r1["signal_state"] == "new" and r2["signal_state"] == "unchanged"


def test_late_commit_is_flagged(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    day = days[-1]                                          # Friday 2024-06-28
    late = datetime(2024, 7, 1, 14, 0, tzinfo=timezone.utc)   # after Monday's 13:30 UTC open
    r = _run(offline, ledger_repo, _after_close(day), monkeypatch, commit_time=late)
    assert r["audit"]["late"] == ["2024-06-28"]


def test_revised_history_is_detected(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    run_days = list(days[-15:])
    for day in run_days[:10]:
        _run(offline, ledger_repo, _after_close(day), monkeypatch)
    root = ledger_repo / "paper" / "SP500" / "signals"
    committed = {p.stem: json.loads(p.read_text()) for p in root.glob("*.json")}
    armed = [d for d, s in committed.items() if s["entries_next_open"]]
    assert armed, "fixture should produce at least one entry signal in the first 10 days"
    d0 = sorted(armed)[0]
    sym = committed[d0]["entries_next_open"][0]["symbol"]
    # rewrite that symbol's history so it can no longer signal (flat price, tiny volume)
    f = offline / f"{sym}.csv"
    df = pd.read_csv(f)
    df.loc[:, ["Open", "High", "Low", "Close"]] = 50.0
    df.loc[:, "Volume"] = 1.0
    df.to_csv(f, index=False)
    r = _run(offline, ledger_repo, _after_close(run_days[10]), monkeypatch)
    assert d0 in r["audit"]["mismatched"]
    row = next(x for x in r["audit"]["rows"] if x["date"] == d0)
    assert sym in row["entries_only_committed"]


def test_relative_ledger_dir(tmp_path, ledger_repo, monkeypatch):
    """The workflow passes ../ledger/paper; commit times must still be found."""
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    work = tmp_path / "trading"
    work.mkdir()
    monkeypatch.chdir(work)
    now = _after_close(days[-1])
    ct = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", ct)
    monkeypatch.setenv("GIT_AUTHOR_DATE", ct)
    args = P.build_parser().parse_args([
        "--market", "SP500", "--ledger-dir", "../ledger/paper", "--offline-dir", str(offline),
        "--now", now.strftime("%Y-%m-%dT%H:%M:%S")])
    r = P.run(args)
    assert r["audit"]["uncommitted"] == [] and r["audit"]["late"] == []


def test_first_run_after_the_open_does_not_start(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    friday = days[-1]                                        # 2024-06-28
    monday_after_open = datetime(2024, 7, 1, 15, 0, tzinfo=timezone.utc)
    r = _run(offline, ledger_repo, monday_after_open, monkeypatch)
    assert r["started"] is False and r["as_of"] == "2024-06-28"
    root = ledger_repo / "paper" / "SP500"
    assert not (root / "signals").exists()
    cfg = json.loads((root / "config.json").read_text()) if (root / "config.json").exists() else {"start_date": None}
    assert cfg["start_date"] is None
    r2 = _run(offline, ledger_repo, _after_close(friday), monkeypatch)     # a timely run starts it
    assert r2["started"] is True and r2["audit"]["late"] == []
