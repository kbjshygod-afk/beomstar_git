#!/usr/bin/env python3
"""The owner's own checks on the office, from local files only (no board, no model, no network). Python 3.9.

    office.py doctor                       is the Mac mini healthy, and what waits on the owner?
                                           (exit 1 when something is broken)
    office.py report [days]                each staff role's adoption rate and outcomes over the last N days
                                           (default 14), and the time log against its first week (the baseline)
    office.py timelog <업무> <분> [메모]   record minutes spent by hand on one of the five tracked tasks

Every finding names the lesson of the 관제실 수습 과정 game it comes from, so the owner can look the rule up.
"""
import collections
import datetime as dt
import os
import re
import shutil
import sys

import office

OK, WARN, BAD = "✔", "▲", "✖"
TASKS = ("요청정리", "공지", "원가검산", "게이트점검", "주간보고")  # the tracked tasks of the v1 DoD (TEAM_PLAN.md)
SOURCES = {  # roster precheck -> the config line it reads, how many ids, an example
    "cost": ("WORK_AGENT_COST_SOURCES", 2, "겨울2차=<원가표 ID>,<기획 ID>"),
    "notice": ("WORK_AGENT_NOTICE_SOURCES", 5, "겨울2차=<기획 ID>,<레시피 ID>,<규격 ID>"),
}
HINTS = [  # words in a staff error -> what the owner does about it
    ("설정 없음", "config.env에 오류 문구에 나온 설정을 넣기"),
    ("형식 오류", "config.env 형식은 시즌=파일ID,파일ID (ID는 Drive 주소 /d/ 뒤 값)"),
    ("claude 실행 불가", "config.env의 CLAUDE_BIN 경로 확인(which claude)"),
    ("claude 오류", "맥미니에서 claude를 실행해 로그인 상태 확인"),
    ("시간 초과", "다음 폴링에 다시 돈다. 반복되면 WORK_AGENT_STAFF_TIMEOUT 늘리기"),
    ("받기 실패", "Drive 커넥터 로그인과 파일 공유 권한 확인"),
    ("지시문 의심", "그 자료를 직접 열어 확인(자료 속 지시는 따르지 않는다)"),
]


def kst(s):
    d = office.parse_any(s) if s else None
    return d.astimezone(office.KST) if d else None


def hm(d):
    return d.strftime("%m-%d %H:%M")


# ---------------------------------------------------------------- doctor

def check_config(cfg):
    out = []
    if os.environ.get("WORK_AGENT_OFFICE") != "1":
        out.append((WARN, "설정", "사무실이 꺼져 있음(poll.sh가 office를 돌리지 않음)", "config.env에 WORK_AGENT_OFFICE=1", "교육-01"))
    if not cfg.board_url:
        out.append((BAD, "설정", "전광판 주소 없음", "config.env에 WORK_AGENT_BOARD_URL=<전광판 주소>", "교육-01"))
    if not shutil.which(cfg.claude):
        out.append((BAD, "설정", "claude를 찾을 수 없음(%s)" % cfg.claude, "which claude 결과를 config.env의 CLAUDE_BIN에", "교육-04"))
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # with a key, claude bills the API instead of the subscription, and a run in bare mode (announced as the future
        # default of -p) would skip the settings hooks every guard here relies on; without one it fails to log in instead
        out.append((WARN, "설정", "ANTHROPIC_API_KEY가 설정돼 있음: 구독 대신 API 요금으로 돌고, bare 모드면 훅 없이 돌 수 있음",
                    "config.env와 셸 설정에서 ANTHROPIC_API_KEY 지우기", "교육-05"))
    no_folder = []
    for r in cfg.roster.get("roles", []):
        if not r.get("enabled"):
            continue
        if r.get("precheck") in SOURCES:
            var, n, example = SOURCES[r["precheck"]]
            got, bad = office.season_sources(var, n)
            if bad:
                out.append((BAD, "설정", "%s 자료 설정 %d개 형식 오류" % (r.get("title", r["role"]), bad),
                            '%s="%s" (ID는 Drive 주소 /d/ 뒤 값)' % (var, example), "교육-04"))
            elif not got:
                out.append((WARN, "설정", "%s 자료 설정 없음: 이 직원은 쉬고 있음" % r.get("title", r["role"]),
                            'config.env에 %s="%s"' % (var, example), "교육-04"))
        if "drive_draft" in r.get("proposal_kinds", []) and not cfg.draft_folder:
            no_folder.append(r.get("title", r["role"]))
    if no_folder:
        out.append((WARN, "설정", "초안 폴더 없음: %s의 Drive 초안 저장이 꺼져 있음" % "·".join(no_folder),
                    "bash tests/e2e_cost.sh가 PASS substitute면 config.env에 WORK_AGENT_DRIVE_DRAFT_FOLDER", "교육-04"))
    return out or [(OK, "설정", "사무실·전광판·claude·자료 설정 정상", "", "")]


