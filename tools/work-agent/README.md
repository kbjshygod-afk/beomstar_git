# 업무 에이전트 — 맥미니 30분 폴링 (1단계 읽기 전용 · 2a 슬랙 답장 초안 · 3단계 사무실)

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
| `office.py`, `office.sh` | (3단계) 사무실: 직원 실행 → 제안 검증·저장 → 전광판 결정 읽기 → 승인 건 실행 → 상태·결과 쓰기. `poll.sh`가 매 폴링 끝에 `office.sh cycle` 호출(`WORK_AGENT_OFFICE=1`) |
| `call_guard.py` | (3단계) 고정 호출 훅. 코드가 정한 인자(sha256)로 도구 1개를 1회 부르는 것만 허용 |
| `staff/roster.json`, `staff/*.md` | (3단계) 직원 명단과 역할별 지시문 |
| `TEAM_PLAN.md` | R&D AI팀 설계(직원 8명 + 사무보조)와 겨울 2차 파일럿·채용 일정 |
| `board/board.html` | (3단계) 전광판 페이지 원본(claude.ai 아티팩트로 게시) |
| `desks.py`, `pixel_office.sh`, `pixel/` | (3단계) 픽셀 사무실: 책상 폴더·기록 정리, Pixel Agents 설정 합치기·배치 설치, 배치 생성기와 결과(`layout-office.json`) |
| `cost_check.py` | (원가 담당) MASTER 형식 원가표 xlsx에서 시트가 오류 없이 0원으로 계산하는 입력을 찾는 검사기. 표준 라이브러리만 사용 |
| `tests/` | 회귀 시험(`test_work_agent.py`, `test_office.py`, `test_cost.py`, 모델·네트워크 없이) · 실제 claude 끝까지 시험(`e2e_real_claude.sh` 가짜 슬랙, `e2e_office.sh` 실제 전광판 + 가짜 캘린더, `e2e_cost.sh` 가짜 Drive) |
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

## 3단계 사무실 (전광판 + 직원 + 승인 후 실행)

**DoD(이번 단계)**: 직원이 올린 결재 건이 전광판에 나타나고, 대표님이 폰에서 승인하면 다음 폴링이 그 승인을 읽어 "되돌릴 수 있는 실행"(캘린더 등록)을 승인한 내용 그대로 수행하며, 결과가 전광판에 돌아온다. 에이전트 발송 0건.

**전광판**: claude.ai 페이지 `board/board.html` (게시본 `WORK_AGENT_BOARD_URL`). 저장소 규칙은 "쓰기는 아티팩트 소유자만". 맥미니의 `claude -p`는 대표님 계정이라 소유자로 쓰고, 페이지에서 대표님 탭도 소유자 쓰기. 다른 사람에게 공유하면 읽기 전용.

**직원** (`staff/roster.json`): 역할 프롬프트 + 읽기 전용 도구 허용 목록(`tool_guard.py`) + 기존 스킬 내용. 결과는 JSON "제안"뿐이고 코드가 검증해 로컬 파일로 저장합니다. 지금 켜진 직원: 요청 비서(1단계·2a), 신메뉴 게이트 담당(평일 09:00 첫 폴링에 1회, Drive 읽기), 원가·원재료 담당(평일 09:30, 아래 절). 공지·문서 담당은 정의만 있고 꺼짐(다음 단계).

