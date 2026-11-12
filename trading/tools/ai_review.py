"""Cross-review of a pull request by two coding-agent CLIs, read-only: ChatGPT through the Codex
CLI (`codex exec --sandbox read-only`) and Gemini through the Antigravity CLI (`agy -p`). Claude
writes the code; these two only report.

    CODEX_API_KEY=... GEMINI_API_KEY=... python tools/ai_review.py --repo .. --base <sha> --head <sha> \
        [--pr 69] [--out reports/ai_review]

Codex runs in the checked-out repository inside its read-only sandbox, so besides the diff it can
open any file and run read-only commands; its prompt is written to <repo>/.ai-review/ and it is
told to read it. Antigravity has no read-only mode and is never given permission-skipping flags:
its whole prompt (brief, lessons, diff) goes on the command line and it is told not to use tools,
with a timeout in case it waits for an approval. Round 1: each reviews the same PR on its own
(Codex: code correctness and tests; Gemini: trading rules, data assumptions, docs vs code, gaps).
Round 2: each reads the other's findings and answers agree / disagree / unsure, and adds anything
both missed. The result is one Markdown report (consensus first, then disputed, then single) at
--out; the workflow posts it as one PR comment.

With --login the CLIs use their saved subscription logins (`codex login --device-auth`, the
agy Google sign-in) and need no keys. Otherwise a missing key skips that reviewer; with neither key the run writes a note and exits 0. Keys are
read from the environment and only passed to their own CLI; they are never printed. Model ids
come from OPENAI_REVIEW_MODEL / GEMINI_REVIEW_MODEL (repository variables; empty = the CLI's
default). A CLI failure is reported with the end of its output, so a wrong model id or a login
problem shows up in the PR comment.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_DIFF_CHARS = 100_000   # Antigravity gets the prompt as one argument (Linux limit 128 KiB)
TIMEOUT = 900             # seconds per CLI call; agy has been seen to hang without a TTY
MARKER = "<!-- ai-cross-review -->"
SEVERITIES = ("blocker", "major", "minor", "nit")

ROLES = {
    "openai": "Code reviewer: correctness bugs, edge cases (time zones, holidays, empty data, partial "
              "downloads, caching), error handling that could stop the ledger, and missing tests for risky paths.",
    "gemini": "Logic and rules reviewer: does the change respect the trading rules and the grade-3 freeze, are "
              "the data-source assumptions right, do the docs and comments still match the code, and what did the "
              "PR leave out (gaps).",
}
NAMES = {"openai": "ChatGPT", "gemini": "Gemini"}
CLI_NAMES = {"openai": "Codex CLI", "gemini": "Antigravity CLI"}

ROUND1 = """{brief}

# Shared lessons
{lessons}

# Your role
{role}

# Pull request {pr}
Changed files:
{files}

Diff (base...head{trunc}):
```diff
{diff}
```

Answer with JSON only:
{{"summary": "<two sentences>",
  "findings": [{{"id": "F1", "severity": "blocker|major|minor|nit", "file": "<path>", "line": <int or null>,
                "claim": "<what is wrong>", "evidence": "<code quote or execution path>",
                "fix": "<suggested fix>", "confidence": "high|medium|low"}}],
  "gaps": ["<something the PR should cover but does not>"],
  "lesson_candidates": ["<a reusable lesson, only if it would help future reviews>"]}}
Report only what you can support from the diff. An empty findings list is a fine answer."""

ROUND2 = """You reviewed pull request {pr} (your role: {role}).
The other reviewer ({other}) reported the findings below. For each one, say whether you agree, and why,
quoting the diff when you can. Then add anything that both of you missed.

Other reviewer's findings:
```json
{other_findings}
```

