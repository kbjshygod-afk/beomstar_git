"""Verdict rules for the robustness study, fixed before the full results were read.

Per market, from tools/robustness.py output:
  A  10-year excess CAGR over the index > 0
  B  excess > 0 in both halves (2016-09..2021-09 and 2021-09..2026-09)
  C  portfolio CAGR above the 90th percentile of portfolios with random entries drawn from
     stocks above their 50-day MA in a regime-ON market (same dates, counts, sizing, exits)
  D  risk-adjusted: Sharpe >= the index's, or max drawdown at least 5 points shallower
  E  robustness: excess > 0 in at least 70% of the one-parameter variants (cost variants excluded)
  F  still ahead of the index at 0.4% cost per side

  유효          A, B, C and E
  조건부 유효   A and (C or D), but not all of A, B, C, E
  실효성 낮음   otherwise
"""

VARIANT_EXCLUDE = ("비용 편도",)


def verdict(base: dict, random_above_pct: float | None, variants: list, cost04_excess: float | None) -> dict:
    f, h1, h2, risk = base["full"], base["h1"], base["h2"], base["risk"]
    A = f["excess_cagr_pp"] > 0
    B = h1["excess_cagr_pp"] > 0 and h2["excess_cagr_pp"] > 0
    C = random_above_pct is not None and random_above_pct >= 90
    D = (risk["sharpe"] is not None and risk["bench_sharpe"] is not None and risk["sharpe"] >= risk["bench_sharpe"]) \
        or (f["max_drawdown_pct"] - risk["bench_mdd_pct"] >= 5)
    vs = [v for v in variants if v["n"] != 0 and not v["label"].startswith(VARIANT_EXCLUDE)]
    share = sum(1 for v in vs if v["full"]["excess_cagr_pp"] > 0) / len(vs) * 100 if vs else 0.0
    E = share >= 70
    F = cost04_excess is not None and cost04_excess > 0
    if A and B and C and E:
        label = "유효"
    elif A and (C or D):
        label = "조건부 유효"
    else:
        label = "실효성 낮음"
    return {"label": label, "A": A, "B": B, "C": C, "D": D, "E": E, "F": F, "variant_pass_pct": share}
