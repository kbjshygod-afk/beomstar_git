# GitHub 인기 에이전트 스킬 Top 10 (2026-09-25 기준)

## 목적

Claude Code·Codex·Cursor 등에서 쓰는 Agent Skills(`SKILL.md`) 가운데 GitHub에서 가장 인기 있는 10개를 실측 데이터로 추리고, 설치 여부를 판단할 근거를 남긴다.

## 선정 기준

| 항목 | 기준 |
|---|---|
| 순위 | GitHub 스타 수 (2026-09-25 15:49 UTC, GitHub 검색 API로 확인) |
| 포함 | 저장소 안에 실제 스킬 파일(`SKILL.md` 또는 스킬 정의 md)이 있는 것. 각 저장소를 직접 클론해서 확인 |
| 제외 | 스킬을 "지원"만 하는 앱·플랫폼(dify, cc-switch, lobehub, open-design 등)과 링크 모음(awesome-* 목록) |
| 상승 속도 | 일평균 스타 = 총 스타 ÷ 생성 후 경과일. **추정치**이며 최근 7일 증가량이 아님 |

## 핵심 요약

- **1위 superpowers (29.2만⭐)**: 개발 방법론 스킬 묶음. 브레인스토밍 → 계획 → TDD → 코드리뷰 → 브랜치 마무리 흐름을 에이전트에게 강제한다.
- **가장 빠르게 뜨는 스킬은 ponytail**: 6월 12일에 생성돼 하루 평균 약 1,389⭐. "필요한 만큼만 가장 짧게" 코딩하게 만든다.
- **공식 anthropics/skills (17.8만⭐)**: 이 안의 `docx`·`xlsx`·`pptx`·`pdf`·`skill-creator`는 현재 Claude 환경에 이미 설치돼 있어서 따로 설치할 필요가 없다.

## Top 10

