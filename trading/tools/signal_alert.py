"""Signal alert for the paper-trading ledger (docs/swing-improvement-policy.md, R7).

    python tools/signal_alert.py --ledger ../ledger/paper --market KOSDAQ --since <sha> \
        [--report-url URL] [--github-issue TITLE] [--latest] [--dry-run]

One message per signal file (new day or revision) committed to the ledger since <sha>, the
ledger HEAD before this run, so a rerun that committed nothing sends nothing. --latest takes
the newest signal file whether or not it is new (a test post).

Delivery: a Slack incoming webhook when SLACK_WEBHOOK_URL is set; otherwise a comment on the
GitHub issue with the given title (created on first use, through `gh`), so GitHub's own
notifications reach the owner by e-mail and in the app. The message is printed either way.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import data as D                              # noqa: E402
from swing_engine.paper import DISCLAIMER, MARKET_KO            # noqa: E402

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
WEEKDAY_KO = "월화수목금토일"


def _git(repo: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def new_signal_files(ledger: Path, market: str, since: str | None) -> list[Path]:
    """Signal files added to the ledger repository since commit `since` (all of them when empty)."""
    repo = Path(_git(ledger, "rev-parse", "--show-toplevel"))
    sig_dir = (ledger / market / "signals").resolve()
    has_head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
                              capture_output=True).returncode == 0
    if not has_head:
        return []                                                 # no commit yet
    base = since.strip() if since and since.strip() else EMPTY_TREE
    # pathspecs are relative to git's working directory, so run from the repository root
    out = _git(repo, "diff", "--name-only", "--diff-filter=A", base, "HEAD", "--",
               str(sig_dir.relative_to(repo)))
    return sorted(repo / ln for ln in out.splitlines() if ln.strip().endswith(".json"))


def latest_signal_file(ledger: Path, market: str) -> Path | None:
    files = sorted((ledger / market / "signals").glob("*.json"))
    return files[-1] if files else None


def latest_entry(ledger: Path, market: str) -> dict | None:
    p = ledger / "latest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("markets", {}).get(market)


def _f(x, fmt="{:,.2f}"):
    return "-" if x is None else fmt.format(x)


def _qty(q):
    return "-" if q is None else (f"{q:,.0f}" if float(q).is_integer() else f"{q:,.2f}")


def _local(iso: str | None, market: str) -> str:
    if not iso:
        return ""
    sess = D.session_for(market)
    tz = ZoneInfo(sess[0]) if sess else timezone.utc
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)
    return t.strftime("%H:%M ") + ("KST" if tz.key == "Asia/Seoul" else "UTC" if tz is timezone.utc else t.tzname())


def render(signal: dict, entry: dict | None, fmt: str = "github", report_url: str | None = None,
           revision: int | None = None) -> str:
    """The message for one signal file. `entry` is latest.json's market entry (positions, stale)."""
    slack = fmt == "slack"
    B = "*" if slack else "**"
    bullet = "•" if slack else "-"
    market = signal["market"]
    name = MARKET_KO.get(market, market)
    as_of = datetime.strptime(signal["as_of"], "%Y-%m-%d")
    rg = signal["regime"]
    L = []
    head = f"{name} 모의투자 신호 · 기준일 {signal['as_of']} ({WEEKDAY_KO[as_of.weekday()]})"
    if revision:
        head = f"⚠ 신호 수정본 {revision} — " + head
    L.append(f"{B}{head}{B} → 다음 거래일 시가에 실행")
    if revision:
        L.append("앞서 커밋한 신호 파일은 그대로 남고, 이 수정본은 감사 기록에 '수정'으로 집계됩니다.")
    state = "ON" if rg.get("on") else ("OFF — 신규 진입 없음" if rg.get("on") is not None else "?")
    filt = {"NONE": "필터 없음", "BREADTH50": "폭 레짐 50"}.get(rg.get("mode"), rg.get("mode", ""))
    L.append(f"레짐 {state} ({filt}) — {rg['benchmark']} 종가 {_f(rg.get('close'))} · 200일선 {_f(rg.get('ma200'))}"
             + (f" · 200일선 위 비율 {rg['breadth_pct']:.1f}%" if rg.get("breadth_pct") is not None else ""))

    ent = signal.get("entries_next_open", [])
    L.append(f"{B}다음 시가 진입 ({len(ent)}){B}" + ("" if ent else ": 없음"))
    for e in ent:
        stop_pct = (e["est_stop_from_close"] / e["signal_close"] - 1) * 100 if e.get("signal_close") else None
        L.append(f"{bullet} {e['symbol']} — 신호 종가 {_f(e['signal_close'])} · 예상 손절 {_f(e['est_stop_from_close'])}"
                 + (f" ({stop_pct:+.0f}%)" if stop_pct is not None else "")
                 + f" · 모의 수량 {_qty(e.get('desired_qty'))} · RS {_f(e.get('rs'), '{:.1f}')}")
    if ent:
        L.append("실제 손절가는 체결가(시가) × (1 − 손절%). 시가가 신호 종가보다 15% 넘게 높으면 추격하지 않습니다.")
    ex = signal.get("exits_next_open", [])
    L.append(f"{B}다음 시가 청산 ({len(ex)}){B}" + (": " + ", ".join(ex) if ex else ": 없음"))

    positions = (entry or {}).get("positions")
    if positions is not None:
        L.append(f"{B}보유 ({len(positions)}){B}" + ("" if positions else ": 없음"))
        for p in sorted(positions, key=lambda x: x.get("entry_date", "")):
            L.append(f"{bullet} {p['symbol']} — 진입 {p.get('entry_date', '-')} {_f(p.get('entry_price'))} · "
                     f"손절 {_f(p.get('stop_price'))} · 현재 {_f(p.get('last_close'))} · {p.get('price_pnl_pct', 0):+.2f}%")
    else:
        syms = signal.get("positions", [])
        L.append(f"{B}보유 ({len(syms)}){B}: " + (", ".join(syms) or "없음"))
    stale = (entry or {}).get("stale_positions") or []
    for st in stale:
        L.append(f"⚠ {B}{st['symbol']}: 기준일 시세 없음{B} (마지막 봉 {st.get('last_bar') or '?'}, "
                 f"{st.get('sessions_missing') or '?'}거래일째) — 거래정지·상장폐지 의심, 종목 상태를 확인하세요.")

    near = [w["symbol"] for w in signal.get("watchlist", []) if "1순위" in w.get("label", "")]
    if near:
        L.append(f"관찰 임박 (피벗 1% 이내): {', '.join(near)}")
    cov = signal.get("coverage", {})
    if cov.get("failed"):
        L.append(f"데이터 실패 {len(cov['failed'])}/{cov.get('requested', '?')}종목: {', '.join(cov['failed'][:8])}")

    tail = []
    gen = _local(signal.get("generated_at"), market)
    if gen:
        tail.append(f"신호 생성 {gen}")
    if report_url:
        tail.append(f"<{report_url}|보고서>" if slack else f"[보고서]({report_url})")
    if tail:
        L.append(" · ".join(tail))
    L.append(f"_{DISCLAIMER}_")
    return "\n".join(L)