**결재 규칙(핵심)**
- 실행 내용의 기준은 **맥미니 로컬 사본**(`state/office/proposals/*.json`)입니다. 전광판은 승인/반려 결정만 전달합니다.
- 승인 시 페이지가 본 내용의 해시(`approved_sha`)를 함께 씁니다. 맥미니는 전광판의 내용 해시·승인 해시·로컬 해시가 모두 같고, 만료(48시간) 전이고, 그 건을 실행한 적이 없을 때만 실행합니다. 어긋나면 "실패"로 전광판에 이유를 돌려보냅니다.
- **보류**(실패가 아님): 전체 정지 중, 하루 상한(10건) 도달, 정지 여부를 읽지 못한 폴링에서는 승인 건을 건드리지 않고 다음 폴링에 다시 봅니다(`office.log`에 "보류: … — 이유"). 상한은 캘린더 도구에 실제로 닿은 실행만 셉니다. 승인 없이 48시간이 지난 건은 "만료"로 전광판에 돌려보내고, 반려·만료된 안건은 직원이 다시 올릴 수 있습니다(실행된 안건은 다시 올리지 않음).
- 실행기: `calendar_event`(참석자 금지·8시간 이하·400일 안, 등록 후 삭제 가능) · `info`(확인만). 슬랙·메일 발송은 승인해도 초안까지입니다.
- 전광판 읽기·쓰기와 실행은 모두 **고정 호출**(`call_guard.py`)로만 합니다: 코드가 정한 인자의 sha256과 다른 호출, 다른 도구, 두 번째 호출은 훅이 막습니다. 데이터는 파일(`file_path`/`out_dir`)로 오가며 호출 모델은 내용을 보지 않습니다. 전광판 쓰기는 도구가 사람 승인을 요구해서 그 호출에만 `--permission-mode bypassPermissions`를 씁니다 — 훅이 유일한 관문이고, 훅이 죽어도 막힙니다(`onFailure: block`).
- **전체 정지**: 전광판 "⏸ 전체 정지" 또는 맥미니 `state/STOP` 파일. 그다음 폴링부터 직원 실행·실행기가 멈춥니다(읽기·보고는 계속). 다시 시작하면 보류됐던 승인 건이 그대로 실행됩니다.
- **맥미니 신호**: 폴링마다 "마지막 신호"와 "다음 예정 시각"(평일 09:00~18:00 안의 다음 폴링)을 전광판에 씁니다. 지각 여부는 예정 시각 기준이라 저녁·주말에는 빨갛게 되지 않습니다.

**켜는 법 (★ 대표님)**
1. `config.env`에 `WORK_AGENT_OFFICE=1`, `WORK_AGENT_BOARD_URL=<전광판 주소>` (예시 파일 참고).
2. 확인: 다음 폴링 뒤 `tail -n 3 state/poll.log`에 `office: staff=… pull=ok … push=ok(…)`. 전광판 상단 "맥미니 N분 전"이 초록.
3. 직원을 바로 돌려 보려면 `bash office.sh staff gate` (1~3분, sonnet). 결과는 전광판 "직원 현황"과 "결재 대기".
4. 끝까지 시험: `WORK_AGENT_BOARD_URL=<주소> bash tests/e2e_office.sh` — 실제 claude·실제 전광판·**가짜 캘린더**로 제안→승인→실행→보고를 한 바퀴 돕니다. 전광판에 "[e2e]" 완료 건 1개가 남고, `bash tests/e2e_office.sh --cleanup`으로 지웁니다.

**픽셀 사무실(Pixel Agents)**: 직원마다 책상 폴더 `state/office/desks/<desk>`(secretary·gate·notice·cost·runner)에서 실행됩니다. Pixel Agents는 사람 없는 세션을 책상 폴더 이름으로 이름표를 달아 보여 주고, `areaMappings`로 그 책상의 한글 구역("요청비서", "게이트담당", "공지문서", "원가담당", "사무보조")에 앉힙니다. 실행이 끝나도 기록 파일이 남아 있는 한 캐릭터가 자리를 지키며, 같은 책상의 이전 기록은 지워서 **책상당 1명**을 유지합니다(`office.py tidy`). 훅은 설치하지 않습니다(훅을 깔면 세션이 끝날 때 캐릭터가 사라져 사무실이 비어 보입니다).
- 설치(★ 1회): `bash pixel_office.sh install` → `~/.pixel-agents/config.json`에 설정(다른 폴더 세션 보기·이름표·구역 표시·구역 매핑)을 합치고, 배치 `pixel/layout-office.json`(기본 사무실 + 구역 5개)을 넣습니다. 기존 배치가 있으면 그대로 두고 알려 줍니다(`--force`로 교체, 백업 생성). 그다음 Pixel Agents를 다시 띄웁니다(`bash pixel.sh` 또는 다음 정시 자동 실행).
- 확인: `bash pixel_office.sh status`. 사무실 화면에서 책상 위 이름표(gate 등)와 바닥 구역색을 봅니다.
- 배치를 바꾸려면 Pixel Agents 편집기에서 수정하거나 `pixel/make_layout.py`의 AREAS를 고치고 다시 생성합니다. 기본 사무실 원본 `pixel/base-layout.json`은 pixel-agents 1.4.1(MIT)의 것입니다.

**기록**: `state/office/office.log`(사무실 활동), `state/office/call_guard.log`(고정 호출 허용·차단), `state/office/tool_guard.log`(직원 실행에서 막힌 도구), `state/office/proposals/`(결재 건 원본), `state/office/calls/<호출>/`(마지막 호출 원본).

