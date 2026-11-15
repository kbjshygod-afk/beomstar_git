# 스윙 모의투자 예약 인수인계 (2026-11-15)

## 목적

Claude 클라우드 세션(스윙 모의투자)에 묶여 있는 예약 10개를 다른 실행 환경으로 옮길 수 있도록, 예약의 원문과 실행 조건을 그대로 적는다. 이 문서는 기록이다. 예약을 끄거나 지우지 않았다.

## 핵심 요약

- 예약은 10개다. 반복 5개, 1회성 5개다.
- 모두 한 세션에 묶여 그 세션의 대화 맥락 안에서 실행된다. 프롬프트가 "이 세션", "대표님 승인 항목"처럼 앞선 대화를 전제로 쓰여 있어, 새 환경에서는 아래 "옮길 때 고칠 점"을 반영해야 한다.
- GitHub Actions 쪽 자동 실행(장부 2시간 주기, 실시간 감시 예비 시작)은 세션과 무관하게 계속 돈다.
- 키·토큰·계좌·개인정보는 이 문서에 없다. 비밀값은 이름만 적었다.

## 공통 실행 조건

| 항목 | 내용 |
|---|---|
| 저장소 | `kbjshygod-afk/beomstar_git` (기준 브랜치 `claude/dazzling-ride-a0nb4k`) |
| 필요한 브랜치 | `paper-trading`(장부), `swing-results`(백테스트 결과), `swing-data`(시세 스냅샷) |
| 실행 환경 | Python 3.12, `pip install -r trading/requirements.txt`, git |
| GitHub 작업 | 워크플로 실행 목록 조회, 워크플로 수동 실행(dispatch), 실행 로그 조회, 이슈·PR 조회와 PR 생성. 클라우드 세션은 GitHub 커넥터 도구로 했고, 로컬에서는 `gh` 명령으로 같은 일을 할 수 있다 |
| 아티팩트 작업 | Claude의 `Artifact` 도구(자산 업로드·삭제)와 `ArtifactData` 도구(문서 조회·갱신). 대시보드 갱신과 체크리스트 갱신에 필요하다 |
| 자기 예약 | 일부 프롬프트는 "다시 확인을 예약한다"고 지시한다. 실행 환경에 예약을 새로 거는 수단이 있어야 한다 |
| AI 교차 검수 | 코드 PR을 올릴 때 Codex CLI(ChatGPT 구독 로그인)와 Antigravity CLI(Google 로그인)를 `trading/tools/ai_review.py --login`으로 돌린다. API 키는 쓰지 않는다(대표님 지시) |
| 작업 규칙 | PR은 초안으로 열고 대표님 "병합승인" 뒤에만 스쿼시 병합. 모의투자 기간 중 룰·파라미터·신호 데이터 출처 변경 금지. Slack 연동 금지 |

### 비밀값 이름 (값은 GitHub Secrets에만 있다)

| 이름 | 쓰는 곳 | 비고 |
|---|---|---|
| `KIS_APP_KEY`, `KIS_APP_SECRET` | `swing-paper.yml`(한국장 대조), `kis-ws.yml`(실시간 수신) | 시세 조회·수신 전용. 주문 코드는 없다 |
| `KRX_API_KEY` | `swing-paper.yml`(KRX 전일 봉 대조), `krx-probe.yml` | |
| `TIINGO_TOKEN` | `swing-paper.yml`(미국장 대조), `tiingo-probe.yml` | |
| `GITHUB_TOKEN` | 모든 워크플로 | Actions가 자동으로 준다 |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | `ai-cross-review.yml` | 설정하지 않았다. 구독 로그인 방식을 쓴다 |
| `SLACK_WEBHOOK_URL` | `swing-paper.yml`의 선택 경로 | 설정하지 않았고, 설정하지 않는다(Slack 연동 금지) |

저장소 변수: `KIS_ENV`, `KIS_GUARD`, `OPENAI_REVIEW_MODEL`, `GEMINI_REVIEW_MODEL`.

예약 프롬프트 자체는 비밀값을 직접 쓰지 않는다. 비밀값은 프롬프트가 시작시키는 워크플로 안에서만 쓰인다.

## 예약 목록

