"""The swing-paper-keeper loop, run exactly as written in the workflow file with a virtual clock.

The keeper is the heart of the paper ledger (it dispatches every run), so its shell loop is tested
here instead of being trusted: `date`, `sleep` and `gh` are replaced by stubs on PATH, `sleep`
advances the clock, and the script runs under the same `bash -e -o pipefail` GitHub uses.
"""
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
KEEPER = ROOT / ".github" / "workflows" / "swing-paper-keeper.yml"
KIS_WS = ROOT / ".github" / "workflows" / "kis-ws.yml"
KST = ZoneInfo("Asia/Seoul")
REAL_DATE = shutil.which("date")

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and REAL_DATE), reason="needs bash and date")

FAKE_DATE = """#!/bin/bash
for a in "$@"; do if [ "$a" = "-d" ]; then exec {real} "$@"; fi; done
exec {real} -d "@$(cat "$CLOCK")" "$@"
"""
# sleep stub: advances the clock by its argument; once the clock has passed $STATE/fast_after (set by
# tests that have seen what they came for) it advances 15 minutes at a time so the run ends quickly.
FAKE_SLEEP = """#!/bin/bash
now=$(cat "$CLOCK"); step=${1%.*}
if [ -e "$STATE/fast_after" ] && [ "$now" -ge "$(cat "$STATE/fast_after")" ] && [ "$step" -lt 900 ]; then step=900; fi
echo $((now + step)) > "$CLOCK"
"""
# gh stub: logs "<epoch> <args>"; `run list` prints the content of $STATE/have (default 0) or fails
# when $STATE/list_fail exists; `workflow run kis-ws.yml` fails while $STATE/kis_fail holds a count > 0.
FAKE_GH = """#!/bin/bash
echo "$(cat "$CLOCK") $*" >> "$STATE/gh.log"
if [ "$1 $2" = "run list" ]; then
  [ -e "$STATE/list_fail" ] && { echo "gh: unknown flag" >&2; exit 1; }
  cat "$STATE/have" 2>/dev/null || echo 0
  exit 0
fi
if [ "$1 $2 $3" = "workflow run kis-ws.yml" ] && [ -e "$STATE/kis_fail" ]; then
  left=$(cat "$STATE/kis_fail")
  if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$STATE/kis_fail"; echo "HTTP 502" >&2; exit 1; fi
fi
exit 0
"""


def _steps():
    return yaml.safe_load(KEEPER.read_text())["jobs"]["keep"]["steps"]


def _step(name_part):
    return next(s for s in _steps() if name_part in s["name"])


def _epoch(text):
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp())


def _run(tmp_path, script, start, env=None, state=None):
    bindir, st = tmp_path / "bin", tmp_path / "state"
    bindir.mkdir(exist_ok=True)
    st.mkdir(exist_ok=True)
    for name, body in (("date", FAKE_DATE.format(real=REAL_DATE)), ("sleep", FAKE_SLEEP), ("gh", FAKE_GH)):
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    (st / "clock").write_text(str(start))
    for k, v in (state or {}).items():
        (st / k).write_text(str(v))
    e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CLOCK": str(st / "clock"), "STATE": str(st),
         **(env or {})}
    r = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                       env=e, capture_output=True, text=True, timeout=120)
    log = (st / "gh.log").read_text().splitlines() if (st / "gh.log").exists() else []
    calls = [(int(line.split(" ", 1)[0]), line.split(" ", 1)[1]) for line in log]
    return r, calls, int((st / "clock").read_text())


def _of(calls, text):
    return [(t, c) for t, c in calls if text in c]


LOOP = _step("Dispatch swing-paper")["run"]


