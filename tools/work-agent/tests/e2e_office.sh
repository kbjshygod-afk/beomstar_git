#!/usr/bin/env bash
# End-to-end check of the office with the REAL claude CLI and the REAL board database, but a FAKE calendar.
#   propose (saved staff output) -> cycle (push to the board, haiku pinned call) -> approve (the same write the
#   board page makes, as the owner) -> cycle (execute against the fake calendar MCP, report back) -> verify.
# Costs a few cents. Nothing touches the real calendar or Slack. Leaves one finished test item on the board
# (title starts with [e2e]); remove it with: bash tests/e2e_office.sh --cleanup
# Usage: WORK_AGENT_BOARD_URL=https://claude.ai/artifact/... bash tests/e2e_office.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
[ -n "${WORK_AGENT_BOARD_URL:-}" ] || { echo "set WORK_AGENT_BOARD_URL"; exit 2; }
REAL="$(command -v claude)" || { echo "claude not found"; exit 2; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/state"
cat > "$T/mcp.json" <<EOF
{"mcpServers":{"fakecal":{"command":"python3","args":["$HERE/fake_slack_mcp.py"],"env":{"FAKE_SLACK_LOG":"$T/calls.jsonl"}}}}
EOF
# the wrapper adds the fake calendar server; office.py's own --disallowedTools keep the real connectors out
printf '#!/usr/bin/env bash\nexec "%s" --mcp-config "%s" "$@"\n' "$REAL" "$T/mcp.json" > "$T/claude"; chmod +x "$T/claude"
export CLAUDE_BIN="$T/claude" WORK_AGENT_STATE="$T/state" WORK_AGENT_CONFIG="$T/none.env" WORK_AGENT_MCP_PREFIX="mcp__"
export WORK_AGENT_CALENDAR_TOOL="mcp__fakecal__create_event" WORK_AGENT_ROSTER="$ROOT/staff/roster.json"
fails=0
day="$(TZ=Asia/Seoul date +%Y-%m-%d)"; start="$(TZ=Asia/Seoul date -v+3d +%Y-%m-%d 2>/dev/null || TZ=Asia/Seoul date -d '+3 days' +%Y-%m-%d)"
cat > "$T/staff_out.json" <<EOF
{"status":"ok","summary":"[e2e] 시험 실행 $day","open_items":["[e2e] 시험 항목"],"seasons":[],
 "proposals":[{"kind":"calendar_event","key":"e2e:$day","title":"[e2e] 사무실 왕복 시험 (가짜 캘린더)","reason":"전광판 왕복 시험",
   "payload":{"summary":"[e2e] 사무실 시험 일정","startTime":"${start}T09:00:00","endTime":"${start}T09:30:00","description":"가짜 캘린더에만 등록됩니다."}}],
 "errors":[]}
EOF
step() { echo "== $1"; }
step "propose"; out="$(python3 "$ROOT/office.py" propose gate "$T/staff_out.json")"; echo "$out"
[[ "$out" == *"proposed=1"* ]] || { echo "FAIL propose"; exit 1; }
pid="$(python3 "$ROOT/office.py" status | cut -f1)"
step "cycle 1 (push)"; out="$(python3 "$ROOT/office.py" cycle)"; echo "$out"
[[ "$out" == *"pull=ok"* && "$out" == *"push=ok("* ]] || { echo "FAIL cycle1: $out"; sed -n '1,20p' "$T/state/office/office.log"; exit 1; }
step "approve as the owner (same write as the board page)"
python3 - "$ROOT" "$pid" <<'PY'
import json, os, sys
sys.path.insert(0, sys.argv[1]); import office, call_guard
cfg = office.Cfg(); pid = sys.argv[2]
prop = office.read_json(office.proposal_path(cfg, pid))
data, version, r = office.board_get(cfg, "queue", pid, "e2e-get")
assert data and data["status"] == "pending" and data["payload_sha256"] == prop["payload_sha256"], (data, r["status"])
body = {"status": "approved", "decided_at": office.utc_z(office.now()), "approved_sha": call_guard.sha(data["payload"]), "note": "e2e"}
r = office.pinned_call(cfg, "ArtifactData", {"action": "update", "url": cfg.board_url, "collection": "queue", "doc_id": pid, "data": body, "if_version": version}, "e2e-approve")
print(r["status"], r["text"][:120]); assert r["status"] == "ok"
PY
[ $? -eq 0 ] || { echo "FAIL approve"; exit 1; }
step "cycle 2 (execute + report)"; out="$(python3 "$ROOT/office.py" cycle)"; echo "$out"
[[ "$out" == *"approved=1 executed=1 failed=0"* && "$out" == *"push=ok("* ]] || { echo "FAIL cycle2: $out"; fails=$((fails+1)); }
step "verify"
grep -q '"tool": "create_event"' "$T/calls.jsonl" 2>/dev/null && python3 - "$T/calls.jsonl" "$T/staff_out.json" <<'PY' || { echo "FAIL: fake calendar never called"; fails=$((fails+1)); }
import json, sys
calls = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
want = json.load(open(sys.argv[2]))["proposals"][0]["payload"]
got = [c["args"] for c in calls if c["tool"] == "create_event"]
assert got == [want], (got, want)
print("calendar called once with the exact approved payload")
PY
python3 - "$ROOT" "$pid" <<'PY' || fails=$((fails+1))
import sys
sys.path.insert(0, sys.argv[1]); import office
cfg = office.Cfg(); data, version, r = office.board_get(cfg, "queue", sys.argv[2], "e2e-verify")
assert data and data["status"] == "done" and "등록됨" in data.get("result", ""), (data, r["status"])
print("board shows done:", data["result"])
PY
echo "guard audit (blocks):"; grep -c '"block"' "$T/state/office/call_guard.log" 2>/dev/null || echo 0
echo "failures: $fails"; exit "$fails"
