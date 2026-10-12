#!/usr/bin/env bash
# Keep Pixel Agents (local pixel-art view of Claude sessions) up during work hours.
# Started by launchd every hour on the hour; exits at once outside work hours or
# when a Pixel Agents server is already running. Stops at PIXEL_AGENTS_END (default 1815).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[ -f "$DIR/config.env" ] && . "$DIR/config.env"
. "$DIR/lib.sh"

VERSION="${PIXEL_AGENTS_VERSION:-1.4.1}"
PORT="${PIXEL_AGENTS_PORT:-17777}"
END="${PIXEL_AGENTS_END:-1815}"
STATE="${WORK_AGENT_STATE:-$DIR/state}"
PREFIX="$STATE/pixel"; PLOG="$STATE/pixel.log"; LOG="$STATE/poll.log"
CLI="$PREFIX/node_modules/pixel-agents/dist/cli.js"
log() { printf '%s %s\n' "$(kst '+%F %T')" "$*" >> "$LOG"; }

in_work_hours "${WORK_AGENT_START:-0900}" "$END" || exit 0
mkdir -p "$STATE"

# Pixel Agents keeps one server per user (~/.pixel-agents/server.json) and a new
# process attaches to a live one instead of binding PORT. Print that server's pid
# (only if it matches $1 when given) and save its tokened URL for the owner; never echo the URL.
save_url() {
  python3 - "$STATE/pixel_url.txt" "${1:-}" <<'PY2'
import json,os,sys
try: s=json.load(open(os.path.expanduser("~/.pixel-agents/server.json")))
except Exception: sys.exit(1)
pid=int(s.get("pid") or 0)
if not pid or not s.get("token") or (sys.argv[2] and str(pid)!=sys.argv[2]): sys.exit(1)
try: os.kill(pid,0)
except OSError: sys.exit(1)
fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
os.write(fd,f"http://127.0.0.1:{s['port']}/?token={s['token']}\n".encode()); os.close(fd)
print(pid)
PY2
}
if other="$(save_url)"; then exit 0; fi   # someone else's server is already up

if [ ! -f "$CLI" ] || ! grep -q "\"version\": \"$VERSION\"" "$PREFIX/node_modules/pixel-agents/package.json" 2>/dev/null; then
  npm install --prefix "$PREFIX" --no-save --silent "pixel-agents@$VERSION" >> "$PLOG" 2>&1 || { log "pixel: install failed"; exit 1; }
fi

end_epoch="$(python3 -c "
import datetime as d,sys
k=d.timezone(d.timedelta(hours=9)); n=d.datetime.now(k); e=sys.argv[1]
print(int(n.replace(hour=int(e[:2]),minute=int(e[2:]),second=0,microsecond=0).timestamp()))" "$END")"

pid=""; nap=""
stop_server() {
  [ -n "$pid" ] || return 0
  kill "$pid" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  kill -KILL "$pid" 2>/dev/null; pid=""
}
cleanup() { [ -n "$nap" ] && kill "$nap" 2>/dev/null; stop_server; rm -f "$STATE/pixel_url.txt"; }
trap cleanup EXIT
trap 'log "pixel: stopped by signal"; exit 0' INT TERM
# sleep in the background so a signal from launchd is handled at once
pause() { sleep "$1" & nap=$!; wait "$nap" 2>/dev/null; nap=""; }

restarts=0
while [ "$(date +%s)" -lt "$end_epoch" ]; do
  (cd "$DIR" && exec node "$CLI" --host 127.0.0.1 --port "$PORT") >> "$PLOG" 2>&1 &
  pid=$!
  for _ in $(seq 1 30); do pause 1; save_url "$pid" >/dev/null && break; done
  log "pixel: started on 127.0.0.1:$PORT (pid $pid)"
  while kill -0 "$pid" 2>/dev/null && [ "$(date +%s)" -lt "$end_epoch" ]; do pause 30; done
  kill -0 "$pid" 2>/dev/null && break
  pid=""; restarts=$((restarts+1)); log "pixel: exited unexpectedly (restart $restarts)"
  if [ "$restarts" -ge 3 ]; then
    "$DIR/slack_dm.sh" "pixel-down" "[업무 에이전트] Pixel Agents가 오늘 3번 꺼져서 재시작을 멈췄습니다($(kst +%H:%M)). 맥미니 state/pixel.log 를 확인하세요." || true
    exit 1
  fi
  pause 10
done
log "pixel: stopped (end of work hours)"