def test_a_weekday_keeper_dispatches_the_ledger_three_times_and_both_slots_on_time(tmp_path):
    start = _epoch("2026-11-16 08:00")                              # Monday; runs to 13:45 KST
    r, calls, end = _run(tmp_path, LOOP, start)
    assert r.returncode == 0, r.stderr
    paper = _of(calls, "workflow run swing-paper.yml -f tries=1")
    assert [t - start for t, _ in paper] == [0, 7200, 14400]
    am, pm = _of(calls, "workflow run kis-ws.yml -f slot=am"), _of(calls, "workflow run kis-ws.yml -f slot=pm")
    assert len(am) == 1 and 0 <= am[0][0] - _epoch("2026-11-16 08:50") < 30
    assert len(pm) == 1 and 0 <= pm[0][0] - _epoch("2026-11-16 12:05") < 30
    assert 20700 <= end - start < 20700 + 30                        # hands over after 5 h 45 min
    assert "dispatched swing-paper 3/3" in r.stdout and "dispatched kis-ws slot pm" in r.stdout
    assert len(_of(calls, "run list")) == 2                         # one look per slot, not one per tick


def test_no_slot_is_dispatched_on_a_weekend(tmp_path):
    start = _epoch("2026-11-14 08:00")                              # Saturday
    r, calls, _ = _run(tmp_path, LOOP, start, state={"fast_after": _epoch("2026-11-14 12:40")})
    assert r.returncode == 0, r.stderr
    assert len(_of(calls, "swing-paper.yml")) == 3 and not _of(calls, "kis-ws.yml")


def test_a_slot_that_is_already_running_is_not_dispatched_again(tmp_path):
    start = _epoch("2026-11-16 09:05")                              # a new keeper 15 min into the am slot
    r, calls, _ = _run(tmp_path, LOOP, start, state={"have": 1, "fast_after": _epoch("2026-11-16 12:40")})
    assert r.returncode == 0, r.stderr
    assert not _of(calls, "workflow run kis-ws.yml")
    lists = _of(calls, "run list")
    assert len(lists) == 2                                          # asked once for am, once for pm
    assert 'kis-ws slot am' in lists[0][1] and "--workflow kis-ws.yml" in lists[0][1]
    assert "already started" in r.stdout


def test_a_keeper_that_starts_late_in_a_slot_leaves_it_to_the_backups(tmp_path):
    start = _epoch("2026-11-16 09:21")                              # 31 minutes after the am start
    r, calls, _ = _run(tmp_path, LOOP, start, state={"fast_after": _epoch("2026-11-16 09:30")})
    assert r.returncode == 0, r.stderr
    assert not _of(calls, "slot=am") and not _of(calls, "kis-ws slot am")   # no dispatch and no look for am
    start = _epoch("2026-11-16 11:50")                              # ...but the next slot is still its job
    (tmp_path / "pm").mkdir()
    r, calls, _ = _run(tmp_path / "pm", LOOP, start, state={"fast_after": _epoch("2026-11-16 12:10")})
    assert r.returncode == 0, r.stderr
    assert not _of(calls, "slot=am") and len(_of(calls, "workflow run kis-ws.yml -f slot=pm")) == 1


def test_a_failed_slot_dispatch_is_retried_at_the_next_tick(tmp_path):
    start = _epoch("2026-11-16 08:49")
    r, calls, _ = _run(tmp_path, LOOP, start, state={"kis_fail": 2, "fast_after": _epoch("2026-11-16 09:00")})
    assert r.returncode == 0, r.stderr
    am = _of(calls, "workflow run kis-ws.yml -f slot=am")
    assert len(am) == 3 and am[2][0] - am[0][0] == 60               # two failures, then the one that worked
    assert r.stdout.count("dispatch failed; trying again") == 2 and r.stdout.count("dispatched kis-ws slot am") == 1


def test_when_the_run_list_fails_the_slot_is_dispatched_anyway(tmp_path):
    start = _epoch("2026-11-16 08:49")
    r, calls, _ = _run(tmp_path, LOOP, start, state={"list_fail": 1, "fast_after": _epoch("2026-11-16 09:00")})
    assert r.returncode == 0, r.stderr
    assert len(_of(calls, "workflow run kis-ws.yml -f slot=am")) == 1