| # | 이름 | 시각 (KST) | 반복 |
|---|---|---|---|
| 1 | Paper trading daily health check | 매일 19:16 | 반복 |
| 2 | Dashboard refresh (in this session) | 매일 08:50, 17:50 | 반복 |
| 3 | kis-ws am slot dispatch (08:50 KST) | 평일 08:50 | 반복 |
| 4 | kis-ws pm slot dispatch (12:05 KST) | 평일 12:05 | 반복 |
| 5 | Swing rules monthly market review | 매월 3일 09:45 | 반복 |
| 6 | kis-ws first scheduled day check (2.6) | 2026-11-16 15:45 | 1회 |
| 7 | Paper trading: schedule-alive check | 2026-11-20 09:10 | 1회 |
| 8 | Paper trading: crypto 60-day record | 2026-11-24 09:40 | 1회 |
| 9 | Paper trading: 60-day verdict | 2026-12-23 09:10 | 1회 |
| 10 | Paper trading: KOSDAQ v2 60-day verdict | 2026-12-29 09:30 | 1회 |

---

## 1. Paper trading daily health check

- **시각:** 매일 19:16 KST (`CRON_TZ=Asia/Seoul 16 19 * * *`), 반복
- **필요한 도구:** git, Python(`trading/tools/daily_check.py`), GitHub 실행 목록 조회·워크플로 수동 실행·로그 조회·이슈 조회, `ArtifactData`(대시보드 신선도), 필요 시 예약 추가
- **비밀값:** 직접 쓰지 않음
- **결과를 남기는 곳:** 이상이 있을 때만 대표님께 대화로 보고. keeper가 끊겼으면 `swing-paper-keeper.yml`을 다시 시작시킨다
- **원문:**

```text
모의투자 일일 상태 점검 (docs/swing-improvement-policy.md 점검 주기). 시장은 6개: SP500 NDX100 KOSPI KOSDAQ KOSDAQ_V2(코스닥 v2 병행 장부, 폭 레짐 50, 시작일 2026-10-02, 판정 12-29 트리거 있음) CRYPTO. 먼저 `git fetch origin paper-trading` 후 `python trading/tools/daily_check.py` 를 실행해 시장별 기준일·다음 시가 진입/청산(종목명)·보유·시세 끊김·레짐(폭)·감사 플래그·최근 청산·판정 기준(A~C)을 읽는다(스크립트가 없으면, 즉 PR 병합 전이면 엔진 키 그대로 읽는다: paper/latest.json의 markets.<시장>.entries_next_open·exits_next_open·positions·stale_positions, paper/<시장>/audit.json, trades.csv — 다른 키로 읽어 0건으로 보고하지 않는다). exit 1(PROBLEM)이면 원인부터 확인. 특히 "판정 기준 위반(새로 발생)" PROBLEM은 12월 판정(계획서 A~C)에 직접 걸리므로 반드시 대표님께 보고하고, 대표님이 확인한 뒤에만 daily_check.py의 KNOWN_CRITERIA에 올린다. "criteria (known)" 줄은 이미 보고된 것이라 다시 보고하지 않는다. 그리고 GitHub Actions 실행 목록으로 확인: ① keeper 체인 생존 — 최근 3시간 안에 github-actions[bot]이 요청한 swing-paper 실행이 있는지. 없으면 swing-paper-keeper.yml을 claude/dazzling-ride-a0nb4k에서 한 번 실행해 재시작 ② 신호 커밋 기한 — 오늘 한국장 신호(KOSPI·KOSDAQ·KOSDAQ_V2, 평일, KRX 휴장일 제외)가 커밋됐는지(기한 다음 날 00:00 UTC). 주의: Yahoo는 저녁(관측 15:30 UTC 이후)에 그날 한국장 봉을 빼고 전날까지만 줄 때가 있어, 한국장 신호는 08:00~15:00 UTC 사이 실행에서 커밋돼야 한다. 이 점검 시각(10:16 UTC)에 아직 없으면 즉시 swing-paper.yml을 KOSPI KOSDAQ KOSDAQ_V2로 수동 실행(tries 1)하고, 그래도 데이터 미준비(exit 75)이거나 기준일이 오늘이 아니면 보고하고 22:30 UTC에 한 번 더 확인을 예약한다(기한 넘기면 계획서 A 위반) ③ 6개 시장 감사: late·uncommitted·mismatched·revised·missing_days 새 항목 ④ stale_positions(보유 종목 시세 끊김) ⑤ 실패한 swing-paper 실행 ⑥ 신호 알림: 오늘 코스닥(또는 코스닥 v2) 신호가 새로 커밋됐으면 이슈 "코스닥 모의투자 신호 알림"(#32) / "코스닥 v2 모의투자 신호 알림"(#34)에 같은 날짜의 댓글이 달렸는지. 없으면 해당 swing-paper 실행의 "Signal alert" 단계 로그를 보고 원인을 고친다 ⑦ KOSDAQ_V2 레짐이 OFF에서 ON으로(또는 반대로) 바뀐 날이면 대표님께 한 줄 알린다(폭 비율 포함) ⑧ 대시보드 신선도: ArtifactData get, url https://claude.ai/artifact/5JdurhpACTCAkvSuNZFFcJ, collection "datasets", doc_id "latest"의 updated.at이 30시간보다 오래됐으면 이 세션에서 직접 갱신한다(예약 작업 "Dashboard refresh (in this session)" trig_01Y1kfZFePjagsLnCBh7mMhC의 절차 그대로: dash_data.py → 자산 4개 업로드 → datasets 문서 4개 batch update → 옛 blob 삭제) 그리고 대표님께 그 예약 작업이 왜 돌지 않았는지와 함께 보고한다 ⑨ 손절 근접 알림(평일, KRX 휴장일 제외): 오늘 kis-ws 실행 중 오전 구간(08:50~12:00 KST)과 오후 구간(12:05~15:35 KST)이 각각 한 번씩 성공으로 끝났는지(같은 구간의 두 번째 실행이 "already started"로 바로 끝나거나 대기 중 취소된 것은 정상). 한 구간이라도 빠졌거나 실패했으면 원인(세션 예약 작업이 시작시키지 못함, KIS 접속 실패 등)을 확인해 보고하고, 알림 댓글이 달린 날은 이슈 "한국장 손절 근접 알림"의 내용을 대표님께 한 줄로 전한다. 이상이 없으면 아무 말도 하지 않는다. 이상이 있으면 조치하고 대표님께 한국어로 짧게 보고(무엇이, 무엇을 했는지, 남은 위험). 보고할 때는 진입·청산 건수를 종목명과 함께 적는다.
```

