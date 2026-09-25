# 업무 자동화·코인 기술적 분석·미국 주식/ETF 거시 매매 스킬

GitHub 공개 스킬을 분야별로 조사해 고른 10개입니다(조사일 2026-09-25). 이 폴더의 스킬은 이 저장소에서 자동으로 켜지지 않습니다. 쓰려면 아래 방법으로 claude.ai 또는 Claude Code에 설치합니다.

## 한눈에 보기

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

## 사용 순서 (미국 주식·ETF)

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
3. **데이터를 가져오는 스킬**(`google-apps-script`, `technical-analyst`의 차트 분석, `exposure-coach`, `position-sizer`를 뺀 나머지)은 코드 실행의 인터넷 접속이 필요합니다. 설정 → 기능 → "코드 실행 및 파일 생성"에서 네트워크 접속을 **모든 도메인** 또는 필요한 도메인 허용으로 바꿉니다. Team·Enterprise 요금제는 조직 관리자가 바꿉니다. 접속이 막히면 스킬은 추정값을 만들지 않고 오류로 멈춥니다.

### Claude Code (맥)

```bash
git clone --depth 1 -b claude/github-top-10-skills-k1u8yp https://github.com/kbjshygod-afk/beomstar_git.git /tmp/beomstar-skills
mkdir -p ~/.claude/skills
cp -R /tmp/beomstar-skills/skills-library/{automation,crypto,macro}/* ~/.claude/skills/
pip3 install requests yfinance pandas
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
| 동작 시험 (`google-apps-script`) | "팀 웹앱이 있는 시트에 매주 메일 스크립트 추가" 요청에 스킬이 호출돼 안전 규칙 문서를 읽고, 기존 파일을 지우지 말고 새 파일로 추가하며 사본에서 먼저 시험하라고 답함 |
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

`google-apps-script`:

- 설치 단계의 "기존 코드를 지우고 붙여넣기"를 "**새 파일**을 추가하고 기존 파일은 절대 지우지 않기"로 바꿨습니다. 팀이 쓰는 웹앱이 지워지는 것을 막기 위해서입니다.
- 운영 중인 시트·웹앱을 바꾸기 전에 경고하고 승인을 받는 단계(Step 3a)를 넣고, 한국어 참고 문서 `references/team-web-app-safety.md`를 추가했습니다: 동시 저장 잠금, 배포 URL 유지, 대량 삭제 차단, 6분 제한.
- Claude Code 전용 표시(`compatibility: claude-code-only`)를 지웠습니다. 실제로는 claude.ai에서도 동작합니다.
- 할당량 표에서 공식 문서로 확인되지 않는 "시간 트리거 실행 30분" 행을 지웠습니다.
- 설명에 한국어 호출어(구글 시트 자동화, 앱스 스크립트 등)를 추가하고, 코드 없이 설치 절차만 묻는 질문에도 켜지도록 문구를 보강했습니다. 보강 전에는 "설치 절차만 알려줘"라는 질문에 스킬이 켜지지 않아 "새 파일로 추가"와 "사본에서 먼저 시험"이 답변에서 빠졌습니다.

## 검토했지만 넣지 않은 것

| 후보 | 이유 |
|---|---|
| googleworkspace/cli | 기능은 강력하지만 로컬 전용이고, 메인 브랜치가 6개월째 멈춰 있음. 구글 클라우드 인증 설정이 필요하고, 이미 연결된 Gmail·캘린더·드라이브 커넥터와 겹침 |
| n8n-skills, Composio | 별도 서버나 유료 서비스가 필요하고, 회사 데이터가 제3자를 거침 |
| 거래소 공식 스킬 (Binance, Bybit, OKX, BingX, Gate) | 주문 기능이 함께 있거나, 시세 조회에도 API 키가 필요하거나, 실행 중 스스로 업데이트함 |
| Bitget-AI/bitget-signal | 지표 23개를 직접 계산하는 점은 좋지만, 스타 2개로 검증이 적고 데이터 출처를 숨기라는 지시가 있음 |
| agiprolabs/claude-trading-skills | 펀딩비를 난수로 생성하는 코드가 있음 |
| tradermonty의 `portfolio-manager` 등 | 주문 API(Alpaca) 키를 쓰거나 세션 기록을 읽음 |