def tail(path, n=60):
    try:
        with open(path) as f:
            return list(collections.deque(f, n))
    except IOError:
        return None


def check_poll(cfg, t):
    base = cfg.state if os.path.exists(os.path.join(cfg.state, "poll.log")) else os.path.join(office.DIR, "state")
    lines = tail(os.path.join(base, "poll.log"))
    if not lines:
        return [(WARN, "폴링", "폴링 기록 없음(state/poll.log)", "WORK_AGENT_FORCE=1 bash poll.sh로 한 번 돌려 보기", "교육-04")]
    rows = []
    for ln in lines:
        m = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$", ln.rstrip("\n"))
        if m:
            rows.append((dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=office.KST), m.group(2)))
    if not rows:
        return [(WARN, "폴링", "폴링 기록을 읽지 못함", "state/poll.log 확인", "교육-04")]
    out = []
    last, msg = rows[-1]
    due = office.next_heartbeat(cfg, last)
    if t > due + dt.timedelta(minutes=20):
        out.append((BAD, "폴링", "폴링이 멈춤: 마지막 기록 %s, 예정이던 시각 %s" % (hm(last), hm(due)),
                    "맥미니 잠자기와 claude 로그인(claude 실행) 확인, state/last.err 보기", "교육-04"))
    fails = 0
    for _, m in reversed(rows):
        if m.startswith("FAIL"):
            fails += 1
        elif m.startswith("ok:"):
            break
    if fails:
        out.append((BAD if fails >= 3 else WARN, "폴링", "최근 폴링 %d회 연속 실패" % fails,
                    "state/last.err와 state/last_raw.jsonl 확인", "교육-04"))
    office_lines = [m for _, m in rows if "office:" in m]
    if office_lines:
        bad = [x for x in re.findall(r"(?:pull|push)=(\S+)", office_lines[-1]) if not x.startswith(("ok", "no-url"))]
        if bad or "office: error" in office_lines[-1]:
            out.append((WARN, "폴링", "전광판 주고받기 실패: %s" % office_lines[-1][:120],
                        "claude 로그인과 전광판 주소 확인, 다음 폴링에도 같으면 state/office.err", "교육-04"))
    return out or [(OK, "폴링", "마지막 %s · %s" % (hm(last), msg[:60]), "", "")]


def check_stop(cfg):
    out = []
    if os.path.exists(os.path.join(cfg.state, "STOP")):
        out.append((WARN, "정지", "맥미니 정지 파일이 있음: 직원 실행·실행기가 멈춰 있음",
                    "다시 시작은 rm state/STOP (재개하면 보류된 승인 건이 실행되니 결재 대기부터 정리)", "교육-05"))
    if cfg.meta.get("stop"):
        out.append((WARN, "정지", "전광판 전체 정지 중(마지막으로 읽은 전광판 기준)", "전광판에서 정지 해제(결재 대기부터 정리)", "교육-05"))
    return out