## 2. Dashboard refresh (in this session)

- **시각:** 매일 08:50, 17:50 KST (`CRON_TZ=Asia/Seoul 50 8,17 * * *`), 반복
- **필요한 도구:** git, Python(`trading/tools/dash_data.py`), `Artifact`(자산 업로드·삭제), `ArtifactData`(목록 조회·일괄 갱신)
- **비밀값:** 없음
- **결과를 남기는 곳:** 대시보드 아티팩트 `5JdurhpACTCAkvSuNZFFcJ`의 자산 4개와 `datasets` 문서 4개
- **원문:** (`<scratchpad>`는 실행 환경의 임시 폴더)

```text
대시보드 정기 갱신 (이 세션에서 실행; 새 세션 방식은 필요한 도구가 없어 11-03~11-10 여러 번 조용히 실패해 11-12 대표님 승인으로 이전). 순서:
1. `git -C /home/user/beomstar_git fetch -q origin paper-trading swing-results claude/dazzling-ride-a0nb4k`
2. `python3 /home/user/beomstar_git/trading/tools/dash_data.py --repo /home/user/beomstar_git --out <scratchpad>/dashdata` — UTC 시각과 행 수(latest=6 ...)를 출력한다. 실패하거나 latest=0이면 대시보드는 건드리지 말고 대표님께 한 줄 보고.
3. ArtifactData list: url https://claude.ai/artifact/5JdurhpACTCAkvSuNZFFcJ, collection "datasets" → 각 문서(latest, equity, trades, backtest)의 version과 source.url(/_blob/<id>)을 적어둔다.
4. Artifact publish(url 위, asset: true)로 4개 파일을 하나씩 올려 새 /_blob url을 받는다.
5. ArtifactData batch 한 번: 각 문서 op update, if_version = 3단계 version, data = {source: {kind: file, url: <새 url>, name: <파일명>, format: json}, updated: {at: <도구가 출력한 UTC 시각>, by: claude}, edit: {via: claude, at: <지금 UTC>}}.
6. batch 성공 후 3단계의 옛 blob id 4개만 Artifact delete(path = id)로 지운다.
성공하면 아무 말도 하지 않는다. 실패하면 어느 단계에서 무슨 오류인지 대표님께 한국어로 짧게 보고한다.
```

## 3. kis-ws am slot dispatch (08:50 KST)

- **시각:** 평일 08:50 KST (`CRON_TZ=Asia/Seoul 50 8 * * 1-5`), 반복
- **필요한 도구:** GitHub 워크플로 수동 실행, 실행 목록 조회
- **비밀값:** 직접 쓰지 않음(워크플로가 `KIS_APP_KEY`, `KIS_APP_SECRET`을 쓴다)
- **결과를 남기는 곳:** `kis-ws` 워크플로 실행(체결 기록은 실행 산출물, 손절 근접 알림은 이슈 "한국장 손절 근접 알림"의 댓글)
- **원문:**

