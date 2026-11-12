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


def test_no_keys_skips_and_a_failed_provider_is_reported(monkeypatch):
    assert R.render({}, R.merge({}), "#69", "abc").count("건너뛰었습니다") == 1
    monkeypatch.setattr(R, "available_models", lambda p, k: ["gemini-x", "gemini-y"])
    def call(provider, model, system, prompt):
        if provider == "gemini":
            raise R.ReviewError('HTTP 404: {"error": "models/m-g is not found"}')
        return _answer([])
    res = R.review(CTX, "69", MODELS, {"openai": "k", "gemini": "k"}, call=call)
    assert res["gemini"]["error"].startswith("HTTP 404") and res["gemini"]["models_available"] == ["gemini-x", "gemini-y"]
    assert res["openai"]["round2"] == {}                                           # no second opinion to read
    md = R.render(res, R.merge(res), "#69", "abc")
    assert "`gemini-x`" in md and "GEMINI_REVIEW_MODEL" in md and "지적 사항 없음" in md


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