def check_staff(cfg, t):
    out = []
    for r in cfg.roster.get("roles", []):
        if not r.get("enabled") or not r.get("prompt"):
            continue
        role, name = r["role"], "%s %s" % (r.get("emoji", ""), r.get("title", r["role"]))
        st = office.read_json(os.path.join(cfg.office, "staff", role + ".json"))
        if not isinstance(st, dict):
            out.append((WARN, "직원", "%s: 아직 한 번도 돌지 않음" % name, "bash office.sh staff %s" % role, "교육-01"))
            continue
        errors = [office.norm(e) for e in st.get("errors") or [] if office.norm(e)]
        if st.get("status") == "blocked":
            todo = next((h for w, h in HINTS if any(w in e for e in errors)), "bash office.sh staff %s로 다시 돌려 확인" % role)
            out.append((BAD, "직원", "%s 막힘: %s" % (name, " / ".join(errors[:2]) or "이유 없음"), todo, "교육-04"))
            continue
        if errors:
            out.append((WARN, "직원", "%s: 확인하지 못한 것 %d건 (%s)" % (name, len(errors), errors[0][:60]), "", "교육-04"))
        daily = (r.get("schedule") or {}).get("daily_at")
        if daily and office.is_workday(cfg, t) and int(t.strftime("%H%M")) >= int(daily) + 100:
            ran = office.read_json(office.daily_marker(cfg, role), {}).get("day") if r.get("orders") else \
                (kst(st.get("last_run")) or t - dt.timedelta(days=9)).strftime("%Y-%m-%d")
            if ran != t.strftime("%Y-%m-%d") and not os.path.exists(os.path.join(cfg.state, "STOP")) and not cfg.meta.get("stop"):
                out.append((WARN, "직원", "%s: 오늘 %s:%s 예정인데 아직 안 돎" % (name, daily[:2], daily[2:]),
                            "poll.log 확인, 또는 bash office.sh staff %s" % role, "교육-01"))
    return out


def check_board(cfg, t):
    props = office.load_proposals(cfg).values()
    waiting = [p for p in props if p.get("local_status") in ("proposed", "pushed") and not p.get("hold")]
    held = [p for p in props if p.get("hold") and p.get("local_status") in ("proposed", "pushed")]
    soon = [p for p in waiting if p.get("local_status") == "pushed" and kst(p.get("expires"))
            and kst(p["expires"]) - t < dt.timedelta(hours=12)]
    unsent = [p for p in waiting if p.get("local_status") == "proposed" and kst(p.get("created"))
              and t - kst(p["created"]) > dt.timedelta(hours=1)]
    failed = [p for p in props if p.get("local_status") == "failed" and kst(p.get("created"))
              and t - kst(p["created"]) < dt.timedelta(days=7)]
    out = []
    if soon:
        out.append((WARN, "결재", "12시간 안에 만료되는 결재 건 %d건: %s" % (len(soon), soon[0].get("title", "")[:50]),
                    "전광판에서 승인하거나 메모와 함께 반려", "교육-02"))
    if unsent:
        out.append((WARN, "결재", "전광판에 아직 못 올린 제안 %d건" % len(unsent), "poll.log의 push= 결과 확인", "교육-04"))
    for p in held[:3]:
        out.append((WARN, "결재", "보류: %s — %s" % (p.get("title", "")[:50], p["hold"]), "정지 해제나 다음 날 상한이 풀리면 실행됨", "교육-02"))
    for p in failed[:3]:
        out.append((WARN, "결재", "실패: %s — %s" % (p.get("title", "")[:50], (p.get("report") or {}).get("result", "")[:60]),
                    "state/office/office.log의 실행 거부·실행 실패 줄 확인", "교육-04"))
    used = office.exec_count_today(cfg, t)
    if used >= cfg.daily_exec_max:
        out.append((WARN, "결재", "오늘 실행 상한 도달(%d/%d): 남은 승인 건은 내일 첫 폴링에" % (used, cfg.daily_exec_max), "", "교육-02"))
    return out or [(OK, "결재", "결재 대기 %d건 · 오늘 실행 %d/%d" % (len(waiting), used, cfg.daily_exec_max), "", "")]


