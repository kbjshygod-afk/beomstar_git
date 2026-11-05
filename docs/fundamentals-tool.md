# 재무제표 조회 도구 (공시 API) — 사용 안내

**목적:** 대표님이 종목을 부르면 공시 원본에서 재무제표를 읽어 표준 요약 1장(Markdown + JSON)을 만든다. 참고 자료이며 스윙 룰(기술적 신호)에는 쓰지 않는다(`docs/swing-improvement-policy.md`, 판정 기간 중 룰 변경 금지).

| 시장 | 출처 | 범위 | 필요한 것 |
|---|---|---|---|
| 한국 (6자리 코드, `.KS`/`.KQ`) | DART OpenAPI `fnlttSinglAcntAll` (연결재무제표 우선, 없으면 개별) | 분기·반기·3분기·사업보고서 → 8분기 + 5년 | 저장소 Secret `DART_API_KEY` (opendart.fss.or.kr 무료 발급, 하루 20,000회) |
| 미국 (티커) | SEC EDGAR XBRL company facts | 10-Q/10-K 프레임 → 8분기 + 5년 | 키 없음. User-Agent에 연락처 필수(`EDGAR_USER_AGENT`). **GitHub Actions에서는 SEC가 403으로 거부 → 맥에서 실행** |

## 실행
- 한국 종목: GitHub Actions → **fundamentals** → Run workflow → `symbols`에 `005930.KS,096530.KQ` 처럼 입력. 결과는 실행 Summary에 바로 보이고, `fundamentals-<run id>` 아티팩트(md·json)로 30일 보관.
- 미국 종목(그리고 한국 종목도 가능): 맥 터미널에서
  ```bash
  cd ~/beomstar_git && git pull
  export EDGAR_USER_AGENT="beomstar-swing you@example.com"   # SEC 규정: 프로젝트명 + 영문 이메일(한글 불가)
  export DART_API_KEY=...                                     # 한국 종목을 같이 볼 때만
  python3 trading/tools/fundamentals_report.py --symbols AAPL,NVDA,BRK-B --out ~/beomstar_reports
  ```
  결과: `~/beomstar_reports/<symbol>.md`·`.json`. 요약 페이지를 대화에 붙여 주면 해석을 돕는다.
- SEC는 GitHub 호스티드 러너(Azure IP)를 `www.sec.gov`·`data.sec.gov`·`efts.sec.gov` 모두 403으로 거부한다(2026-11-03 확인, 올바른 User-Agent로도 동일). Actions에서 미국 티커를 넣으면 "SEC refuses this network"로 실패한다.

## 요약 1장에 들어가는 것
- TTM(최근 4분기): 매출·영업이익·순이익·영업현금흐름, 영업이익률·순이익률, ROE(평균 자본), 부채비율·자기자본비율, 매출/매출채권·매출/재고 회전(원가 미공개라 매출 기준), 영업현금흐름/순이익(이익의 질).
- 분기 8개 추이, 연간 5년 추이(성장률·ROE), 매출 CAGR, 영업흑자 연도 수.
- 시가총액·PER(TTM)·PBR·PSR: Yahoo 종가(가능할 때)와 주식수(DART 유통주식수 / EDGAR dei) — 둘 중 하나가 없으면 생략.
- 사실/해석 구분 문단과 룰과의 관계(참고용) 문구.

## 집계 규칙
- 분기 손익: 분기·반기·3분기 보고서의 **3개월 값**(`thstrm_amount`), 4분기 = 사업보고서 − 3분기 누적. 현금흐름은 누적만 공시되므로 차감해서 분기화.
- EDGAR: XBRL 프레임(`CY2026Q2`, `CY2025`, 잔액은 `...I`)으로 재공시 중복을 피하고, 4분기 프레임이 없으면 연간 − 1~3분기.
- 계정 탐색: `account_id`(IFRS/dart 태그) 우선, 없으면 계정명(매출액·영업이익·당기순이익 등). 매출 개념이 여러 개인 미국 기업은 값이 있는 첫 개념을 쓴다(페이지 하단에 표기).

## 알려진 한계
- 금융업(은행·보험·증권)은 매출·영업이익 계정이 달라 비어 있을 수 있다. 지주회사 연결 범위 변경, 회계연도가 12월이 아닌 기업(미국 일부)은 분기 라벨이 회계연도 기준으로 어긋날 수 있다.
- 공시 직후(분기 마감 후 45일 안)에는 최신 분기가 아직 없다. "보고서 미공시"로 표기.
- EDGAR는 User-Agent에 연락처(이메일)가 없으면 403으로 막는다. 워크플로는 저장소 변수 `EDGAR_USER_AGENT`(`beomstar-swing you@example.com`)를 쓰고, 없으면 실행자의 GitHub noreply 주소로 대신한다. 2026-11-03 첫 실행이 이 403으로 실패해 추가.
- 밸류에이션의 종가는 Yahoo 마지막 종가이며, 실행 시점에 따라 하루 늦을 수 있다.
