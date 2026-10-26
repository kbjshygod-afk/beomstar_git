#!/usr/bin/env bash
# End-to-end check of the cost staff with the REAL claude CLI and a FAKE Drive MCP server:
#   pinned download (over ~25k tokens, so Claude Code saves it to tool-results) -> office reads and deletes that
#   file -> cost_check -> the model (real, sonnet) reads the fake plan file and adds notes -> local proposals.
# No real Drive, board or calendar is touched. A few cents.
# Usage: bash tests/e2e_cost.sh
#   E2E_COST_BOOK=<xlsx> E2E_COST_PLAN=<txt>  use your own files instead of the synthetic ones (stay local)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
REAL="$(command -v claude)" || { echo "claude not found"; exit 2; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
BOOK="${E2E_COST_BOOK:-$T/book.xlsx}"; PLAN="${E2E_COST_PLAN:-$T/plan.txt}"
if [ -z "${E2E_COST_BOOK:-}" ]; then
  python3 - "$HERE" "$BOOK" <<'PY'
import os, sys, zipfile
sys.path.insert(0, sys.argv[1]); import test_cost
data = test_cost.master([("빈 메뉴 (HOT)", "HOT / M", 3900, []), ("라떼", "HOT / M", 3900, [("바닐라시럽", 20), ("우유", 200)]),
                         ("모카", "ICE / M", 4500, [("초코 소스", 30), ("우유", 180)])])
with open(sys.argv[2], "wb") as f:
    f.write(data)
with zipfile.ZipFile(sys.argv[2], "a") as z:  # a big picture, as real workbooks have: the answer goes over ~25k tokens
    z.writestr("xl/media/image1.bin", os.urandom(400000))
PY
fi
[ -n "${E2E_COST_PLAN:-}" ] || printf '%s\n' '잠정 원가표 메뉴,온도,원가율,검증 상태 라떼,HOT,31.2%,잠정 / 관능·확정 견적 미검증 모카,ICE,42.5%,잠정 / 견적 미검증' > "$PLAN"
cat > "$T/mcp.json" <<JSON
{"mcpServers":{"Google_Drive":{"command":"python3","args":["$HERE/fake_slack_mcp.py"],"env":{"FAKE_SLACK_LOG":"$T/calls.jsonl","FAKE_DRIVE_FILE":"$BOOK","FAKE_DRIVE_TEXT":"$PLAN"}}}}
JSON
printf '#!/usr/bin/env bash\nexec "%s" --mcp-config "%s" --strict-mcp-config "$@"\n' "$REAL" "$T/mcp.json" > "$T/claude"; chmod +x "$T/claude"
export CLAUDE_BIN="$T/claude" WORK_AGENT_STATE="$T/state" WORK_AGENT_CONFIG="$T/none.env" WORK_AGENT_MCP_PREFIX="mcp__" \
  WORK_AGENT_COST_SOURCES="테스트=FAKEMASTER0001,FAKEPLAN00001"
fails=0
out="$(python3 "$ROOT/office.py" staff cost 2>&1)"; echo "$out"
python3 - "$T/state" "$T/calls.jsonl" "$ROOT" "$BOOK" <<'PY' || fails=$((fails+1))
import glob, json, os, re, sys
st, calls = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3]); import cost_check
names = dict((c, short) for c, short, _ in cost_check.CHECKS)
want = sorted({names[f["check"]] for f in cost_check.check(open(sys.argv[4], "rb").read())["findings"]})
props = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(st, "office", "proposals", "*.json")))]
status = json.load(open(os.path.join(st, "office", "staff", "cost.json")))
ran = [json.loads(l)["tool"] for l in open(calls)]
bad = []
print("summary:", status.get("summary")); print("errors:", status.get("errors")); print("open_items:", status.get("open_items"))
for p in props:
    print("-", p["title"], "|", p["payload"]["text"].replace("\n", " / ")[:220])
if status.get("status") != "idle": bad.append("status %s" % status.get("status"))
code = [p for p in props if p["reason"] == "코드 검산(입력값 기준)"]
missing = [w for w in want if not any((" %s " % w) in p["title"] for p in code)]
if missing or len(code) != len(want): bad.append("code cards %s, expected %s" % ([p["title"] for p in code], want))
leaked = [x for x in status.get("open_items", []) + [p["payload"]["text"] for p in props] if re.search(r"\d\s*원\s*/\s*(kg|g|ml|bag)", x)]
if leaked: bad.append("unit price on the board: %s" % leaked[:2])
if ran.count("download_file_content") != 1: bad.append("download calls %s" % ran)
if [t for t in ran if t not in ("download_file_content", "read_file_content")]: bad.append("unexpected tools %s" % ran)
spilled = [p for p in glob.glob(os.path.expanduser("~/.claude/projects/*/*/tool-results/*download_file_content*"))
           if os.path.getmtime(p) > os.path.getmtime(calls) - 600]
if spilled: bad.append("saved download not deleted: %s" % spilled)
guard = os.path.join(st, "office", "tool_guard.log")
if os.path.exists(guard) and open(guard).read().strip(): bad.append("tool_guard blocked: %s" % open(guard).read()[:200])
if not any("권장:" in p["payload"]["text"] for p in code): print("WARN no model note on the code cards")
print("PASS cost e2e" if not bad else "FAIL " + "; ".join(bad))
sys.exit(1 if bad else 0)
PY
echo "failures: $fails"; exit "$fails"
