#!/usr/bin/env bash
# Work agent, stage 0: run `claude -p` every few minutes in business hours,
# collect new Slack requests / Plaud recordings, write a digest to inbox/.
# Read-only by design (the only outbound action is slack_dm.sh, which sends
# fixed-template alerts to the owner). Checkpoint advances only after a valid result.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[ -f "$DIR/config.env" ] && . "$DIR/config.env"
. "$DIR/lib.sh"

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MODEL="${WORK_AGENT_MODEL:-sonnet}"
START="${WORK_AGENT_START:-0900}"
END="${WORK_AGENT_END:-1800}"
HOLIDAYS="${WORK_AGENT_HOLIDAYS:-$DIR/holidays_kr.txt}"
STATE="${WORK_AGENT_STATE:-$DIR/state}"
INBOX="${WORK_AGENT_INBOX:-$DIR/inbox}"
ALLOWED="${WORK_AGENT_ALLOWED_TOOLS:-}"
DISALLOWED="${WORK_AGENT_DISALLOWED_TOOLS:-}"
LOCK="$STATE/lock.d"
LOG="$STATE/poll.log"

mkdir -p "$STATE" "$INBOX"
log() { printf '%s %s\n' "$(TZ=Asia/Seoul date '+%F %T')" "$*" >> "$LOG"; }
notify() { command -v osascript >/dev/null 2>&1 && osascript -e "display notification \"$2\" with title \"$1\"" >/dev/null 2>&1 || true; }

# 1. business-hours gate (KST, Mon-Fri, START..END inclusive, minus listed holidays).
#    WORK_AGENT_FORCE=1 skips it.
if [ "${WORK_AGENT_FORCE:-0}" != "1" ]; then
  in_work_hours "$START" "$END" || exit 0
  year="$(kst +%F)"; year="${year:0:4}"
  if ! { [ -f "$HOLIDAYS" ] && grep -q "^$year-" "$HOLIDAYS"; }; then
    log "warn: no holidays listed for $year in $(basename "$HOLIDAYS"); running anyway"
  fi
fi

