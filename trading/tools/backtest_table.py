"""Build the Korean backtest comparison page for the skill from backtest results.json files.

    python tools/backtest_table.py RESULTS_DIR OUT_MD

RESULTS_DIR holds <MARKET>/results.json as published on the swing-results branch (latest/results).
"""
import json
import sys
from pathlib import Path

MARKETS = [("SP500", "S&P500"), ("NDX100", "나스닥100"), ("KOSPI", "코스피"), ("KOSDAQ", "코스닥"), ("CRYPTO", "크립토")]
SCANNER = {  # scanner dashboard 2026-09-04: CAGR minus index CAGR (10y, OOS, last 1y)
    "SP500": ("+1.1%p", "+12.4%p", "+42.8%p"),
    "NDX100": ("+2.0%p", "+23.5%p", "+67.5%p"),
    "KOSPI": ("−2.1%p", "−6.9%p", "−74.1%p"),
    "KOSDAQ": ("+21.1%p (MDD −53.7%)", "+49.6%p", "+95.9%p"),
    "CRYPTO": ("−23.8%p", "−42.0%p", "+30.2%p"),
}


def pp(x):
    return "-" if x is None else f"{x:+.1f}%p"


def pct(x):
    return "-" if x is None else f"{x:+.1f}%"


def num(x, f="{:.1f}"):
    return "-" if x is None else f.format(x)


def row_metrics(m: dict, key: str) -> dict:
    return m.get(key) or {}


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    lines = ["# 10년 백테스트 — 엔진 vs 스캐너 계기판", "",
             "엔진(`trading/swing_engine`)으로 현재 지수 구성종목에 룰을 적용한 포트폴리오 모의 결과입니다. "
             "스캐너 계기판(2026-09-04) 수치와 나란히 둡니다. 수치는 **CAGR − 지수 가격지수 CAGR**(같은 구간), "
             "수수료 편도 0.2% 차감 후입니다. 생존편향이 있어 낙관적 상한으로 봐야 합니다.", ""]
    first = None
    rows10, rows1, rowst = [], [], []
    for mk, name in MARKETS:
        p = src / mk / "results.json"
        if not p.exists():
            rows10.append(f"| {name} | 실행 실패 | {SCANNER[mk][0]} | - | - | - | - |")
            continue
        d = json.loads(p.read_text())
        first = first or d
        cov = d["coverage"]
        pm = d["modes"].get("percentile", {}).get("metrics", {})
        px = d["modes"].get("proxy", {}).get("metrics", {})
        f, fx = row_metrics(pm, "full"), row_metrics(px, "full")
        y1 = row_metrics(pm, "last_1y")
        rows10.append(f"| {name} | {pp(f.get('excess_cagr_pp'))} | {SCANNER[mk][0]} | {pp(fx.get('excess_cagr_pp'))} | "
                      f"{pct(f.get('cagr_pct'))} / {pct(f.get('bench_cagr_pct'))} | {pct(f.get('max_drawdown_pct'))} | "
                      f"{cov['loaded']}/{cov['requested']} |")
        rows1.append(f"| {name} | {pp(y1.get('excess_cagr_pp'))} | {SCANNER[mk][2]} |")
        rowst.append(f"| {name} | {num(f.get('trades'), '{:.0f}')} | {num(f.get('win_rate_pct'), '{:.1f}%')} | "
                     f"{pct(f.get('avg_win_pct'))} | {pct(f.get('avg_loss_pct'))} | {num(f.get('profit_factor'), '{:.2f}')} | "
                     f"{num(f.get('big_win_trade_share_pct'), '{:.1f}%')} | {num(f.get('big_win_profit_share_pct'), '{:.1f}%')} | "
                     f"{num(f.get('exposure_pct'), '{:.1f}%')} |")
    if first:
        lines += [f"- 테스트 구간: {first['config']['test_start']} ~ {first.get('data_last_date')} · "
                  f"생성 {first['generated_at']}", ""]
    lines += ["## 10년 초과수익", "",
              "| 시장 | 엔진 (RS 백분위 ≥ 70, 스캐너 룰) | 스캐너 10년 | 엔진 (RS 프록시, TradingView 룰) | 엔진 CAGR / 지수 CAGR | 엔진 MDD | 데이터 |",
              "|---|---|---|---|---|---|---|", *rows10, "",
              "## 최근 1년 초과수익", "", "| 시장 | 엔진 | 스캐너 |", "|---|---|---|", *rows1, "",
              "스캐너의 OOS 구간은 정의를 알 수 없어 비교하지 않았습니다.", "",
              "## 거래 특성 (10년, RS 백분위)", "",
              "| 시장 | 거래 | 승률 | 평균 이익 | 평균 손실 | PF | +20% 초과 거래 비중 | 그 거래의 이익 비중 | 평균 노출 |",
              "|---|---|---|---|---|---|---|---|---|", *rowst, "",
              "스캐너 룰 시트: 승률 30%대, 이익의 77~84%가 +20% 초과 거래(전체의 8~9%)에서 나옴.", "",
              "## 해석할 때 주의", "",
              "- 유니버스: 코스피·코스닥은 시가총액 상위 200·150개로 지수 구성종목을 근사했고, 크립토는 현재 상위 30개(스테이블·래핑 토큰 제외)라 초기 몇 해는 거래 가능 종목이 적습니다.",
              "- 스캐너 원본의 추정값 7개(피벗 기간, 거래량 평균, RS 방식 등)가 다르면 수치도 달라집니다.",
              "- 과거 성과는 미래 수익을 보장하지 않습니다. 기계적 룰 출력이며 투자 자문이 아닙니다.", ""]
    out.write_text("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
