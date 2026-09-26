"""analyze.py report and backtest.py CLI (offline)."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import make_bars, rising_bench, uptrend_with_breakout
from swing_engine import analyze, backtest
from swing_engine.data import write_bars_csv

FORBIDDEN = ("목표가", "익절", "목표 가격", "target")


def _append(df, o, h, l, c, v=1e6):
    d = df.index[-1] + pd.offsets.BDay(1)
    return pd.concat([df, pd.DataFrame({"open": [o], "high": [h], "low": [l], "close": [c], "volume": [v]}, index=[d])])


def test_report_signal_pending():
    df = uptrend_with_breakout()
    rep = analyze.build_report(df, rising_bench(df.index), "SP500", "TEST", equity=100_000_000)
    assert rep["position"]["state"] == "entry_pending"
    assert rep["status"] == "신호 확정 → 다음 시가 진입"
    c = float(df["close"].iloc[-1])
    assert rep["position"]["est_stop_from_close"] == pytest.approx(c * 0.9)
    assert rep["position"]["sizing"]["qty"] == pytest.approx(100_000_000 * 0.75 / 100 / (c * 10 / 100))
    assert rep["trend_template"]["count"] == 8 and len(rep["trend_template"]["conditions"]) == 8
    txt = analyze.render_text(rep)
    for s in ("데이터 기준일", "레짐: S&P500 · ON", "트렌드 템플릿: 8/8", "RS 프록시", "트리거(피벗)",
              "당일 거래량 배수: 2.00배", "다음 거래일 시가", "진입가 × (1 − 10%)", "신호봉 종가 기준 추정",
              "비중 7.5%", "미확인 추정값", "기계적 룰 출력", "소유자 본인"):
        assert s in txt, s
    assert not any(f in txt for f in FORBIDDEN)
    json.dumps(rep, ensure_ascii=False, default=str)


def test_report_in_position_and_exit_pending():
    df = uptrend_with_breakout()
    c = float(df["close"].iloc[-1])
    df = _append(df, c * 1.01, c * 1.03, c * 1.0, c * 1.02)
    rep = analyze.build_report(df, rising_bench(df.index), "SP500", "TEST")
    pos = rep["position"]
    assert pos["state"] == "in_position" and pos["entry_price"] == pytest.approx(c * 1.01)
    assert pos["stop_price"] == pytest.approx(c * 1.01 * 0.9) and not pos["exit_pending"]
    assert rep["status"] == "보유 중 — 50일선 종가 이탈 시 청산"
    # close below the 50-day MA but above the stop -> exit pending, label unchanged
    ma50 = rep["trend_template"]["conditions"][4]["values"]["ma50"]
    df2 = _append(df, c * 1.0, c * 1.0, ma50 * 0.985, ma50 * 0.99)      # low stays above the stop
    rep2 = analyze.build_report(df2, rising_bench(df2.index), "SP500", "TEST")
    assert rep2["position"]["exit_pending"] and rep2["status"].startswith("보유 중")
    txt = analyze.render_text(rep2)
    assert "다음 거래일 시가에 전량 청산 대기" in txt and "청산선 여유" in txt
    assert not any(f in txt for f in FORBIDDEN)


def test_report_integer_shares_for_kospi():
    df = uptrend_with_breakout() * 1000
    rep = analyze.build_report(df, rising_bench(df.index), "KOSDAQ", "123456.KQ", equity=50_000_000)
    q = rep["position"]["sizing"]["qty"]
    assert q == int(q) and rep["integer_shares"]


def test_analyze_cli_csv_json_and_text(tmp_path, capsys):
    df = uptrend_with_breakout()
    write_bars_csv(df, tmp_path / "SYM.csv")
    write_bars_csv(rising_bench(df.index), tmp_path / "BENCH.csv")
    args = ["--preset", "SP500", "--symbol", "SYM", "--csv", str(tmp_path / "SYM.csv"),
            "--bench-csv", str(tmp_path / "BENCH.csv"), "--equity", "10000000"]
    assert analyze.main(args + ["--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["status"] == "신호 확정 → 다음 시가 진입" and rep["equity"] == 10_000_000
    assert rep["data_date"] == df.index[-1].strftime("%Y-%m-%d")
    assert analyze.main(args + ["--as-of", df.index[-2].strftime("%Y-%m-%d")]) == 0
    out = capsys.readouterr().out
    assert "데이터 기준일: " + df.index[-2].strftime("%Y-%m-%d") in out
    assert analyze.main(args + ["--drop-last-bar"]) == 0
    assert "마지막 확정 일봉 (장중 미확정 봉은 제외)" in capsys.readouterr().out


def _universe(tmp_path, n_sym=5, n=900):
    rng = np.random.default_rng(11)
    d = pd.bdate_range("2019-01-01", periods=n)
    for k in range(n_sym):
        c = 30 * np.exp(np.cumsum(rng.normal(0.0012, 0.018, n)))
        o = c * (1 + rng.normal(0, 0.004, n))
        v = rng.lognormal(13, 0.5, n)
        df = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
                           "close": c, "volume": v}, index=d)
        write_bars_csv(df, tmp_path / f"S{k}.csv")
    write_bars_csv(pd.DataFrame({"close": 3000 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n)))}, index=d),
                   tmp_path / "GSPC.csv")
    return d


def test_backtest_cli_offline(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    d = _universe(data_dir)
    out = tmp_path / "out"
    rc = backtest.main(["--market", "SP500", "--start", "2019-01-01", "--end", d[-1].strftime("%Y-%m-%d"),
                        "--test-start", "2020-03-01", "--rs-mode", "both", "--offline-dir", str(data_dir),
                        "--out", str(out), "--max-symbols", "4"])
    assert rc == 0
    for f in ("results.json", "trades.csv", "equity.csv", "summary.md"):
        assert (out / f).exists(), f
    res = json.loads((out / "results.json").read_text())
    assert set(res["modes"]) == {"proxy", "percentile"}
    assert res["coverage"]["requested"] == 4 and res["coverage"]["loaded"] == 4
    assert res["modes"]["proxy"]["metrics"]["full"]["start"] >= "2020-03-01"
    eq = pd.read_csv(out / "equity.csv")
    assert {"equity_proxy", "equity_percentile", "benchmark_close"} <= set(eq.columns)
    md = (out / "summary.md").read_text()
    for s in ("데이터 커버리지", "스캐너 계기판 수치와 비교", "| S&P500 | +1.1%p | +12.4%p | +42.8%p |",
              "확인되지 않은 값", "| 1 | 피벗 기간 |", "| 7 | 비용 |", "최근 1년", "생존편향"):
        assert s in md, s
    assert "로드 4/4" in capsys.readouterr().out


def _fake_yahoo(frames_by_ticker):
    """Mock for data._yf_download returning (Ticker, Price) columns like yfinance group_by='ticker'."""
    calls = []

    def fake(**kw):
        calls.append(kw)
        t = kw["tickers"]
        tickers = [t] if isinstance(t, str) else list(t)
        parts = {}
        for x in tickers:
            if x not in frames_by_ticker:
                continue
            df = frames_by_ticker[x]
            df = df[(df.index >= pd.Timestamp(kw["start"])) & (df.index < pd.Timestamp(kw["end"]))]
            parts[x] = pd.DataFrame({"Open": df["open"], "High": df["high"], "Low": df["low"],
                                     "Close": df["close"], "Adj Close": df["close"] * 0.5,
                                     "Volume": df["volume"]})
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, axis=1, names=["Ticker", "Price"])
    fake.calls = calls
    return fake


def test_analyze_cli_yahoo_mocked(monkeypatch, capsys):
    from swing_engine import data as D
    df = uptrend_with_breakout()
    b = rising_bench(df.index)
    b = b.assign(open=b["close"], high=b["close"], low=b["close"], volume=np.nan)
    fake = _fake_yahoo({"AAA": df, "^GSPC": b})
    monkeypatch.setattr(D, "_yf_download", fake)
    as_of = df.index[-1].strftime("%Y-%m-%d")
    assert analyze.main(["--preset", "SP500", "--symbol", "AAA", "--yahoo", "--as-of", as_of, "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["status"] == "신호 확정 → 다음 시가 진입" and rep["data_date"] == as_of
    assert fake.calls[0]["auto_adjust"] is False
    assert rep["closing"].startswith("※") and "50일선" in rep["exit_rules"]


def test_backtest_cli_online_mocked(tmp_path, monkeypatch):
    from swing_engine import data as D
    rng = np.random.default_rng(3)
    d = pd.bdate_range("2019-01-01", periods=700)
    frames = {}
    for t in ("AAA", "BBB", "CCC"):
        c = 20 * np.exp(np.cumsum(rng.normal(0.0012, 0.018, len(d))))
        frames[t] = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                                  "volume": rng.lognormal(13, 0.5, len(d))}, index=d)
    bc = 3000 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(d))))
    frames["^NDX"] = pd.DataFrame({"open": bc, "high": bc, "low": bc, "close": bc, "volume": np.nan}, index=d)
    monkeypatch.setattr(D, "_yf_download", _fake_yahoo(frames))
    monkeypatch.setattr(D, "fetch_ndx100", lambda: ["AAA", "BBB", "CCC", "GONE"])
    monkeypatch.setattr(D, "_sleep", lambda s: None)
    out = tmp_path / "o"
    backtest.main(["--market", "NDX100", "--start", "2019-01-01", "--end", d[-1].strftime("%Y-%m-%d"),
                   "--test-start", "2020-01-02", "--cache-dir", str(tmp_path / "c"), "--out", str(out)])
    res = json.loads((out / "results.json").read_text())
    cov = res["coverage"]
    assert (cov["requested"], cov["loaded"], cov["failed"]) == (4, 3, ["GONE"])
    assert list(res["modes"]) == ["percentile"] and res["config"]["params"]["stop_pct"] == 7.0
    assert "실패 종목: GONE" in (out / "summary.md").read_text()


def test_backtest_drops_forming_bar(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from swing_engine import data as D
    d = pd.bdate_range("2026-01-01", "2026-09-25")
    c = np.linspace(10, 20, len(d))
    fr = {t: pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=d) for t in ("AAA", "^GSPC")}
    monkeypatch.setattr(D, "_yf_download", _fake_yahoo(fr))
    args = backtest.build_parser().parse_args(["--market", "SP500", "--start", "2026-01-01", "--end", "2026-09-25",
                                               "--out", str(tmp_path), "--no-cache", "--universe-file",
                                               str(tmp_path / "u.txt")])
    (tmp_path / "u.txt").write_text("AAA\n")
    args.now = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)          # 13:00 ET, session open
    frames, bench, _ = backtest.load_inputs(args, "SP500", "^GSPC")
    assert frames["AAA"].index[-1] == pd.Timestamp("2026-09-24") and bench.index[-1] == pd.Timestamp("2026-09-24")
    args.now = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)          # 17:00 ET, closed
    frames, bench, _ = backtest.load_inputs(args, "SP500", "^GSPC")
    assert frames["AAA"].index[-1] == pd.Timestamp("2026-09-25")


# --- review regressions ----------------------------------------------------------------

def _dated(df, last="2026-09-25"):
    out = df.copy()
    out.index = pd.bdate_range(end=last, periods=len(df))
    return out


def test_analyze_as_of_today_still_drops_the_forming_bar(monkeypatch, capsys):
    from datetime import datetime, timezone
    from swing_engine import data as D
    df = _dated(uptrend_with_breakout())                      # breakout on 9/25 = today's forming bar
    b = rising_bench(df.index)
    b = b.assign(open=b["close"], high=b["close"], low=b["close"], volume=np.nan)
    monkeypatch.setattr(D, "_yf_download", _fake_yahoo({"AAA": df, "^GSPC": b}))
    base = ["--preset", "SP500", "--symbol", "AAA", "--yahoo", "--json"]

    def run(now, as_of):
        monkeypatch.setattr(D, "_now", lambda: now)
        assert analyze.main(base + ["--as-of", as_of]) == 0
        return json.loads(capsys.readouterr().out)
    session = datetime(2026, 9, 25, 19, 41, tzinfo=timezone.utc)          # 15:41 ET, market open
    rep = run(session, "2026-09-25")
    assert (rep["data_date"], rep["dropped_unconfirmed_bar"]) == ("2026-09-24", True)
    assert rep["status"] != "신호 확정 → 다음 시가 진입"
    rep = run(session, "2026-09-24")                                      # past as-of: nothing dropped
    assert (rep["data_date"], rep["dropped_unconfirmed_bar"]) == ("2026-09-24", False)
    rep = run(datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc), "2026-09-25")   # after the close
    assert (rep["data_date"], rep["dropped_unconfirmed_bar"]) == ("2026-09-25", False)
    assert rep["status"] == "신호 확정 → 다음 시가 진입"
    assert analyze.main(base + ["--as-of", "2026-09-25", "--keep-last-bar"]) == 0
    assert json.loads(capsys.readouterr().out)["data_date"] == "2026-09-25"


def test_exit_signal_event_label_follows_exit_ma_len():
    from swing_engine.params import resolve
    p = resolve("SP500", exit_ma_len=20)
    df = uptrend_with_breakout()
    c = float(df["close"].iloc[-1])
    df = _append(df, c * 1.01, c * 1.03, c * 1.0, c * 1.02)              # entry bar
    ema = analyze.build_report(df, rising_bench(df.index), "SP500", "T", params=p)["position"]["exit_ma"]
    df2 = _append(df, c, c, ema * 0.985, ema * 0.99)                      # close below the 20-day MA
    rep = analyze.build_report(df2, rising_bench(df2.index), "SP500", "T", params=p)
    assert rep["position"]["exit_pending"] and rep["recent_events"][-1]["type"] == "EXIT_SIGNAL"
    txt = analyze.render_text(rep)
    assert "20일선 이탈" in txt and "50일선 이탈" not in txt


def test_backtest_default_test_start_skips_warmup_and_prints_spec9(tmp_path, capsys):
    from swing_engine.notes import DISCLAIMER, UNCONFIRMED_LINE
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    d = _universe(data_dir)                                              # 900 bars from 2019-01-01
    out = tmp_path / "out"
    assert backtest.main(["--market", "SP500", "--start", "2019-01-01", "--end", d[-1].strftime("%Y-%m-%d"),
                          "--rs-mode", "proxy", "--offline-dir", str(data_dir), "--out", str(out)]) == 0
    res = json.loads((out / "results.json").read_text())
    wb = backtest.warmup_bars(res["config"]["params"])
    assert wb == 253                                                     # weighted_perf needs close[252]
    warm = d[wb - 1].strftime("%Y-%m-%d")
    assert res["config"]["test_start"] == warm and res["config"]["test_start_auto"]
    assert res["modes"]["proxy"]["metrics"]["full"]["start"] == warm
    assert res["unconfirmed"] == UNCONFIRMED_LINE and res["disclaimer"] == DISCLAIMER
    printed = capsys.readouterr().out
    assert UNCONFIRMED_LINE in printed and DISCLAIMER in printed


def test_default_test_start_is_the_last_ten_years_when_history_is_long():
    from swing_engine.params import resolve
    bench = pd.DataFrame({"close": 1.0}, index=pd.bdate_range("2012-01-02", "2026-09-25"))
    got = backtest.default_test_start(bench, resolve("SP500"), "2026-09-25")
    assert got == pd.Timestamp("2016-09-25")
    short = bench.loc["2019-01-01":]
    assert backtest.default_test_start(short, resolve("SP500"), "2026-09-25") == short.index[252]


def test_backtest_summary_shows_the_actual_last_bar(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    d = _universe(data_dir, n=700)
    out = tmp_path / "out"
    end = (d[-1] + pd.Timedelta(days=10)).strftime("%Y-%m-%d")            # later than the data
    backtest.main(["--market", "SP500", "--start", "2019-01-01", "--end", end, "--test-start", "2020-03-02",
                   "--rs-mode", "proxy", "--offline-dir", str(data_dir), "--out", str(out)])
    res = json.loads((out / "results.json").read_text())
    last = d[-1].strftime("%Y-%m-%d")
    assert res["data_last_date"] == last and res["test_first_date"] == "2020-03-02"
    md = (out / "summary.md").read_text()
    assert f"기준일(마지막 확정 봉) = {last}" in md and f"기준일 as_of = {end}" not in md
    assert f"요청한 끝 {end}보다 이전" in md and "테스트 구간: 2020-03-02 ~ " + last in md
