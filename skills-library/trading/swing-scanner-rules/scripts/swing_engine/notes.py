"""Korean texts that must accompany every result (SPEC sections 8 and 9)."""
from __future__ import annotations

DISCLAIMER = "기계적 룰 출력이며 투자 자문이 아닙니다. 매수·매도 결정은 소유자 본인이 합니다."

# SPEC 9 - shown wherever results are shown.
UNCONFIRMED = [
    ("1", "피벗 기간", "직전 20봉 최고가 (당일 제외)", "타점표상 트리거가 52주 고점과 다른 경우가 많음"),
    ("2", "거래량 평균", "직전 50일 (당일 제외)", "미너비니의 \"50일 평균 대비 +40%\""),
    ("3", "RS", "단일 차트: 지수 대비 가중 1년 수익률 ≥ 0%p · 포트폴리오: 백분위 ≥ 70",
     "스캐너는 유니버스 백분위 ≥ 70"),
    ("4", "52주 고가·저가", "종가 기준", "타점표의 \"52주 고점 대비\" 값과 일치"),
    ("5", "200일선 상승", "22봉 전보다 높음", "트렌드 템플릿 \"최소 1개월 상승\""),
    ("6", "수축비", "10일 평균 TR ÷ 40일 평균 TR", "표시용"),
    ("7", "비용", "편도 0.2%", "스캐너의 슬리피지 가정(20bp)에 근접"),
]

UNCONFIRMED_LINE = ("미확인 추정값(스캐너 원본 코드 미확인): 피벗=직전 20봉 최고가(당일 제외) · "
                    "거래량 평균=직전 50일(당일 제외) · RS=지수 대비 가중 1년 수익률 ≥ 0%p"
                    "(스캐너는 유니버스 백분위 ≥ 70) · 52주 고저=종가 기준 · 200일선 상승=22봉 전 대비 · "
                    "수축비=10/40일 평균 TR · 비용=편도 0.2%")

# SPEC 8 - scanner dashboard (2026-09-04), CAGR minus index CAGR in %p.
SCANNER_TABLE = {
    "SP500": ("S&P500", "+1.1%p", "+12.4%p", "+42.8%p"),
    "NDX100": ("NDX100", "+2.0%p", "+23.5%p", "+67.5%p"),
    "KOSPI": ("KOSPI", "−2.1%p", "−6.9%p", "−74.1%p"),
    "KOSDAQ": ("KOSDAQ", "+21.1%p (MDD −53.7%)", "+49.6%p", "+95.9%p"),
    "CRYPTO": ("Crypto", "−23.8%p", "−42.0%p", "+30.2%p"),
}
SCANNER_FOOTNOTE = ("룰 시트 기준: 승률 30%대, 이익의 77~84%가 +20% 초과 거래(전체 거래의 8~9%)에서 나옴. "
                    "스캐너 계기판 2026-09-04 생성.")

EXIT_RULES = ("청산 규칙은 두 가지뿐입니다: ① 손절가 도달 즉시(매수와 동시에 거는 손절 주문) "
              "② 종가가 {n}일선 아래로 마감하면 다음 거래일 시가에 전량.")

CLOSING_LINE = "※ 이 결과는 기계적 룰 출력입니다. 매수·매도 결정은 소유자 본인이 합니다."


def unconfirmed_table_md() -> str:
    lines = ["| # | 항목 | 이 엔진의 기본값 | 근거 |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in UNCONFIRMED]
    return "\n".join(lines)


def scanner_table_md() -> str:
    lines = ["| 시장 | 10년 | OOS | 최근 1년 |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in SCANNER_TABLE.values()]
    return "\n".join(lines)
