"""Probe the KRX Open API (checklist 1.4): one date, the four services the ledger will cross-check
against Yahoo. Prints row counts, the field names, one sample row per service and, when a Yahoo
bar for the same date is cached, the differences.

    KRX_API_KEY=... python tools/krx_probe.py --date 20261029 [--symbol 096530] [--cache-dir .cache]

Request shape (confirmed from three public clients, 2026-10-30): GET
https://data-dbg.krx.co.kr/svc/apis/<group>/<service>?basDd=YYYYMMDD with the key in the AUTH_KEY
header (never in the URL, so it cannot leak into logs or redirects); the body is {"OutBlock_1":
[rows]}, numbers as strings that may carry thousands separators. Data covers T-1 and earlier;
asking for today returns an empty list. Each service must be approved separately on
openapi.krx.co.kr after the key is issued: an unapproved one answers with an error page or an
empty block, which this probe reports instead of hiding.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://data-dbg.krx.co.kr/svc/apis"
SERVICES = {                      # name: (path, description)
    "KOSPI_STOCKS": ("sto/stk_bydd_trd", "유가증권 일별매매정보"),
    "KOSDAQ_STOCKS": ("sto/ksq_bydd_trd", "코스닥 일별매매정보"),
    "KOSPI_INDEX": ("idx/kospi_dd_trd", "KOSPI 시리즈 일별시세정보"),
    "KOSDAQ_INDEX": ("idx/kosdaq_dd_trd", "KOSDAQ 시리즈 일별시세정보"),
}
STOCK_FIELDS = ("BAS_DD", "ISU_CD", "ISU_NM", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL")
INDEX_FIELDS = ("BAS_DD", "IDX_NM", "OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "CLSPRC_IDX", "ACC_TRDVOL")


def num(s):
    """'1,234.5' -> 1234.5; '-' or '' -> None."""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def short_code(isu_cd: str) -> str:
    """KRX gives either the 6-digit short code or the 12-character ISIN (KR7005930003);
    Yahoo symbols are the 6-digit code plus .KS/.KQ."""
    s = str(isu_cd).strip()
    return s[3:9] if len(s) == 12 and s.startswith("KR") else s


def fetch(service: str, date: str, key: str, timeout: int = 30) -> tuple[list[dict] | None, str]:
    """(rows, note). rows is None when the call failed; note explains either way."""
    path, _ = SERVICES[service]
    req = urllib.request.Request(f"{BASE}/{path}?basDd={date}",
                                 headers={"AUTH_KEY": key.strip(), "User-Agent": "beomstar-swing-probe/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} ({'key rejected' if e.code == 401 else 'rate limit' if e.code == 429 else 'error'})"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"network: {getattr(e, 'reason', e)}"
    try:
        data = json.loads(body)
    except ValueError:
        head = body[:120].decode("utf-8", "replace").replace("\n", " ")
        return None, f"not JSON (HTTP {status}); service probably not approved yet: {head!r}"
    if not isinstance(data, dict) or "OutBlock_1" not in data:
        return None, f"no OutBlock_1; keys {list(data)[:5] if isinstance(data, dict) else type(data).__name__}"
    return data["OutBlock_1"], f"HTTP {status}"


def yahoo_bar(cache_dir: Path, symbol: str, date_iso: str) -> dict | None:
    """The cached Yahoo bar (data.py CSV cache) for one symbol and date, if present."""
    import csv
    for p in cache_dir.rglob(f"{symbol}.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Date", "")[:10] == date_iso:
                    return {k: num(v) for k, v in row.items() if k in ("Open", "High", "Low", "Close", "Volume")}
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="YYYYMMDD, a past KRX trading day")
    ap.add_argument("--symbol", default="096530", help="6-digit code to show and compare (default 096530, KOSDAQ)")
    ap.add_argument("--cache-dir", default=None, help="Yahoo CSV cache to compare against (optional)")
    a = ap.parse_args(argv)
    key = os.environ.get("KRX_API_KEY", "")
    if not key:
        print("KRX_API_KEY is not set", file=sys.stderr)
        return 2
    if len(a.date) != 8 or not a.date.isdigit():
        print("--date must be YYYYMMDD", file=sys.stderr)
        return 2
    date_iso = f"{a.date[:4]}-{a.date[4:6]}-{a.date[6:]}"
    ok = True
    print(f"KRX probe · basDd={a.date} · key length {len(key.strip())} (value never printed)")
    for name, (path, desc) in SERVICES.items():
        rows, note = fetch(name, a.date, key)
        if rows is None:
            print(f"\n[{name}] {desc} · {path} · FAILED · {note}")
            ok = False
            continue
        print(f"\n[{name}] {desc} · {path} · {note} · rows {len(rows)}")
        if not rows:
            print("  empty: date not a trading day, data not published yet (T-1 rule), or service not approved")
            ok = False
            continue
        print(f"  fields: {', '.join(rows[0].keys())}")
        if name.endswith("STOCKS"):
            hit = next((r for r in rows if short_code(r.get("ISU_CD", "")) == a.symbol), None)
            sample = hit or rows[0]
            print(f"  code format: ISU_CD={rows[0].get('ISU_CD')!r} -> short {short_code(rows[0].get('ISU_CD', ''))}")
            print("  sample:", {k: sample.get(k) for k in STOCK_FIELDS if k in sample})
            if hit and a.cache_dir:
                suffix = ".KQ" if name.startswith("KOSDAQ") else ".KS"
                yb = yahoo_bar(Path(a.cache_dir), a.symbol + suffix, date_iso)
                if yb:
                    kb = {"Open": num(hit["TDD_OPNPRC"]), "High": num(hit["TDD_HGPRC"]), "Low": num(hit["TDD_LWPRC"]),
                          "Close": num(hit["TDD_CLSPRC"]), "Volume": num(hit["ACC_TRDVOL"])}
                    print(f"  Yahoo {a.symbol}{suffix} {date_iso}: {yb}")
                    print(f"  KRX   {a.symbol}{suffix} {date_iso}: {kb}")
                    diffs = {k: (yb[k], kb[k]) for k in kb if yb.get(k) is not None and kb[k] is not None and yb[k] != kb[k]}
                    print("  differences:", diffs or "none")
                else:
                    print(f"  (no Yahoo bar for {a.symbol}{suffix} on {date_iso} in the cache)")
        else:
            want = "코스닥" if name.startswith("KOSDAQ") else "코스피"
            hit = next((r for r in rows if str(r.get("IDX_NM", "")).strip() in (want, "KOSPI", "KOSDAQ")), rows[0])
            print("  sample:", {k: hit.get(k) for k in INDEX_FIELDS if k in hit})
            print("  index names:", [r.get("IDX_NM") for r in rows[:8]], "..." if len(rows) > 8 else "")
    print("\nRESULT:", "all four services answered with rows" if ok else "something needs attention (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