### 원가·원재료 담당 (그림자 운영: info만)

**DoD**: 평일 09:30 폴링에 설정한 시즌 원가표(MASTER 형식)를 받아, 시트가 오류 없이 0원으로 계산하는 입력과 단종·검토중 재료를 행 번호와 함께 전광판 info로 올린다. 숫자·행은 코드가 쓰고, AI는 권장 한 줄과 기획 파일의 원가 미결만 덧붙인다. 지어낸 값·실행 0건.

**잡는 것** (`cost_check.py`, 신메뉴_원가표): 재료 미입력 행(컵원가만 잡혀 판정 ✓) · 원재료DB·베이스 표와 글자·띄어쓰기가 다른 재료명(가까운 DB 표기 제시) · 정량 없음 · 재료명 없이 정량만 · 원재료DB 단가·규격 없음(두 가격 모두 0인 정수 같은 재료는 제외) · 베이스 구성 오류(총중량·구성 재료) · 컵 표에 없는 구분 · 판매가 없음 · 단종·폐기 / 검토중·테스트중 재료 · 원재료DB 같은 이름 여러 행. 원가 기준(매출가/매입가)은 물류수수료 C3를 따릅니다.

**흐름**: 고정 호출로 `download_file_content` 1회 → 큰 응답은 Claude Code가 세션 `tool-results/`에 저장하고 경로만 알려 줌 → `office.py`가 그 안내문 첫머리일 때만, `~/.claude/projects/…/tool-results/` 안의 파일만 읽고 바로 지움 → 검사 → AI 실행(sonnet, Drive 읽기 도구 2개만, 검산 결과를 입력으로 받음) → 카드. AI가 실패해도 검사 카드는 올라가고 "AI 메모 없음"이 남습니다. 원가표를 못 받으면 AI는 돌지 않습니다.
- 같은 지적은 한 번만: 대기 중·확인됨이면 다시 안 올리고, 반려해도 내용(행·재료)이 바뀌기 전엔 다시 안 올립니다.
- AI 글 속 단가(`원/kg`·`원/g`·`원/bag` 등)는 코드가 `[단가]`로 가립니다. 원가율·잔당 원가는 출처와 함께 남습니다.
- 카드에는 메뉴명과 재료명이 들어갑니다. 전광판을 다른 사람에게 공유할 때 참고하세요.

**켜는 법 (★ 대표님)**
1. ★ 맥미니 `git pull`
2. ★ `config.env`에 한 줄: `WORK_AGENT_COST_SOURCES="겨울2차=<02 원가표 파일 ID>,<01 기획 파일 ID>"` (ID는 Drive 주소 `/d/` 뒤 값. 이 저장소에는 적지 않습니다)
3. 확인: `bash office.sh staff cost` (1~3분) → `state/office/staff/cost.json`의 summary와 전광판 "결재 대기"의 원가 카드
4. 끝까지 시험: `bash tests/e2e_cost.sh` → 마지막 줄 `failures: 0` (가짜 Drive, 몇 센트). 맥미니 Drive 도구 이름이 다르면 `WORK_AGENT_DRIVE_DOWNLOAD_TOOL`

**한계**: 원가·원가율 같은 계산값은 다시 계산하지 않습니다. 스크립트로 저장된 xlsx에는 수식 결과가 들어 있지 않아서, 사람이 입력한 값만 봅니다. 원가율 40% 초과 같은 판단은 AI가 기획 파일(Drive가 계산해 보여 주는 값)에서만 합니다. 검사 범위는 신메뉴_원가표뿐입니다(음료·디저트 전체 원가표는 다음 단계).

## 알려진 한계
- 사무실은 폴링 안에서 돕니다(평일 09:00~18:00). 저녁에 누른 승인은 다음 날 09:00 폴링에 실행됩니다.
- Pixel Agents는 보는 창입니다. 이름표는 책상 폴더 이름(영문)이고 한글은 바닥 구역 라벨로만 보입니다. 승인 버튼은 없습니다(전광판에서).
- 전광판 도구(ArtifactData)는 Claude Code 내장 도구라 맥미니의 claude.ai 로그인으로 동작합니다. 로그인이 끊기면 전광판 갱신·승인 반영이 함께 멈추고, "맥미니 신호"가 노랑→빨강으로 바뀝니다.
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
