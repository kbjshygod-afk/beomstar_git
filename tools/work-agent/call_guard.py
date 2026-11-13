#!/usr/bin/env python3
"""PreToolUse hook that lets ONE named tool be called with EXACTLY the arguments we
decided in code, each expected call at most once. Everything else is blocked.

Usage (wired through --settings with onFailure: block):
    python3 call_guard.py <expect.json>

expect.json:
    {"tool": "ArtifactData",
     "calls": [{"sha256": "<sha256 of canonical tool_input>", "once": "/path/marker"}],
     "audit": "/path/audit.jsonl"}

Substitute mode (a call with "input"): the arguments are too long to have a model retype them (a draft
document). The model passes only "hint" (a few short fields that must match exactly) and this hook hands
Claude Code the real arguments as updatedInput, so what runs is "input", byte for byte. Checked on Claude
Code 2.1.296 and 2.1.310 (tests/e2e_cost.sh "substitute" proves it on each machine).

canonical(tool_input) = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
Strings are compared after stripping surrounding whitespace and normalizing CRLF.
ToolSearch (schema loading only) is always allowed. Python 3.9 compatible.
"""
import hashlib
import json
import os
import sys
import time


def canon(obj):
    def norm(v):
        if isinstance(v, str):
            return v.replace("\r\n", "\n").strip()
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in v.items()}
        return v
    return json.dumps(norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def audit(expect, decision, name, reason, digest=""):
    path = expect.get("audit") if isinstance(expect, dict) else None
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "decision": decision, "tool": name,
                                "sha256": digest[:16], "reason": reason}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def block(expect, name, reason, digest=""):
    audit(expect, "block", name, reason, digest)
    sys.stderr.write("blocked by call_guard: %s\n" % reason)
    return 2


def main():
    expect = {}
    with open(sys.argv[1]) as f:
        expect = json.load(f)
    call = json.load(sys.stdin)
    name = str(call.get("tool_name", ""))
    args = call.get("tool_input")
    if not isinstance(args, dict):
        args = {}
    if name == "ToolSearch":
        audit(expect, "allow", name, "schema lookup")
        return 0
    if name != expect.get("tool"):
        return block(expect, name, "only %s may be called" % expect.get("tool"))
    digest = sha(args)
    for c in expect.get("calls", []):
        full = c.get("input")
        sub = isinstance(full, dict)
        if sub:
            hint = c.get("hint") or {}
            if not hint or any(canon(args.get(k)) != canon(v) for k, v in hint.items()):
                continue
        elif c.get("sha256") != digest:
            continue
        try:
            fd = os.open(c["once"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            return block(expect, name, "this call was already made once", digest)
        if sub:
            audit(expect, "allow", name, "pinned call, arguments supplied by the guard", c.get("sha256", ""))
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                                "updatedInput": full}}, ensure_ascii=False))
            return 0
        audit(expect, "allow", name, "pinned call", digest)
        return 0
    return block(expect, name, "arguments differ from the pinned call (%s)" % digest[:12], digest)


if __name__ == "__main__":
    # Fail closed: any exit code other than 2 lets Claude Code run the call.
    try:
        rc = main()
    except BaseException:
        sys.stderr.write("blocked by call_guard: internal error\n")
        rc = 2
    sys.exit(rc)
