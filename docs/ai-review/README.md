# AI 교차 검수 (ChatGPT · Gemini)

**목적:** Claude가 올린 코드 PR을 ChatGPT(**Codex CLI**)와 Gemini(**Antigravity CLI**)가 읽기 전용으로 교차 검수해서, 한 모델의 확신에서 나오는 실수를 잡는다. 채택된 지적은 교훈 파일로 쌓아 다음 검수에 쓴다.

## 흐름
| 단계 | 내용 |
|---|---|
| 1차 | ChatGPT(Codex CLI, 저장소 전체를 읽기 전용 샌드박스에서 탐색)는 코드 정확성·경계 조건·테스트를, Gemini는 매매 룰·데이터 가정·문서 일치·빠진 부분을 맡아 같은 변경분을 각자 검수 |
| 2차 | 서로의 지적을 읽고 동의 / 반박 / 모름 + 둘 다 놓친 것 추가 |
| 정리 | PR 댓글 하나로 합산: 합의 → 의견 갈림 → 한쪽만 지적 → 추가 → 빠진 부분 → 교훈 후보 (푸시마다 같은 댓글이 갱신됨) |
| 반영 | Claude가 지적마다 재현·확인 후 수정하거나 근거를 들어 반박. 의견이 갈리면 대표님께 보고 |
| 학습 | 채택된 교훈을 `lessons.md`에 추가 → 다음 검수부터 세 모델 모두 먼저 읽음 |

## 설정 (대표님, 한 번만)
1. **API 키 2개를 발급합니다.** ChatGPT·Antigravity 구독과 API는 별개라서 따로 받아야 합니다.
   - OpenAI: platform.openai.com → API keys → Create new secret key
   - Gemini: aistudio.google.com → Get API key
2. **GitHub에 등록합니다.** 저장소 → Settings → Secrets and variables → Actions → **Secrets** 탭 → New repository secret
   - `OPENAI_API_KEY` (Codex CLI가 `CODEX_API_KEY`로 받아 씀)
   - `GEMINI_API_KEY`
   - 하나만 등록하면 그쪽만 검수합니다.
3. (선택) 같은 화면 **Variables** 탭에서 모델을 지정합니다: `OPENAI_REVIEW_MODEL`, `GEMINI_REVIEW_MODEL`.
   - 비워 두면 각 CLI의 기본 모델을 씁니다.
   - 이름이 틀리면 CLI의 오류 메시지가 검수 댓글에 나옵니다.

## 안전장치
- 검수자는 읽기만 합니다. 저장소 쓰기, 자동 수정, 병합 권한은 없습니다.
  - Codex는 `--sandbox read-only`로 돌아 파일을 바꿀 수 없습니다.
  - Antigravity CLI는 읽기 전용 모드가 없습니다. 그래서 권한 승인을 생략하는 옵션은 쓰지 않습니다. 대신 검수 내용을 프롬프트에 직접 넣고 "도구 사용 금지"로 지시하며, 15분 시간 제한을 둡니다.
  - 검수 작업에는 읽기 토큰만 줍니다. 댓글은 키도 PR 코드도 없는 별도 작업이 올립니다.
- 키는 Secrets에서 검수 단계에만 주입하고 출력하지 않습니다. 다른 사람이 fork해서 연 PR에는 키를 주지 않습니다.
- 키가 없으면 아무것도 하지 않습니다(댓글도 없음).
- 비용: PR 한 번 푸시에 CLI 실행 4번(1차 2번 + 2차 2번). 변경분은 10만 자에서 자릅니다. Codex는 파일을 더 읽는 만큼 호출이 늘 수 있습니다. 실제 금액은 첫 주 사용량으로 확인합니다.
- 확인 전 사항: Antigravity CLI의 설치 스크립트와 API 키 변수(`GEMINI_API_KEY`)는 문서 사이트가 이 환경에서 막혀 있어 검색 결과로만 확인했습니다. 첫 실행에서 실패하면 그 원인이 검수 댓글에 그대로 나옵니다.

## 파일
- `brief.md`: 검수자 지침(프로젝트, 금지 사항, 좋은 지적의 기준)
- `lessons.md`: 공유 교훈(검증된 것만)
- `trading/tools/ai_review.py`: 검수 도구 · `.github/workflows/ai-cross-review.yml`: 실행
