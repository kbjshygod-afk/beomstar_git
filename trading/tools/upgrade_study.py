"""Pre-registered upgrade study (docs/swing-upgrade-study-2026-10.md).

    python tools/upgrade_study.py --data DATA_DIR --out OUT_DIR [--markets KOSDAQ KOSPI SP500]

Each hypothesis is an extra gate on the signal bar (information up to that bar only) ANDed with
the current full_signal, on point-in-time index members; U13 swaps the exit MA. Everything else
(RS percentile 70, 0.75% risk, 0.2% cost, test window and halves) is the published setup.
Writes OUT_DIR/<MARKET>/upgrade/<key>.json and OUT_DIR/upgrade_summary.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import robustness as R                                   # noqa: E402
from swing_engine.indicators import normalize_bars       # noqa: E402
from swing_engine.params import COST_PCT, resolve        # noqa: E402
from swing_engine.portfolio import simulate              # noqa: E402

# KOSDAQ point-in-time baseline (rob/KOSDAQ/variants_pit/00.json) and the fixed pass criteria
CRITERIA = {"cagr_min": 12.0, "pf_min": 1.33, "h1_excess_min": 11.8, "h2_excess_min": 4.5,
            "trades_min": 534, "mdd_min": -49.0, "other_excess_slack_pp": 3.0}


def breadth_pct(frames: dict, member: pd.DataFrame) -> pd.Series:
    """% of the day's index members whose close is above their 200-day MA."""
    close = pd.DataFrame({s: f["close"] for s, f in frames.items()})
    ma = pd.DataFrame({s: f["ma200"] for s, f in frames.items()})
    mem = member.reindex(index=close.index, columns=close.columns).fillna(False).astype(bool)
    valid = mem & ma.notna()
    above = (close > ma) & valid
    return above.sum(axis=1) / valid.sum(axis=1).replace(0, float("nan")) * 100


def adr20(f: pd.DataFrame) -> pd.Series:
    return (f["high"] / f["low"] - 1).rolling(20).mean() * 100


GATES = {
    "U1_tight085": ("수축 0.85", lambda f, x: f["contraction"].shift(1) <= 0.85),
    "U2_tight100": ("수축 1.0", lambda f, x: f["contraction"].shift(1) <= 1.0),
    "U3_dryup085": ("거래량 건조 0.85", lambda f, x: f["dry_up"].shift(1) <= 0.85),
    "U4_cap5": ("추격 5%", lambda f, x: f["breakout_pct"] <= 5.0),
    "U5_cap3": ("추격 3%", lambda f, x: f["breakout_pct"] <= 3.0),
    "U6_ext20": ("이격 20%", lambda f, x: f["close"] <= f["ma50"] * 1.20),
    "U7_adr3": ("ADR 3%", lambda f, x: adr20(f) >= 3.0),
    "U8_adr4": ("ADR 4%", lambda f, x: adr20(f) >= 4.0),
    "U9_mom63": ("절대 모멘텀 63봉 +20%", lambda f, x: f["close"] / f["close"].shift(63) - 1 >= 0.20),
    "U10_breadth40": ("폭 레짐 40", lambda f, x: x["breadth"].reindex(f.index) >= 40.0),
    "U11_breadth50": ("폭 레짐 50", lambda f, x: x["breadth"].reindex(f.index) >= 50.0),
    "U12_nearhigh10": ("고점 근접 10%", lambda f, x: f["from_high52"] >= -10.0),
}


def apply_gate(frames: dict, orig: dict, gate, ctx: dict) -> None:
    for s, f in frames.items():
        g = gate(f, ctx)
        f["full_signal"] = orig[s] & pd.Series(g, index=f.index).fillna(False).to_numpy()