| # | 스킬 (저장소) | 스타 | 생성일 | 일평균 스타 | 스킬 수 | 한 줄 요약 |
|---|---|---:|---|---:|---:|---|
| 1 | [obra/superpowers](https://github.com/obra/superpowers) | 291,509 | 2025-10-09 | 831 | 15 | 개발 방법론 스킬: 브레인스토밍·계획·TDD·디버깅·리뷰·서브에이전트 |
| 2 | [mattpocock/skills](https://github.com/mattpocock/skills) | 269,520 | 2026-02-03 | 1,152 | 38 | 실무 엔지니어링 스킬 모음. `grill-me`(집요한 질문으로 계획·설계를 다듬음)가 대표 |
| 3 | [affaan-m/ECC](https://github.com/affaan-m/ECC) | 267,301 | 2026-01-18 | 1,069 | 903 | 스킬·메모리·보안·훅을 한꺼번에 까는 에이전트 하네스 (초대형) |
| 4 | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 215,095 | 2026-01-27 | 893 | 1 | 카파시의 LLM 코딩 실수 관찰을 규칙 4개로 정리: 먼저 생각, 단순하게, 필요한 곳만 수정, 목표 기반 실행 |
| 5 | [anthropics/skills](https://github.com/anthropics/skills) | 178,143 | 2025-09-22 | 484 | 19 | Anthropic 공식 스킬: docx/xlsx/pptx/pdf, frontend-design, skill-creator, mcp-builder 등 |
| 6 | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | 145,833 | 2026-06-12 | **1,389** | 6 | "가장 게으른 시니어 개발자" 모드: YAGNI, 표준 라이브러리 우선, 코드량 최소화 |
| 7 | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 130,574 | 2025-11-30 | 437 | 7 | UI/UX 디자인 지식 스킬: 디자인 시스템, 브랜드, 배너, 슬라이드 |
| 8 | [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | 121,366 | 2026-04-03 | 694 | 1 | 코드베이스·문서·SQL·PDF를 질의 가능한 지식 그래프로 변환 (`/graphify`) |
| 9 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | 107,822 | 2026-04-04 | 620 | 20 | "원시인 말투"로 출력 토큰을 줄이는 밈 계열 스킬. 저장소는 약 65% 절감을 주장 |
| 10 | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | 99,005 | 2026-02-15 | 446 | 25 | Addy Osmani의 프로덕션 엔지니어링 스킬: 스펙·보안·성능·CI/CD·리뷰 |

차순위: [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) 90,051 · [tt-a1i/archify](https://github.com/tt-a1i/archify) 71,548 · [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) 62,799 · [blader/humanizer](https://github.com/blader/humanizer) 51,975

## 스킬별 설치 명령 (각 README 원문 기준)

| # | 스킬 | Claude Code 설치 명령 |
|---|---|---|
| 1 | superpowers | `/plugin install superpowers@claude-plugins-official` |
| 2 | mattpocock/skills | `npx skills@latest add mattpocock/skills` 또는 `/plugin install mattpocock-skills` |
| 3 | ECC | `npx ecc-universal@2.2.2 install --guided` (`--dry-run`으로 먼저 확인 권장) |
| 4 | karpathy-skills | `/plugin marketplace add forrestchang/andrej-karpathy-skills` → `/plugin install andrej-karpathy-skills@karpathy-skills` ※ 저장소가 multica-ai로 이전됨. README 명령은 옛 경로 기준 |
| 5 | anthropics/skills | `/plugin marketplace add anthropics/skills` → `/plugin install document-skills@anthropic-agent-skills` |
| 6 | ponytail | `/plugin marketplace add DietrichGebert/ponytail` → `/plugin install ponytail@ponytail` |
| 7 | ui-ux-pro-max | `/plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill` → `/plugin install ui-ux-pro-max@ui-ux-pro-max-skill` |
| 8 | graphify | `uv tool install graphifyy` (파이썬 CLI 설치 후 스킬 등록) |
| 9 | caveman | `claude plugin marketplace add JuliusBrussee/caveman && claude plugin install caveman@caveman` |
| 10 | addyosmani/agent-skills | `npx skills add addyosmani/agent-skills --list`로 목록을 본 뒤 필요한 것만 `--skill <이름>`으로 설치 |

## 참고: 설치 수 기준 순위 (2차 출처)

스타는 "저장소 단위" 인기이고, 실제 사용량은 스킬 단위 설치 수로 봐야 한다. [LinklyAI/best-skills](https://github.com/LinklyAI/best-skills)의 종합 점수(Best 100, 2026-09-25 갱신) 상위 5개는 다음과 같다.

1. agent-browser (vercel-labs)
2. frontend-design (anthropics)
3. find-skills (vercel-labs)
4. grill-me (mattpocock)
5. nano-banana-pro (steipete)

※ 설치 수 원천인 skills.sh는 이 작업 환경에서 접속이 차단돼 직접 검증하지 못했다.

## 권장 도입안

| 구분 | 스킬 | 이유 |
|---|---|---|
| 오늘 | karpathy-skills | 파일 1개, 규칙 4개. 부작용이 가장 적고 코딩 실수(과설계, 불필요한 수정)를 바로 줄인다 |
| 이번 주 | superpowers **또는** mattpocock/skills 중 1개만 | 둘 다 개발 흐름 자체를 바꾸므로 동시에 설치하면 충돌한다. 개발 프로젝트 하나에서 먼저 시험 |
| 이번 주 (UI 작업 시) | ui-ux-pro-max 또는 taste-skill | 앱 화면 품질 개선용. UI 작업이 있을 때만 |
| 보류 | ponytail, caveman | 모든 응답에 항상 켜지는 모드라 기존 답변 형식을 덮어쓴다. caveman은 영어 토큰 절약용이라 한국어 보고 품질이 떨어질 수 있다 |
| 보류 | graphify | 대형 코드베이스용. 이 저장소 규모에서는 이득이 작다 |
| 폐기 | ECC | 스킬 903개짜리 하네스. 설정 충돌·컨텍스트 낭비 위험이 이득보다 크다 |
| 설치 불필요 | anthropics/skills | 문서 스킬(docx/xlsx/pptx/pdf)과 skill-creator가 이미 설치돼 있다 |

## 리스크

1. **보안**: 제3자 스킬은 에이전트에게 지시문을 주입하고, `scripts/`가 있으면 코드도 실행한다. 설치 전에 `SKILL.md`와 스크립트를 직접 읽고, 필요하면 [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector) 같은 스캐너로 점검한다.
2. **스타 ≠ 품질**: 급등한 저장소 가운데 일부는 바이럴·밈 성격이다(caveman은 스스로 밈이라고 소개한다).
3. **상시 모드 충돌**: ponytail·caveman·superpowers(`using-superpowers`)는 매 응답에 개입해서 기존 지침과 부딪칠 수 있다.
4. **버전 변동**: `@latest`로 설치하면 업데이트 때 동작이 바뀐다. 검증한 뒤에는 버전이나 커밋을 고정한다.

## 의사결정 포인트

- 설치 범위: 이 저장소에만 적용(`.claude/skills/`)할지, 개인 전역(`~/.claude/skills/`)에 적용할지
- 개발 방법론 스킬을 superpowers로 할지 mattpocock/skills로 할지 (둘 중 하나만 선택)
