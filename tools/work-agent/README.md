# 업무 에이전트 — 1단계 가교 (맥미니 5분 폴링, 읽기 전용)

**DoD**: 업무시간(월~금 09:00~18:00 KST, 공휴일 제외)에 슬랙에 새 요청이 올라오거나 플라우드 전사가 끝나면 30분 안에 `inbox/`에 담당·기한·답변 초안이 정리되고 맥미니에 알림이 뜬다. 같은 항목은 두 번 처리하지 않는다. 연속 3회 실패하면 알림이 온다.

이 단계는 **읽기 전용**입니다. 메시지·메일 발송, 일정 변경, 파일 수정은 도구 수준에서 막혀 있습니다. 슬랙·플라우드 텍스트는 데이터로만 취급하고, 안에 든 지시문은 따르지 않습니다.

## 파일
| 파일 | 역할 |
|---|---|
| `poll.sh` | 5분마다 실행되는 래퍼. 업무시간 확인 → 중복 실행 방지 → `claude -p` 호출 → 결과 검증 → `inbox/` 기록. 결과가 유효할 때만 체크포인트를 옮김 |
| `prompt.md` | 에이전트 지시문(규칙·절차·출력 형식) |
| `config.example.env` | 설정 예시 → `config.env`로 복사 |
| `com.beomstar.work-agent.plist.template` | launchd 자동 실행 설정 |
| `state/`, `inbox/` | 실행 기록과 결과(git에 올라가지 않음) |

## 맥미니 설치 순서 (대표님이 직접 할 단계는 ★)
1. ★ Claude Code CLI 설치 후 로그인 (`claude` 실행 → 로그인). 슬랙·플라우드 커넥터가 같은 계정에 연결돼 있어야 합니다.
2. 이 저장소를 맥미니에 받습니다. `cd tools/work-agent && cp config.example.env config.env`
3. **커넥터 확인(가장 중요)**: 터미널에서 `claude` → `/mcp` 로 슬랙·플라우드 도구 이름을 확인하고, 다르면 `config.env`의 `WORK_AGENT_ALLOWED_TOOLS`를 맞춥니다. 헤드리스(`-p`)에서 커넥터가 실제로 호출되는지 아래 4번으로 확인합니다.
4. 수동 1회 시험: `WORK_AGENT_FORCE=1 bash poll.sh` → `state/poll.log` 마지막 줄이 `ok:`인지, `inbox/`에 파일이 생겼는지 확인. `FAIL`이면 `state/last.err`, `state/last_raw.json`을 봅니다.
5. `config.env`에 `CLAUDE_BIN=/절대경로/claude` 추가 (`which claude`로 확인; launchd는 PATH가 짧습니다).
6. ★ 자동 실행 등록:
   ```
   sed "s|__DIR__|$PWD|g; s|__HOME__|$HOME|g" com.beomstar.work-agent.plist.template > ~/Library/LaunchAgents/com.beomstar.work-agent.plist
   launchctl load ~/Library/LaunchAgents/com.beomstar.work-agent.plist
   ```
7. ★ 시스템 설정 → 에너지: 자동 잠자기 방지, 정전 후 자동 시작 켜기. 맥미니가 잠들면 폴링이 멈춥니다.

## 완료 증명 (한 주 시범 후 판정)
- 슬랙에 테스트 메시지 5건(DM·멘션·키워드 각각)을 보내 `inbox/` 반영까지 걸린 시간 측정 → 전부 30분 이내
- 같은 항목이 두 번 나오지 않음, 슬랙 수기 대조 시 누락 0건(샘플 3건 이상)
- 맥미니 재부팅 후 로그에 다시 `ok:` 기록, 연속 실패 알림 동작 확인

## 알려진 한계
- 매시 0분·30분에 실행됩니다(plist `StartCalendarInterval`). 지연은 최대 약 30분입니다. 일정을 바꾸면 plist를 다시 만들고 `launchctl unload`/`load` 하세요.
- 쉬는 날은 `holidays_kr.txt`(2026~2027 공휴일 + 근로자의날)로 거릅니다. 회사 휴무일은 직접 한 줄씩 추가하세요. 목록에 그해 날짜가 없으면 로그에 `warn:`이 남습니다.
- 실시간 감지(슬랙 Socket Mode)는 회사 워크스페이스에 새 앱 설치가 필요해 하지 않기로 했습니다(2026-10-12).
- 폰으로 바로 알림이 가는 경로는 아직 없습니다(맥미니 알림과 `inbox/`만). 발송 성격이라 대표님 결정이 필요합니다: ① 본인 슬랙 DM으로 요약 전송 ② 푸시 서비스 사용 ③ 맥미니 파일을 Jump Desktop으로 확인.
- 이 저장소는 공개 저장소입니다. `config.env`, `state/`, `inbox/`는 `.gitignore`로 제외돼 있으니 사내 내용을 커밋하지 마세요.
