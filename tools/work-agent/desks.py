#!/usr/bin/env python3
"""Desks: where each worker's `claude -p` runs, so Pixel Agents shows one character per desk.

Pixel Agents (JSONL mode, no hooks) labels a headless session by the last "-" token of its
project directory under ~/.claude/projects, seats it in the Area mapped to that label, and keeps
the character until the transcript file disappears. So:
- every run of a role starts in state/office/desks/<desk> (ASCII desk names, no "-"),
- after a run, older transcripts of that desk are deleted so exactly one character stays.
Only directories whose name contains "-desks-" are ever touched. Python 3.9 compatible.
"""
import glob
import os

DESKS = ("secretary", "gate", "notice", "cost", "runner")


def desk_dir(state, desk):
    if desk not in DESKS:
        desk = "runner"
    path = os.path.join(state, "office", "desks", desk)
    os.makedirs(path, exist_ok=True)
    return path


def projects_dir():
    return os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "projects")


def tidy_transcripts(session_id):
    """Delete the other transcripts in the desk project dir that holds <session_id>.jsonl. Returns the count."""
    if not session_id or "/" in session_id or ".." in session_id:
        return 0
    removed = 0
    for keep in glob.glob(os.path.join(projects_dir(), "*", session_id + ".jsonl")):
        d = os.path.dirname(keep)
        if "-desks-" not in os.path.basename(d):
            continue
        for other in glob.glob(os.path.join(d, "*.jsonl")):
            if os.path.abspath(other) != os.path.abspath(keep):
                try:
                    os.remove(other)
                    removed += 1
                except OSError:
                    pass
    return removed


if __name__ == "__main__":
    import sys
    print(tidy_transcripts(sys.argv[1] if len(sys.argv) > 1 else ""))
