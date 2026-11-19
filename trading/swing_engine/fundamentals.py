"""Financial statements for one listed company, read from the official filings APIs and laid
out the same way for Korea (DART) and the US (SEC EDGAR): periods -> figures -> ratios -> a
Markdown page. Reference material only: the swing rules stay technical (docs/swing-improvement-
policy.md, grade 1), nothing here feeds signals.

A period is a dict: {"label": "2026Q2" | "FY2025", "kind": "Q" | "FY", "end": "YYYY-MM-DD",
"revenue", "op_income", "net_income", "ocf", "assets", "liabilities", "equity", "inventory",
"receivables", "eps"} in the filing currency (KRW or USD); a figure the filing lacks is None.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FIGURES = ("revenue", "op_income", "net_income", "ocf", "assets", "liabilities", "equity", "inventory", "receivables", "eps")
FLOW = ("revenue", "op_income", "net_income", "ocf")           # summed over time; the rest are balances at period end


def _num(x):
    return None if x is None else float(x)


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _pct(a, b):
    r = _div(a, b)
    return None if r is None else r * 100


def _growth(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    if prev < 0:                      # growth from a loss has no meaningful percent
        return None
    return (cur / prev - 1) * 100


def quarters(periods: list[dict], n: int = 8) -> list[dict]:
    qs = sorted((p for p in periods if p["kind"] == "Q"), key=lambda p: p["end"])
    return qs[-n:]


def annuals(periods: list[dict], n: int = 5) -> list[dict]:
    ys = sorted((p for p in periods if p["kind"] == "FY"), key=lambda p: p["end"])
    return ys[-n:]


def ttm(periods: list[dict]) -> dict | None:
    """Sum of the last four quarters' flows (None when fewer than four)."""
    qs = quarters(periods, 4)
    if len(qs) < 4:
        return None
    out = {"label": f"TTM {qs[-1]['label']}", "kind": "TTM", "end": qs[-1]["end"]}
    for f in FLOW:
        vals = [q.get(f) for q in qs]
        out[f] = None if any(v is None for v in vals) else sum(vals)
    for f in FIGURES:
        if f not in FLOW:
            out[f] = qs[-1].get(f)
    return out


def ratios(periods: list[dict]) -> dict:
    """Margins, growth, returns and balance-sheet health from the periods."""
    qs = quarters(periods, 8)
    ys = annuals(periods, 5)
    t = ttm(periods)
    last = qs[-1] if qs else (ys[-1] if ys else None)
    out = {"ttm": t, "last_period": last["label"] if last else None}
    if t:
        out["op_margin_ttm_pct"] = _pct(t["op_income"], t["revenue"])
        out["net_margin_ttm_pct"] = _pct(t["net_income"], t["revenue"])
        out["ocf_to_net_income"] = _div(t["ocf"], t["net_income"]) if (t["net_income"] or 0) > 0 else None
        eq_now = t.get("equity")
        eq_prev = next((q.get("equity") for q in reversed(qs[:-4])), None) if len(qs) >= 5 else None
        avg_eq = (eq_now + eq_prev) / 2 if eq_now is not None and eq_prev is not None else eq_now
        out["roe_ttm_pct"] = _pct(t["net_income"], avg_eq) if avg_eq and avg_eq > 0 else None
        out["revenue_to_receivables"] = _div(t["revenue"], t.get("receivables"))
        out["revenue_to_inventory"] = _div(t["revenue"], t.get("inventory"))
    if last:
        out["debt_ratio_pct"] = _pct(last.get("liabilities"), last.get("equity")) if (last.get("equity") or 0) > 0 else None
        out["equity_ratio_pct"] = _pct(last.get("equity"), last.get("assets"))
    if len(qs) >= 5:
        cur, yago = qs[-1], qs[-5]
        out["revenue_yoy_pct"] = _growth(cur.get("revenue"), yago.get("revenue"))
        out["op_income_yoy_pct"] = _growth(cur.get("op_income"), yago.get("op_income"))
        out["net_income_yoy_pct"] = _growth(cur.get("net_income"), yago.get("net_income"))
    if len(ys) >= 2:
        out["revenue_cagr_pct"] = _cagr([y.get("revenue") for y in ys])
        out["op_income_streak"] = sum(1 for y in ys if (y.get("op_income") or 0) > 0)
    return out