```text
한국장 실시간 손절 감시(체크리스트 2.6) 오전 구간 시작. GitHub 자체 예약이 늦거나 빠지기 때문에(11-13 확인) 이 세션이 정시에 시작시킨다. 대표님 11-13 "병합승인"(PR #76) 승인 항목.
1. mcp__github__actions_run_trigger(스키마가 없으면 ToolSearch "select:mcp__github__actions_run_trigger,mcp__github__actions_list")로 method run_workflow, owner kbjshygod-afk, repo beomstar_git, workflow_id kis-ws.yml, ref claude/dazzling-ride-a0nb4k, inputs {"slot":"am"} 를 한 번만 실행한다.
2. actions_list(list_workflow_runs, resource_id kis-ws.yml, perPage 3)로 방금 실행이 queued/in_progress로 생겼는지 확인한다. 같은 구간의 실행이 이미 돌고 있어도 문제없다(워크플로가 직렬화하고, 완료 표시가 있으면 스스로 끝낸다).
3. 성공하면 아무 말도 하지 않는다. 실행 요청이 실패하면 한 번만 다시 시도하고, 그래도 실패하면 대표님께 한국어 한 줄로 오류를 보고한다(백업으로 GitHub 예약이 남아 있음을 함께 적는다).
다른 작업은 하지 않는다. 한국 휴장일에도 그대로 실행한다(체결 없이 끝나면 정상 처리된다).
```

로컬에서 같은 일을 하는 명령: `gh workflow run kis-ws.yml --repo kbjshygod-afk/beomstar_git --ref claude/dazzling-ride-a0nb4k -f slot=am`

## 4. kis-ws pm slot dispatch (12:05 KST)

- **시각:** 평일 12:05 KST (`CRON_TZ=Asia/Seoul 5 12 * * 1-5`), 반복
- **필요한 도구·비밀값·결과:** 3번과 같다
- **원문:**

```text
한국장 실시간 손절 감시(체크리스트 2.6) 오후 구간 시작. GitHub 자체 예약이 늦거나 빠지기 때문에(11-13 확인) 이 세션이 정시에 시작시킨다. 대표님 11-13 "병합승인"(PR #76) 승인 항목.
1. mcp__github__actions_run_trigger(스키마가 없으면 ToolSearch "select:mcp__github__actions_run_trigger,mcp__github__actions_list")로 method run_workflow, owner kbjshygod-afk, repo beomstar_git, workflow_id kis-ws.yml, ref claude/dazzling-ride-a0nb4k, inputs {"slot":"pm"} 를 한 번만 실행한다.
2. actions_list(list_workflow_runs, resource_id kis-ws.yml, perPage 5)로 ① 방금 실행이 생겼는지 ② 오늘 오전 구간(slot am) 실행이 성공으로 끝났는지 확인한다. 오전 실행이 아직 돌고 있으면 오후 실행은 대기했다가 이어서 시작하므로 그대로 둔다.
3. 성공하면 아무 말도 하지 않는다. 실행 요청이 실패하면 한 번만 다시 시도하고, 그래도 실패하거나 오늘 오전 구간 실행이 실패(failure)로 끝났으면 대표님께 한국어 한두 줄로 보고한다(무엇이 실패했는지, 백업으로 GitHub 예약이 남아 있음).
다른 작업은 하지 않는다. 한국 휴장일에도 그대로 실행한다(체결 없이 끝나면 정상 처리된다).
```

## 5. Swing rules monthly market review

- **시각:** 매월 3일 09:45 KST (`CRON_TZ=Asia/Seoul 45 9 3 * *`), 반복. 다음 실행 2026-12-03
- **필요한 도구:** git, Python(백테스트·판정 도구), GitHub PR 생성, 코드 PR이면 Codex·Antigravity CLI
- **비밀값:** 직접 쓰지 않음
- **결과를 남기는 곳:** `docs/swing-monthly-review.md`(PR로), 대표님께 대화로 보고
- **원문:**

