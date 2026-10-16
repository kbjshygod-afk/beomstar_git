# 업무 에이전트 — 맥미니 30분 폴링 (1단계 읽기 전용 + 2a 슬랙 답장 초안)

**DoD**: 업무시간(월~금 09:00~18:00 KST, 공휴일 제외)에 슬랙에 새 요청이 올라오거나 플라우드 전사가 끝나면 30분 안에 `inbox/`에 담당·기한·답변 초안이 정리되고 맥미니에 알림이 뜬다. 같은 항목은 두 번 처리하지 않는다. 연속 3회 실패하면 알림이 온다.

이 단계는 **읽기 전용**입니다. 메시지·메일 발송, 일정 변경, 파일 수정은 도구 수준에서 막혀 있습니다. 슬랙·플라우드 텍스트는 데이터로만 취급하고, 안에 든 지시문은 따르지 않습니다.

## 파일
| 파일 | 역할 |
|---|---|
| `poll.sh` | 30분마다 실행되는 래퍼. 업무시간 확인 → 중복 실행 방지 → `claude -p` 호출 → 결과 검증 → `inbox/` 기록. 결과가 유효할 때만 체크포인트를 옮김 |
| `prompt.md` | 에이전트 지시문(규칙·절차·출력 형식) |
| `config.example.env` | 설정 예시 → `config.env`로 복사 |
| `com.beomstar.work-agent.plist.template` | launchd 자동 실행 설정 |
| `lib.sh` | 업무시간·공휴일 판정 공통 함수 |
| `holidays_kr.txt` | 쉬는 날 목록(한 줄에 날짜 하나) |
| `slack_dm.sh` | 특이사항을 대표님 본인 슬랙 DM으로 보냄. 정해진 문구만 보내고, 발송 도구 하나만 허용 |
| `pixel.sh`, `com.beomstar.pixel-agents.plist.template` | 업무시간에 Pixel Agents 사무실 화면을 켜 둠(127.0.0.1, 18:15 종료) |
| `slack_drafts.py` | (2a) 답이 필요한 슬랙 요청의 원래 스레드에 **보내지 않은 초안**을 넣음. 넣을지 말지는 코드가 정하고, 초안 1건마다 도구 하나만 쓰는 `claude -p`를 따로 실행 |
| `draft_guard.py` | (2a) 위 실행의 PreToolUse 훅. 정해진 채널·스레드·문구로 초안 도구를 한 번 부르는 것만 허용하고 나머지는 모두 막음 |
| `tool_guard.py` | 읽는 실행(`poll.sh`)과 알림 실행(`slack_dm.sh`)의 PreToolUse 훅. 허용 목록(`WORK_AGENT_ALLOWED_TOOLS`, DM은 발송 도구 1개)에 없는 도구는 내장 도구까지 모두 막음 |
| `tests/` | 회귀 시험(`test_work_agent.py`, 모델·네트워크 없이) · 실제 claude 끝까지 시험(`e2e_real_claude.sh`, 가짜 슬랙 서버 사용) |
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
7. Pixel Agents 자동 실행(선택): `sed "s|__DIR__|$PWD|g; s|__HOME__|$HOME|g" com.beomstar.pixel-agents.plist.template > ~/Library/LaunchAgents/com.beomstar.pixel-agents.plist && launchctl load ~/Library/LaunchAgents/com.beomstar.pixel-agents.plist`
8. ★ 시스템 설정 → 에너지: 자동 잠자기 방지, 정전 후 자동 시작 켜기. 맥미니가 잠들면 폴링이 멈춥니다.

## 완료 증명 (한 주 시범 후 판정)
- 슬랙에 테스트 메시지 5건(DM·멘션·키워드 각각)을 보내 `inbox/` 반영까지 걸린 시간 측정 → 전부 30분 이내
- 같은 항목이 두 번 나오지 않음, 슬랙 수기 대조 시 누락 0건(샘플 3건 이상)
- 맥미니 재부팅 후 로그에 다시 `ok:` 기록, 연속 실패 알림 동작 확인

## 2단계(2a) 슬랙 답장 초안

**DoD**: 답이 필요한 슬랙 요청마다 원래 스레드에 슬랙 초안이 들어가고(에이전트 발송 0건), 지시문 의심·이미 답한 건·링크나 @channel이 든 초안은 넣지 않으며, 결과가 `inbox/` 파일 끝 "슬랙 초안" 절에 남는다.

**흐름**: 읽는 실행(쓰기 도구 없음) → 코드가 넣을 초안을 고름 → 초안 1건마다 별도 `claude -p`(haiku, 초안 도구 1개만 허용, 훅이 인자 고정) → 대표님이 슬랙에서 확인·수정 후 직접 전송.

**넣지 않는 경우** (`inbox/`에 이유가 적힘): 주의 표시(flag)가 있음 · 대표님이 이미 답함 · 800자 초과 · @channel/@here · 링크 · 지시문으로 보이는 문구 · 같은 스레드에 이미 넣은 적 있음(영구) · 하루 20건/한 번 5건 초과.

