#!/usr/bin/env bash
# End-to-end check of the notice staff with the REAL claude CLI and a FAKE Drive MCP server:
#   order -> pinned read_file_content per source -> the writer (real sonnet, no tools) drafts -> code checks the
#   numbers and appends its block -> drive_draft proposal -> executed through the substitute pinned call.
# No real Drive, board or calendar is touched. A few cents.
# Usage: bash tests/e2e_notice.sh
#   E2E_NOTICE_TEXTS='{"<id>": ["<title>", "<txt>"], ...}' E2E_NOTICE_ORDER="<요청>"   your own texts (stay local)
#   E2E_NOTICE_MODE=daily   run the daily season check instead of an order (E2E_NOTICE_SEASON=<label>)
#   E2E_CLAUDE=<path>       another claude binary
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
REAL="${E2E_CLAUDE:-$(command -v claude)}"; [ -x "$REAL" ] || { echo "claude not found"; exit 2; }
echo "claude $("$REAL" --version 2>/dev/null)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
TEXTS="${E2E_NOTICE_TEXTS:-}"
if [ -z "$TEXTS" ]; then
  printf '%s\n' '프로젝트,2026 시험 시즌 신메뉴 출시 목표,2026-12-17,목표일이며 승인된 확정 출시일 아님 메뉴,온도,규격,잠정판매가 시험 라떼,HOT,M16oz,3900 시험 모카,ICE,M22oz,4300' > "$T/plan.txt"
  printf '%s\n' '매장 레시피 시험 라떼 HOT 우유 200 시럽 20 / 시험 모카 ICE 우유 180 초코 소스 30 교육 영상 미착수' > "$T/recipe.txt"
  TEXTS="{\"FAKEPLAN00001\": [\"01_기획.xlsx\", \"$T/plan.txt\"], \"FAKERECIPE001\": [\"03_레시피.xlsx\", \"$T/recipe.txt\"]}"
fi
IDS="$(python3 -c 'import json,sys; print(",".join(json.loads(sys.argv[1])))' "$TEXTS")"
ORDER="${E2E_NOTICE_ORDER:-시험 시즌 신메뉴 출시 공지 초안. 정보가 없는 곳은 [입력 필요]로.}"
cat > "$T/mcp.json" <<JSON
{"mcpServers":{"Google_Drive":{"command":"python3","args":["$HERE/fake_slack_mcp.py"],"env":{"FAKE_SLACK_LOG":"$T/calls.jsonl","FAKE_DRIVE_TEXTS":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$TEXTS")}}}}
JSON
printf '#!/usr/bin/env bash\nexec "%s" --mcp-config "%s" --strict-mcp-config "$@"\n' "$REAL" "$T/mcp.json" > "$T/claude"; chmod +x "$T/claude"
export CLAUDE_BIN="$T/claude" WORK_AGENT_STATE="$T/state" WORK_AGENT_CONFIG="$T/none.env" WORK_AGENT_MCP_PREFIX="mcp__" \
  WORK_AGENT_NOTICE_SOURCES="${E2E_NOTICE_SEASON:-시험}=$IDS" WORK_AGENT_DRIVE_DRAFT_FOLDER="FAKEFOLDER0001"
fails=0
[ "${E2E_NOTICE_MODE:-order}" = "daily" ] || python3 "$ROOT/office.py" order notice "$ORDER"
python3 "$ROOT/office.py" staff notice
python3 - "$T/state" "$T/calls.jsonl" "$ROOT" "${E2E_NOTICE_MODE:-order}" "${E2E_NOTICE_OUT:-}" <<'PY' || fails=$((fails+1))
import glob, json, os, sys
st, calls, root, mode, keep = sys.argv[1:6]
sys.path.insert(0, root); import office
props = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(st, "office", "proposals", "*.json")))]
status = json.load(open(os.path.join(st, "office", "staff", "notice.json")))
ran = [json.loads(l)["tool"] for l in open(calls)]
print("summary:", status.get("summary")); print("open_items:", status.get("open_items")); print("errors:", status.get("errors"))
bad = []
drafts = [p for p in props if p["kind"] == "drive_draft"]
for p in props:
    print("-", p["kind"], p["title"], "|", p["reason"])
if [t for t in ran if t != "read_file_content"]: bad.append("unexpected tools %s" % ran)
guard = os.path.join(st, "office", "tool_guard.log")
blocked = open(guard).read().strip() if os.path.exists(guard) else ""
if blocked: print("NOTE writer tried tools (blocked):", blocked[:200])
if mode == "order":
    if len(drafts) != 1: bad.append("drafts %d" % len(drafts))
    elif "**※ [자동 확인 — 맥미니 코드]**" not in drafts[0]["payload"]["content"]: bad.append("no check block")
    if glob.glob(os.path.join(st, "office", "orders", "notice", "*.json")): bad.append("order not closed")
    if drafts:
        d = drafts[0]
        if keep:
            open(keep, "w").write(d["payload"]["content"])
            print("draft saved:", keep)
        status_, result, _ = office.execute(office.Cfg(), d)
        got = [json.loads(l)["args"] for l in open(calls) if json.loads(l)["tool"] == "create_file"]
        want = {"title": office.draft_name(d), "parentId": "FAKEFOLDER0001", "textContent": d["payload"]["content"], "contentMimeType": "text/markdown"}
        print("execute:", status_, result)
        if got != [want]: bad.append("substitute: %s" % str(got)[:200])
elif drafts and keep:
    open(keep, "w").write(drafts[0]["payload"]["content"])
if status.get("status") != "idle": bad.append("status %s" % status.get("status"))
print("PASS notice e2e" if not bad else "FAIL " + "; ".join(bad))
sys.exit(1 if bad else 0)
PY
echo "failures: $fails"; exit "$fails"