def check_orders(cfg, t):
    out = []
    for r in cfg.roster.get("roles", []):
        if not r.get("orders") or not r.get("enabled"):
            continue
        waiting = office.pending_orders(cfg, r["role"])
        if not waiting:
            continue
        old = kst(waiting[0].get("created"))
        if any(int(o.get("attempts", 0)) for o in waiting):
            out.append((WARN, "요청", "%s 요청이 한 번 실패해 다음 폴링에 다시 시도함" % r.get("title", r["role"]), "", "교육-03"))
        if old and t - old > dt.timedelta(hours=1) and office.is_workday(cfg, t):
            out.append((WARN, "요청", "%s 요청 %d건이 1시간 넘게 대기" % (r.get("title", r["role"]), len(waiting)),
                        "bash office.sh staff %s" % r["role"], "교육-03"))
        elif not out:
            out.append((OK, "요청", "%s 요청 %d건 대기(다음 폴링에 처리)" % (r.get("title", r["role"]), len(waiting)), "", ""))
    return out


def cmd_doctor(cfg, t):
    found = (check_config(cfg) + check_poll(cfg, t) + check_stop(cfg) + check_staff(cfg, t) + check_board(cfg, t)
             + check_orders(cfg, t))
    print("사무실 점검 · %s(%s) %s KST%s" % (t.strftime("%Y-%m-%d"), "월화수목금토일"[t.weekday()], t.strftime("%H:%M"),
                                         " · 팀 %s" % cfg.team if cfg.team else ""))
    for sev, area, text, todo, lesson in found:
        print("%s %s  %s" % (sev, area, text))
        if todo or lesson:
            print("       → %s%s" % (todo, ("  (%s)" % lesson) if lesson else ""))
    n = collections.Counter(f[0] for f in found)
    print("정상 %d · 확인 %d · 문제 %d" % (n[OK], n[WARN], n[BAD]))
    return 1 if n[BAD] else 0


# ---------------------------------------------------------------- report

def outcome(p):
    """approved / rejected / expired / waiting for one local proposal (an approval on hold is still an approval)."""
    s = p.get("local_status")
    if s in ("executed", "failed") or p.get("hold"):
        return "approved"
    return s if s in ("rejected", "expired") else "waiting"


def rate(c):
    decided = c["approved"] + c["rejected"] + c["expired"]
    return (c["approved"] / decided, decided) if decided else (None, 0)


def pct(r):
    return "-" if r is None else "%d%%" % round(r * 100)


def cmd_report(cfg, t, days):
    since = t - dt.timedelta(days=days)
    props = [p for p in office.load_proposals(cfg).values() if p.get("role") and kst(p.get("created")) and kst(p["created"]) >= since]
    print("직원 성적표 · 최근 %d일 (%s~%s)" % (days, since.strftime("%m/%d"), t.strftime("%m/%d")))
    roles = sorted({p["role"] for p in props}, key=lambda r: (cfg.role(r) or {}).get("order", 99))
    if not roles:
        print("  이 기간에 올라온 제안이 없음")
    for role in roles:
        mine = [p for p in props if p["role"] == role]
        c = collections.Counter(outcome(p) for p in mine)
        r, decided = rate(c)
        rc = cfg.role(role) or {}
        print("%s %s  올림 %d · 승인 %d · 반려 %d · 만료 %d · 대기 %d · 채택률 %s"
              % (rc.get("emoji", ""), rc.get("title", role), len(mine), c["approved"], c["rejected"], c["expired"], c["waiting"], pct(r)))
        weeks = []
        if days >= 14:
            for lo, hi in ((t - dt.timedelta(days=14), t - dt.timedelta(days=7)), (t - dt.timedelta(days=7), t)):
                weeks.append(rate(collections.Counter(outcome(p) for p in mine if lo <= kst(p["created"]) < hi)))
        if decided < 4:
            verdict = "판단 보류(결정된 제안 4건 미만)"
        elif weeks and all(w[0] is not None and w[1] >= 2 and w[0] < 0.5 for w in weeks):
            verdict = "%s 2주 연속 50%% 미만 (지난주 %s · 이번 주 %s) → 지시문 고치기·합치기·끄기 검토 (교육-06)" % (BAD, pct(weeks[0][0]), pct(weeks[1][0]))
        elif r < 0.5:
            verdict = "%s 50%% 미만 → 반려 메모로 이유를 남기기 (교육-02)" % WARN
        elif r >= 0.7:
            verdict = "%s v1 목표(70%%) 이상" % OK
        else:
            verdict = "보통 (v1 목표 70%)"
        print("       %s" % verdict)
    done = [p for p in props if p.get("local_status") in ("executed", "failed")]
    if done:
        fails = collections.Counter((p.get("report") or {}).get("result", "")[:40] for p in done if p["local_status"] == "failed")
        print("실행: 완료 %d · 실패 %d%s" % (len(done) - sum(fails.values()), sum(fails.values()),
                                       (" (" + ", ".join("%s %d" % kv for kv in fails.most_common(3)) + ")") if fails else ""))
    print_timelog(cfg, t)
    return 0


