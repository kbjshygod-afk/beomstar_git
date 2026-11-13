# Shared helpers for poll.sh / pixel.sh / slack_dm.sh. Source after config.env.
# shellcheck shell=bash

kst() { TZ=Asia/Seoul date "$@"; }

# 0 when now is a work slot: Mon-Fri, START..END inclusive (HHMM, KST), not in the holiday file.
in_work_hours() {
  local start="${1:-${WORK_AGENT_START:-0900}}" end="${2:-${WORK_AGENT_END:-1800}}"
  local hol="${WORK_AGENT_HOLIDAYS:-$DIR/holidays_kr.txt}"
  local dow hm today
  dow="$(kst +%u)"; hm=$((10#$(kst +%H%M))); today="$(kst +%F)"
  [ "$dow" -le 5 ] || return 1
  [ "$hm" -ge $((10#$start)) ] && [ "$hm" -le $((10#$end)) ] || return 1
  if [ -f "$hol" ] && grep -q "^$today" "$hol"; then return 1; fi
  return 0
}

# Write a claude --settings file ($1) whose PreToolUse hook (tool_guard.py) allows only ToolSearch and
# the tools listed in $2, logging blocks to $3. onFailure block: a crashed or missing guard blocks too.
guard_settings() {
  python3 - "$1" "$DIR/tool_guard.py" "$2" "$3" <<'GUARD_PY'
import json, shlex, sys
out, guard, allow, audit = sys.argv[1:5]
cmd = " ".join(shlex.quote(x) for x in (sys.executable, guard, allow, audit))
with open(out, "w") as f:
    json.dump({"disableAllHooks": False, "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": cmd, "onFailure": "block"}]}]}}, f)
GUARD_PY
}
