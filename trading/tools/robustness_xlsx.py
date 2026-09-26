"""Korean Excel report of the robustness study.

    python tools/robustness_xlsx.py ROB_DIR OUT.xlsx NOTES.json

ROB_DIR is tools/robustness.py output. NOTES.json holds the written summary lines
({"summary": [...], "actions": [...], "risks": [...], "decisions": [...]}), which are
drafted after reading the numbers; every number in the tables comes from ROB_DIR.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from robustness_verdict import verdict  # noqa: E402

MARKETS = [("SP500", "S&P500"), ("NDX100", "나스닥100"), ("KOSPI", "코스피"), ("KOSDAQ", "코스닥"), ("CRYPTO", "크립토")]
BROWN, BEIGE, RED = "4A3730", "EEE3D0", "D20B10"
F = "Arial"
PCT, PP, NUM, RATIO = "0.0%", "+0.0%;-0.0%;0.0%", "#,##0", "0.00"
SRC = "출처: tools/robustness.py 실행 결과 (데이터 스냅샷 swing-data 브랜치, 2026-09-26 수집)"
thin = Side(style="thin", color="BFB5A8")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def _variants(dirp: Path) -> list:
    out = []
    for p in sorted(dirp.glob("*.json")):
        v = json.loads(p.read_text())
        v["n"] = int(p.stem)
        out.append(v)
    return out


def _runs(root: Path, prefix: str) -> list:
    runs = [json.loads(p.read_text()) for p in sorted((root / "random").glob(f"{prefix}_*.json"))]
    return [r for r in runs if r.get("full")]


def load(rob: Path, mk: str) -> dict | None:
    """{"views": {"current": view, "pit": view?}, "edge": ..., "pit_info": ...}; a view has
    base, variants, random {above_ma, candidates}, equity, trades."""
    root = rob / mk
    if not (root / "baseline.json").exists():
        return None
    views = {"current": {
        "base": json.loads((root / "baseline.json").read_text()),
        "variants": _variants(root / "variants"),
        "random": {"above_ma": _runs(root, "above_ma"), "candidates": _runs(root, "candidates")},
        "equity": pd.read_csv(root / "equity.csv", parse_dates=["date"]).set_index("date"),
        "trades": pd.read_csv(root / "trades.csv")}}
    vp = _variants(root / "variants_pit") if (root / "variants_pit").exists() else []
    if vp and (root / "equity_pit.csv").exists():
        views["pit"] = {
            "base": next(v for v in vp if v["n"] == 0), "variants": vp,
            "random": {"above_ma": [r for r in _runs(root, "pit_above_ma") if r.get("pit")],
                       "candidates": [r for r in _runs(root, "pit_candidates") if r.get("pit")]},
            "equity": pd.read_csv(root / "equity_pit.csv", parse_dates=["date"]).set_index("date"),
            "trades": pd.read_csv(root / "trades_pit.csv")}
    return {"views": views,
            "edge": json.loads((root / "edge.json").read_text()) if (root / "edge.json").exists() else None,
            "pit_info": json.loads((root / "pit.json").read_text()) if (root / "pit.json").exists() else None}


def headline(d: dict) -> tuple[str, dict]:
    return ("pit", d["views"]["pit"]) if "pit" in d["views"] else ("current", d["views"]["current"])


VIEW_LABEL = {"pit": "당시 구성종목 (실전 조건)", "current": "현재 구성종목 (기존 백테스트)"}


def rand_stats(view: dict, pool: str) -> dict | None:
    runs = view["random"].get(pool) or []
    if not runs:
        return None
    c = np.array([r["full"]["cagr_pct"] for r in runs])
    rule = view["base"]["full"]["cagr_pct"]
    return {"n": len(c), "p05": np.percentile(c, 5), "p50": np.percentile(c, 50), "p95": np.percentile(c, 95),
            "pct": float((c < rule).mean() * 100)}


def variant(view: dict, label_prefix: str):
    for v in view["variants"]:
        if v["label"].startswith(label_prefix):
            return v
    return None


def view_verdict(view: dict) -> dict:
    ra = rand_stats(view, "above_ma")
    c04 = variant(view, "비용 편도 0.4")
    return verdict(view["base"], ra["pct"] if ra else None, view["variants"],
                   c04["full"]["excess_cagr_pp"] if c04 else None)


# ---------------------------------------------------------------------------
# styling helpers
# ---------------------------------------------------------------------------

def style_ws(ws):
    ws.sheet_view.showGridLines = False
    for row in ws.iter_rows():
        for c in row:
            if c.font is None or c.font.name != F:
                c.font = Font(name=F, size=c.font.size if c.font and c.font.size else 10, bold=c.font.bold if c.font else False,
                              color=c.font.color if c.font else None)


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = Font(name=F, size=14, bold=True, color=BROWN)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(name=F, size=9, color="7F7F7F")


def section(ws, row, text, width=12):
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(name=F, size=11, bold=True, color=BROWN)
    for j in range(1, width + 1):
        ws.cell(row=row, column=j).fill = PatternFill("solid", fgColor=BEIGE)


def header(ws, row, labels, col=1):
    for j, lab in enumerate(labels):
        c = ws.cell(row=row, column=col + j, value=lab)
        c.font = Font(name=F, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BROWN)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BOX
    ws.row_dimensions[row].height = 14 * max(2, max(str(x).count("\n") + 1 for x in labels)) + 6


def put(ws, row, col, value, fmt=None, bold=False, color=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(name=F, size=10, bold=bold, color=color)
    c.border = BOX
    if fmt:
        c.number_format = fmt
    return c


def frac(x):
    return None if x is None else x / 100.0


def widths(ws, w: dict):
    for k, v in w.items():
        ws.column_dimensions[k].width = v


def text_block(ws, row, lines, width=14):
    for line in lines:
        c = ws.cell(row=row, column=1, value=line)
        c.font = Font(name=F, size=10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        ws.row_dimensions[row].height = 15 * max(1, len(line) // 110 + 1)
        row += 1
    return row


# ---------------------------------------------------------------------------
# sheets
# ---------------------------------------------------------------------------

VERDICT_COLOR = {"유효": "00703C", "조건부 유효": BROWN, "실효성 낮음": RED}


def metric_row(ws, r, name, uni, view, v, extra_cols=True):
    b = view["base"]
    ra, rc = rand_stats(view, "above_ma"), rand_stats(view, "candidates")
    c04 = variant(view, "비용 편도 0.4")
    put(ws, r, 1, name, bold=True)
    put(ws, r, 2, uni)
    put(ws, r, 3, v["label"], bold=True, color=VERDICT_COLOR[v["label"]])
    put(ws, r, 4, frac(b["full"]["cagr_pct"]), PCT)
    put(ws, r, 5, frac(b["full"]["bench_cagr_pct"]), PCT)
    put(ws, r, 6, f"=D{r}-E{r}", PP, bold=True)
    put(ws, r, 7, frac(b["h1"]["excess_cagr_pp"]), PP)
    put(ws, r, 8, frac(b["h2"]["excess_cagr_pp"]), PP)
    put(ws, r, 9, frac(b["full"]["max_drawdown_pct"]), PCT)
    put(ws, r, 10, frac(b["risk"]["bench_mdd_pct"]), PCT)
    put(ws, r, 11, b["risk"]["sharpe"], RATIO)
    put(ws, r, 12, b["risk"]["bench_sharpe"], RATIO)
    put(ws, r, 13, frac(ra["pct"]) if ra else None, "0%")
    put(ws, r, 14, frac(rc["pct"]) if rc else None, "0%")
    put(ws, r, 15, frac(v["variant_pass_pct"]), "0%")
    put(ws, r, 16, frac(c04["full"]["excess_cagr_pp"]) if c04 else None, PP)


def sheet_summary(wb, data, notes):
    ws = wb.active
    ws.title = "결론"
    W = 16
    title(ws, "스윙 룰 10년 백테스트 — 실효성 검증", "데이터 기준일 2026-09-25 · 테스트 구간 2016-09-26 ~ 2026-09-25 · 작성 2026-09-26 · " + SRC)
    section(ws, 4, "목적", W)
    row = text_block(ws, 5, ["대표님 스캐너 룰(트렌드 템플릿 8/8 + 피벗 돌파 + 거래량 1.4배 + 레짐 + 손절 + 50일선 청산)이 "
                             "지수를 사서 들고 있는 것보다 실제로 나은지, 우연이나 설정값 운이나 생존편향이 아닌지를 판정한다."], W)
    section(ws, row + 1, "핵심 요약", W)
    row = text_block(ws, row + 2, notes["summary"], W)
    section(ws, row + 1, "시장별 판정 — 굵은 행이 실전 조건 판정", W)
    hr = row + 2
    header(ws, hr, ["시장", "유니버스", "판정", "10년 CAGR", "지수 CAGR", "초과\n(CAGR−지수)", "전반 5년\n초과", "후반 5년\n초과",
                    "최대 낙폭", "지수\n최대 낙폭", "샤프", "지수 샤프", "무작위 대비\n백분위\n(추세 종목)",
                    "무작위 대비\n백분위\n(템플릿 후보)", "민감도\n통과율", "비용 0.4%\n초과"])
    r = hr + 1
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        hk, _ = headline(d)
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            view = d["views"][key]
            uni = VIEW_LABEL[key] if key == "pit" or "pit" in d["views"] else "현재 구성종목 (편향 미보정)"
            metric_row(ws, r, name, uni, view, view_verdict(view))
            if key == hk:
                for j in range(1, W + 1):
                    ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=BEIGE)
                    ws.cell(row=r, column=j).font = Font(name=F, size=10, bold=True,
                                                         color=ws.cell(row=r, column=j).font.color)
            else:
                for j in range(1, W + 1):
                    ws.cell(row=r, column=j).font = Font(name=F, size=9, color="7F7F7F")
            r += 1
    note = ws.cell(row=r, column=1, value="초과 = 연복리 수익률(CAGR) − 같은 구간 지수 가격지수 CAGR, 수수료 편도 0.2% 차감. "
                                          "당시 구성종목 = 그날 실제 지수 편입 종목만 매수 가능(스캐너 실전과 같은 조건). "
                                          "무작위 대비 백분위 = 같은 날짜·같은 개수로 무작위 종목을 산 포트폴리오 중 룰보다 낮은 비율.")
    note.font = Font(name=F, size=9, color="7F7F7F")
    note.alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=W)
    ws.row_dimensions[r].height = 28
    r += 2
    section(ws, r, "판정 기준 (결과를 보기 전에 고정 · 커밋 f3d167f · 두 유니버스에 똑같이 적용)", W)
    r = text_block(ws, r + 1, [
        "A. 10년 초과수익 > 0   B. 전반·후반 5년 모두 초과수익 > 0   C. 무작위 진입 포트폴리오(추세 종목) 대비 상위 10% 이내",
        "D. 샤프 ≥ 지수 또는 최대 낙폭이 지수보다 5%p 이상 얕음   E. 설정값을 하나씩 바꾼 변형의 70% 이상에서 초과수익 > 0   F. 비용 편도 0.4%에서도 초과수익 > 0",
        "유효 = A·B·C·E 모두 충족 / 조건부 유효 = A 충족 + (C 또는 D) / 실효성 낮음 = 그 외"], W)
    rr = r + 1
    header(ws, rr, ["시장", "유니버스", "A 초과>0", "B 양쪽 기간", "C 무작위\n상위10%", "D 위험조정", "E 민감도\n70%", "F 비용\n0.4%"])
    rr += 1
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            v = view_verdict(d["views"][key])
            put(ws, rr, 1, name, bold=True)
            put(ws, rr, 2, VIEW_LABEL[key] if "pit" in d["views"] else "현재 구성종목 (편향 미보정)")
            for j, k in enumerate("ABCDEF"):
                put(ws, rr, 3 + j, "충족" if v[k] else "미충족", color=None if v[k] else RED)
            rr += 1
    r = rr + 1
    for head, key in (("실행 항목", "actions"), ("리스크", "risks"), ("의사결정 포인트", "decisions")):
        section(ws, r, head, W)
        r = text_block(ws, r + 1, notes[key], W) + 1
    widths(ws, {"A": 11, "B": 26, "C": 12, **{get_column_letter(i): 11 for i in range(4, 17)}})


def sheet_perf(wb, data):
    ws = wb.create_sheet("기본성과")
    title(ws, "기본 성과 — 현재 룰 그대로 (RS 백분위 ≥ 70), 유니버스별", SRC)
    header(ws, 4, ["시장", "유니버스", "구간", "CAGR", "지수 CAGR", "초과", "최대 낙폭", "청산 거래", "승률",
                   "평균 이익", "평균 손실", "손익비(PF)", "평균 노출"])
    r = 5
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            b = d["views"][key]["base"]
            for per, lab in (("full", "10년 전체"), ("h1", "전반 2016-09~2021-09"), ("h2", "후반 2021-09~2026-09")):
                m = b[per]
                put(ws, r, 1, name, bold=True)
                put(ws, r, 2, VIEW_LABEL[key])
                put(ws, r, 3, lab)
                put(ws, r, 4, frac(m["cagr_pct"]), PCT)
                put(ws, r, 5, frac(m["bench_cagr_pct"]), PCT)
                put(ws, r, 6, f"=D{r}-E{r}", PP, bold=True)
                put(ws, r, 7, frac(m["max_drawdown_pct"]), PCT)
                put(ws, r, 8, m["trades"], NUM)
                put(ws, r, 9, frac(m["win_rate_pct"]), PCT)
                put(ws, r, 10, frac(m["avg_win_pct"]), PCT)
                put(ws, r, 11, frac(m["avg_loss_pct"]), PCT)
                put(ws, r, 12, m["profit_factor"], RATIO)
                put(ws, r, 13, frac(m["exposure_pct"]), PCT)
                r += 1
    r += 1
    section(ws, r, "위험 대비 성과 (10년, 일간 수익률 기준)", 13)
    header(ws, r + 1, ["시장", "유니버스", "샤프", "지수 샤프", "변동성", "지수 변동성", "최대 낙폭", "지수 최대 낙폭",
                       "칼마\n(CAGR÷낙폭)", "지수 칼마", "연 거래 수", "보유 봉수\n(중간값)", "상위 10거래\n이익 비중"])
    r += 2
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            b = d["views"][key]["base"]
            k, f, t = b["risk"], b["full"], b.get("trades", {})
            put(ws, r, 1, name, bold=True)
            put(ws, r, 2, VIEW_LABEL[key])
            put(ws, r, 3, k["sharpe"], RATIO)
            put(ws, r, 4, k["bench_sharpe"], RATIO)
            put(ws, r, 5, frac(k["vol_pct"]), PCT)
            put(ws, r, 6, frac(k["bench_vol_pct"]), PCT)
            put(ws, r, 7, frac(f["max_drawdown_pct"]), PCT)
            put(ws, r, 8, frac(k["bench_mdd_pct"]), PCT)
            put(ws, r, 9, k["calmar"], RATIO)
            put(ws, r, 10, k["bench_calmar"], RATIO)
            put(ws, r, 11, t.get("per_year"), "0.0")
            put(ws, r, 12, t.get("median_bars_held"), "0")
            put(ws, r, 13, frac(t.get("top10_profit_share_pct")), PCT)
            r += 1
    note = ws.cell(row=r, column=1, value="상위 10거래 이익 비중이 100%를 넘으면 나머지 거래를 모두 합한 손익이 마이너스라는 뜻.")
    note.font = Font(name=F, size=9, color="7F7F7F")
    widths(ws, {"A": 11, "B": 27, "C": 22, **{get_column_letter(i): 11 for i in range(4, 14)}})
    ws.freeze_panes = "D5"


def yearly(eq: pd.DataFrame) -> pd.DataFrame:
    e = eq[["equity", "bench_close"]]
    ye = pd.concat([e.iloc[[0]], e.resample("YE").last()])
    rets = ye.pct_change().dropna()
    rets.index = rets.index.year
    return rets[~rets.index.duplicated(keep="last")]


def sheet_years(wb, data):
    ws = wb.create_sheet("연도별")
    title(ws, "연도별 수익률 — 실전 조건 유니버스 기준 룰 vs 지수 (2016년은 9월 26일부터, 2026년은 9월 25일까지)", SRC)
    years = list(range(2016, 2027))
    labels = ["연도"]
    cols, rets = {}, {}
    for i, (mk, name) in enumerate(MARKETS):
        d = data.get(mk)
        if d is None:
            continue
        hk, view = headline(d)
        tag = "" if hk == "pit" else " (편향 미보정)"
        labels += [f"{name}{tag}\n룰", f"{name}\n지수", f"{name}\n초과"]
        cols[mk] = 2 + 3 * len(rets)
        rets[mk] = yearly(view["equity"])
    header(ws, 4, labels)
    for k, y in enumerate(years):
        r = 5 + k
        put(ws, r, 1, str(y), bold=True)
        for mk in rets:
            if y not in rets[mk].index:
                continue
            c = cols[mk]
            put(ws, r, c, float(rets[mk].loc[y, "equity"]), PCT)
            put(ws, r, c + 1, float(rets[mk].loc[y, "bench_close"]), PCT)
            a, b = get_column_letter(c), get_column_letter(c + 1)
            put(ws, r, c + 2, f"={a}{r}-{b}{r}", PP, bold=True)
    r = 5 + len(years)
    put(ws, r, 1, "초과 > 0 연도 수", bold=True)
    for mk in rets:
        col = get_column_letter(cols[mk] + 2)
        put(ws, r, cols[mk] + 2, f'=COUNTIF({col}5:{col}{r - 1},">0")&"/"&COUNT({col}5:{col}{r - 1})', bold=True)
    widths(ws, {"A": 16, **{get_column_letter(i): 11 for i in range(2, 17)}})
    ws.freeze_panes = "B5"


def sheet_curves(wb, data):
    ws = wb.create_sheet("자산곡선")
    title(ws, "자산 곡선 — 시작 = 100 (월말 기준): 실전 조건 룰 · 기존 백테스트 룰 · 지수", SRC)
    series, months = {}, None
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        cols = {}
        if "pit" in d["views"]:
            cols["룰 (당시 구성종목)"] = d["views"]["pit"]["equity"]["equity"]
        cur = d["views"]["current"]["equity"]
        cols["룰 (현재 구성종목)"] = cur["equity"]
        cols["지수"] = cur["bench_close"]
        e = pd.DataFrame(cols).resample("ME").last().dropna()
        e = e / e.iloc[0] * 100
        series[mk] = (name, e)
        months = e.index if months is None or len(e.index) > len(months) else months
    labels = ["월"]
    for mk, (name, e) in series.items():
        labels += [f"{name} {c}" for c in e.columns]
    header(ws, 4, labels)
    for i, m in enumerate(months):
        ws.cell(row=5 + i, column=1, value=m.strftime("%Y-%m")).font = Font(name=F, size=9)
    col, k = 2, 0
    palette = [RED, "B08968", BROWN]
    for mk, (name, e) in series.items():
        e = e.reindex(months)
        for j, c in enumerate(e.columns):
            for i, v in enumerate(e[c].to_numpy()):
                if v == v:
                    cell = ws.cell(row=5 + i, column=col + j, value=round(float(v), 2))
                    cell.number_format = "0.0"
                    cell.font = Font(name=F, size=9)
        ch = LineChart()
        ch.title = f"{name} (시작 = 100)"
        ch.height, ch.width = 7.5, 16
        ch.add_data(Reference(ws, min_col=col, max_col=col + len(e.columns) - 1, min_row=4, max_row=4 + len(months)),
                    titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + len(months)))
        pal = palette[-len(e.columns):] if len(e.columns) < 3 else palette
        for s, c in zip(ch.series, pal):
            s.graphicalProperties.line.solidFill = c
            s.graphicalProperties.line.width = 20000
        ch.x_axis.tickLblSkip = 12
        ws.add_chart(ch, f"{get_column_letter(2 + sum(len(x[1].columns) for x in series.values()) + 1)}{4 + k * 16}")
        col += len(e.columns)
        k += 1
    widths(ws, {"A": 9, **{get_column_letter(i): 10 for i in range(2, 16)}})
    ws.freeze_panes = "B5"


def sheet_edge(wb, data):
    ws = wb.create_sheet("우위검증")
    title(ws, "우위 검증 — 룰이 무작위로 고른 종목보다 나은가", SRC)
    section(ws, 4, "① 포트폴리오: 같은 날짜에 같은 개수를 무작위로 샀을 때 (자금·수량·손절·청산·비용은 룰과 동일)", 10)
    header(ws, 5, ["시장", "유니버스", "무작위 풀", "룰 CAGR", "무작위\n하위 5%", "무작위\n중앙값", "무작위\n상위 5%",
                   "룰 − 무작위\n중앙값", "룰보다 낮은\n무작위 비율", "실행 횟수"])
    r = 6
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            view = d["views"][key]
            for pool, lab in (("above_ma", "추세 종목 (레짐 ON·50일선 위)"), ("candidates", "템플릿 후보 (8/8·RS≥70·레짐 ON)")):
                s = rand_stats(view, pool)
                if s is None:
                    continue
                put(ws, r, 1, name, bold=True)
                put(ws, r, 2, VIEW_LABEL[key])
                put(ws, r, 3, lab)
                put(ws, r, 4, frac(view["base"]["full"]["cagr_pct"]), PCT, bold=True)
                put(ws, r, 5, frac(s["p05"]), PCT)
                put(ws, r, 6, frac(s["p50"]), PCT)
                put(ws, r, 7, frac(s["p95"]), PCT)
                put(ws, r, 8, f"=D{r}-F{r}", PP, bold=True)
                put(ws, r, 9, frac(s["pct"]), "0%", bold=True, color=None if s["pct"] >= 90 else RED)
                put(ws, r, 10, s["n"], NUM)
                r += 1
    r += 1
    section(ws, r, "② 신호 단위 (현재 구성종목): 룰 신호 한 건 한 건을 같은 날 무작위 종목과 비교 (2,000회 추첨, 현금 제약 없음, 신호일 전체)", 10)
    header(ws, r + 1, ["시장", "비교 대상", "건수", "평균 순수익", "+20% 초과 비율", "승률", "손익비",
                       "100봉당 수익", "룰보다 낮은\n무작위 비율"])
    r += 2
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None or d["edge"] is None:
            continue
        e = d["edge"]
        ru = e["rule"]
        put(ws, r, 1, name, bold=True)
        put(ws, r, 2, "룰 신호")
        put(ws, r, 3, ru["n"], NUM)
        put(ws, r, 4, frac(ru["mean_pct"]), PCT, bold=True)
        put(ws, r, 5, frac(ru["big_rate_pct"]), PCT)
        put(ws, r, 6, frac(ru["win_rate_pct"]), PCT)
        put(ws, r, 7, ru["profit_factor"], RATIO)
        put(ws, r, 8, frac(ru["ret_per_100_bars_pct"]), PCT)
        r += 1
        for pool, lab in (("above_ma_regime_on", "같은 날 추세 종목 무작위 (중앙값)"), ("candidates", "같은 날 템플릿 후보 무작위 (중앙값)")):
            p = e["pools"].get(pool)
            if not p:
                continue
            put(ws, r, 1, name)
            put(ws, r, 2, lab)
            put(ws, r, 3, p["matched"], NUM)
            put(ws, r, 4, frac(p["mean_pct"]["p50"]), PCT)
            put(ws, r, 5, frac(p["big_rate_pct"]["p50"]), PCT)
            put(ws, r, 6, frac(p["win_rate_pct"]["p50"]), PCT)
            put(ws, r, 7, p["profit_factor"]["p50"], RATIO)
            put(ws, r, 8, frac(p["ret_per_100_bars_pct"]["p50"]), PCT)
            pc = p["mean_pct"]["rule_percentile"]
            put(ws, r, 9, frac(pc), "0%", bold=True, color=None if pc >= 90 else RED)
            r += 1
    r += 1
    section(ws, r, "③ 신호 단위 평균 순수익: 전반 vs 후반 (현재 구성종목)", 10)
    header(ws, r + 1, ["시장", "구간", "룰 신호 수", "룰 평균", "템플릿 후보 평균", "룰 − 후보", "추세 종목 평균", "룰 − 추세"])
    r += 2
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None or d["edge"] is None:
            continue
        for h, lab in (("h1", "전반 2016-09~2021-09"), ("h2", "후반 2021-09~2026-09")):
            x = d["edge"]["halves"][h]
            put(ws, r, 1, name, bold=True)
            put(ws, r, 2, lab)
            put(ws, r, 3, x["rule"]["n"], NUM)
            put(ws, r, 4, frac(x["rule"]["mean_pct"]), PCT)
            put(ws, r, 5, frac(x["candidates"]["mean_pct"]), PCT)
            put(ws, r, 6, f"=D{r}-E{r}", PP, bold=True)
            put(ws, r, 7, frac(x["above_ma_regime_on"]["mean_pct"]), PCT)
            put(ws, r, 8, f"=D{r}-G{r}", PP, bold=True)
            r += 1
    widths(ws, {"A": 11, "B": 30, "C": 30, **{get_column_letter(i): 12 for i in range(4, 11)}})


def sheet_pit(wb, data):
    ws = wb.create_sheet("생존편향")
    title(ws, "생존편향 측정 — 현재 구성종목 vs 그날의 실제 구성종목",
          SRC + " · 편입 이력: S&P500 github.com/fja05680/sp500, 코스피200·코스닥150 근사: github.com/FinanceData/marcap (시가총액 상위 200·150, 상장폐지 포함)")
    header(ws, 4, ["시장", "유니버스", "CAGR", "지수 CAGR", "초과", "최대 낙폭", "청산 거래", "승률", "전반 초과", "후반 초과", "샤프"])
    r = 5
    blocks = []
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None or d["pit_info"] is None:
            continue
        p = d["pit_info"]
        rows = [("① 현재 구성종목 (기존 백테스트)", d["views"]["current"]["base"]),
                ("② 당시 구성종목 중 현재도 편입된 종목만", p["current_members_pit_rule"]),
                ("③ 당시 구성종목 전부 (시세가 남아 있는 종목)", p["pit"])]
        first = r
        for lab, s in rows:
            put(ws, r, 1, name, bold=True)
            put(ws, r, 2, lab)
            put(ws, r, 3, frac(s["full"]["cagr_pct"]), PCT)
            put(ws, r, 4, frac(s["full"]["bench_cagr_pct"]), PCT)
            put(ws, r, 5, f"=C{r}-D{r}", PP, bold=True)
            put(ws, r, 6, frac(s["full"]["max_drawdown_pct"]), PCT)
            put(ws, r, 7, s["full"]["trades"], NUM)
            put(ws, r, 8, frac(s["full"]["win_rate_pct"]), PCT)
            put(ws, r, 9, frac(s["h1"]["excess_cagr_pp"]), PP)
            put(ws, r, 10, frac(s["h2"]["excess_cagr_pp"]), PP)
            put(ws, r, 11, s["risk"]["sharpe"], RATIO)
            r += 1
        put(ws, r, 1, name, bold=True, color=RED)
        put(ws, r, 2, "편향 크기 (① − ③)", bold=True, color=RED)
        put(ws, r, 5, f"=E{first}-E{first + 2}", PP, bold=True, color=RED)
        r += 2
        blocks.append((name, p))
    section(ws, r, "그날의 구성종목 중 시세 데이터가 있는 비율 (연도별)", 11)
    header(ws, r + 1, ["연도"] + [f"{n}\n편입 종목" for n, _ in blocks] + [f"{n}\n시세 있음 비율" for n, _ in blocks])
    r += 2
    years = sorted(set().union(*[set(p["coverage_by_year"]) for _, p in blocks]))
    for y in years:
        put(ws, r, 1, y, bold=True)
        for j, (_, p) in enumerate(blocks):
            c = p["coverage_by_year"].get(y)
            if c:
                put(ws, r, 2 + j, c["members_during_year"], NUM)
                put(ws, r, 2 + len(blocks) + j, frac(c["coverage_pct"]), "0%")
        r += 1
    r += 1
    lines = ["②와 ③의 차이는 지수에서 빠진 종목의 영향, ①과 ②의 차이는 나중에 편입된 종목을 편입 전에 미리 산 효과(미래 정보)다. "
             "스캐너는 그날의 구성종목만 보므로 실전 성과에 가까운 것은 ③이다.",
             "시세가 없는 종목은 대부분 상장폐지·인수합병·티커 변경 종목이라 무료 데이터(Yahoo)에 없다. 이 종목들을 뺄 수밖에 없어 편향이 완전히 제거되지는 않는다. "
             "상장폐지 종목은 손실로 끝난 경우가 많아 ③도 실제보다 약간 낙관적일 수 있다.",
             "코스피·코스닥의 '구성종목'은 KOSPI200·KOSDAQ150 공식 편입 이력이 아니라, 기존 백테스트와 같은 방식(그날 시가총액 상위 200·150 보통주, 스팩 제외)으로 복원했다."]
    for n, p in blocks:
        lines.append(f"{n}: 테스트 기간 구성종목 {p['members_since_test_start']}개 중 {p['members_without_data']}개 시세 없음. 예: "
                     + ", ".join(p["missing_sample"][:25]))
    text_block(ws, r, lines, 11)
    widths(ws, {"A": 11, "B": 40, **{get_column_letter(i): 12 for i in range(3, 12)}})


def sheet_variants(wb, data):
    ws = wb.create_sheet("민감도")
    title(ws, "민감도 — 설정값을 하나씩 바꿨을 때 (나머지는 현재 룰 그대로), 유니버스별", SRC)
    header(ws, 4, ["시장", "유니버스", "변형", "CAGR", "지수 CAGR", "초과", "기준 대비\n초과 변화", "전반 초과", "후반 초과",
                   "최대 낙폭", "샤프", "청산 거래"])
    r = 5
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        for key in ("pit", "current"):
            if key not in d["views"]:
                continue
            base_row = r
            for v in sorted(d["views"][key]["variants"], key=lambda x: x["n"]):
                f = v["full"]
                put(ws, r, 1, name, bold=v["n"] == 0)
                put(ws, r, 2, VIEW_LABEL[key])
                put(ws, r, 3, v["label"], bold=v["n"] == 0)
                put(ws, r, 4, frac(f["cagr_pct"]), PCT)
                put(ws, r, 5, frac(f["bench_cagr_pct"]), PCT)
                put(ws, r, 6, f"=D{r}-E{r}", PP, bold=True)
                put(ws, r, 7, f"=F{r}-$F${base_row}", PP)
                put(ws, r, 8, frac(v["h1"]["excess_cagr_pp"]), PP)
                put(ws, r, 9, frac(v["h2"]["excess_cagr_pp"]), PP)
                put(ws, r, 10, frac(f["max_drawdown_pct"]), PCT)
                put(ws, r, 11, v["risk"]["sharpe"], RATIO)
                put(ws, r, 12, f["trades"], NUM)
                if v["n"] == 0:
                    for j in range(1, 13):
                        ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=BEIGE)
                r += 1
            r += 1
    widths(ws, {"A": 11, "B": 27, "C": 28, **{get_column_letter(i): 11 for i in range(4, 13)}})
    ws.freeze_panes = "D5"


def sheet_trades(wb, data):
    ws = wb.create_sheet("거래목록")
    title(ws, "거래 목록 — 실전 조건 유니버스 기준 10년 포트폴리오 (청산 완료 거래)", SRC)
    header(ws, 4, ["시장", "유니버스", "종목", "신호일", "신호 RS", "진입일", "진입가", "청산일", "청산가", "청산 사유",
                   "보유 봉수", "순수익률", "순손익 (현지 통화)"])
    r = 5
    kind = {"STOP": "손절", "EXIT_MA": "50일선 이탈"}
    for mk, name in MARKETS:
        d = data.get(mk)
        if d is None:
            continue
        hk, view = headline(d)
        uni = VIEW_LABEL[hk] if hk == "pit" else "현재 구성종목 (편향 미보정)"
        for x in view["trades"].sort_values("entry_date").itertuples():
            vals = [name, uni, x.symbol, x.signal_date, round(float(x.rs_at_signal), 1), x.entry_date,
                    float(x.entry_price), x.exit_date, float(x.exit_price), kind.get(x.exit_type, x.exit_type),
                    int(x.bars_held), float(x.pnl_pct) / 100, float(x.net_pnl)]
            fmts = [None, None, None, None, "0.0", None, "#,##0.00", None, "#,##0.00", None, "0", PCT, "#,##0"]
            for j, (v, fm) in enumerate(zip(vals, fmts)):
                c = ws.cell(row=r, column=j + 1, value=v)
                c.font = Font(name=F, size=9, color=(RED if j == 11 and v < 0 else None))
                if fm:
                    c.number_format = fm
            r += 1
    ws.auto_filter.ref = f"A4:M{r - 1}"
    widths(ws, {"A": 10, "B": 26, "C": 12, "D": 11, "E": 8, "F": 11, "G": 12, "H": 11, "I": 12, "J": 11, "K": 9, "L": 10, "M": 16})
    ws.freeze_panes = "D5"


def sheet_method(wb, notes):
    ws = wb.create_sheet("방법·한계")
    title(ws, "방법과 한계")
    text_block(ws, 3, notes["method"], 12)
    widths(ws, {"A": 14})


def main():
    rob, out, notes_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    notes = json.loads(notes_path.read_text())
    data = {mk: load(rob, mk) for mk, _ in MARKETS}
    data = {k: v for k, v in data.items() if v is not None}
    wb = Workbook()
    sheet_summary(wb, data, notes)
    sheet_perf(wb, data)
    sheet_years(wb, data)
    sheet_curves(wb, data)
    sheet_edge(wb, data)
    sheet_pit(wb, data)
    sheet_variants(wb, data)
    sheet_trades(wb, data)
    sheet_method(wb, notes)
    for ws in wb.worksheets:                      # print: landscape, one page wide
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    wb.save(out)
    print(json.dumps({mk: {k: view_verdict(v) for k, v in d["views"].items()} for mk, d in data.items()},
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