def test_the_slot_query_looks_back_45_minutes_and_counts_only_live_or_successful_runs(tmp_path):
    start = _epoch("2026-11-16 08:49")
    _, calls, _ = _run(tmp_path, LOOP, start, state={"fast_after": _epoch("2026-11-16 09:00")})
    t, q = _of(calls, "run list")[0]
    since = datetime.fromtimestamp(t - 2700, ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f"--created >={since}" in q
    assert '.displayTitle == "kis-ws slot am"' in q
    assert '.conclusion == "" or .conclusion == null or .conclusion == "success"' in q


@pytest.mark.skipif(not shutil.which("jq"), reason="needs jq")
def test_the_slot_filter_counts_the_right_runs(tmp_path):
    """The jq filter the keeper sends, taken from the call it really makes and applied to
    representative run records (a gap named by the Codex/Gemini cross-review of 2026-11-13)."""
    import json
    start = _epoch("2026-11-16 08:49")
    _, calls, _ = _run(tmp_path, LOOP, start, state={"fast_after": _epoch("2026-11-16 09:00")})
    flt = _of(calls, "run list")[0][1].split("--jq ", 1)[1]
    runs = [
        {"displayTitle": "kis-ws slot am", "conclusion": ""},            # queued or in progress
        {"displayTitle": "kis-ws slot am", "conclusion": None},
        {"displayTitle": "kis-ws slot am", "conclusion": "success"},
        {"displayTitle": "kis-ws slot am", "conclusion": "failure"},     # left no marker: does not count
        {"displayTitle": "kis-ws slot am", "conclusion": "cancelled"},
        {"displayTitle": "kis-ws slot pm", "conclusion": "success"},     # the other slot
        {"displayTitle": "kis-ws", "conclusion": ""},                    # a manual test or a smoke run
    ]
    def count(records):
        r = subprocess.run(["jq", flt], input=json.dumps(records), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return int(r.stdout)
    assert count(runs) == 3
    assert count(runs[3:]) == 0 and count([]) == 0


def test_the_hand_over_waits_when_the_loop_failed(tmp_path):
    script = _step("Hand over")["run"]
    r, calls, end = _run(tmp_path, script, 1_000_000, env={"LOOP": "success"})
    assert r.returncode == 0 and end == 1_000_000
    assert [c for _, c in calls] == ["workflow run swing-paper-keeper.yml"]
    (tmp_path / "failed").mkdir()
    r, calls, end = _run(tmp_path / "failed", script, 1_000_000, env={"LOOP": "failure"})
    assert r.returncode == 0 and end == 1_000_000 + 1200
    assert [c for _, c in calls] == ["workflow run swing-paper-keeper.yml"] and "waiting 20 minutes" in r.stdout


def test_workflow_wiring():
    steps = _steps()
    loop, hand, smoke = _step("Dispatch swing-paper"), _step("Hand over"), _step("Smoke test")
    assert loop["id"] == "loop" and "steps.loop.outcome" in hand["env"]["LOOP"]
    assert "!cancelled()" in hand["if"] and "push" in hand["if"] and loop["if"] == "github.event_name != 'push'"
    assert len(steps) == 3
    # the smoke run exercises the same read-only query as the loop
    clause = '(.conclusion == \\"\\" or .conclusion == null or .conclusion == \\"success\\")'
    assert clause in loop["run"] and clause in smoke["run"] and "--created" in smoke["run"]
    kis = yaml.safe_load(KIS_WS.read_text())
    assert "format('kis-ws slot {0}', github.event.inputs.slot)" in kis["run-name"]
    group = kis["concurrency"]["group"]
    assert "'daily'" in group and "github.event_name == 'push' && 'smoke'" in group and "github.run_id" in group
    assert kis["concurrency"]["cancel-in-progress"] is False
    crons = [c["cron"] for c in kis[True]["schedule"]]                # YAML reads the key `on` as True
    assert crons == ["50 23 * * 0-4", "5 3 * * 1-5"] and "'50 23 * * 0-4'" in kis["run-name"]