```text
스윙 룰 월간 시장 적합성 검토 (대표님 지시 2026-10-02: 계속 보완·수정하며 시장에 맞춰 나간다. 원칙은 docs/swing-improvement-policy.md). 1) 시장별 현재 레짐(지수 vs 200일선, 코스피는 20일선 포함)과 지난달 변화. 2) 모의투자 성과를 docs/paper-trading-plan.md의 고정 경고선과 실전 조건 기준 경고선에 비교(거래일 20일 미만이면 '표본 부족'으로만 표시). 3) 연구 목록 R1~R8 진행: 새 데이터로 검증할 수 있는 항목이 있으면 판정 기준을 먼저 커밋하고 실전 조건(당시 구성종목) 백테스트로 확인. 4) 1·2등급 개선(운영·문서·스킬)은 PR로 올리고 병합 승인 요청, 스킬이 바뀌면 새 zip 전달. 5) 3등급(룰·파라미터) 변경은 모의투자 기간 중 절대 적용하지 않고 '새 기간 후보'로만 제안. 첫 실행(2026-10-03)은 모의투자 1주차라 레짐 현황과 연구 목록 상태만 기록하고 성과 평가는 하지 않는다. 대표님께 한국어로 결론·근거·리스크·실행표 형식으로 보고.
```

## 6. kis-ws first scheduled day check (2.6)

- **시각:** 2026-11-16 15:45 KST, 1회
- **필요한 도구:** GitHub 실행 목록 조회, `ArtifactData`(체크리스트 갱신)
- **비밀값:** 없음
- **결과를 남기는 곳:** 체크리스트 아티팩트 `6NM15Y87GfUEwX9w8DJTtc`의 `items/2_6` 문서, 대표님께 대화로 보고
- **원문:**

```text
체크리스트 2.6 마무리 확인(11-16 월). actions_list로 kis-ws.yml의 오늘 실행을 확인한다: ① 08:50 KST 무렵 workflow_dispatch slot=am 실행이 정시에 시작해 12:00 무렵 success ② 12:05 KST 무렵 slot=pm 실행이 15:35 무렵 success ③ GitHub 예약(schedule) 백업 실행은 "이미 완료" 표시로 조용히 끝났는지(실패로 끝났으면 원인 확인) ④ 재연결·알림 건수. 둘 다 정상이면 체크리스트 https://claude.ai/artifact/6NM15Y87GfUEwX9w8DJTtc collection items doc 2_6을 done=true로 갱신하고 대표님께 한국어 2~3줄로 보고한다. 문제가 있으면 재현 → 원인 → 수정 순서로 처리하고 보고한다. 참고: 11-13 병합 직후 push 점검 실행 2개가 겹쳐 하나가 "ALREADY IN USE"(exit 4)로 실패했다 — push 점검 실행끼리 직렬화하는 작은 수정(동시성 그룹에 'smoke' 추가)을 다음 코드 PR에 넣기로 했다. PR #78(문서 전용, v2 재검증)의 병합 승인 여부도 확인한다.
```

참고: 원문 끝의 두 문장은 이미 지난 일이다. PR #78은 11-13에 병합됐고, 직렬화 수정은 PR #79에 들어 있다.

## 7. Paper trading: schedule-alive check

- **시각:** 2026-11-20 09:10 KST, 1회
- **필요한 도구:** GitHub 실행 목록·워크플로 상태 조회, 워크플로 수동 실행, git(장부 감사 읽기)
- **비밀값:** 없음
- **결과를 남기는 곳:** 이상이 있을 때만 대표님께 대화로 보고
- **원문:**

```text
모의투자 실행 생존 점검. 2026-09-30부터 2시간 실행은 swing-paper-keeper 체인(workflow_dispatch, github-actions[bot])이 맡고, GitHub 예약 실행은 보조다. 확인: ① keeper 체인이 살아 있는지(최근 1주 swing-paper 실행이 약 2시간 간격, 5시간 45분마다 새 keeper) ② swing-paper·swing-paper-keeper 워크플로가 활성 상태인지(공개 저장소는 60일간 활동이 없으면 예약 워크플로가 비활성화될 수 있음) ③ 5개 시장 감사(늦음·미커밋·불일치·수정본·누락 0건). 체인이 끊겼으면 swing-paper-keeper.yml을 claude/dazzling-ride-a0nb4k에서 한 번 실행해 재시작하고 결과를 보고. 비활성화 경고나 중단이 있으면 대표님께 알리고 대응안을 승인받아 처리. 이상이 없으면 보고하지 않음.
```

## 8. Paper trading: crypto 60-day record

- **시각:** 2026-11-24 09:40 KST, 1회
- **필요한 도구:** git, Python(`trading/tools/paper_verdict.py`), 60일이 안 됐으면 예약 추가
- **비밀값:** 없음
- **결과를 남기는 곳:** 대표님께 대화로 보고
- **원문:**

