"""Point-in-time KOSPI top-200 / KOSDAQ top-150 membership from the FinanceData/marcap dataset.

    python tools/krx_membership.py --market KOSPI --start 2014 --out data/KOSPI_membership.csv.gz \
        [--extra extra.txt]

marcap (github.com/FinanceData/marcap) holds KRX's daily all-stock snapshot since 1995,
including delisted stocks. For every trading day the universe is the top-N common stocks
of the market by market cap, with the same filters as data.fetch_krx_top (codes ending
in '0', no SPACs). Output rows: date, codes (comma-joined 6-digit codes).
--extra writes every code that was ever in the universe as a Yahoo ticker (.KS/.KQ by the
stock's last market in the data).
"""
import argparse
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swing_engine.data import UNIVERSE_SIZES  # noqa: E402

URL = "https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"


def load_year(year: int) -> pd.DataFrame:
    r = requests.get(URL.format(year=year), timeout=120)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    if "Date" not in df.columns:
        df = df.reset_index()
    return df


def membership(df: pd.DataFrame, market: str, n: int) -> tuple[pd.DataFrame, dict]:
    d = df.copy()
    d["Code"] = d["Code"].astype(str).str.zfill(6).str.upper()
    d["Market"] = d["Market"].astype(str)
    is_mk = d["Market"].str.upper().str.startswith(market)          # KOSDAQ includes 'KOSDAQ GLOBAL'
    ok = d["Code"].str.fullmatch(r"[0-9A-Z]{5}0") & ~d["Name"].astype(str).str.contains("스팩")
    if "Dept" in d.columns:
        ok &= ~d["Dept"].astype(str).str.contains("SPAC", case=False, na=False)
    d["Marcap"] = pd.to_numeric(d["Marcap"], errors="coerce")
    d = d[is_mk & ok & d["Marcap"].notna()]
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.sort_values(["Date", "Marcap"], ascending=[True, False], kind="stable")
    top = d.groupby("Date").head(n)
    rows = top.groupby("Date")["Code"].apply(lambda s: ",".join(s)).reset_index()
    rows.columns = ["date", "codes"]
    last_market = df.assign(Code=df["Code"].astype(str).str.zfill(6).str.upper(),
                            Date=pd.to_datetime(df["Date"])).sort_values("Date").groupby("Code")["Market"].last()
    return rows, last_market.to_dict()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["KOSPI", "KOSDAQ"])
    ap.add_argument("--start", type=int, default=2014)
    ap.add_argument("--end", type=int, default=date.today().year)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", default=None)
    ap.add_argument("--latest", default=None, help="write the latest day's universe as Yahoo tickers")
    a = ap.parse_args()
    n = UNIVERSE_SIZES[a.market]
    rows, last_market = [], {}
    for y in range(a.start, a.end + 1):
        df = load_year(y)
        r, lm = membership(df, a.market, n)
        rows.append(r)
        last_market.update(lm)
        print(y, len(df), "rows ->", len(r), "days", flush=True)
    out = pd.concat(rows, ignore_index=True)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False)
    codes = sorted(set(",".join(out["codes"]).split(",")))
    print(a.market, "top", n, ":", len(codes), "codes ever in the universe", flush=True)
    def yahoo(c):
        return c + (".KS" if str(last_market.get(c, a.market)).upper().startswith("KOSPI") else ".KQ")

    if a.extra:
        Path(a.extra).write_text("\n".join(yahoo(c) for c in codes))
    if a.latest:
        Path(a.latest).write_text("\n".join(yahoo(c) for c in out["codes"].iloc[-1].split(",")))


if __name__ == "__main__":
    main()
