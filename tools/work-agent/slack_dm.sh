#!/usr/bin/env bash
# Send one fixed-template Slack DM to the owner through `claude -p`.
# Usage: slack_dm.sh <dedupe-key> <text>
# The text must be built from our own templates (counts, file names, times),
# never from Slack/Plaud content, so nothing untrusted reaches the sending model.
# The only tool the model may use is slack_send_message.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
CONFIG="${WORK_AGENT_CONFIG:-$DIR/config.env}"
[ -f "$CONFIG" ] && . "$CONFIG"
. "$DIR/lib.sh"

TO="${WORK_AGENT_SLACK_DM_USER:-}"
[ -n "$TO" ] || exit 0
KEY="$1"; TEXT="$2"
STATE="${WORK_AGENT_STATE:-$DIR/state}"
SENT="$STATE/dm_sent.txt"; LOG="$STATE/poll.log"
mkdir -p "$STATE"; touch "$SENT"
today="$(kst +%F)"
log() { printf '%s %s\n' "$(kst '+%F %T')" "$*" >> "$LOG"; }

grep -qxF "$today $KEY" "$SENT" && exit 0
if [ "$(grep -c "^$today " "$SENT")" -ge "${WORK_AGENT_DM_DAILY_MAX:-10}" ]; then log "dm: daily cap reached, dropped $KEY"; exit 0; fi

TOOL="mcp__claude_ai_Slack__slack_send_message"
PROMPT="Call $TOOL exactly once with channel_id \"$TO\" and the message between the markers, unchanged. Call no other tool. Then reply with the single word DONE.
<<<MESSAGE
$TEXT
MESSAGE>>>"
OUT="$STATE/dm_last.json"
GUARD=()
if printf '%s\n' "$TOOL" > "$STATE/dm_allow.txt" &&
   guard_settings "$STATE/dm_settings.json" "$STATE/dm_allow.txt" "$STATE/tool_guard.log" 2>> "$STATE/dm_last.err"; then
  GUARD=(--settings "$STATE/dm_settings.json")
else
  # the alert matters most when something is broken (e.g. python3); the text is our own template
  log "dm: guard unavailable, sending $KEY with the tool allowlist only"
fi
DESK="$STATE/office/desks/secretary"; mkdir -p "$DESK"; cd "$DESK" || exit 1
"${CLAUDE_BIN:-claude}" -p "$PROMPT" --model "${WORK_AGENT_DM_MODEL:-haiku}" --output-format json --max-turns 3 \
  ${GUARD[@]+"${GUARD[@]}"} \
  --allowedTools "$TOOL" \
  --disallowedTools Bash Write Edit NotebookEdit WebFetch WebSearch Read Glob Grep Task \
    mcp__claude_ai_Gmail mcp__claude_ai_Google_Calendar mcp__claude_ai_Google_Drive mcp__claude_ai_Notion \
    mcp__claude_ai_Claude_Docs mcp__claude_ai_Plaud \
  > "$OUT" 2> "$STATE/dm_last.err" < /dev/null
rc=$?
python3 "$DIR/office.py" tidy "$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("session_id",""))
except Exception: print("")' "$OUT")" > /dev/null 2>&1 || true
ok=1
if [ $rc -eq 0 ]; then
  python3 -c "import json,sys;o=json.load(open(sys.argv[1]));sys.exit(0 if not o.get('is_error') and not o.get('permission_denials') else 3)" "$OUT" 2>/dev/null
  prc=$?
  if [ $prc -eq 0 ]; then ok=0
  # python3 itself unusable (the case the no-guard fallback exists for): read claude's compact JSON directly
  elif [ $prc -ne 3 ] && grep -q '"is_error":false' "$OUT" && grep -q '"permission_denials":\[\]' "$OUT"; then ok=0
  fi
fi
if [ $ok -eq 0 ]; then
  echo "$today $KEY" >> "$SENT"; log "dm: sent $KEY"
else
  log "dm: FAILED $KEY (rc=$rc); see state/dm_last.json"; exit 1
fi
