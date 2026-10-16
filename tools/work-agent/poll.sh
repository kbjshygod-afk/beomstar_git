#!/usr/bin/env bash
# Work agent, stage 0: run `claude -p` every few minutes in business hours,
# collect new Slack requests / Plaud recordings, write a digest to inbox/.
# The reader run is read-only. Writes happen only in two pinned helpers:
# slack_dm.sh (fixed-template alerts to the owner) and, when WORK_AGENT_SLACK_DRAFTS=1,
# slack_drafts.py (unsent reply drafts in the source threads; nothing is sent).
# Checkpoint advances only after a valid result.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
CONFIG="${WORK_AGENT_CONFIG:-$DIR/config.env}"   # tests point this at a missing file
[ -f "$CONFIG" ] && . "$CONFIG"
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
SEEN_PLAUD="$( [ -s "$STATE/plaud_seen.txt" ] && tail -n 200 "$STATE/plaud_seen.txt" | paste -sd, - || true )"

PROMPT="$(cat "$DIR/prompt.md")

## 이번 실행 입력
- now: $NOW_ISO
- since: $SINCE_ISO
- channels: ${WORK_AGENT_CHANNELS:-}
- keywords: ${WORK_AGENT_KEYWORDS:-}
- seen_plaud_ids: ${SEEN_PLAUD:-}"

# 4. run the agent
RAW="$STATE/last_raw.json"; rm -f "$RAW"
# allowlist hook: the reader reads untrusted text, so any tool not in WORK_AGENT_ALLOWED_TOOLS is blocked,
# including built-ins that -p would otherwise run without a permission check
args=(-p "$PROMPT" --model "$MODEL" --output-format json --max-turns 30 --settings "$STATE/reader_settings.json")
[ -n "$ALLOWED" ] && args+=(--allowedTools $ALLOWED)
[ -n "$DISALLOWED" ] && args+=(--disallowedTools $DISALLOWED)
# a guard setup failure (e.g. python3 broken after a macOS update) must reach the FAIL count and alerts below;
# claude is not started without its guard
if ! { printf '%s\n' $ALLOWED > "$STATE/reader_allow.txt" &&
       guard_settings "$STATE/reader_settings.json" "$STATE/reader_allow.txt" "$STATE/tool_guard.log"; } 2> "$STATE/last.err"; then
  rc=1
elif ! (cd "$DIR" && "$CLAUDE_BIN" "${args[@]}") > "$RAW" 2> "$STATE/last.err"; then
  rc=1
else
  rc=0
fi

# 5. validate + write digest (python does the JSON work; exit 0 = valid result)
set +e
PYOUT="$(python3 - "$RAW" "$INBOX" "$STATE" "$NOW_ISO" <<'PY'
import json, re, sys, os
raw_path, inbox, state, now_iso = sys.argv[1:5]
try:
    outer = json.load(open(raw_path))
    if outer.get("is_error"): raise ValueError("claude reported is_error")
    text = outer.get("result", "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        res = json.loads(text)
    except ValueError:
        # the model sometimes writes a sentence (or a fence) before the JSON: take the last {"status": ...} object
        starts = [m.start() for m in re.finditer(r'\{\s*"status"\s*:', text)]
        if not starts: raise
        res = json.JSONDecoder().raw_decode(text[starts[-1]:])[0]
    items = res.get("items", [])
    assert isinstance(items, list) and res.get("status") == "ok"
except Exception as e:
    print(f"invalid:{e}"); sys.exit(2)

seen_path = os.path.join(state, "seen_ids.txt")
seen = set(open(seen_path).read().split()) if os.path.exists(seen_path) else set()
new = [i for i in items if i.get("id") and i["id"] not in seen]
order = {"urgent": 0, "normal": 1, "fyi": 2}
new.sort(key=lambda i: order.get(i.get("priority"), 3))

fname = "-"
if new:
    stamp = now_iso[:16].replace("-", "").replace(":", "").replace("T", "-")
    fname = f"{stamp}.md"
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
    open(os.path.join(inbox, fname), "w").write("\n".join(lines) + "\n")
    open(seen_path, "a").write("".join(i["id"] + "\n" for i in new))
if res.get("plaud_seen"):
    open(os.path.join(state, "plaud_seen.txt"), "a").write("".join(str(x) + "\n" for x in res["plaud_seen"]))
json.dump(new, open(os.path.join(state, "new_items.json"), "w"), ensure_ascii=False)
urgent = sum(1 for i in new if i.get("priority") == "urgent")
print(f"ok:{len(new)}:{urgent}:{len(res.get('errors', []))}:{fname}")
PY
)"
pyrc=$?
set -e