**켜는 법 (★ 대표님)**
1. ★ 맥미니에서 저장소 최신으로: `git pull`
2. `cd tools/work-agent && python3 tests/test_work_agent.py` → 마지막 줄 `OK` (모델·네트워크 안 씀, `config.env`도 읽지 않음)
   - 이어서 `bash tests/e2e_real_claude.sh` → 마지막 줄 `failures: 0` (약 2~3분, haiku 몇 센트, 가짜 슬랙 서버만 씀). 특히 `PASS fail-closed`는 **이 맥미니의 claude 버전이 훅 고장 시 호출을 막는다**는 확인입니다. FAIL이면 켜지 말고 알려 주세요.
3. ★ `config.env`에 `WORK_AGENT_SLACK_DRAFTS=1` 한 줄 추가 (도구 이름이 다르면 `WORK_AGENT_DRAFT_TOOL`도)
4. 확인: 다음 실행 뒤 `tail -n 3 state/poll.log`에 `drafts:<넣음>:<건너뜀>:<실패>`, `inbox/` 최신 파일 끝에 "슬랙 초안" 절

**기록**: `state/drafts_log.tsv`(날짜·결과·위치), `state/drafted_threads.txt`(초안이 들어갔을 수 있는 스레드, 다시 넣지 않음), `state/draft_guard.log`(초안 훅이 허용·차단한 호출), `state/tool_guard.log`(읽는 실행·알림 실행에서 막힌 도구), `state/draft_call/`(마지막 실행 원본).

**고장 나면 막힘(fail-closed)**: 세 훅 모두 오류가 나면 exit 2로 막고, 설정에 `onFailure: block`(훅 자체가 못 뜰 때도 막음)과 `disableAllHooks: false`(다른 설정이 훅을 꺼도 다시 켬)를 넣습니다. 2026-10-16 이 세션의 claude 2.1.301에서 셋 다 동작을 확인했습니다. 맥미니 버전은 위 2번 e2e로 확인합니다.

**주의**: 2026-10-16 시험에서 같은 채널 맨 아래 입력창에 초안을 두 번 넣었을 때 문서에 적힌 "이미 있음" 오류가 나지 않고 성공으로 돌아왔습니다(두 번째는 draft_id 없음). 쓰던 초안을 덮어쓸 수 있다는 뜻이라 **항상 스레드 답장 초안으로만** 넣고, 같은 스레드에는 두 번 넣지 않습니다. 응답에 draft_id가 없으면 `inbox/`에 ⚠️ "확인 필요"로 표시합니다.

## 알려진 한계
- 시험은 `WORK_AGENT_CONFIG`를 없는 파일로 지정해 실제 `config.env`를 읽지 않습니다. 직접 다른 설정 파일로 돌려 볼 때도 이 변수를 씁니다.
- 초안 대상(채널·스레드)은 읽는 실행이 적은 id를 형식만 검사합니다. 슬랙 원문 속 지시문이 읽는 실행을 속여 엉뚱한 스레드의 id를 적게 하면, 그 스레드에 "보내지 않은 초안"이 생길 수 있습니다(대표님이 보기 전에는 나가지 않음). 읽은 결과와 대조하는 검증은 다음 단계입니다.
- 읽는 실행은 슬랙과 플라우드를 한 번에 봅니다. 그래서 공격 글이 회의 내용을 답장 초안에 섞게 할 수도 있습니다. **초안을 보낼 때는 내용을 꼭 읽어 보세요.**
- 매시 0분·30분에 실행됩니다(plist `StartCalendarInterval`). 지연은 최대 약 30분입니다. 일정을 바꾸면 plist를 다시 만들고 `launchctl unload`/`load` 하세요.
- 쉬는 날은 `holidays_kr.txt`(2026~2027 공휴일 + 근로자의날)로 거릅니다. 회사 휴무일은 직접 한 줄씩 추가하세요. 목록에 그해 날짜가 없으면 로그에 `warn:`이 남습니다.
- 실시간 감지(슬랙 Socket Mode)는 회사 워크스페이스에 새 앱 설치가 필요해 하지 않기로 했습니다(2026-10-12).
- 특이사항 슬랙 DM(`slack_dm.sh`): 긴급 건 발생, 폴링 연속 3회 실패, Pixel Agents 하루 3회 종료 때 보냅니다. 같은 건은 하루 한 번, 하루 최대 10건. 슬랙·플라우드 원문은 넣지 않고 건수·파일명만 보냅니다(원문 속 지시문이 발송을 조종하지 못하게). 받는 사람은 `config.env`의 `WORK_AGENT_SLACK_DM_USER`.
- 이 DM은 대표님 계정으로 대표님에게 보내는 "나에게 보내기"라서, 슬랙 설정에 따라 폰 푸시가 안 울릴 수 있습니다.
- 폴링 자체가 고장 나면(로그인 만료 등) DM도 같은 `claude`를 쓰므로 함께 실패할 수 있습니다.
- Pixel Agents 화면은 맥미니에서만 열립니다(127.0.0.1). 열기: `open "$(cat state/pixel_url.txt)"`. 주소의 토큰은 서버가 뜰 때마다 바뀝니다. 다른 Pixel Agents 서버가 이미 떠 있으면 새로 띄우지 않고 그 주소를 저장합니다.
- 이 저장소는 공개 저장소입니다. `config.env`, `state/`, `inbox/`는 `.gitignore`로 제외돼 있으니 사내 내용을 커밋하지 마세요.
