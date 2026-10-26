#!/usr/bin/env bash
# Office runner: exports config.env for office.py and runs it.
#   office.sh cycle          (poll.sh calls this every cycle when WORK_AGENT_OFFICE=1)
#   office.sh staff gate     (run one staff role now)
#   office.sh status
#   office.sh teams          (every enabled team in teams.json, one after another — what poll.sh runs)
#   office.sh team <id> ...  (any command for one team)
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${WORK_AGENT_CONFIG:-$DIR/config.env}"
set -a
# shellcheck disable=SC1090
[ -f "$CONFIG" ] && . "$CONFIG"
set +a
exec python3 "$DIR/office.py" "$@"