def run_market(data_dir: str, out_dir: str, market: str) -> dict:
    out_root = Path(out_dir) / market / "upgrade"
    out_root.mkdir(parents=True, exist_ok=True)
    snap, _, bench = R.load(data_dir, market)
    frames_all = dict(snap["frames"])
    cfg = R._cfg(resolve(market), 70.0, COST_PCT)
    dates = normalize_bars(bench, require_ohlc=False).index
    rdates, sets = R.membership_rows(market, Path(data_dir) / R.MEMBERSHIP_FILES[market], sorted(frames_all))
    member = R.membership_mask(rdates, sets, dates, sorted(frames_all))
    frames = R.prepare_pit(frames_all, bench, cfg, member)
    orig = {s: f["full_signal"].to_numpy().copy() for s, f in frames.items()}
    exit_orig = {s: f["exit_ma"].to_numpy().copy() for s, f in frames.items()}
    ctx = {"breadth": breadth_pct(frames, member)}

    results = {}

    def run(key, label, extra=None):
        path = out_root / f"{key}.json"
        if path.exists():
            results[key] = json.loads(path.read_text())
            return
        res = simulate(frames, cfg)
        s = R.summarize(res, bench, market)
        d = {"label": label, **(extra or {}), **s}
        R._write(path, d)
        results[key] = d
        print(f"{market} {key} {label}: cagr {s['full']['cagr_pct']:.2f} pf {s['full']['profit_factor']:.2f} "
              f"win {s['full']['win_rate_pct']:.1f} trades {s['full']['trades']}", flush=True)

    run("U0_base", "기준 (현재 룰)")
    for key, (label, gate) in GATES.items():
        apply_gate(frames, orig, gate, ctx)
        run(key, label)
    for s, f in frames.items():                       # U13: Stage-2 hold, exit on a close below MA200
        f["full_signal"] = orig[s]
        f["exit_ma"] = f["ma200"].to_numpy()
    run("U13_exit200", "청산 200일선")
    for s, f in frames.items():
        f["exit_ma"] = exit_orig[s]

    # U14: the two passing gates with the highest profit factor, combined (KOSDAQ decides)
    combo = (Path(out_dir) / "KOSDAQ" / "upgrade" / "combo.json")
    if market == "KOSDAQ":
        passing = [k for k in GATES if passes(results[k], results)["pass"]]
        passing.sort(key=lambda k: -results[k]["full"]["profit_factor"])
        combo.write_text(json.dumps(passing[:2]))
    pair = json.loads(combo.read_text()) if combo.exists() else []
    if len(pair) == 2:
        apply_gate(frames, orig, lambda f, x: GATES[pair[0]][1](f, x) & GATES[pair[1]][1](f, x), ctx)
        run("U14_combo", f"조합: {GATES[pair[0]][0]} + {GATES[pair[1]][0]}", {"pair": pair})
    return results


def passes(d: dict, _results=None) -> dict:
    """KOSDAQ criteria 1-4 (criterion 5 is checked across markets in the summary)."""
    f, h1, h2 = d["full"], d["h1"], d["h2"]
    checks = {
        "cagr": f["cagr_pct"] >= CRITERIA["cagr_min"],
        "pf": f["profit_factor"] >= CRITERIA["pf_min"],
        "h1": h1["excess_cagr_pp"] >= CRITERIA["h1_excess_min"],
        "h2": h2["excess_cagr_pp"] >= CRITERIA["h2_excess_min"],
        "trades": f["trades"] >= CRITERIA["trades_min"],
        "mdd": f["max_drawdown_pct"] >= CRITERIA["mdd_min"],
    }
    return {"pass": all(checks.values()), **checks}


def summary_md(out_dir: str, markets: list[str]) -> str:
    L = []
    allres = {}
    for mk in markets:
        root = Path(out_dir) / mk / "upgrade"
        allres[mk] = {p.stem: json.loads(p.read_text()) for p in sorted(root.glob("U*.json"))}
    for mk in markets:
        res = allres[mk]
        base = res.get("U0_base")
        L += [f"### {mk} (실전 조건, 2016-09-26 ~ 2026-09-23)", "",
              "| 가설 | 거래 | CAGR | 지수 초과 | PF | 승률 | 평균 이익 | 평균 손실 | 최대 낙폭 | 전반 초과 | 후반 초과 | 판정 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, d in res.items():
            f, h1, h2 = d["full"], d["h1"], d["h2"]
            if mk == "KOSDAQ":
                verdict = "기준" if key == "U0_base" else ("**합격**" if passes(d)["pass"] else "불합격")
            else:
                slack = CRITERIA["other_excess_slack_pp"]
                ok = base is None or f["excess_cagr_pp"] >= base["full"]["excess_cagr_pp"] - slack
                verdict = "기준" if key == "U0_base" else ("이상 없음" if ok else "**악화**")
            L.append(f"| {d['label']} | {f['trades']} | {f['cagr_pct']:.1f}% | {f['excess_cagr_pp']:+.1f}%p | "
                     f"{f['profit_factor']:.2f} | {f['win_rate_pct']:.1f}% | {f['avg_win_pct']:+.1f}% | "
                     f"{f['avg_loss_pct']:+.1f}% | {f['max_drawdown_pct']:.1f}% | {h1['excess_cagr_pp']:+.1f}%p | "
                     f"{h2['excess_cagr_pp']:+.1f}%p | {verdict} |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--markets", nargs="+", default=["KOSDAQ", "KOSPI", "SP500"])
    a = ap.parse_args()
    for mk in a.markets:                  # KOSDAQ first: it decides the U14 pair
        run_market(a.data, a.out, mk)
    md = summary_md(a.out, a.markets)
    (Path(a.out) / "upgrade_summary.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