```text
크립토 모의투자 60거래일 기록 판정 (대표님 11-13 "전부 진행" 승인 항목). 계획서의 실전 투입 결정(2026-10-02)상 크립토는 "실전 판정에서 제외, 기록만"이다. `git fetch origin paper-trading` 후 `python trading/tools/paper_verdict.py --repo .. --markets CRYPTO`로 60/60일이 됐는지 확인한다(아직이면 남은 일수만 한 줄 보고하고 그날로 다시 예약). 60일이 됐으면 대표님께 한국어로 보고: ① 판정표(A 무결성·B 운영·C 룰 준수·D 건전성, 수익률·최대낙폭·청산 건수·비트코인 대비) ② B 실패의 내용(유니버스 30종목 중 Yahoo 시세가 없는 종목 수와 이름, 기간 중 변동) ③ 선택지 2~3개와 추천: 가) 기록만 남기고 크립토 장부는 계속 운영(현 상태 유지), 나) 데이터 실패 종목을 다른 출처(Coinbase/Kraken)로 보완한 뒤 새 60일 기간으로 재시작 — 데이터 출처 변경은 3등급이라 새 기간에만 적용, 다) 크립토 장부 종료 ④ 반대논리·리스크 1개 이상. 결정은 대표님이 한다. 형식: 결론 → 근거 → 리스크 → 실행표 → Next actions 3줄.
```

## 9. Paper trading: 60-day verdict

- **시각:** 2026-12-23 09:10 KST, 1회
- **필요한 도구:** git, Python(`paper_verdict.py`, `paper_thresholds.py`)
- **비밀값:** 없음
- **결과를 남기는 곳:** 대표님께 대화로 보고(실전 1/4 비중 시작 여부는 대표님 결정)
- **원문:**

```text
모의투자 60거래일 최종 판정. docs/paper-trading-plan.md의 판정 기준(A·B·C 통과, D 경고 여부)으로 시장별 판정을 내리고, 60거래일에 못 미친 시장은 남은 일수를 표시. D는 사전 고정 표로 판정하고, 같은 문서의 "실전 조건 기준 경고선"(trading/tools/paper_thresholds.py로 산출)을 참고로 나란히 표시. 판정 뒤 적용은 문서의 "실전 투입 결정(2026-10-02, 대표님)"을 따름: 실전 후보는 코스닥뿐(통과 시 계획 비중의 1/4로 시작, 20거래일마다 재점검), S&P500·나스닥100·코스피는 통과해도 실전 보류, 크립토는 실전 판정 제외(기록만). 추가로 docs/backtest-patterns-ko.md의 가설(RS 90 이상 신호 우위, 나스닥100 RS 70~80 손실)을 모의투자 기간 신호로 참고 확인(표본 작음, 그 문서도 현재 구성종목 기준이라 편향 있음을 명시). 대표님께 한국어로 결론·근거·리스크·실행표 형식으로 보고하고, 코스닥 실전 1/4 비중 시작 여부는 대표님이 결정하도록 함.
```

## 10. Paper trading: KOSDAQ v2 60-day verdict

- **시각:** 2026-12-29 09:30 KST, 1회
- **필요한 도구:** git, Python(`paper_verdict.py`), GitHub 실행 목록·이슈 조회
- **비밀값:** 없음
- **결과를 남기는 곳:** 대표님께 대화로 보고(실전 룰 교체 여부는 대표님 결정)
- **원문:**

