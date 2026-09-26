# 프로젝트 스킬

이 저장소에서 Claude Code를 쓸 때 자동으로 불러오는 스킬입니다. 선정 근거는 [`docs/top-10-agent-skills-2026-09.md`](../../docs/top-10-agent-skills-2026-09.md)에 있습니다.

## 적용된 스킬

| 스킬 | 켜지는 방식 | 하는 일 |
|---|---|---|
| `karpathy-guidelines` | 코드 작성·수정·리뷰 시 자동 | 과설계 금지, 요청받은 곳만 수정, 가정 명시, 검증 가능한 완료 기준 |
| `systematic-debugging` | 버그·예상 밖 동작이 생기면 자동 | 재현 → 원인 추적 → 가설 검증 → 수정. 원인을 찾기 전에는 고치지 않음 |
| `verification-before-completion` | "완료/고쳤음/통과"라고 말하기 직전 자동 | 검증 명령을 실제로 돌리고 결과를 확인한 뒤에만 완료 보고 |
| `grill-me` | **`/grill-me`로 직접 호출할 때만** | 계획·설계를 질문 라운드로 끝까지 파고들어 빈틈을 없앰 |

## 출처 (버전 고정)

| 스킬 | 원본 | 커밋 | 라이선스 |
|---|---|---|---|
| `karpathy-guidelines` | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) `skills/karpathy-guidelines` | `2c606141936f1eeef17fa3043a72095b4765b9c2` | MIT (SKILL.md와 원본 README에 명시) |
| `systematic-debugging` | [obra/superpowers](https://github.com/obra/superpowers) `skills/systematic-debugging` | `5bf4e78011075bcfc0dc295f0724994cd123ee71` | MIT, `LICENSE` 동봉 |
| `verification-before-completion` | [obra/superpowers](https://github.com/obra/superpowers) `skills/verification-before-completion` | `5bf4e78011075bcfc0dc295f0724994cd123ee71` | MIT, `LICENSE` 동봉 |
| `grill-me` | [mattpocock/skills](https://github.com/mattpocock/skills) `skills/productivity/grill-me` + `grilling` | `c55ee46073ed923f86ce59a5eb3b6d895095d1b7` | MIT, `LICENSE` 동봉 |

## 원본에서 바꾼 점

- `karpathy-guidelines`: "불확실하면 질문" 규칙 아래에 "결과를 크게 바꿀 때만 질문하고, 그 외에는 가정을 명시하고 진행"이라는 로컬 규칙을 한 줄 추가했습니다.
- `systematic-debugging`: `superpowers:` 접두어를 지웠습니다. 이 저장소에는 테스트 프레임워크가 없어서 TDD 스킬 참조를 "일회성 재현 스크립트 작성"으로 바꿨습니다. 스킬 개발용 파일(`test-pressure-*.md`, `test-academic.md`, `CREATION-LOG.md`)은 빼고 가져왔습니다.
- `grill-me`: 원본은 `grill-me`가 `grilling` 스킬을 다시 호출하는 구조입니다. 직접 호출할 때만 켜지도록 두 파일을 하나로 합쳤습니다.
- `verification-before-completion`: 원문 그대로입니다.

## 일부러 넣지 않은 스킬

- **ponytail, caveman**: 모든 응답에 항상 켜져서 보고 형식을 덮어씁니다.
- **superpowers 전체**: `using-superpowers`가 모든 응답 앞에 스킬 호출을 강제하고, 브레인스토밍 단계가 작업을 무겁게 만듭니다. 필요한 두 개만 골랐습니다.
- **frontend-design, ui-ux-pro-max**: 기존 앱 디자인을 임의로 바꿀 위험이 있습니다. 새 앱을 만들 때 다시 검토합니다.
- **webapp-testing**: 내장 `run` 스킬과 역할이 겹치고, Python Playwright가 필요합니다.

## 업데이트 방법

원본 저장소의 새 커밋을 확인하고, 변경분을 읽은 뒤에 파일을 교체하고, 위 표의 커밋 값을 갱신합니다. 자동 업데이트는 쓰지 않습니다.
