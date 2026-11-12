import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ai_review as R  # noqa: E402

CTX = {"files": "M\ta.py", "diff": "+x = 1", "trunc": "", "brief": "brief", "lessons": "lessons"}
MODELS = {"openai": "m-o", "gemini": "m-g"}


def _answer(findings, gaps=(), lessons=()):
    return json.dumps({"summary": "s", "findings": findings, "gaps": list(gaps), "lesson_candidates": list(lessons)})


def fake_call(round1, round2):
    def call(provider, model, system, prompt):
        return round2[provider] if "other reviewer" in prompt else round1[provider]
    return call


def test_two_rounds_group_findings_by_the_other_reviewers_verdict():
    r1 = {"openai": _answer([{"id": "F1", "severity": "major", "file": "a.py", "line": 3, "claim": "off by one"},
                             {"id": "F2", "severity": "nit", "file": "a.py", "claim": "name"}], gaps=["no test"]),
          "gemini": _answer([{"id": "F1", "severity": "BLOCKER", "file": "b.py", "claim": "rule change"}], lessons=["L"])}
    r2 = {"openai": json.dumps({"verdicts": [{"id": "F1", "verdict": "disagree", "reason": "observation only"}], "additions": []}),
          "gemini": json.dumps({"verdicts": [{"id": "F1", "verdict": "agree", "reason": "yes"}],
                                "additions": [{"id": "A1", "severity": "minor", "file": "c.py", "claim": "missed"}]})}
    res = R.review(CTX, "69", MODELS, {"openai": "k", "gemini": "k"}, call=fake_call(r1, r2))
    m = R.merge(res)
    assert [f["claim"] for f in m["consensus"]] == ["off by one"]                 # Gemini agreed with ChatGPT F1
    assert [f["claim"] for f in m["disputed"]] == ["rule change"] and m["disputed"][0]["severity"] == "blocker"
    assert [f["claim"] for f in m["single"]] == ["name"]                          # no verdict on F2
    assert m["additions"][0]["by"] == "Gemini" and m["gaps"] == [("ChatGPT", "no test")] and m["lessons"] == [("Gemini", "L")]
    md = R.render(res, m, "#69", "abcdef123456")
    assert md.startswith(R.MARKER) and "두 검수자 합의 (1)" in md and "의견 갈림" in md and "상대 검토: disagree" in md


def test_one_key_runs_one_reviewer_without_round_two():
    calls = []
    def call(provider, model, system, prompt):
        calls.append((provider, "other reviewer" in prompt))
        return _answer([{"severity": "minor", "claim": "x"}])
    res = R.review(CTX, "69", MODELS, {"openai": "", "gemini": "k"}, call=call)
    assert calls == [("gemini", False)] and list(res) == ["gemini"]
    assert R.merge(res)["single"][0]["id"] == "F1"


def test_no_keys_skips_and_a_failed_provider_is_reported():
    assert R.render({}, R.merge({}), "#69", "abc").count("건너뛰었습니다") == 1
    def call(provider, model, system, prompt):
        if provider == "gemini":
            raise R.ReviewError("exit 1: unknown model 'm-g'")
        return _answer([])
    res = R.review(CTX, "69", MODELS, {"openai": "k", "gemini": "k"}, call=call)
    assert res["gemini"]["error"] == "exit 1: unknown model 'm-g'"
    assert res["openai"]["round2"] == {}                                           # no second opinion to read
    md = R.render(res, R.merge(res), "#69", "abc")
    assert "unknown model" in md and "Antigravity CLI" in md and "지적 사항 없음" in md