```text
코스닥 v2 병행 모의투자(KOSDAQ_V2, 코스닥 룰 + 폭 레짐 50) 60거래일 최종 판정. 시작일 2026-10-02. `paper-trading` 브랜치 paper/KOSDAQ_V2/와 paper/KOSDAQ/를 읽어 docs/paper-trading-plan.md의 A 무결성·B 운영·C 룰 준수·D 건전성(코스닥 값, 고정 경고선과 실전 조건 경고선 나란히)을 v1·v2 모두에 적용한 판정표를 만든다. v1(12-23 판정)과 v2를 같은 기간(10-02~판정일)으로 나란히 비교: 레짐 ON/OFF 일수, 진입·청산 수, 수익률, 지수 대비, 최대 낙폭, 승률, 손익비. docs/swing-upgrade-study-2026-10.md의 사전 규정(합격 시 실전 룰 교체 여부는 대표님 결정)에 따라 추천안 1~3개와 반대논리를 제시하고, 실전 투입 결정(docs/paper-trading-plan.md "실전 투입 결정")과 충돌하지 않게 정리해 대표님께 한국어로 보고한다. 보고 전 keeper 체인·알림 이슈(#32, #34) 상태도 확인한다.

[2026-11-13 추가 — 반드시 반영] 상장폐지 종목을 복원한 데이터로 근거 연구를 다시 돌린 결과(docs/swing-monthly-review.md "코스닥 v2(폭 레짐 50) 재검증", docs/swing-upgrade-study-2026-10.md "2026-11-13 보완")를 먼저 읽는다. 요지: v2 백테스트는 CAGR 15.2% → 13.8%, PF 1.44, 최대 낙폭 −35.4%, 전반 5년 초과 +7.0%p(v1 +7.6%p와 같은 수준)이고 사전 등록 고정 기준으로는 불합격(기준 2·5)이다. 따라서 "v2가 사전 등록 연구에 합격했다"를 근거로 쓰지 않는다. v2 참고 경고선(보완 데이터): 60일 수익률 하위 5% −13.5%, 구간 최대낙폭 하위 5% −22.6%, 지수 대비 초과 하위 5% −13.6%p (D 판정은 고정 표 그대로).

[2026-11-13 추가 2 — 추천안의 틀] docs/swing-breadth-threshold-prereg-2026-11.md(사전 등록)를 읽고 그 "결정 규칙 제안" 표를 추천안의 틀로 쓴다. 검증 1(경로 오차, tools/path_noise.py, 방식당 40회 짝 비교)은 이미 끝났고 판정은 "오차 안"이다: v2 − v1 연 수익률 차이의 하위 5%가 체결 순서 무작위 +1.7%p(v2 우위 40/40), 신호 10% 누락 −1.1%p(33/40). 손익비와 최대 낙폭은 80회 모두 v2 우위(낙폭 중앙값 약 6~7%p 얕음). 같은 룰의 10년 CAGR은 경로에 따라 약 7~14%(표준편차 약 1.9%p)이므로 3%p 안쪽 차이를 근거로 쓰지 않는다. 코스닥 v1은 80회 모두 지수를 이겼다(최악 연 +4.7%p). 표에 따르면 검증 1이 "오차 안"이면 "룰 교체 보류(v1·v2 병행 연장 또는 v2 종료 중 선택)" 줄이 적용된다. 다만 "수익률이 아니라 낙폭을 줄이려고 v2를 쓴다"는 목적의 별도 안건은 올릴 수 있다. 검증 2(문턱 40·45·50·55 평탄성, tools/breadth_sensitivity.py)의 결과는 그 문서 끝이나 월간 검토 문서에 기록돼 있으면 함께 인용하고, 없으면 아직 돌리지 않았다고 적는다(45·55는 사전 등록 문서가 병합된 뒤에만 돌린다). 문턱값을 결과가 가장 좋았던 값으로 바꾸자는 추천은 하지 않는다.
```

참고: 이 원문이 가리키는 `docs/swing-breadth-threshold-prereg-2026-11.md`, `tools/path_noise.py`, `tools/breadth_sensitivity.py`는 PR #79에 있고, 2026-11-15 현재 기준 브랜치에는 아직 없다.

---

## 대시보드 갱신이 아티팩트를 다시 게시하는 방식

대시보드(`https://claude.ai/artifact/5JdurhpACTCAkvSuNZFFcJ`)는 Claude의 "Dashboard" 유형 아티팩트다. 페이지 자체는 다시 게시하지 않는다. 페이지가 읽는 데이터 파일 4개만 갈아 끼운다.

### 1단계: 데이터 파일 만들기

```bash
git fetch -q origin paper-trading swing-results claude/dazzling-ride-a0nb4k
python3 trading/tools/dash_data.py --repo . --out <임시폴더>/dashdata
```

`dash_data.py`는 작업 폴더가 아니라 git 브랜치에서 직접 읽는다(읽기 전용).

| 만드는 파일 | 읽는 곳 | 내용 |
|---|---|---|
| `latest.json` | `origin/paper-trading`의 `paper/latest.json` | 시장별 한 행: 기준일, 레짐, 성과, 보유, 대기 신호, 감사, 데이터 대조 |
| `equity.json` | `origin/paper-trading`의 `paper/<시장>/equity.csv` | 6개 장부의 일별 현금·평가액·자본·보유 수·노출 |
| `trades.json` | `origin/paper-trading`의 `paper/<시장>/trades.csv` | 6개 장부의 청산 거래 |
| `backtest.json` | `origin/swing-results`의 `latest/results/<시장>/results.json` | 5개 시장의 백테스트 지표(전체, 최근 1년, 연도별) |

실행하면 `2026-11-14T23:51:19Z latest=6 equity=215 trades=28 backtest=65`처럼 UTC 시각과 행 수를 한 줄로 출력한다. `latest=0`이면 대시보드를 건드리지 않는다.

