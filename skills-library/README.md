# 업무 자동화·코인 기술적 분석·미국 주식/ETF 거시 매매 스킬

이 폴더의 스킬은 이 저장소에서 자동으로 켜지지 않습니다. 쓰려면 아래 방법으로 claude.ai 또는 Claude Code에 설치합니다.

## 대표님 룰 스킬: `swing-scanner-rules` (우선 사용)

대표님 매매 스캐너의 룰(2026-09-04 룰 시트)을 그대로 옮긴 스킬입니다. 종목을 물으면 이 룰만으로 판정합니다: 트렌드 템플릿 8/8, 피벗 돌파와 거래량 1.4배, 추격 15% 제한, 시장별 레짐, 손절 −7%/−10%, 50일선 종가 이탈 청산, 0.75% 위험 기준 수량, 목표가 없음.

| 항목 | 내용 |
|---|---|
| 위치 | `trading/swing-scanner-rules/`, 업로드용 `dist/swing-scanner-rules.zip` |
| 수치 출처 | ① 매일 모의투자가 올리는 종목별 상태표(`paper-trading` 브랜치의 `status.csv`) ② 같이 들어 있는 엔진을 Yahoo 데이터나 트레이딩뷰 CSV로 실행 ③ 둘 다 안 되면 CSV를 요청하고 추정하지 않음 |
| 엔진 검증 | 트레이딩뷰 지표를 따로 옮긴 코드와 일봉 492,965개를 대조해 불일치 0건 |
| 10년 백테스트 | `trading/swing-scanner-rules/references/backtest-ko.md` (스캐너 계기판 수치와 나란히 비교) |
| 모의투자 | 판정 기준은 `docs/paper-trading-plan.md`에 미리 고정 |
| 동작 시험 | "AAPL 지금 사도 돼? 내 스윙 룰로 봐줘" → 스킬 호출, 상태표 수치와 일치, 목표가 없음, 데이터 기준일·추정값 7개 표시, S&P500·나스닥100 두 손절 기준을 함께 제시 |
| 필요 환경 | 상태표만 읽을 때는 GitHub 접속만 있으면 됩니다. 엔진을 직접 돌릴 때는 Python과 `pandas`, `numpy`, `yfinance`가 필요합니다 |

**같이 켜지 않는 것을 권하는 스킬:** `technical-analyst`(목표가·패턴 판단), `position-sizer`(다른 수량 공식), `exposure-coach`(다른 노출 상한), `crypto-regime-analyzer`(다른 코인 국면 기준). 대표님 룰과 다른 답을 내서 판단이 섞일 수 있습니다. 거시 참고용(`digital-oracle`, `macro-regime-detector`, 참여도·섹터 스킬)은 룰을 바꾸지 않는 배경 정보로만 씁니다.

## 조사한 공개 스킬 10개 (2026-09-25)

GitHub 공개 스킬을 분야별로 조사해 고른 10개입니다.

### 한눈에 보기