Answer with JSON only:
{{"verdicts": [{{"id": "<their id>", "verdict": "agree|disagree|unsure", "reason": "<one or two sentences>"}}],
  "additions": [<findings in the same shape as before, ids A1, A2, ...>]}}"""


class ReviewError(Exception):
    pass


KEY_ENV = {"openai": "CODEX_API_KEY", "gemini": "GEMINI_API_KEY"}
LOGIN = "<login>"         # placeholder key: run the CLI with its saved subscription login
MAX_ARG = 125_000
POINTER = ("Read the file {path} in this repository and follow its instructions exactly. Do not modify, create "
           "or delete files. Your final answer must be only the JSON object it asks for.")
INLINE = "Do not use any tools or open any files; everything you need is below. Answer with the JSON only.\n\n"


def cli_command(provider: str, model: str, prompt: str, prompt_file: str, out_file: Path) -> list[str]:
    if provider == "openai":
        cmd = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-o", str(out_file)]
        return cmd + (["-m", model] if model else []) + [POINTER.format(path=prompt_file)]
    text = INLINE + prompt
    if len(text.encode()) > MAX_ARG:
        text = text.encode()[:MAX_ARG].decode("utf-8", "ignore") + "\n[truncated]"
    return ["agy", "-p", text] + (["--model", model] if model else [])


def run_cli(provider: str, model: str, prompt: str, key: str, repo: Path, tag: str, timeout: int = TIMEOUT) -> str:
    """Run one CLI on one prompt and return its final answer. Raises ReviewError with the tail of
    the CLI's output on a missing binary, a timeout or a non-zero exit."""
    work = repo / ".ai-review"
    work.mkdir(exist_ok=True)
    rel = f".ai-review/{provider}_{tag}.md"
    (repo / rel).write_text(prompt)
    out_file = work / f"{provider}_{tag}.out"
    out_file.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CODEX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")}
    if key and key != LOGIN:
        env[KEY_ENV[provider]] = key          # else the CLI uses its own saved login
    cmd = cli_command(provider, model, prompt, rel, out_file)
    try:
        r = subprocess.run(cmd, cwd=repo, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ReviewError(f"{cmd[0]} CLI is not installed") from None
    except subprocess.TimeoutExpired:
        raise ReviewError(f"timed out after {timeout}s (waiting for an approval or stuck without a TTY?)") from None
    tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-1500:]
    if r.returncode != 0:
        raise ReviewError(f"exit {r.returncode}: {tail}")
    answer = out_file.read_text() if out_file.exists() else (r.stdout or "")
    if not answer.strip():
        raise ReviewError(f"empty answer: {tail}")
    return answer


