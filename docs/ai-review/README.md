# AI 교차 검수 (ChatGPT · Gemini)

**목적:** Claude가 올린 코드 PR을 ChatGPT와 Gemini가 읽기 전용으로 교차 검수해서, 한 모델의 확신에서 나오는 실수를 잡는다. 채택된 지적은 교훈 파일로 쌓아 다음 검수에 쓴다.

## 흐름
| 단계 | 내용 |
|---|---|
| 1차 | ChatGPT는 코드 정확성·경계 조건·테스트를, Gemini는 매매 룰·데이터 가정·문서 일치·빠진 부분을 맡아 같은 변경분을 각자 검수 |
| 2차 | 서로의 지적을 읽고 동의 / 반박 / 모름 + 둘 다 놓친 것 추가 |
| 정리 | PR 댓글 하나로 합산: 합의 → 의견 갈림 → 한쪽만 지적 → 추가 → 빠진 부분 → 교훈 후보 (푸시마다 같은 댓글이 갱신됨) |
| 반영 | Claude가 지적마다 재현·확인 후 수정하거나 근거를 들어 반박. 의견이 갈리면 대표님께 보고 |
| 학습 | 채택된 교훈을 `lessons.md`에 추가 → 다음 검수부터 세 모델 모두 먼저 읽음 |

## 설정 (대표님, 한 번만)
1. **API 키 2개를 발급합니다.** ChatGPT·Antigravity 구독과 API는 별개라서 따로 받아야 합니다.
   - OpenAI: platform.openai.com → API keys → Create new secret key
   - Gemini: aistudio.google.com → Get API key
2. **GitHub에 등록합니다.** 저장소 → Settings → Secrets and variables → Actions → **Secrets** 탭 → New repository secret
   - `OPENAI_API_KEY`
   - `GEMINI_API_KEY`
   - 하나만 등록하면 그쪽만 검수합니다.
3. (선택) 같은 화면 **Variables** 탭에서 모델을 지정합니다: `OPENAI_REVIEW_MODEL`, `GEMINI_REVIEW_MODEL`.
   - 비워 두면 기본값을 씁니다.
   - 이름이 틀리면 검수 댓글에 그 계정에서 쓸 수 있는 모델 목록이 나옵니다.

## 안전장치
- 검수자는 읽기만 합니다. 저장소 쓰기, 자동 수정, 병합 권한은 없습니다.
- 키는 Secrets에서 검수 단계에만 주입하고 출력하지 않습니다. 다른 사람이 fork해서 연 PR에는 키를 주지 않습니다.
- 키가 없으면 아무것도 하지 않습니다(댓글도 없음).
- 비용: PR 한 번 푸시에 모델 호출 4번(1차 2번 + 2차 2번). 변경분은 12만 자에서 자르고, 답변 길이도 상한을 둡니다. 실제 금액은 첫 주 사용량으로 확인합니다.

## 파일
- `brief.md`: 검수자 지침(프로젝트, 금지 사항, 좋은 지적의 기준)
- `lessons.md`: 공유 교훈(검증된 것만)
- `trading/tools/ai_review.py`: 검수 도구 · `.github/workflows/ai-cross-review.yml`: 실행
