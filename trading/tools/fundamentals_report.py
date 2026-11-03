"""Financial-statement summary for listed companies from the official filings APIs.

    DART_API_KEY=... python tools/fundamentals_report.py --symbols 005930.KS,AAPL [--years 5] [--out reports/] [--cache-dir .cache] [--no-price]

Korean codes (6 digits, .KS/.KQ optional) are read from DART (연결재무제표), US tickers from SEC EDGAR
company facts. One Markdown page per symbol plus a JSON with the periods and ratios. The last
close (for PER/PBR) comes from Yahoo when available; without it valuation rows are left out.
Reference material only: the swing rules stay technical.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine import dart, edgar, fundamentals  # noqa: E402

KR = re.compile(r"^\d{5}[0-9A-Z]$")


def last_close(symbol: str):
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
        return float(h["Close"].dropna().iloc[-1]) if len(h) else None
    except Exception:                                   # noqa: BLE001 - price is optional
        return None


def build(symbol: str, years: int, cache_dir, with_price: bool) -> fundamentals.Company:
    code = symbol.split(".")[0].upper()
    if KR.match(code):
        key = dart.api_key()
        if not key:
            raise dart.DARTError("DART_API_KEY is not set")
        ysym = symbol if "." in symbol else f"{code}.KS"
        yrs = list(range(date.today().year - years, date.today().year + 1))
        price = last_close(ysym) if with_price else None
        codes = dart.corp_codes(key, cache_dir)
        corp = codes.get(code, (None, None))[0]
        shares = dart.shares_outstanding(key, corp, date.today().year - 1, cache_dir) if corp else None
        return dart.company(ysym, key, yrs, cache_dir, price=price, shares=shares)
    price = last_close(symbol) if with_price else None
    return edgar.company(symbol, cache_dir, price=price)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", required=True, help="comma-separated: 005930.KS, 096530.KQ, AAPL, BRK-B")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--cache-dir", default=".cache")
    ap.add_argument("--no-price", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rc = 0
    for sym in [s.strip() for s in a.symbols.split(",") if s.strip()]:
        try:
            c = build(sym, a.years, a.cache_dir, not a.no_price)
        except (dart.DARTError, edgar.EdgarError) as e:
            print(f"## {sym}\n\nFAILED: {e}\n")
            rc = 1
            continue
        md = fundamentals.render(c)
        stem = sym.replace(".", "_").replace("-", "_")
        (out / f"{stem}.md").write_text(md, encoding="utf-8")
        (out / f"{stem}.json").write_text(json.dumps({"symbol": c.symbol, "name": c.name, "source": c.source, "currency": c.currency,
                                                        "price": c.price, "shares": c.shares, "periods": c.periods,
                                                        "ratios": fundamentals.ratios(c.periods), "valuation": c.valuation(), "notes": c.notes},
                                                       ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(md)
    return rc


if __name__ == "__main__":
    sys.exit(main())