def test_cli_commands_are_read_only_and_never_skip_permissions(tmp_path):
    out = tmp_path / "o.out"
    codex = R.cli_command("openai", "m-o", "PROMPT", ".ai-review/openai_round1.md", out)
    assert codex[:4] == ["codex", "exec", "--sandbox", "read-only"] and ["-m", "m-o"] == codex[-3:-1]
    assert ".ai-review/openai_round1.md" in codex[-1] and "PROMPT" not in codex[-1]
    agy = R.cli_command("gemini", "", "PROMPT", "x", out)
    assert agy[:2] == ["agy", "-p"] and agy[2].endswith("PROMPT") and "Do not use any tools" in agy[2]
    assert not any("dangerously" in a or "yolo" in a for a in codex + agy)
    big = R.cli_command("gemini", "", "x" * 200_000, "x", out)[2]
    assert len(big.encode()) <= R.MAX_ARG + 20 and big.endswith("[truncated]")


def test_run_cli_passes_only_its_own_key_and_reports_failures(tmp_path, monkeypatch):
    seen = {}
    def fake_run(cmd, cwd, env, stdin, capture_output, text, timeout):
        seen.update(cmd=cmd, env=env, cwd=cwd)
        if cmd[0] == "codex":
            Path(cmd[cmd.index("-o") + 1]).write_text('{"findings": []}')
            return subprocess.CompletedProcess(cmd, 0, "log", "")
        return subprocess.CompletedProcess(cmd, 2, "", "Error: model not found")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setenv("GEMINI_API_KEY", "g-secret")
    assert R.run_cli("openai", "", "P", "o-key", tmp_path, "round1") == '{"findings": []}'
    assert seen["env"]["CODEX_API_KEY"] == "o-key" and "GEMINI_API_KEY" not in seen["env"] and seen["cwd"] == tmp_path
    assert (tmp_path / ".ai-review" / "openai_round1.md").read_text() == "P"
    try:
        R.run_cli("gemini", "", "P", "g-key", tmp_path, "round1")
        raise AssertionError("expected ReviewError")
    except R.ReviewError as e:
        assert str(e).startswith("exit 2") and "model not found" in str(e)
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("agy", 1)
    monkeypatch.setattr(R.subprocess, "run", slow)
    try:
        R.run_cli("gemini", "", "P", "g-key", tmp_path, "round2", timeout=1)
        raise AssertionError("expected ReviewError")
    except R.ReviewError as e:
        assert "timed out" in str(e)


def test_parse_json_tolerates_fences_and_keeps_prose():
    assert R.parse_json('```json\n{"findings": []}\n```') == {"findings": []}
    assert R.parse_json('Here you go: {"summary": "ok"} thanks')["summary"] == "ok"
    bad = R.parse_json("The diff looks fine to me.")
    assert bad["findings"][0]["claim"] == "The diff looks fine to me."


def test_build_context_reads_the_diff_brief_and_lessons(tmp_path, monkeypatch):
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (tmp_path / "docs" / "ai-review").mkdir(parents=True)
    (tmp_path / "docs" / "ai-review" / "brief.md").write_text("BRIEF")
    (tmp_path / "a.py").write_text("x = 1\n")
    run("add", ".")
    run("commit", "-qm", "a")
    base = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (tmp_path / "a.py").write_text("x = 2\n" + "y = 0\n" * 10)
    run("commit", "-qam", "b")
    monkeypatch.setattr(R, "MAX_DIFF_CHARS", 60)
    ctx = R.build_context(tmp_path, base, "HEAD")
    assert ctx["files"] == "M\ta.py" and ctx["brief"] == "BRIEF" and ctx["lessons"] == "(missing)"
    assert len(ctx["diff"]) == 60 and "truncated" in ctx["trunc"]


def test_login_mode_sets_no_key_variable(tmp_path, monkeypatch):
    seen = {}
    def fake_run(cmd, cwd, env, stdin, capture_output, text, timeout):
        seen["env"] = env
        return subprocess.CompletedProcess(cmd, 0, '{"findings": []}', "")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-leak")
    R.run_cli("gemini", "", "P", R.LOGIN, tmp_path, "round1")
    assert "GEMINI_API_KEY" not in seen["env"] and "CODEX_API_KEY" not in seen["env"]