def parse_json(text: str) -> dict:
    """The model's JSON answer; tolerates code fences and leading prose. A non-JSON answer
    becomes one 'unparsed' finding so nothing the reviewer said is lost."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        t = t[i:j + 1] if 0 <= i < j else t
    try:
        out = json.loads(t)
        return out if isinstance(out, dict) else {"findings": []}
    except json.JSONDecodeError:
        return {"summary": "(answer was not JSON)", "findings": [
            {"id": "F1", "severity": "minor", "file": "", "line": None, "claim": text.strip()[:2000],
             "evidence": "", "fix": "", "confidence": "low"}]}


def _findings(d: dict, key: str = "findings") -> list[dict]:
    out = []
    for i, f in enumerate(d.get(key) or [], 1):
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "minor")).lower()
        f = {**f, "severity": sev if sev in SEVERITIES else "minor", "id": str(f.get("id") or f"F{i}")}
        out.append(f)
    return out


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def build_context(repo: Path, base: str, head: str) -> dict:
    files = git(repo, "diff", "--name-status", f"{base}...{head}").strip()
    diff = git(repo, "diff", "--unified=5", f"{base}...{head}")
    trunc = ""
    if len(diff) > MAX_DIFF_CHARS:
        diff, trunc = diff[:MAX_DIFF_CHARS], f", truncated to the first {MAX_DIFF_CHARS:,} characters"
    read = lambda p: (repo / p).read_text() if (repo / p).exists() else "(missing)"   # noqa: E731
    return {"files": files or "(none)", "diff": diff, "trunc": trunc,
            "brief": read("docs/ai-review/brief.md"), "lessons": read("docs/ai-review/lessons.md")}


def review(ctx: dict, pr: str, models: dict, keys: dict, call=None, repo: Path = Path("..")) -> dict:
    """Round 1 and round 2 for every provider with a key. `call(provider, model, system, prompt)`
    is injectable for tests. Errors are recorded per provider and never raised."""
    tags = {}

    def default_call(p, m, system, prompt):
        tags[p] = tags.get(p, 0) + 1
        return run_cli(p, m, system + "\n\n" + prompt, keys[p], repo, f"round{tags[p]}")
    call = call or default_call
    active = [p for p in ("openai", "gemini") if keys.get(p)]
    res = {p: {"model": models[p], "error": None, "round1": {}, "round2": {}} for p in active}
    system = "You are a careful senior reviewer. You never edit code; you report findings as JSON."
    for p in active:
        prompt = ROUND1.format(role=ROLES[p], pr=pr, **ctx)
        try:
            res[p]["round1"] = parse_json(call(p, models[p], system, prompt))
        except ReviewError as e:
            res[p]["error"] = str(e)
    ok = [p for p in active if not res[p]["error"]]
    if len(ok) == 2:
        for p in ok:
            other = "gemini" if p == "openai" else "openai"
            prompt = ROUND2.format(pr=pr, role=ROLES[p], other=NAMES[other],
                                   other_findings=json.dumps(_findings(res[other]["round1"]), ensure_ascii=False, indent=1))
            try:
                res[p]["round2"] = parse_json(call(p, models[p], system, prompt))
            except ReviewError as e:
                res[p]["round2"] = {"error": str(e)}
    return res


def merge(res: dict) -> dict:
    """Findings grouped by what the other reviewer said: consensus (agreed), disputed, and single
    (no second opinion: unsure, not answered, or only one reviewer ran), plus additions and gaps."""
    groups = {"consensus": [], "disputed": [], "single": []}
    for p, r in res.items():
        other = "gemini" if p == "openai" else "openai"
        verdicts = {}
        if other in res:
            verdicts = {str(v.get("id")): v for v in (res[other].get("round2", {}).get("verdicts") or []) if isinstance(v, dict)}
        for f in _findings(r.get("round1", {})):
            v = verdicts.get(f["id"], {})
            item = {**f, "by": NAMES[p], "other_verdict": v.get("verdict"), "other_reason": v.get("reason", "")}
            g = {"agree": "consensus", "disagree": "disputed"}.get(str(v.get("verdict")).lower(), "single")
            groups[g].append(item)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    for g in groups.values():
        g.sort(key=lambda f: rank[f["severity"]])
    additions = [{**f, "by": NAMES[p]} for p, r in res.items() for f in _findings(r.get("round2", {}), "additions")]
    gaps = [(NAMES[p], g) for p, r in res.items() for g in (r.get("round1", {}).get("gaps") or [])]
    lessons = [(NAMES[p], l) for p, r in res.items() for l in (r.get("round1", {}).get("lesson_candidates") or [])]
    return {**groups, "additions": additions, "gaps": gaps, "lessons": lessons}


def _row(f: dict, with_verdict: bool = True) -> str:
    loc = f"`{f.get('file', '')}{':' + str(f['line']) if f.get('line') else ''}`" if f.get("file") else ""
    text = f"- **{f['severity']}** {loc} — {f.get('claim', '').strip()} _({f['by']}, {f.get('confidence', '?')})_"
    if f.get("evidence"):
        text += f"\n  - 근거: {str(f['evidence']).strip()[:600]}"
    if f.get("fix"):
        text += f"\n  - 제안: {str(f['fix']).strip()[:400]}"
    if with_verdict and f.get("other_verdict"):
        text += f"\n  - 상대 검토: {f['other_verdict']} — {f.get('other_reason', '').strip()}"
    return text


def render(res: dict, merged: dict, pr: str, head: str) -> str:
    lines = [MARKER, f"## AI 교차 검수 — PR {pr} @ `{head[:8]}`", ""]
    if not res:
        lines += ["검수 키(`OPENAI_API_KEY`, `GEMINI_API_KEY`)가 없어 건너뛰었습니다."]
        return "\n".join(lines) + "\n"
    for p, r in res.items():
        state = f"오류: {r['error']}" if r["error"] else (r["round1"].get("summary") or "요약 없음")
        lines.append(f"- **{NAMES[p]}** ({CLI_NAMES[p]}, 모델 `{r['model'] or 'CLI 기본값'}`): {state}")
    lines.append("")
    sections = (("consensus", "두 검수자 합의"), ("disputed", "의견 갈림 — 대표님 판단 필요 시 Claude가 정리"),
                ("single", "한쪽만 지적 (상대 확인 없음)"))
    for key, title in sections:
        if merged[key]:
            lines += [f"### {title} ({len(merged[key])})", *[_row(f) for f in merged[key]], ""]
    if merged["additions"]:
        lines += [f"### 2차에서 추가로 찾은 것 ({len(merged['additions'])})", *[_row(f, False) for f in merged["additions"]], ""]
    if merged["gaps"]:
        lines += ["### 빠진 부분", *[f"- {g} _({who})_" for who, g in merged["gaps"]], ""]
    if merged["lessons"]:
        lines += ["### 교훈 후보 (Claude가 검증 후 `docs/ai-review/lessons.md`에 반영)",
                  *[f"- {l} _({who})_" for who, l in merged["lessons"]], ""]
    if not any(merged[k] for k in ("consensus", "disputed", "single", "additions")):
        lines += ["지적 사항 없음.", ""]
    lines.append("_검수자는 읽기 전용입니다. 각 지적은 Claude가 재현·확인한 뒤에만 반영합니다._")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="..")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--pr", default="")
    ap.add_argument("--out", default="reports/ai_review")
    ap.add_argument("--login", action="store_true",
                    help="use the CLIs' saved subscription logins (codex login, agy sign-in) instead of API keys")
    a = ap.parse_args(argv)
    keys = {"openai": (os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip(),
            "gemini": os.environ.get("GEMINI_API_KEY", "").strip()}
    if a.login:
        keys = {p: keys[p] or LOGIN for p in keys}
    models = {p: os.environ.get(f"{p.upper()}_REVIEW_MODEL", "").strip() for p in ("openai", "gemini")}
    repo = Path(a.repo).resolve()
    ctx = build_context(repo, a.base, a.head)
    res = review(ctx, a.pr or a.head[:8], models, keys, repo=repo)
    merged = merge(res)
    md = render(res, merged, f"#{a.pr}" if a.pr else "", a.head)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text(md)
    out.with_suffix(".json").write_text(json.dumps({"results": res, "merged": merged}, ensure_ascii=False, indent=1))
    print(md)
    failed = [p for p, r in res.items() if r["error"]]
    return 1 if res and len(failed) == len(res) else 0


if __name__ == "__main__":
    sys.exit(main())
