"""Listen to KIS real-time trades for the held symbols on the owner's Mac (checklist 2.5).

    python tools/kis_ws_probe.py [--minutes 60] [--symbols 425420,093320] [--venue J|NX|UN]
                                 [--env-file ~/.config/beomstar/kis.env] [--out ~/beomstar/kis_ws]

Without --symbols the held symbols (and their stop prices) of the Korean ledgers are read from
paper/latest.json on origin/paper-trading (the repository must be a clone with that remote).
Writes <out>/ticks_<date>.jsonl (every trade) and <out>/summary_<date>.json, prints a summary
every 5 minutes and at the end. Needs `pip install websocket-client`. Listening only: no orders.
Market hours: KRX 09:00-15:30 KST (venue J); NXT 08:00-20:00 (NX); UN = both.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import kis_ws  # noqa: E402
from swing_engine.kis import KISError  # noqa: E402

KR_MARKETS = ("KOSPI", "KOSDAQ", "KOSDAQ_V2")


def held_from_ledger(repo: Path, ref: str = "origin/paper-trading") -> dict:
    """{code: stop_price} of the Korean ledgers' open positions."""
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", "paper-trading"], capture_output=True)
    r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:paper/latest.json"], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    out = {}
    for m, e in json.loads(r.stdout).get("markets", {}).items():
        if m in KR_MARKETS:
            for p in e.get("positions") or []:
                out[p["symbol"].split(".")[0]] = p.get("stop_price")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--symbols", default=None, help="comma-separated 6-digit codes (default: held symbols)")
    ap.add_argument("--venue", default="J", choices=sorted(kis_ws.TR_ID))
    ap.add_argument("--env-file", default=os.path.expanduser("~/.config/beomstar/kis.env"))
    ap.add_argument("--out", default=os.path.expanduser("~/beomstar/kis_ws"))
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--report-every", type=float, default=300, help="seconds between interim summaries")
    a = ap.parse_args(argv)
    try:
        import websocket  # websocket-client
    except ImportError:
        print("pip install websocket-client", file=sys.stderr)
        return 2
    try:
        cred = kis_ws.env_file_credentials(a.env_file)
    except KISError as e:
        print(e, file=sys.stderr)
        return 2
    if cred is None:
        print(f"KIS_APP_KEY / KIS_APP_SECRET not set (env or {a.env_file})", file=sys.stderr)
        return 2
    if a.symbols:
        stops = {c.strip().split(".")[0]: None for c in a.symbols.split(",") if c.strip()}
    else:
        stops = held_from_ledger(Path(a.repo))
        if not stops:
            print("no held Korean symbols in the ledger; pass --symbols", file=sys.stderr)
            return 2
    codes = sorted(stops)[:kis_ws.MAX_SUBSCRIPTIONS]
    print(f"KIS WebSocket probe · env {cred['env']} · venue {a.venue} ({kis_ws.TR_ID[a.venue]}) · "
          f"{len(codes)} symbols {codes} · {a.minutes:g} min · key length {len(cred['key'])} (never printed)")
    try:
        key = kis_ws.approval_key(cred)
    except KISError as e:
        print("APPROVAL FAILED:", e)
        return 1
    print(f"approval key ok (length {len(key)})")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    log = open(out / f"ticks_{day}.jsonl", "a", encoding="utf-8")
    rec = kis_ws.Recorder(stops=stops)
    deadline = time.monotonic() + a.minutes * 60
    next_report = time.monotonic() + a.report_every
    reconnects = 0
    while time.monotonic() < deadline:
        try:
            ws = websocket.create_connection(kis_ws.WS_URL[cred["env"]], timeout=30)
            for c in codes:
                ws.send(kis_ws.subscribe_message(key, c, a.venue))
            while time.monotonic() < deadline:
                try:
                    text = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                kind, payload = rec.on_frame(text)
                if kind == "control":
                    if kis_ws.is_pingpong(payload):
                        ws.send(text)                              # echo the ping back
                    else:
                        trk, rt, msg = kis_ws.ack_status(payload)
                        if rt is not None:
                            print(f"  ack {trk}: rt_cd {rt} {msg}")
                elif kind == "ticks":
                    for t in payload:
                        log.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **t}, ensure_ascii=False) + "\n")
                    log.flush()
                elif kind == "other":
                    print(f"  ? {text[:120]}")
                if time.monotonic() >= next_report:
                    print(f"[{datetime.now():%H:%M:%S}] {rec.summary_text()}")
                    next_report = time.monotonic() + a.report_every
            ws.close()
        except (OSError, websocket.WebSocketException) as e:
            reconnects += 1
            print(f"socket error ({e}); reconnect {reconnects}")
            if reconnects > 5:
                break
            time.sleep(5)
    log.close()
    sm = rec.summary()
    sm["reconnects"], sm["venue"], sm["env"], sm["minutes"] = reconnects, a.venue, cred["env"], a.minutes
    (out / f"summary_{day}.json").write_text(json.dumps(sm, ensure_ascii=False, indent=1))
    print("\nRESULT:", rec.summary_text())
    print(f"files: {out / f'ticks_{day}.jsonl'} · {out / f'summary_{day}.json'} (send the summary, never the env file)")
    return 0 if rec.stats else 1


if __name__ == "__main__":
    sys.exit(main())