def print_timelog(cfg, t):
    rows = []
    try:
        with open(os.path.join(cfg.office, "timelog.tsv")) as f:
            for ln in f:
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[1] in TASKS and parts[2].isdigit():
                    rows.append((dt.datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=office.KST), parts[1], int(parts[2])))
    except (IOError, ValueError):
        pass
    print("업무 시간 · 기준선(업무별 첫 기록부터 7일) 대비, v1 목표는 40% 감소")
    today = t.replace(hour=0, minute=0, second=0, microsecond=0)
    for task in TASKS:
        mine = [r for r in rows if r[1] == task]
        if not mine:
            print("  %s: 기록 없음 → bash office.sh timelog %s <분>" % (task, task))
            continue
        start = min(r[0] for r in mine)
        base = [r[2] for r in mine if r[0] < start + dt.timedelta(days=7)]
        recent = [r[2] for r in mine if r[0] >= start + dt.timedelta(days=7) and r[0] > today - dt.timedelta(days=7)]
        b = sum(base) / len(base)
        if not recent:
            print("  %s: 기준선 %d분/건 (%d건) · 최근 7일 비교 기록 없음" % (task, round(b), len(base)))
            continue
        a = sum(recent) / len(recent)
        cut = (b - a) / b if b else 0
        print("  %s: 기준선 %d분/건 (%d건) → 최근 7일 %d분/건 (%d건) %s%d%% %s"
              % (task, round(b), len(base), round(a), len(recent), "−" if cut >= 0 else "+", abs(round(cut * 100)),
                 OK if cut >= 0.4 else WARN))


# ---------------------------------------------------------------- timelog

def cmd_timelog(cfg, t, args):
    if len(args) < 2 or args[0] not in TASKS or not args[1].isdigit() or not 1 <= int(args[1]) <= 600:
        sys.stderr.write("사용법: office.sh timelog <업무> <분 1~600> [메모]\n업무: %s\n" % " · ".join(TASKS))
        return 64
    memo = re.sub(r"\s+", " ", office.norm(" ".join(args[2:])))[:200]
    with open(os.path.join(cfg.office, "timelog.tsv"), "a") as f:
        f.write("%s\t%s\t%d\t%s\n" % (t.strftime("%Y-%m-%d"), args[0], int(args[1]), memo))
    print("timelog: %s %s분 기록 (%s)" % (args[0], args[1], t.strftime("%m/%d")))
    return 0


def main(cfg, cmd, args):
    t = office.now()
    if cmd == "doctor":
        return cmd_doctor(cfg, t)
    if cmd == "report":
        if args and not (args[0].isdigit() and 1 <= int(args[0]) <= 90):
            sys.stderr.write("사용법: office.sh report [일수 1~90]\n")
            return 64
        return cmd_report(cfg, t, int(args[0]) if args else 14)
    return cmd_timelog(cfg, t, args)