# 6. checkpoint / failure accounting
if [ "$rc" = "0" ] && [ "$pyrc" = "0" ]; then
  printf '%s' "$NOW_ISO" > "$STATE/last_ok_iso"; echo 0 > "$STATE/fail_count"; date +%s > "$STATE/heartbeat"
  IFS=: read -r _ n u e f <<< "$PYOUT"
  if [ "${n:-0}" -gt 0 ]; then
    log "ok: $n new item(s), $u urgent, $e error(s)"
    # stage 2a: leave unsent reply drafts in the source Slack threads (off unless WORK_AGENT_SLACK_DRAFTS=1)
    dnote=""
    if [ "${WORK_AGENT_SLACK_DRAFTS:-0}" = "1" ]; then
      DOUT="$(CLAUDE_BIN="$CLAUDE_BIN" WORK_AGENT_STATE="$STATE" \
        WORK_AGENT_DRAFT_TOOL="${WORK_AGENT_DRAFT_TOOL:-}" WORK_AGENT_DRAFT_MODEL="${WORK_AGENT_DRAFT_MODEL:-}" \
        WORK_AGENT_DRAFT_DAILY_MAX="${WORK_AGENT_DRAFT_DAILY_MAX:-}" WORK_AGENT_DRAFT_RUN_MAX="${WORK_AGENT_DRAFT_RUN_MAX:-}" \
        WORK_AGENT_DRAFT_TIMEOUT="${WORK_AGENT_DRAFT_TIMEOUT:-}" \
        python3 "$DIR/slack_drafts.py" "$STATE/new_items.json" "$INBOX/$f" 2>> "$STATE/drafts.err")" || DOUT="drafts:error"
      log "$DOUT"
      case "$DOUT" in
        drafts:*:*:*) IFS=: read -r _ dc _ _ <<< "$DOUT"; if [ "${dc:-0}" -gt 0 ]; then dnote=", 슬랙 초안 ${dc}건"; fi ;;
      esac
    fi
    notify "업무 에이전트" "새 항목 ${n}건 (긴급 ${u}건${dnote})"
    if [ "${u:-0}" -gt 0 ]; then
      "$DIR/slack_dm.sh" "urgent:$f" "[업무 에이전트] 긴급 ${u}건 (새 항목 ${n}건${dnote}, $(kst +%H:%M) 확인분). 맥미니 inbox/$f 을 확인하세요." || true
    fi
  else
    log "ok: nothing new"
  fi
else
  f=$(( $(cat "$STATE/fail_count" 2>/dev/null || echo 0) + 1 )); echo "$f" > "$STATE/fail_count"
  log "FAIL($f): claude rc=$rc, parse rc=$pyrc ($PYOUT); see state/last.err, state/last_raw.json"
  if [ "$f" -ge 3 ]; then notify "업무 에이전트 이상" "연속 ${f}회 실패. 로그 확인 필요"; fi
  if [ "$f" -eq 3 ]; then
    "$DIR/slack_dm.sh" "fail3:$(kst +%H%M)" "[업무 에이전트] 폴링이 연속 3회 실패했습니다($(kst +%H:%M)). 맥미니 state/poll.log 와 state/last.err 를 확인하세요." || true
  fi
  exit 1
fi
