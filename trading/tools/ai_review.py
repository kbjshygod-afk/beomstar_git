"""Cross-review of a pull request by two outside models (ChatGPT via the OpenAI API, Gemini via
the Gemini API), read-only. Claude writes the code; these two only report.

    OPENAI_API_KEY=... GEMINI_API_KEY=... python tools/ai_review.py --repo .. --base <sha> --head <sha> \
        [--pr 69] [--out reports/ai_review] [--post]

Round 1: each model reviews the same diff on its own (OpenAI: code correctness and tests; Gemini:
trading rules, data assumptions, docs vs code, gaps). Round 2: each reads the other's findings
and answers agree / disagree / unsure, and adds anything both missed. The result is one Markdown
report (consensus first, then disputed, then single-reviewer findings) written to --out and, with
--post, kept as one PR comment that is updated on each run. Both read docs/ai-review/brief.md
(project rules) and docs/ai-review/lessons.md (accepted lessons) first.

A missing key skips that reviewer; with neither key the run writes a note and exits 0. Keys are
read from the environment and never printed. Model ids come from OPENAI_REVIEW_MODEL /
GEMINI_REVIEW_MODEL (repository variables); when a provider rejects the id, the report lists the
ids that account can use, so the variable can be fixed without guessing.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODELS = {"openai": "gpt-5.6-sol", "gemini": "gemini-4-argon"}
MAX_DIFF_CHARS = 120_000
MAX_OUTPUT_TOKENS = 6000
TIMEOUT = 300
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


def _post_json(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise ReviewError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ReviewError(f"network: {getattr(e, 'reason', e)}") from None


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def call_openai(model: str, system: str, prompt: str, key: str) -> str:
    data = _post_json("https://api.openai.com/v1/chat/completions",
                      {"model": model, "messages": [{"role": "system", "content": system},
                                                    {"role": "user", "content": prompt}],
                       "response_format": {"type": "json_object"}, "max_completion_tokens": MAX_OUTPUT_TOKENS},
                      {"authorization": f"Bearer {key}"})
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ReviewError(f"unexpected OpenAI response: {str(data)[:300]}") from None


def call_gemini(model: str, system: str, prompt: str, key: str) -> str:
    data = _post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      {"systemInstruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": MAX_OUTPUT_TOKENS}},
                      {"x-goog-api-key": key})
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise ReviewError(f"unexpected Gemini response: {str(data)[:300]}") from None


def available_models(provider: str, key: str) -> list[str]:
    """Ids the account can use, for the report when a configured id is rejected. Never raises."""
    try:
        if provider == "openai":
            data = _get_json("https://api.openai.com/v1/models", {"authorization": f"Bearer {key}"})
            return sorted(m["id"] for m in data.get("data", []) if m.get("id", "").startswith(("gpt", "o")))
        data = _get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": key})
        return sorted(m["name"].split("/", 1)[-1] for m in data.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))
    except Exception:                                   # noqa: BLE001 - only a hint for the report
        return []


CALLERS = {"openai": call_openai, "gemini": call_gemini}


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


def review(ctx: dict, pr: str, models: dict, keys: dict, call=None) -> dict:
    """Round 1 and round 2 for every provider with a key. `call(provider, model, system, prompt)`
    is injectable for tests. Errors are recorded per provider and never raised."""
    call = call or (lambda p, m, s, q: CALLERS[p](m, s, q, keys[p]))
    active = [p for p in ("openai", "gemini") if keys.get(p)]
    res = {p: {"model": models[p], "error": None, "round1": {}, "round2": {}} for p in active}
    system = "You are a careful senior reviewer. You never edit code; you report findings as JSON."
    for p in active:
        prompt = ROUND1.format(role=ROLES[p], pr=pr, **ctx)
        try:
            res[p]["round1"] = parse_json(call(p, models[p], system, prompt))
        except ReviewError as e:
            res[p]["error"] = str(e)
            if "model" in str(e).lower() or "HTTP 404" in str(e):
                res[p]["models_available"] = available_models(p, keys[p]) if keys.get(p) else []
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
        lines.append(f"- **{NAMES[p]}** (`{r['model']}`): {state}")
        if r.get("models_available") is not None:
            ids = ", ".join(f"`{m}`" for m in r["models_available"][:25]) or "(목록을 받지 못함)"
            lines.append(f"  - 사용 가능한 모델: {ids} — 저장소 변수 `{p.upper()}_REVIEW_MODEL`로 지정")
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


def post_comment(repo_slug: str, pr: str, body: str, token: str) -> str:
    """Create or update the single cross-review comment on the PR."""
    api = f"https://api.github.com/repos/{repo_slug}/issues/{pr}/comments"
    hdr = {"authorization": f"Bearer {token}", "accept": "application/vnd.github+json"}
    existing = None
    for page in range(1, 6):
        rows = _get_json(f"{api}?per_page=100&page={page}", hdr)
        existing = next((c for c in rows if MARKER in (c.get("body") or "")), existing)
        if len(rows) < 100:
            break
    url, method = (existing["url"], "PATCH") if existing else (api, "POST")
    req = urllib.request.Request(url, data=json.dumps({"body": body}).encode(), method=method,
                                 headers={**hdr, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("html_url", "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="..")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--pr", default="")
    ap.add_argument("--out", default="reports/ai_review")
    ap.add_argument("--post", action="store_true", help="create/update the PR comment (needs GITHUB_TOKEN, GITHUB_REPOSITORY)")
    a = ap.parse_args(argv)
    keys = {"openai": os.environ.get("OPENAI_API_KEY", "").strip(), "gemini": os.environ.get("GEMINI_API_KEY", "").strip()}
    models = {p: os.environ.get(f"{p.upper()}_REVIEW_MODEL", "").strip() or m for p, m in DEFAULT_MODELS.items()}
    ctx = build_context(Path(a.repo), a.base, a.head)
    res = review(ctx, a.pr or a.head[:8], models, keys)
    merged = merge(res)
    md = render(res, merged, f"#{a.pr}" if a.pr else "", a.head)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text(md)
    out.with_suffix(".json").write_text(json.dumps({"results": res, "merged": merged}, ensure_ascii=False, indent=1))
    print(md)
    if a.post and a.pr:
        try:
            print("comment:", post_comment(os.environ["GITHUB_REPOSITORY"], a.pr, md, os.environ["GITHUB_TOKEN"]))
        except Exception as e:                          # noqa: BLE001 - the report file is still there
            print(f"could not post the comment: {e}", file=sys.stderr)
            return 1
    failed = [p for p, r in res.items() if r["error"]]
    return 1 if res and len(failed) == len(res) else 0


if __name__ == "__main__":
    sys.exit(main())