| 분야 | 스킬 | 하는 일 | 데이터·키 | 매매 주문 |
|---|---|---|---|---|
| 업무 자동화 | `google-apps-script` | 구글 시트 자동화 코드 작성: 메뉴, 정기 실행 트리거, 메일 발송, PDF 내보내기, 팀 웹앱 수정 | 없음 | - |
| 코인 | `crypto-regime-analyzer` | 코인 시장 국면 점수(0~100): BTC 50/200일선, 알트 참여도, 도미넌스, 펀딩비, 낙폭·변동성, 모멘텀 | CoinGecko·바이낸스 공개 API, 키 없음 | 없음 |
| 코인·주식 | `technical-analyst` | 차트 캡처를 읽어 시나리오 2~4개와 각 시나리오의 무효화 가격을 제시 (주봉 중심) | 차트 이미지 | 없음 |
| 거시 | `digital-oracle` | 금리·연준 경로·물가 기대를 시장 가격으로 읽음: 국채 곡선, 실질금리, Kalshi 연준 계약, CFTC 포지션, 공포탐욕지수, 옵션 내재변동성 | 공개 API, 키 없음 | 없음 |
| 거시 | `macro-regime-detector` | 자산 간 비율 6개(RSP/SPY, 10Y−2Y, HYG/LQD, IWM/SPY, SPY/TLT, XLY/XLP)로 거시 국면 5단계 판정 | Yahoo(yfinance), 키 없음 | 없음 |
| 거시 | `market-breadth-analyzer` | 시장 참여도(상승·하락 종목 비율, 신고가·신저가) 점수 | 공개 CSV, 키 없음 | 없음 |
| 거시 | `uptrend-analyzer` | 상승 추세 종목 비율로 본 시장 참여도와 노출 가이드 | 공개 CSV, 키 없음 | 없음 |
| 거시 | `sector-analyst` | 섹터 순환, 경기민감 vs 방어, 과매수·과매도 섹터 | 공개 CSV, 키 없음 | 없음 |
| 거시 | `exposure-coach` | 위 결과를 합쳐 주식 노출 상한(%)과 판정 제시: 신규 진입 허용 / 축소만 / 현금 우선 | 위 스킬 출력 파일 | 없음 |
| 거시 | `position-sizer` | 계좌 대비 위험 %, 진입가, 손절가로 매수 수량 계산 | 없음 (계산만) | 없음 |

**어떤 스킬도 주문을 내지 않습니다.** 모두 분석과 계산만 하고, 매매 판단은 사용자가 합니다.

### 사용 순서 (미국 주식·ETF)

1. `digital-oracle`: 금리·연준·물가 기대로 거시 배경 확인
2. `macro-regime-detector`: 자산 간 비율로 지금이 어떤 국면인지 판정
3. `market-breadth-analyzer` + `uptrend-analyzer`: 상승이 넓게 퍼져 있는지 확인
4. `sector-analyst`: 어느 섹터로 돈이 도는지 확인
5. `exposure-coach`: 1~4를 합쳐 노출 상한과 신규 진입 가능 여부 판정
6. `position-sizer`: 개별 종목의 손절가 기준 매수 수량 계산

코인: `crypto-regime-analyzer`로 시장 국면을 보고, 트레이딩뷰 차트를 캡처해 `technical-analyst`로 시나리오와 무효화 가격을 받습니다.

## 설치

### claude.ai (웹·앱)

1. `dist/`의 zip 파일을 받습니다 (스킬 하나당 zip 하나).
2. 설정 → 기능(Capabilities) → 스킬 → 업로드.
3. **데이터를 가져오는 스킬**은 코드 실행의 인터넷 접속이 필요합니다. 필요 없는 것은 `google-apps-script`, `technical-analyst`의 차트 분석, `exposure-coach`, `position-sizer`입니다. `swing-scanner-rules`는 `raw.githubusercontent.com` 접속이 필요하고, 엔진을 직접 돌릴 때는 Yahoo 접속도 필요합니다. 설정 → 기능 → "코드 실행 및 파일 생성"에서 네트워크 접속을 **모든 도메인** 또는 필요한 도메인 허용으로 바꿉니다. Team·Enterprise 요금제는 조직 관리자가 바꿉니다. 접속이 막히면 스킬은 추정값을 만들지 않고 오류로 멈춥니다.

### Claude Code (맥)

```bash
git clone --depth 1 -b claude/github-top-10-skills-k1u8yp https://github.com/kbjshygod-afk/beomstar_git.git /tmp/beomstar-skills
mkdir -p ~/.claude/skills
cp -R /tmp/beomstar-skills/skills-library/trading/swing-scanner-rules ~/.claude/skills/
# 필요한 공개 스킬만 골라서 복사 (위 '같이 켜지 않는 것을 권하는 스킬' 참고)
cp -R /tmp/beomstar-skills/skills-library/automation/google-apps-script ~/.claude/skills/
pip3 install requests yfinance pandas numpy
```

