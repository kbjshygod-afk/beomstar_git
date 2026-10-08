"""Paper trading: pre-committed signals, deterministic ledger, integrity audit."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_engine import data as D
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


def _run(offline, repo, now, monkeypatch, commit_time=None, extra=()):
    ct = (commit_time or now).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", ct)
    monkeypatch.setenv("GIT_AUTHOR_DATE", ct)
    args = P.build_parser().parse_args([
        "--market", "SP500", "--ledger-dir", str(repo / "paper"), "--offline-dir", str(offline),
        "--now", now.strftime("%Y-%m-%dT%H:%M:%S"), *extra])
    return P.run(args)


def _after_close(day):          # 22:35 UTC, after the 16:00 ET close
    return datetime(day.year, day.month, day.day, 22, 35, tzinfo=timezone.utc)


def test_next_open_deadline():
    # Friday 2024-06-28 -> Monday 09:30 ET (EDT) = 13:30 UTC
    assert P.next_open_deadline("SP500", "2024-06-28") == datetime(2024, 7, 1, 13, 30, tzinfo=timezone.utc)
    # KRX: Friday -> Monday 09:00 KST = 00:00 UTC
    assert P.next_open_deadline("KOSPI", "2024-06-28") == datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)
    # crypto: before the next bar closes, 24 hours after the 00:00 UTC close
    assert P.next_open_deadline("CRYPTO", "2024-06-28") == datetime(2024, 6, 30, 0, 0, tzinfo=timezone.utc)


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
    head = subprocess.run(["git", "-C", str(ledger_repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    r2 = _run(offline, ledger_repo, now + pd.Timedelta(hours=2), monkeypatch)   # the next 2-hourly run
    assert r1["signal_state"] == "new" and r2["signal_state"] == "unchanged"
    # nothing new: no commit, latest.json keeps the first run's time
    assert subprocess.run(["git", "-C", str(ledger_repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head
    latest = json.loads((ledger_repo / "paper" / "latest.json").read_text())
    assert latest["updated_at"] == P._iso(now)


def test_bar_is_used_only_after_the_settle_time(tmp_path, ledger_repo, monkeypatch):
    offline = tmp_path / "data"
    offline.mkdir()
    _write_market(offline)                                  # last bar Friday 2024-06-28
    early = datetime(2024, 6, 28, 20, 30, tzinfo=timezone.utc)   # 16:30 ET, 30 min after the close
    r = _run(offline, ledger_repo, early, monkeypatch)
    # 06-28 is not used yet; 06-27's next open has passed, so the paper period does not start
    assert r["started"] is False and r["as_of"] == "2024-06-27"
    assert not (ledger_repo / "paper" / "SP500" / "signals").exists()
    r = _run(offline, ledger_repo, datetime(2024, 6, 28, 21, 35, tzinfo=timezone.utc), monkeypatch)
    assert r["started"] and r["snapshot"]["as_of"] == "2024-06-28" and r["signal_state"] == "new"


def test_older_data_never_rewinds_the_ledger(tmp_path, ledger_repo, monkeypatch):
    """Yahoo served KRX data ending a day early just before the open (2026-09-29 23:45 UTC):
    such a run commits nothing instead of writing an older signal file."""
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    r1 = _run(offline, ledger_repo, _after_close(days[-1]), monkeypatch)
    assert r1["signal_state"] == "new"
    head = subprocess.run(["git", "-C", str(ledger_repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    short = tmp_path / "short"                              # the same data without the last bar
    short.mkdir()
    for f in offline.glob("*.csv"):
        pd.read_csv(f).iloc[:-1].to_csv(short / f.name, index=False)
    cache = tmp_path / "cache"                              # cached bars of that incomplete download
    stale = [q for t in ("T00", "^GSPC") for q in D._cache_paths(cache, t)]
    for q in stale:
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text("stale")
    r2 = _run(short, ledger_repo, _after_close(days[-1]) + pd.Timedelta(hours=4), monkeypatch,
              extra=("--cache-dir", str(cache)))
    assert r2["ready"] is False and r2["as_of"] == days[-2].strftime("%Y-%m-%d")
    assert not any(q.exists() for q in stale)               # the next run downloads them again
    root = ledger_repo / "paper" / "SP500"
    assert sorted(q.name for q in (root / "signals").iterdir()) == [f"{days[-1]:%Y-%m-%d}.json"]
    assert subprocess.run(["git", "-C", str(ledger_repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head
    assert json.loads((ledger_repo / "paper" / "latest.json").read_text())["markets"]["SP500"]["as_of"] == f"{days[-1]:%Y-%m-%d}"
    assert P.main(["--market", "SP500", "--ledger-dir", str(ledger_repo / "paper"), "--offline-dir", str(short),
                   "--now", (_after_close(days[-1]) + pd.Timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")]) == P.NOT_READY


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


def test_stale_symbols_are_not_committed(tmp_path, ledger_repo, monkeypatch):
    """Symbols a day behind the benchmark: nothing is committed and main exits 75."""
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    friday = days[-1]
    for f in offline.glob("T*.csv"):                         # symbols stop on Thursday
        df = pd.read_csv(f)
        df.iloc[:-1].to_csv(f, index=False)
    r = _run(offline, ledger_repo, _after_close(friday), monkeypatch)
    assert r["ready"] is False and r["as_of"] == friday.strftime("%Y-%m-%d")
    root = ledger_repo / "paper" / "SP500"
    assert not (root / "signals").exists()
    assert not (root / "config.json").exists() or json.loads((root / "config.json").read_text())["start_date"] is None
    code = P.main(["--market", "SP500", "--ledger-dir", str(ledger_repo / "paper"), "--offline-dir", str(offline),
                   "--now", _after_close(friday).strftime("%Y-%m-%dT%H:%M:%S"), "--no-commit"])
    assert code == P.NOT_READY


def test_crypto_needs_yesterdays_candle():
    d = pd.date_range("2026-09-01", "2026-09-24")
    bench = pd.DataFrame({"close": range(len(d))}, index=d, dtype=float)
    frames = {"ETH-USD": bench.copy()}
    after_midnight = datetime(2026, 9, 26, 0, 40, tzinfo=timezone.utc)   # 09-25 closed 40 min ago
    ok, why = P.data_ready("CRYPTO", frames, bench, after_midnight, bench_name="BTC-USD")
    assert not ok and "2026-09-24 < 2026-09-25" in why
    ok, _ = P.data_ready("CRYPTO", frames, bench, datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc))
    assert ok                                            # 09-25 still forming: 09-24 is the latest final bar
    ok, _ = P.data_ready("SP500", frames, bench, after_midnight)
    assert ok                                            # stocks: holidays make a date check unreliable


def test_stale_positions_are_flagged():
    """A held symbol without a bar on the as-of date (halt, delisting) is reported."""
    from types import SimpleNamespace
    days = pd.bdate_range("2024-06-24", "2024-06-28")
    bench = pd.DataFrame({"close": range(5)}, index=days)
    frames = {"LIVE": pd.DataFrame({"close": range(5)}, index=days),
              "HALT": pd.DataFrame({"close": range(2)}, index=days[:2])}
    res = SimpleNamespace(open_positions=[{"symbol": "LIVE"}, {"symbol": "HALT"}, {"symbol": "GONE"}])
    st = P.stale_positions(res, frames, bench, days[-1])
    assert st == [{"symbol": "HALT", "last_bar": "2024-06-25", "sessions_missing": 3},
                  {"symbol": "GONE", "last_bar": None, "sessions_missing": None}]


def test_ledger_replays_committed_signals_after_a_data_revision(tmp_path, ledger_repo, monkeypatch):
    """2026-10-07: Yahoo raised the 10-06 KOSDAQ volumes during the next session, so recomputing
    10-06 added an entry nobody could have known before the open. The ledger must trade what was
    committed before the open; the audit records the difference; no revision file is written
    once the open has passed."""
    offline = tmp_path / "data"
    offline.mkdir()
    days = _write_market(offline)
    run_days = list(days[-15:])
    d0 = sym = None
    for i, day in enumerate(run_days[:-1]):
        r = _run(offline, ledger_repo, _after_close(day), monkeypatch)
        if r["snapshot"]["entries_next_open"]:
            d0, d1, sym = day, run_days[i + 1], r["snapshot"]["entries_next_open"][0]["symbol"]
            break
    assert d0 is not None, "fixture should produce an entry signal"
    d0s = d0.strftime("%Y-%m-%d")
    # the provider revises d0's volume for that symbol after the open: the breakout loses its volume
    f = offline / f"{sym}.csv"
    df = pd.read_csv(f)
    df.loc[df["Date"] == d0s, "Volume"] = 1.0
    df.to_csv(f, index=False)
    sig = ledger_repo / "paper" / "SP500" / "signals"
    # during the next session (d1 bar not final yet): d0's open has passed, so d0 replays the
    # committed signals - nothing to revise - while the audit already sees the difference
    mid = datetime(d1.year, d1.month, d1.day, 15, 0, tzinfo=timezone.utc)
    r = _run(offline, ledger_repo, mid, monkeypatch)
    assert r["snapshot"]["as_of"] == d0s and r["signal_state"] == "unchanged"
    assert sym in {e["symbol"] for e in r["snapshot"]["entries_next_open"]}
    assert not list(sig.glob(f"{d0s}.rev*.json"))
    assert d0s in r["audit"]["mismatched"]
    # after d1's close: the committed entry was filled at d1's open
    r = _run(offline, ledger_repo, _after_close(d1), monkeypatch)
    root = ledger_repo / "paper" / "SP500"
    trades = pd.read_csv(root / "trades.csv")
    held = [p for p in json.loads((root / "positions.json").read_text()) if p["symbol"] == sym]
    entered = held + ([] if trades.empty or "symbol" not in trades else
                      trades[trades["symbol"] == sym].to_dict("records"))
    assert any(e["entry_date"] == d1.strftime("%Y-%m-%d") for e in entered)
    aud = r["audit"]
    assert d0s in aud["mismatched"] and d0s not in aud["revised"] and aud["revised_after_open"] == []
    row = next(x for x in aud["rows"] if x["date"] == d0s)
    assert row["entries_only_committed"] == [sym] and row["on_time"]
    assert f"진입 −{sym}" in (root / "report.md").read_text()


def test_signal_file_revisions_compare_with_the_latest_and_stop_at_the_open(tmp_path):
    sig = tmp_path / "signals"
    snap = {"as_of": "2024-06-28", "entries_next_open": [{"symbol": "A"}], "exits_next_open": []}
    other = dict(snap, entries_next_open=[{"symbol": "A"}, {"symbol": "B"}])
    now = datetime(2024, 6, 28, 22, 0, tzinfo=timezone.utc)
    deadline = datetime(2024, 7, 1, 13, 30, tzinfo=timezone.utc)
    assert P.write_signal_file(sig, snap, now, deadline)[1] == "new"
    p, state = P.write_signal_file(sig, other, now, deadline)
    assert state == "revised" and p.name == "2024-06-28.rev1.json"
    # the same revised signals again: compared with rev1, nothing new (was a new revN every run)
    p, state = P.write_signal_file(sig, other, now, deadline)
    assert state == "unchanged" and p.name == "2024-06-28.rev1.json"
    assert P.write_signal_file(sig, snap, now, deadline)[0].name == "2024-06-28.rev2.json"
    # after the open: nothing is written
    after = datetime(2024, 7, 1, 15, 0, tzinfo=timezone.utc)
    p, state = P.write_signal_file(sig, other, after, deadline)
    assert state == "differs after the open" and p.name == "2024-06-28.rev2.json"
    assert sorted(x.name for x in sig.glob("*.json")) == ["2024-06-28.json", "2024-06-28.rev1.json",
                                                         "2024-06-28.rev2.json"]
