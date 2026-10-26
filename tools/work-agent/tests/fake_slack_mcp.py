#!/usr/bin/env python3
"""Minimal stdio MCP server that stands in for the Slack connector in tests.

Tools: slack_send_message_draft (answers like the real connector did on 2026-10-16)
and slack_send_message (must never be called; every call is logged).
Env: FAKE_SLACK_LOG (jsonl of calls), FAKE_SLACK_MODE = ok | noid | exists | error.
download_file_content, read_file_content and create_file stand in for the Drive connector (fake_drive.py).
"""
import json
import os
import sys

import fake_drive

LOG = os.environ.get("FAKE_SLACK_LOG", "/dev/null")
MODE = os.environ.get("FAKE_SLACK_MODE", "ok")
SCHEMA = {"type": "object", "properties": {"channel_id": {"type": "string"}, "message": {"type": "string"},
                                           "thread_ts": {"type": "string"}}, "required": ["channel_id", "message"]}
TOOLS = [
    {"name": "slack_send_message_draft", "description": "Creates a draft message in a Slack channel without sending it.",
     "inputSchema": SCHEMA},
    {"name": "slack_send_message", "description": "Sends a message to a Slack channel.", "inputSchema": SCHEMA},
    {"name": "big_result", "description": "Returns a very long text, like a long meeting transcript.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "download_file_content", "description": "Downloads a Drive file as a base64 encoded string (fake).",
     "inputSchema": {"type": "object", "properties": {"fileId": {"type": "string"}}, "required": ["fileId"]}},
    {"name": "read_file_content", "description": "Returns a natural language representation of a Drive file (fake).",
     "inputSchema": {"type": "object", "properties": {"fileId": {"type": "string"}}, "required": ["fileId"]}},
    {"name": "create_file", "description": "Creates a file in Google Drive (fake). Folders via mimeType.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "parentId": {"type": "string"},
                                                      "textContent": {"type": "string"}, "contentMimeType": {"type": "string"}},
                     "required": ["title"]}},
    {"name": "create_event", "description": "Creates a calendar event (fake).",
     "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}, "startTime": {"type": "string"},
                                                      "endTime": {"type": "string"}, "description": {"type": "string"}},
                     "required": ["summary", "startTime", "endTime"]}},
]


def big_text():
    """~60k varied Hangul syllables (well over 25k tokens), deterministic, ending with the code line."""
    x, out = 12345, []
    for i in range(60000):
        x = (x * 1103515245 + 12345) % 2147483648
        out.append(chr(0xAC00 + x % 11172))
        if i % 40 == 39:
            out.append("\n")
    return "".join(out) + "\nCODE: PINEAPPLE-42\n"


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def call(name, args):
    with open(LOG, "a") as f:
        f.write(json.dumps({"tool": name, "args": args}, ensure_ascii=False) + "\n")
    ch = args.get("channel_id", "")
    if name == "create_event":
        return {"content": [{"type": "text", "text": json.dumps({"id": "evt_fake_e2e", "htmlLink": "https://calendar.google.com/event?eid=fake",
                                                                 "summary": args.get("summary", "")})}], "isError": False}
    drive = fake_drive.answer(name, args)
    if drive:
        return {"content": [{"type": "text", "text": drive[1]}], "isError": drive[0]}
    if name == "big_result":
        return {"content": [{"type": "text", "text": big_text()}], "isError": False}
    if name == "slack_send_message":
        return {"content": [{"type": "text", "text": json.dumps({"ok": True, "sent": True})}], "isError": False}
    if MODE == "exists":
        return {"content": [{"type": "text", "text": "Error: attached_draft_exists"}], "isError": True}
    if MODE == "error":
        return {"content": [{"type": "text", "text": "Error: failed_to_create_draft"}], "isError": True}
    body = {"channel_link": "https://example-ws.slack.com/archives/%s" % ch, "widget_id": "w-test",
            "channel_info": {"channel_id": ch, "name": "test", "is_dm": ch.startswith("D")},
            "result": "Draft message is created. They can edit it before sending."}
    if MODE != "noid":
        body["draft_id"] = "DrTEST0001"
    return {"content": [{"type": "text", "text": json.dumps(body)}], "isError": False}


for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    mid, method, params = req.get("id"), req.get("method", ""), req.get("params") or {}
    if mid is None:
        continue
    if method == "initialize":
        reply(mid, {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "fakeslack", "version": "0.1"}})
    elif method == "tools/list":
        reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        reply(mid, call(params.get("name", ""), params.get("arguments") or {}))
    elif method == "ping":
        reply(mid, {})
    else:
        reply(mid, error={"code": -32601, "message": "method not found"})
