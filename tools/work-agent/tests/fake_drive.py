"""The fake Google Drive connector, shared by fake_claude.py (pinned calls in unit tests) and fake_slack_mcp.py
(the MCP server the real CLI talks to in the e2e scripts). Answers like the real connector did on 2026-10-26.

answer(tool, args) -> (is_error, text), or None when the tool is not one of Drive's.
  FAKE_DRIVE_FILE = file served by download_file_content (base64 JSON)
  FAKE_DRIVE_SPILL = dir: answer that download the way Claude Code answers an oversized result (saved to a
                     file in this dir, the tool result only names the path)
  FAKE_DRIVE_TEXTS = {"<file id>": ["<title>", "<text file>"]} served by read_file_content; FAKE_DRIVE_TEXT =
                     the text file for any other id (else: not found)
  FAKE_DRIVE_CREATED = file that receives the arguments each create_file call actually ran with
  FAKE_DRIVE_CREATE_MODE = ok | wrong_parent | error
"""
import base64
import json
import os
import time


def answer(tool, args):
    name = tool.rsplit("__", 1)[-1]
    if name == "download_file_content":
        with open(os.environ["FAKE_DRIVE_FILE"], "rb") as f:
            body = json.dumps({"content": base64.b64encode(f.read()).decode(), "id": args.get("fileId", ""),
                               "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "title": "fake.xlsx"})
        spill = os.environ.get("FAKE_DRIVE_SPILL")
        if spill:
            os.makedirs(spill, exist_ok=True)
            path = os.path.join(spill, "mcp-drive-download_file_content-%d.txt" % int(time.time() * 1000))
            with open(path, "w") as f:
                f.write(body)
            return False, ("Error: result (%d characters across 1 line) exceeds maximum allowed tokens. Output has been saved to %s.\n"
                           "Format: Plain text\nSearch within the file for specific content." % (len(body), path))
        return False, body
    if name == "read_file_content":
        files = json.loads(os.environ.get("FAKE_DRIVE_TEXTS") or "{}")
        if args.get("fileId") in files:
            title, path = files[args["fileId"]]
        elif os.environ.get("FAKE_DRIVE_TEXT"):
            title, path = "plan.xlsx", os.environ["FAKE_DRIVE_TEXT"]
        else:
            return True, "Error: File not found: %s" % args.get("fileId")
        with open(path) as f:
            return False, json.dumps({"fileContent": f.read(), "title": title, "viewUrl": "about:blank"}, ensure_ascii=False)
    if name == "create_file":
        path = os.environ.get("FAKE_DRIVE_CREATED")
        if path:
            with open(path, "a") as f:
                f.write(json.dumps(args, ensure_ascii=False) + "\n")
        mode = os.environ.get("FAKE_DRIVE_CREATE_MODE", "ok")
        if mode == "error":
            return True, "Error: insufficient permissions for the parent folder"
        return False, json.dumps({"id": "fakedoc01", "title": args.get("title", ""), "mimeType": "application/vnd.google-apps.document",
                                  "parentId": "SOMEWHEREELSE" if mode == "wrong_parent" else args.get("parentId", ""),
                                  "viewUrl": "https://docs.google.com/document/d/fakedoc01/edit"}, ensure_ascii=False)
    return None