`~/.claude/skills/`에 넣으면 모든 프로젝트에서 켜집니다. 맥에서는 네트워크 제한이 없어서 데이터를 가져오는 스킬을 쓰기가 가장 편합니다.

## 주의할 점

- **`exposure-coach`는 입력이 모자라면 신뢰도 LOW로 매우 보수적인 결과를 냅니다.** 시험 삼아 입력 하나(uptrend)만 넣었더니 "노출 상한 4%, 현금 우선, 신뢰도 LOW"가 나왔습니다. 이것은 시장 판단이 아니라 데이터 부족 때문입니다. 신뢰도가 LOW면 노출 상한 숫자는 무시합니다.
- **거시 판단은 가격에서 추론합니다.** `macro-regime-detector`는 CPI·고용 같은 경제지표를 직접 보지 않고 자산 가격 비율로 국면을 판단합니다. 경제지표와 금리 경로는 `digital-oracle`로 보완합니다.
- **검증 수준:** 점수 가중치와 노출 표는 경험칙이며 원작자도 백테스트 검증 전이라고 표시했습니다. 대표님 스캐너 룰(지수가 200일선 위일 때만 신규 진입, 시장별 손절 −7%/−10%)과 다르면 **스캐너 룰이 우선**입니다.
- **데이터 출처가 한 사람입니다.** `market-breadth-analyzer`, `uptrend-analyzer`, `sector-analyst`는 원작자(tradermonty)가 GitHub에 올리는 CSV를 씁니다. 결과에 데이터 날짜가 찍히니 당일 데이터인지 확인합니다.
- **코인 스킬의 한계:** 미결제약정, 청산, 롱숏 비율, 매물대 분석은 없습니다. `crypto-regime-analyzer`의 펀딩비는 바이낸스 한 곳의 최신값이고, 같은 날 다시 돌리면 캐시(최대 약 24시간 전 데이터)를 씁니다. 당일 데이터가 필요하면 `.crypto_regime_cache` 폴더를 지우고 실행합니다.
- **출력 언어:** 일부 스킬은 영어로 분석하도록 적혀 있습니다. 최종 보고는 대표님 지침대로 한국어로 요청하면 됩니다.
- **API 키:** 필수 키는 없습니다. `technical-analyst`의 스크립트 모드와 `macro-regime-detector`의 일부 보조 기능만 FMP 키(`FMP_API_KEY` 환경변수)를 쓰고, 없으면 건너뜁니다. 키는 채팅에 붙여넣지 않습니다.

## 검증 결과 (2026-09-25)

| 항목 | 결과 |
|---|---|
| 원문 대조 | tradermonty 스킬 8개는 원작자의 공식 배포 패키지와 파일 단위로 일치 (추가 파일은 LICENSE뿐) |
| 보안 점검 | 전 스크립트 확인: 주문 기능·비밀키 사용·외부 전송·숨은 지시문 없음. 접속 대상은 공개 시세·데이터 사이트뿐 |
| 단위 테스트 | crypto-regime-analyzer 84, technical-analyst 123, macro-regime-detector 113, market-breadth-analyzer 134, uptrend-analyzer 200, sector-analyst 47, exposure-coach 108, position-sizer 42, digital-oracle 246개 통과 |
| 실제 데이터 실행 | uptrend-analyzer·sector-analyst는 2026-09-24자 데이터로 정상 실행. position-sizer는 손 계산과 일치 (10만 달러, 1% 위험, 100→90달러: 100주) |
| 동작 시험 (`google-apps-script`) | 아래 "원본에서 바꾼 점"의 검증 항목 참고 (타입 검사, 모의 실행 12개 시나리오, 실제 호출 12개 항목) |
| 접속 차단 시 동작 | Yahoo·CoinGecko가 막힌 환경에서 macro-regime-detector와 crypto-regime-analyzer는 추정값 없이 오류로 멈춤 |

