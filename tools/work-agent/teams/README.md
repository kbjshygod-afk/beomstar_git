# 팀 추가하기

사무실 엔진 하나가 `teams.json`의 팀을 차례로 돌립니다(`office.py teams`, `poll.sh`가 30분마다 호출). 팀마다 직원 명단·기록·하루 실행 상한·중복 방지·정지 스위치가 따로이고, 전광판(관제실)은 하나입니다.

| | 기본 팀(R&D) | 다른 팀 |
|---|---|---|
| 전광판 경로 | `queue/` `staff/` `log/` (예전 그대로) | `teams/<id>/queue` `…/staff` `…/log` |
| 맥미니 기록 | `state/office/` | `state/teams/<id>/office/` |
| 팀 카드(심장박동·팀 정지) | `teams/rnd` | `teams/<id>` |
| 로컬 설정 | `config.env` | `config.env` + `teams/<id>/config.env`(덮어씀) |

## 순서
1. `cp -r teams/_template teams/<id>` (id는 영문 소문자·숫자·_)
2. `teams/<id>/roster.json`의 직원과 `teams/<id>/staff/*.md` 지시문을 씁니다. 처음에는 `proposal_kinds: ["info"]`(그림자 운영).
3. `teams.json`에 한 줄: `{"id": "<id>", "title": "…팀", "emoji": "…", "order": 2, "enabled": true, "roster": "teams/<id>/roster.json"}`
4. ★ 맥미니: 팀 전용 값(파일 ID, 초안 폴더, `WORK_AGENT_EXEC_DAILY_MAX` 등)은 `teams/<id>/config.env`에(git 제외).
5. 시험: `bash office.sh team <id> staff <role>` → 전광판에서 그 팀 칩을 눌러 확인.

## 주의
- 모든 팀이 대표님 계정의 커넥터로 움직입니다. 다른 사람이 쓰는 팀은 그 사람 계정으로 따로 돌리세요.
- Max 사용량 한도는 모든 팀이 같이 씁니다. 팀마다 `daily_at`을 나누고 하루 실행 상한을 둡니다.
- 돈이 오가거나 되돌릴 수 없는 일은 승인해도 초안·보고까지만(지금 실행기는 캘린더 등록·Drive 초안·확인뿐).
- Pixel Agents 구역은 R&D 책상 5개뿐이라 다른 팀 직원은 사무보조 자리에 보일 수 있습니다.