### 2단계: 아티팩트에 올리기

1. `ArtifactData` list로 `datasets` 컬렉션의 문서 4개(`latest`, `equity`, `trades`, `backtest`)를 읽어 각 문서의 `version`과 지금의 `source.url`(`/_blob/<id>`)을 적어 둔다.
2. `Artifact` publish에 `asset: true`를 주어 파일 4개를 하나씩 올린다. 올릴 때마다 새 `/_blob/<id>` 주소가 나온다.
3. `ArtifactData` batch 한 번으로 문서 4개를 갱신한다. 각 문서에 `if_version`(1에서 읽은 값)을 걸고 `source.url`을 새 주소로, `updated.at`을 1단계가 출력한 UTC 시각으로 바꾼다.
4. batch가 성공한 뒤에만, 1에서 적어 둔 옛 자산 4개를 `Artifact` delete로 지운다.

### 옮길 때 알아 둘 점

- 이 절차는 `Artifact`와 `ArtifactData` 도구가 있는 Claude 세션에서만 된다. `gh`나 일반 명령으로는 아티팩트를 갱신할 수 없다.
- 2026-11-03 ~ 11-10에는 새 세션을 띄우는 방식으로 돌렸는데, 그 세션에 `ArtifactData` 도구가 없어 여러 번 조용히 실패했다. 그래서 도구가 있는 세션 안에서 돌리도록 바꿨다. 새 환경에서도 첫 실행 뒤 `datasets/latest` 문서의 `updated.at`이 실제로 바뀌었는지 확인해야 한다.
- 문서마다 `staleAfterHours: 30`이 있어, 30시간 넘게 갱신이 없으면 대시보드가 오래된 데이터로 표시한다. 일일 점검(1번)의 ⑧이 이것을 따로 확인한다.

## 옮길 때 고칠 점

- **"이 세션"이라는 표현:** 1·2·3·4번 원문은 묶인 세션을 전제로 한다. 새 환경의 이름으로 바꾼다.
- **도구 이름:** 3·4번 원문의 `mcp__github__actions_run_trigger`는 클라우드 세션의 GitHub 커넥터 도구 이름이다. 로컬에서는 `gh workflow run`으로 바꾼다.
- **경로:** 2번 원문의 `/home/user/beomstar_git`은 클라우드 컨테이너의 경로다.
- **3·4번은 곧 예비가 된다:** PR #79가 병합되면 `swing-paper-keeper`가 평일 08:50·12:05에 구간을 직접 시작한다. 그 뒤 3·4번은 "08:55·12:10에, 구간 실행이 없을 때만 시작"하는 예비로 바꿀 계획이었다.
- **병행 기간의 중복:** 두 환경이 같은 예약을 함께 돌려도 장부는 망가지지 않는다. `swing-paper`는 같은 데이터면 다시 커밋하지 않고, `kis-ws`는 같은 구간의 두 번째 실행이 스스로 끝난다. 다만 대시보드 갱신(2번)을 두 곳에서 같은 시각에 돌리면 한쪽의 batch가 버전 충돌로 실패할 수 있다. 시각을 몇 분 어긋나게 잡으면 된다.
- **맥락 의존:** 9·10번 판정 보고는 이 세션에서 쌓인 결정(실전 후보는 코스닥뿐, 판정 기준 해석 두 건, 사전 등록)에 기대고 있다. 근거는 모두 `docs/paper-trading-plan.md`, `docs/swing-monthly-review.md`, `docs/swing-improvement-policy.md`에 기록돼 있으니 새 환경은 이 문서들을 먼저 읽어야 한다.

## 세션과 무관하게 계속 도는 것 (GitHub Actions)

| 워크플로 | 하는 일 | 시작 방식 |
|---|---|---|
| `swing-paper-keeper.yml` | 5시간 45분짜리 작업이 `swing-paper`를 0·2·4시간에 시작시키고 다음 keeper로 넘김 | 연쇄 실행, 끊기면 `47 */6 * * *` 예약이 재시작 |
| `swing-paper.yml` | 6개 장부 갱신과 신호 커밋, 코스닥 신호 알림 댓글 | keeper가 시작, 자체 예약은 예비 |
| `kis-ws.yml` | 한국장 실시간 체결가 수신, 손절 근접 알림 | 세션 예약(3·4번), 자체 예약은 예비 |
| `swing-backtest.yml` | 테스트와 5개 시장 백테스트 | push·PR |
| `ai-cross-review.yml` | 키 방식 교차 검수(키가 없어 쉬는 상태) | PR |