테스트 3건은 원작자 저장소의 폴더 구조를 전제한 탓에 실패했고, 원본 구조에서 다시 돌리면 통과합니다(macro-regime-detector 1건은 원작자 저장소에 배포 파일이 있는지 검사하는 항목이라 해당 없음).

## 출처 (버전 고정)

| 스킬 | 원본 | 커밋 | 라이선스 |
|---|---|---|---|
| `google-apps-script` | [jezweb/claude-skills](https://github.com/jezweb/claude-skills) `plugins/integrations/skills/google-apps-script` | `e875a6bfff809e5d42c584104031e36e1f014f18` | MIT |
| tradermonty 스킬 8개 | [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) `skills/<이름>` | `28503f67265b9e57a40175b8ded222cd9271deac` | MIT |
| `digital-oracle` | [komako-workshop/digital-oracle](https://github.com/komako-workshop/digital-oracle) (SKILL.md, `digital_oracle/`, `references/`) | `a63e4c19a2f3313d54914c44666febaf5ffb9d6f` | MIT |

각 스킬 폴더에 원본 `LICENSE`를 넣었습니다. 테스트 파일과 캐시는 빼고 가져왔습니다.

### 원본에서 바꾼 점

`digital-oracle`: 앞머리 설정의 `version` 항목을 `metadata` 안으로 옮겼습니다. claude.ai 업로드 검증기가 허용하지 않는 항목이라서입니다. 내용은 그대로입니다.

`google-apps-script` (2차 개선 2026-09-25):

**원본 코드의 오류 11건 수정.** 1~9번은 원본과 수정본을 Apps Script 모의 환경에서 같은 조건으로 실행해 재현하고 해결을 확인했습니다. 10~11번은 코드 검토로 확인했습니다.

| # | 원본 동작 | 수정 |
|---|---|---|
| 1 | 외부 API 예제가 정의되지 않은 `getApiKey()`를 호출해 즉시 ReferenceError (2곳) | `getSecret_()`로 Script Properties에서 읽음. 없으면 무엇이 빠졌는지 알려 줌 |
| 2 | 수신자 시트에 헤더만 있으면 헤더를 수신자로 처리하고, 빈 2행에 오류 문구를 기록 | 데이터가 없으면 바로 종료 |
| 3 | 트리거 설치 함수를 두 번 실행하면 트리거가 2개씩 생겨 메일이 두 번 발송 | 같은 이름의 트리거를 지운 뒤 설치 (`removeTriggers_`) |
| 4 | onEdit: 여러 행을 붙여넣으면 첫 행만 시간 기록, 헤더(C1)를 고치면 헤더(D1)를 날짜로 덮어씀 | 붙여넣은 모든 행에 기록하고 헤더 행은 건너뜀 |
| 5 | 주간 메일이 `getActiveSheet()`를 써서, 트리거로 실행하면 첫 번째 탭을 읽고 빈 표를 발송 | 탭 이름을 지정해서 읽음 |
| 6 | 같은 메일의 헤더는 4열, 데이터는 5열이라 표가 어긋남 | 헤더를 시트에서 그대로 읽음 |
| 7 | 셀 값·이름에 `<`, `&`가 있으면 메일·대화상자 HTML이 깨지거나 마크업이 주입됨 | 모든 HTML 출력을 이스케이프 (`escapeHtml_`) |
| 8 | 보관 기능이 행 순서를 뒤집어 옮기고, 한 행씩 개별 쓰기 | 원래 순서로 한 번에 복사하고, 연속 구간 단위로 삭제해 남는 행의 수식 보존 |
| 9 | POST가 201(생성 성공)을 돌려주면 오류로 처리 | 2xx를 모두 성공으로 처리. 429는 재시도하고, 5xx는 GET만 재시도(POST 중복 방지) |
| 10 | 할당량 부족 시 `getUi().alert()`를 호출해, 트리거로 실행하면 "이 컨텍스트에서 getUi 호출 불가" 오류 | 오류를 던져서 실행 기록에 남김 |
| 11 | 비공개 함수(`_`)를 대화상자에 넘겨도 막지 않고, 실패를 "조용히 실패"로 잘못 설명 | 공개 함수만 허용하고, 실제 증상(콘솔 오류, "Script function not found")을 안내 |

**빠진 내용 보완.**
- 규칙: 여러 파일이 하나의 전역 범위를 공유함(`const` 중복, `onOpen`/`onEdit` 덮어쓰기), 스크립트 시간대와 시트 시간대 차이, `getValues`와 `getDisplayValues` 차이, onEdit는 사람이 한 편집에만 반응(가져오기·동기화 제외), 트리거 소유자 계정이 권한을 잃으면 중단, 동시 실행 잠금, 비밀값 분리
- 새 패턴: 헤더 이름으로 열 찾기(열을 끼워 넣어도 안 깨짐), 슬랙 알림, 6분 넘는 작업 이어서 실행, 최소 웹앱, 중복 강조를 한 번의 쓰기로 처리
- 절차: 설치 후 검증 단계(Step 5: 실행 기록, 트리거 1개 확인, 실패 알림), 증상별 해결표 확대, 납품 체크리스트
- 헤더를 모르면 질문으로 멈추지 않고 가정을 밝힌 뒤 코드를 냄
- 구조: SKILL.md를 541줄에서 약 220줄로 줄이고 코드는 `references/patterns.md`로 옮김. 필요한 부분만 읽어서 대화 공간을 덜 씀

**1차 개선 (유지).** "기존 코드 삭제 후 붙여넣기"를 "새 파일 추가"로 바꿈, 운영 중인 시트 변경 전 승인 단계, 한국어 팀 웹앱 안전 문서, `compatibility: claude-code-only` 삭제, 근거 없는 할당량 행 삭제, 한국어 호출어 추가.

**검증.**
- 예제 코드 20블록을 `@types/google-apps-script`로 타입 검사: 원본 8건 → 수정본 0건. 검사기에 일부러 틀린 API 3개를 넣어 모두 잡는지 확인함
- 대화상자·사이드바 안의 브라우저 코드 문법 검사 통과
- 모의 실행 12개 시나리오 통과 (그중 9개는 원본과 비교). 헤더 이름으로 열 찾기 단위 테스트 통과
- 실제 호출 테스트: "기존 스크립트가 있는 시트에서 'Orders'를 매주 월요일 8시 슬랙으로 요약" 요청으로 12개 항목을 점검해 모두 통과함(스킬 호출, 참고 문서 읽기, 새 파일, 중복 없는 트리거, 비밀값 분리, 탭 지정, 사본에서 시험, 가정 명시 등). 이때 생성된 코드 139줄도 타입 오류 0건
- 남은 한계: 실제 구글 서버에서는 실행해 보지 않았습니다. 마지막 확인은 사본 시트에서 해야 합니다

## 검토했지만 넣지 않은 것

| 후보 | 이유 |
|---|---|
| googleworkspace/cli | 기능은 강력하지만 로컬 전용이고, 메인 브랜치가 6개월째 멈춰 있음. 구글 클라우드 인증 설정이 필요하고, 이미 연결된 Gmail·캘린더·드라이브 커넥터와 겹침 |
| n8n-skills, Composio | 별도 서버나 유료 서비스가 필요하고, 회사 데이터가 제3자를 거침 |
| 거래소 공식 스킬 (Binance, Bybit, OKX, BingX, Gate) | 주문 기능이 함께 있거나, 시세 조회에도 API 키가 필요하거나, 실행 중 스스로 업데이트함 |
| Bitget-AI/bitget-signal | 지표 23개를 직접 계산하는 점은 좋지만, 스타 2개로 검증이 적고 데이터 출처를 숨기라는 지시가 있음 |
| agiprolabs/claude-trading-skills | 펀딩비를 난수로 생성하는 코드가 있음 |
| tradermonty의 `portfolio-manager` 등 | 주문 API(Alpaca) 키를 쓰거나 세션 기록을 읽음 |
