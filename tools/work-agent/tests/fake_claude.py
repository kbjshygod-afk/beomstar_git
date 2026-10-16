#!/usr/bin/env python3
"""Stand-in for the `claude` CLI in tests (no model, no network).

Reader mode (any other prompt): prints {"type":"result",...} whose result is the file
named by FAKE_READER_RESULT, like `claude -p --output-format json`. If FAKE_READER_PROBE
names tools, each is first run through the --settings hook and the exit codes are logged.
Writer mode (prompt starts with "Call the tool ", as slack_drafts.py sends): runs the
PreToolUse hook from the settings file on a simulated tool call and prints stream-json.
FAKE_WRITER = honest | tamper_then_honest | tamper_only | send_attempt | none | hang
FAKE_SLACK_MODE = ok | noid | exists | error   (answer of the simulated draft tool)
FAKE_CALLS = file that receives one line per invocation (mode + tool calls that ran)
"""
import json
import os
import re
import subprocess
import sys
import time


def log(row):
    path = os.environ.get("FAKE_CALLS")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def emit(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")


def arg_after(flag):
    a = sys.argv[1:]
    return a[a.index(flag) + 1] if flag in a else None


def run_hook(settings, name, tool_input):
    cmd = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    p = subprocess.run(cmd, shell=True, input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": name,
                                                          "tool_input": tool_input}),
                       capture_output=True, text=True)
    return p.returncode, p.stderr


def slack_answer(ch):
    mode = os.environ.get("FAKE_SLACK_MODE", "ok")
    if mode == "exists":
        return True, "Error: attached_draft_exists"
    if mode == "error":
        return True, "Error: failed_to_create_draft"
    body = {"channel_link": "https://example-ws.slack.com/archives/%s" % ch,
            "result": "Draft message is created. They can edit it before sending."}
    if mode != "noid":
        body["draft_id"] = "DrFAKE01"
    return False, json.dumps(body)


def writer(settings_path):
    settings = json.load(open(settings_path))
    prompt = arg_after("-p")
    tool = re.search(r"Call the tool (\S+) exactly once", prompt).group(1)
    pinned = json.loads(re.search(r"^\{.*\}$", prompt, re.M).group(0))
    mode = os.environ.get("FAKE_WRITER", "honest")
    calls = []
    if mode in ("tamper_then_honest", "tamper_only"):
        bad = dict(pinned, channel_id="C0EVIL0001")
        calls.append((tool, bad))
    if mode == "send_attempt":
        calls.append((tool.rsplit("__", 1)[0] + "__slack_send_message", dict(pinned)))
    if mode in ("honest", "tamper_then_honest", "send_attempt"):
        calls.append((tool, pinned))
    if mode == "hang":  # the guard allows the call, then the Slack answer never comes back
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_hang", "name": tool,
                                                            "input": pinned}]}})
        sys.stdout.flush()
        run_hook(settings, tool, pinned)
        log({"mode": "writer", "ran": [], "attempted": [tool]})
        time.sleep(60)
    ran = []
    for i, (name, inp) in enumerate(calls):
        uid = "toolu_fake_%d" % i
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}]}})
        rc, err = run_hook(settings, name, inp)
        if rc == 2:
            text, is_err = "PreToolUse:%s hook error: [guard]: %s" % (name, err), True
        else:
            is_err, text = slack_answer(inp.get("channel_id", ""))
            ran.append(name)
        emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": text,
                                                         "is_error": is_err}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "DONE"})
    log({"mode": "writer", "ran": ran, "attempted": [c[0] for c in calls]})


def reader():
    path = os.environ.get("FAKE_READER_RESULT")
    text = '{"status":"ok","items":[],"plaud_seen":[],"errors":[]}'
    if path:
        with open(path) as f:
            text = f.read()
    s = arg_after("--settings")
    probes = {}
    if s:
        with open(s) as f:
            settings = json.load(f)
        for name in os.environ.get("FAKE_READER_PROBE", "").split():
            probes[name] = run_hook(settings, name, {})[0]
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text}))
    log({"mode": "reader", "guarded": bool(s), "probes": probes})


if __name__ == "__main__":
    if (arg_after("-p") or "").startswith("Call the tool "):
        writer(arg_after("--settings"))
    else:
        reader()