# 2. single instance (mkdir is atomic on macOS too); drop locks older than 20 min
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then rmdir "$LOCK" 2>/dev/null || true; fi
mkdir "$LOCK" 2>/dev/null || { log "skip: previous run still active"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# 3. inputs for this run
NOW_ISO="$(TZ=Asia/Seoul date '+%Y-%m-%dT%H:%M:%S+09:00')"
if [ -s "$STATE/last_ok_iso" ]; then SINCE_ISO="$(cat "$STATE/last_ok_iso")"
else SINCE_ISO="$(python3 -c "import datetime as d;print((d.datetime.now(d.timezone(d.timedelta(hours=9)))-d.timedelta(minutes=60)).isoformat(timespec='seconds'))")"; fi
SINCE_UNIX="$(python3 -c "import datetime,sys;print(int(datetime.datetime.fromisoformat(sys.argv[1]).timestamp()))" "$SINCE_ISO")"
OWNER_ID="${WORK_AGENT_OWNER_ID:-${WORK_AGENT_SLACK_DM_USER:-}}"
SEEN_PLAUD="$( [ -s "$STATE/plaud_seen.txt" ] && tail -n 200 "$STATE/plaud_seen.txt" | paste -sd, - || true )"

PROMPT="$(cat "$DIR/prompt.md")

## 이번 실행 입력
- now: $NOW_ISO
- since: $SINCE_ISO
- since_unix: $SINCE_UNIX
- owner_id: ${OWNER_ID:-[입력 필요]}
- channels: ${WORK_AGENT_CHANNELS:-}
- keywords: ${WORK_AGENT_KEYWORDS:-}
- seen_plaud_ids: ${SEEN_PLAUD:-}"

# 4. run the agent
# stream-json keeps every tool call, so step 5 can verify the DM lookup really ran.
RAW="$STATE/last_raw.jsonl"; rm -f "$RAW"
args=(-p "$PROMPT" --model "$MODEL" --output-format stream-json --verbose --max-turns 30)
[ -n "$ALLOWED" ] && args+=(--allowedTools $ALLOWED)
[ -n "$DISALLOWED" ] && args+=(--disallowedTools $DISALLOWED)
if ! (cd "$DIR" && "$CLAUDE_BIN" "${args[@]}") > "$RAW" 2> "$STATE/last.err"; then
  rc=1
else
  rc=0
fi

# 5. validate + write digest (python does the JSON work; exit 0 = valid result)
set +e
PYOUT="$(python3 - "$RAW" "$INBOX" "$STATE" "$NOW_ISO" <<'PY'
import json, re, sys, os
raw_path, inbox, state, now_iso = sys.argv[1:5]

def dm_checked(events):
    # True when at least one DM-only Slack lookup returned without a tool error.
    # (A `to:` search finds no DMs, so it does not count.)
    ids = set()
    for ev in events:
        if ev.get("type") != "assistant": continue
        for b in ev.get("message", {}).get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use": continue
            name, inp = b.get("name", ""), b.get("input") or {}
            types = {t.strip() for t in str(inp.get("channel_types", "")).split(",") if t.strip()}
            if name.endswith("slack_search_public_and_private") and (
                    "is:dm" in str(inp.get("filters", "")) or (types and types <= {"im", "mpim"})):
                ids.add(b.get("id"))
            elif name.endswith("slack_read_channel") and str(inp.get("channel_id", "")).startswith(("D", "U")):
                ids.add(b.get("id"))
    for ev in events:
        if ev.get("type") != "user": continue
        content = ev.get("message", {}).get("content")
        if not isinstance(content, list): continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in ids and not b.get("is_error"):
                return True
    return False

try:
    events = []
    for line in open(raw_path):
        try: events.append(json.loads(line))
        except ValueError: pass
    outer = [e for e in events if e.get("type") == "result"][-1]
    if outer.get("is_error"): raise ValueError("claude reported is_error")
    text = outer.get("result", "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    res = json.loads(text)
    items = res.get("items", [])
    assert isinstance(items, list) and res.get("status") == "ok"
    if not dm_checked(events): raise ValueError("no successful Slack DM lookup (is:dm)")
except Exception as e:
    print(f"invalid:{e}"); sys.exit(2)

seen_path = os.path.join(state, "seen_ids.txt")
seen = set(open(seen_path).read().split()) if os.path.exists(seen_path) else set()
new = [i for i in items if i.get("id") and i["id"] not in seen]
order = {"urgent": 0, "normal": 1, "fyi": 2}
new.sort(key=lambda i: order.get(i.get("priority"), 3))

if new:
    stamp = now_iso[:16].replace("-", "").replace(":", "").replace("T", "-")
    lines = [f"# 업무 수신함 {now_iso}", ""]
    for i in new:
        lines += [f"## [{i.get('priority','?')}] {i.get('from','')} — {i.get('summary','')}",
                  f"- 출처: {i.get('source')} ({i.get('id')})",
                  f"- 대표님 할 일: {i.get('action','')}",
                  f"- 기한: {i.get('due','[입력 필요]')}"]
        if i.get("link"): lines.append(f"- 링크: {i['link']}")
        if i.get("flag"): lines.append(f"- ⚠ 주의: {i['flag']}")
        if i.get("draft"): lines += ["- 답변 초안:", "  > " + i["draft"].replace("\n", "\n  > ")]
        lines.append("")
    if res.get("errors"):
        lines += ["## 확인하지 못한 것"] + [f"- {e}" for e in res["errors"]]
    if res.get("notes"):
        lines += ([""] if res.get("errors") else []) + ["## 참고"] + [f"- {e}" for e in res["notes"]]
    open(os.path.join(inbox, f"{stamp}.md"), "w").write("\n".join(lines) + "\n")
    open(seen_path, "a").write("".join(i["id"] + "\n" for i in new))
if res.get("plaud_seen"):
    open(os.path.join(state, "plaud_seen.txt"), "a").write("".join(str(x) + "\n" for x in res["plaud_seen"]))
urgent = sum(1 for i in new if i.get("priority") == "urgent")
print(f"ok:{len(new)}:{urgent}:{len(res.get('errors', []))}")
PY
)"
pyrc=$?
set -e

# 6. checkpoint / failure accounting
if [ "$rc" = "0" ] && [ "$pyrc" = "0" ]; then
  printf '%s' "$NOW_ISO" > "$STATE/last_ok_iso"; echo 0 > "$STATE/fail_count"; date +%s > "$STATE/heartbeat"
  IFS=: read -r _ n u e <<< "$PYOUT"
  if [ "${n:-0}" -gt 0 ]; then
    log "ok: $n new item(s), $u urgent, $e error(s)"
    notify "업무 에이전트" "새 항목 ${n}건 (긴급 ${u}건)"
    if [ "${u:-0}" -gt 0 ]; then
      f="${NOW_ISO:0:16}"; f="${f//-/}"; f="${f//:/}"; f="${f/T/-}.md"
      "$DIR/slack_dm.sh" "urgent:$f" "[업무 에이전트] 긴급 ${u}건 (새 항목 ${n}건, $(kst +%H:%M) 확인분). 맥미니 inbox/$f 을 확인하세요." || true
    fi
  elif [ "${e:-0}" -gt 0 ]; then
    log "ok: nothing new, $e error(s)"
  else
    log "ok: nothing new"
  fi
else
  f=$(( $(cat "$STATE/fail_count" 2>/dev/null || echo 0) + 1 )); echo "$f" > "$STATE/fail_count"
  log "FAIL($f): claude rc=$rc, parse rc=$pyrc ($PYOUT); see state/last.err, state/last_raw.jsonl"
  if [ "$f" -ge 3 ]; then notify "업무 에이전트 이상" "연속 ${f}회 실패. 로그 확인 필요"; fi
  if [ "$f" -eq 3 ]; then
    "$DIR/slack_dm.sh" "fail3:$(kst +%H%M)" "[업무 에이전트] 폴링이 연속 3회 실패했습니다($(kst +%H:%M)). 맥미니 state/poll.log 와 state/last.err 를 확인하세요." || true
  fi
  exit 1
fi