def _cagr(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2 or vals[0] <= 0 or vals[-1] <= 0:
        return None
    years = len(vals) - 1
    return ((vals[-1] / vals[0]) ** (1 / years) - 1) * 100


@dataclass
class Company:
    symbol: str
    name: str
    source: str                      # "DART" | "SEC EDGAR"
    currency: str                    # "KRW" | "USD"
    periods: list[dict] = field(default_factory=list)
    price: float | None = None       # last close in the filing currency, when known
    shares: float | None = None      # shares outstanding, when the filing says
    notes: list[str] = field(default_factory=list)

    def valuation(self) -> dict:
        r = ratios(self.periods)
        t = r.get("ttm")
        out = {}
        if self.price and self.shares and t:
            mcap = self.price * self.shares
            out["market_cap"] = mcap
            out["per_ttm"] = _div(mcap, t["net_income"]) if (t["net_income"] or 0) > 0 else None
            out["pbr"] = _div(mcap, t.get("equity")) if (t.get("equity") or 0) > 0 else None
            out["psr_ttm"] = _div(mcap, t["revenue"]) if (t["revenue"] or 0) > 0 else None
        return out


# -- rendering --------------------------------------------------------------------------------------
def _money(v, cur):
    if v is None:
        return "-"
    if cur == "KRW":
        return f"{v / 1e8:,.0f}억"
    return f"{v / 1e6:,.0f}M"


def _p(v, d=1, suffix="%"):
    return "-" if v is None else f"{v:+.{d}f}{suffix}" if suffix == "%p" else ("-" if v is None else f"{v:.{d}f}{suffix}")


def _x(v, d=2):
    return "-" if v is None else f"{v:.{d}f}x"


def render(c: Company) -> str:
    r = ratios(c.periods)
    v = c.valuation()
    qs = quarters(c.periods, 8)
    ys = annuals(c.periods, 5)
    cur = c.currency
    unit = "억원" if cur == "KRW" else "백만 달러"
    L = [f"# 재무제표 요약 — {c.name} ({c.symbol})", "",
         f"> 출처 {c.source} 공시 원본. 참고 자료이며 스윙 룰(기술적 신호)에는 쓰지 않습니다. 금액 단위 {unit}, 주당 지표는 {cur}.", ""]
    t = r.get("ttm")
    L += ["## 핵심 지표 (최근 4분기 합산 TTM)", "", "| 지표 | 값 | 비고 |", "|---|---|---|"]
    if t:
        L += [f"| 매출 TTM | {_money(t['revenue'], cur)} | 분기 YoY {_p(r.get('revenue_yoy_pct'))} |",
              f"| 영업이익 TTM | {_money(t['op_income'], cur)} | 영업이익률 {_p(r.get('op_margin_ttm_pct'))} · 분기 YoY {_p(r.get('op_income_yoy_pct'))} |",
              f"| 순이익 TTM | {_money(t['net_income'], cur)} | 순이익률 {_p(r.get('net_margin_ttm_pct'))} · 분기 YoY {_p(r.get('net_income_yoy_pct'))} |",
              f"| 영업현금흐름 TTM | {_money(t['ocf'], cur)} | 순이익 대비 {_x(r.get('ocf_to_net_income'))} (1.0 위면 이익의 질 양호) |",
              f"| ROE (TTM) | {_p(r.get('roe_ttm_pct'))} | 평균 자본 기준 |",
              f"| 부채비율 | {_p(r.get('debt_ratio_pct'), 0)} | 부채총계/자본총계 · 자기자본비율 {_p(r.get('equity_ratio_pct'), 0)} |",
              f"| 매출/매출채권 · 매출/재고 | {_x(r.get('revenue_to_receivables'), 1)} · {_x(r.get('revenue_to_inventory'), 1)} | 회전 속도(높을수록 빠름), 원가 미공개라 매출 기준 |"]
    else:
        L.append("| (분기 4개 미만) | - | 연간 표만 참고 |")
    if v:
        L += [f"| 시가총액 | {_money(v.get('market_cap'), cur)} | 종가 {c.price:,.2f} × 주식수 {c.shares:,.0f} |",
              f"| PER (TTM) · PBR · PSR | {_x(v.get('per_ttm'), 1)} · {_x(v.get('pbr'))} · {_x(v.get('psr_ttm'))} | 적자면 PER 없음 |"]
    L.append("")
    if qs:
        L += ["## 분기 추이 (최근 8분기)", "", "| 분기 | 매출 | 영업이익 | 영업이익률 | 순이익 | 영업현금흐름 | 자본총계 | 부채비율 |", "|---|---|---|---|---|---|---|---|"]
        for q in qs:
            L.append(f"| {q['label']} | {_money(q.get('revenue'), cur)} | {_money(q.get('op_income'), cur)} | {_p(_pct(q.get('op_income'), q.get('revenue')))} | "
                     f"{_money(q.get('net_income'), cur)} | {_money(q.get('ocf'), cur)} | {_money(q.get('equity'), cur)} | "
                     f"{_p(_pct(q.get('liabilities'), q.get('equity')) if (q.get('equity') or 0) > 0 else None, 0)} |")
        L.append("")
    if ys:
        L += ["## 연간 추이 (최근 5년)", "", "| 연도 | 매출 | 매출 성장 | 영업이익 | 영업이익률 | 순이익 | ROE | 영업현금흐름 |", "|---|---|---|---|---|---|---|---|"]
        prev = None
        for y in ys:
            roe = _pct(y.get("net_income"), y.get("equity")) if (y.get("equity") or 0) > 0 else None
            L.append(f"| {y['label']} | {_money(y.get('revenue'), cur)} | {_p(_growth(y.get('revenue'), prev.get('revenue')) if prev else None)} | "
                     f"{_money(y.get('op_income'), cur)} | {_p(_pct(y.get('op_income'), y.get('revenue')))} | {_money(y.get('net_income'), cur)} | {_p(roe)} | {_money(y.get('ocf'), cur)} |")
            prev = y
        L += ["", f"매출 CAGR {len(ys) - 1}년: {_p(r.get('revenue_cagr_pct'))} · 영업흑자 연도 {r.get('op_income_streak', '-')}/{len(ys)}", ""]
    L += ["## 읽는 법 (사실 / 해석 구분)", "",
          "- **사실:** 위 숫자는 공시 원본(연결재무제표 우선)을 그대로 집계한 값입니다. 4분기 수치는 연간에서 1~3분기 누적을 뺀 값입니다.",
          "- **해석(참고):** 영업이익률과 ROE가 오르면서 영업현금흐름이 순이익을 따라오면 이익의 질이 좋은 편입니다. 부채비율 200% 초과, 영업현금흐름이 순이익을 크게 밑도는 상태, 매출채권·재고가 매출보다 빨리 늘면 주의합니다.",
          "- **룰과의 관계:** 모의투자 룰은 기술적 신호만 씁니다. 이 표는 종목을 이해하는 참고이며, 진입·청산 판단에 섞지 않습니다(판정 기간 중 룰 변경 금지)."]
    for n in c.notes:
        L.append(f"- {n}")
    return "\n".join(L) + "\n"
