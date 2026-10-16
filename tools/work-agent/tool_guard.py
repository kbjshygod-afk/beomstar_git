#!/usr/bin/env python3
"""PreToolUse allowlist hook for the reader run (poll.sh) and the alert run (slack_dm.sh).

Usage (wired through --settings, with onFailure: block):
    python3 tool_guard.py <allow-file> [<audit-log>]

Allows ToolSearch (schema loading only) and the tools named in <allow-file>
(whitespace separated; an entry may also be a server prefix such as
mcp__claude_ai_Slack). Everything else is blocked with exit 2, including built-in
tools that would otherwise run without a permission check in -p mode and tools
added by future Claude Code versions. Blocks are appended to <audit-log>.
Python 3.9 compatible.
"""
import json
import sys
import time


def allowed(name, allow):
    return name == "ToolSearch" or any(name == a or name.startswith(a + "__") for a in allow)


def main():
    with open(sys.argv[1]) as f:
        allow = set(f.read().split())
    call = json.load(sys.stdin)
    name = str(call.get("tool_name", ""))
    if allowed(name, allow):
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
