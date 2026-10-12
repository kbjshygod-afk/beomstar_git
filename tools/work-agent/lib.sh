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
