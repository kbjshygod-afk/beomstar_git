#!/usr/bin/env python3
"""PreToolUse hook for slack_drafts.py.

Usage (set by slack_drafts.py in a per-call --settings file):
    python3 draft_guard.py <expect.json>

Allows exactly one call: the draft tool with the pinned channel_id, thread_ts and
message. ToolSearch (schema loading only) is let through. Everything else is
blocked with exit code 2, which Claude Code turns into a tool error. Each decision
is appended to the audit file named in expect.json.
Python 3.9 compatible (the Mac mini runs the system python3).
"""
import hashlib
import json
import os
import sys
import time

ALLOW_ALWAYS = {"ToolSearch"}


def norm(text):
    return str(text).replace("\r\n", "\n").strip()


def sha(text):
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def audit(expect, decision, name, args, reason=""):
    path = expect.get("audit") if isinstance(expect, dict) else None
    if not path:
        return
    try:
        row = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": decision,
            "tool": name,
            "channel_id": (args or {}).get("channel_id"),
            "thread_ts": (args or {}).get("thread_ts"),
            "message_sha256": sha((args or {}).get("message", "")) if args else "",
            "reason": reason,
        }
        with open(path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def block(expect, name, args, reason):
    audit(expect, "block", name, args, reason)
    sys.stderr.write("blocked by draft_guard: %s\n" % reason)
    return 2


def main():
    expect = {}
    try:
        with open(sys.argv[1]) as f:
            expect = json.load(f)
        call = json.load(sys.stdin)
    except Exception as e:
        return block(expect, "?", {}, "guard could not read its inputs (%s)" % e.__class__.__name__)

    name = call.get("tool_name", "")
    args = call.get("tool_input") or {}
    if not isinstance(args, dict):
        args = {}
    if name in ALLOW_ALWAYS:
        audit(expect, "allow", name, {}, "schema lookup")
        return 0
    if name != expect.get("tool"):
        return block(expect, name, args, "only %s may be called" % expect.get("tool"))
    extra = sorted(set(args) - {"channel_id", "thread_ts", "message"})
    if extra:
        return block(expect, name, args, "unexpected arguments: %s" % ", ".join(extra))
    if args.get("channel_id") != expect.get("channel_id"):
        return block(expect, name, args, "channel_id must be %s" % expect.get("channel_id"))
    if str(args.get("thread_ts") or "") != str(expect.get("thread_ts") or ""):
        return block(expect, name, args, "thread_ts must be %s" % expect.get("thread_ts"))
    if sha(args.get("message", "")) != expect.get("message_sha256"):
        return block(expect, name, args, "message must be copied exactly")
    try:
        fd = os.open(expect["once"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        return block(expect, name, args, "only one call is allowed")
    except Exception as e:
        return block(expect, name, args, "guard could not record the call (%s)" % e.__class__.__name__)
    audit(expect, "allow", name, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
