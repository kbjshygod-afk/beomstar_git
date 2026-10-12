# STATUS — 업무 에이전트

DoD(1단계): 맥미니에서 실제 `claude -p`로 poll.log가 `ok:`로 끝나고, inbox 형식이 맞고, Pixel Agents 표시 여부를 확인한다.
상태: 진행 (1단계 시험 통과, launchd 등록 대기)

## 2026-10-12 (맥미니 검증)
- **완료한 것**:
  - 맥미니(BEOMui-Macmini, macOS 27, node 24.21, Claude Code 2.1.296, python 3.9.6)에서 실제 `claude -p` 3회 실행 — 모두 `ok:`.
    - 1회차 `ok: 6 new item(s), 3 urgent, 2 error(s)` / 2·3회차 `ok: nothing new`(중복 제거 동작).
  - 헤드리스에서 커넥터 실제 호출 확인: 1회차 Slack 검색 8회, Plaud list_files 1회·get_note 6회, 권한 거부 0건.
  - 버그 수정: `config.example.env`의 `WORK_AGENT_KEYWORDS` 값이 따옴표 없이 공백을 포함해 `source` 때 명령으로 실행되던 문제(재현 → 따옴표 추가 → 재실행 통과).
  - 도구 이름 수정: 이 기기의 claude.ai 커넥터는 `mcp__claude_ai_Slack__*`, `mcp__claude_ai_Plaud__*`. 예시 설정 반영, 쓰기 가능한 Slack 도구와 Gmail·Calendar·Drive·Notion·Claude Docs 서버 전체를 DISALLOWED에 추가.
  - inbox 형식 확인: 6건 모두 제목·출처·할 일·기한 줄 있음, "확인하지 못한 것" 절 있음.
  - Pixel Agents 1.4.1: 127.0.0.1에만 바인딩. 훅 없이도 JSONL 감시로 헤드리스 폴링 세션을 캐릭터로 표시함(스크린샷 확인).
- **현재 상태**: 1단계 시험 통과. launchd 미등록. Pixel Agents 훅 미설치(`~/.claude/settings.json` hooks 비어 있음).
- **막힌 것과 원인**: 없음(등록 여부는 대표님 결정 대기).
- **다음 1개 행동**: 대표님 승인 시 README 6번대로 launchd 등록 → 업무시간 중 5분 간격 로그 3줄 확인.
- **참고(비용)**: `total_cost_usd` 기준 신규 6건 처리 $0.32, 새 항목 없음 $0.14/회(sonnet). 5분 간격·10.5시간이면 하루 약 126회 → 빈 실행만으로 약 $18/일 상당(구독이면 사용량 한도 소모). 등록 전 모델(haiku)·간격(10~15분) 결정 필요.
- **보류 항목**: [보류-승인대기] 2단계 실시간(슬랙 앱 관리자 승인, 플라우드 개발자 포털 접근 확인) / [보류-결정] 폰 알림 경로 선택 / [보류-결정] Pixel Agents 훅 설치(실시간 표시용, 선택).
