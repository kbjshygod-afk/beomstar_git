#!/usr/bin/env python3
"""PreToolUse allowlist hook for the reader run (poll.sh) and the alert run (slack_dm.sh).

Usage (wired through --settings, with onFailure: block):
    python3 tool_guard.py <allow-file> [<audit-log>]

Allows ToolSearch (schema loading only) and the tools named in <allow-file>
(whitespace separated; an entry may also be a server prefix such as
mcp__claude_ai_Slack). Read and Grep are allowed only inside this session's own
tool-results directory: Claude Code saves an MCP result over ~25k tokens there
(a long Plaud transcript, a big Slack read) and tells the model to open it.
Everything else is blocked with exit 2, including built-in tools that would
otherwise run without a permission check in -p mode and tools added by future
Claude Code versions. Blocks are appended to <audit-log>.
Python 3.9 compatible.
"""
import json
import os
import sys
import time


def allowed(name, allow):
    return name == "ToolSearch" or any(name == a or name.startswith(a + "__") for a in allow)


def saved_result(call):
    """Read/Grep of <transcript without .jsonl>/tool-results/, where oversized MCP results are saved."""
    tp, ti = call.get("transcript_path"), call.get("tool_input") or {}
    p = ti.get("file_path") if call.get("tool_name") == "Read" else ti.get("path")
    if not (isinstance(tp, str) and tp.endswith(".jsonl") and isinstance(p, str) and os.path.isabs(p)):
        return False  # Grep with no path searches the cwd (config.env): stays blocked
    root = os.path.join(os.path.realpath(tp[:-len(".jsonl")]), "tool-results")
    rp = os.path.realpath(p)
    return rp == root or rp.startswith(root + os.sep)


def main():
    with open(sys.argv[1]) as f:
        allow = set(f.read().split())
    call = json.load(sys.stdin)
    name = str(call.get("tool_name", ""))
    if allowed(name, allow) or (name in ("Read", "Grep") and saved_result(call)):
        return 0
    if len(sys.argv) > 2:
        try:
            with open(sys.argv[2], "a") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "decision": "block", "tool": name}) + "\n")
        except Exception:
            pass
    sys.stderr.write("blocked by tool_guard: %s is not on this run's allowlist\n" % name)
    return 2


if __name__ == "__main__":
    # Fail closed: any exit code other than 2 lets Claude Code run the call.
    try:
        rc = main()
    except BaseException:
        sys.stderr.write("blocked by tool_guard: internal error\n")
        rc = 2
    sys.exit(rc)