def post_slack(url: str, text: str) -> None:
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:       # noqa: S310 - the owner's own webhook
        if r.status >= 300:
            raise RuntimeError(f"slack webhook returned {r.status}")


def _gh(*args) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


ISSUE_BODY = ("이 이슈는 {name} 모의투자 신호 알림 스레드입니다. 장 마감 후 신호 파일이 장부 브랜치에 커밋될 때마다 "
              "자동으로 댓글이 달립니다. 알림을 받으려면 이 이슈를 구독(Subscribe)하거나 저장소를 Watch 하세요.\n\n"
              "> {disclaimer}")


def post_github_issue(title: str, body: str, name: str, gh=_gh) -> int:
    """Comment on the open issue titled `title`, creating it first when there is none."""
    issues = json.loads(gh("issue", "list", "--state", "open", "--limit", "200", "--json", "number,title") or "[]")
    hit = [i["number"] for i in issues if i["title"] == title]
    if hit:
        number = hit[0]
    else:
        url = gh("issue", "create", "--title", title,
                 "--body", ISSUE_BODY.format(name=name, disclaimer=DISCLAIMER))
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
    gh("issue", "comment", str(number), "--body", body)
    return number


def _revision(path: Path) -> int | None:
    stem = path.stem                                            # 2026-10-02 or 2026-10-02.rev1
    return int(stem.rsplit(".rev", 1)[1]) if ".rev" in stem else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True, help="the ledger's paper/ directory inside its git checkout")
    ap.add_argument("--market", required=True)
    ap.add_argument("--since", default="", help="ledger HEAD before this run (empty: every signal file)")
    ap.add_argument("--latest", action="store_true", help="alert on the newest signal file even if it is not new")
    ap.add_argument("--report-url", default=None)
    ap.add_argument("--github-issue", default=None, help="issue title (default: '<market> 모의투자 신호 알림')")
    ap.add_argument("--slack-webhook", default=os.environ.get("SLACK_WEBHOOK_URL") or None)
    ap.add_argument("--dry-run", action="store_true", help="print only")
    a = ap.parse_args(argv)

    ledger = Path(a.ledger).resolve()
    market = a.market
    name = MARKET_KO.get(market, market)
    if a.latest:
        p = latest_signal_file(ledger, market)
        files = [p] if p else []
    else:
        files = new_signal_files(ledger, market, a.since)
    if not files:
        print(f"{market}: no new signal file; nothing to send")
        return 0
    entry = latest_entry(ledger, market)
    title = a.github_issue or f"{name} 모의투자 신호 알림"
    for p in files:
        signal = json.loads(p.read_text())
        ent = entry if entry and entry.get("as_of") == signal.get("as_of") else None
        fmt = "slack" if a.slack_webhook else "github"
        text = render(signal, ent, fmt, a.report_url, _revision(p))
        if a.latest and not a.dry_run:
            text = ("[테스트 발송] " if fmt == "slack" else "**[테스트 발송]** ") + text
        print(f"----- {p.name}\n{text}\n")
        if a.dry_run:
            continue
        if a.slack_webhook:
            post_slack(a.slack_webhook, text)
            print(f"{market}: sent to Slack")
        else:
            n = post_github_issue(title, text, name)
            print(f"{market}: commented on issue #{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
