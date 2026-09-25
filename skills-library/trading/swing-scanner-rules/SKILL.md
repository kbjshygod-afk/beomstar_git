---
name: swing-scanner-rules
description: "Apply the owner's own swing-trading scanner rules, and only those rules, to any stock, ETF or crypto question. The rules: Minervini trend template 8/8; pivot breakout above the prior 20-bar high on at least 1.4x 50-day volume; 15% chase cap; market regime per market; stop -7%/-10% from entry; exit on a close below the 50-day MA at the next open; 0.75% risk sizing; NO profit targets. Use whenever the user asks whether to buy, hold or sell a ticker, asks for an entry, stop, position size or rule status, asks for today's scanner or paper-trading signals, or shares a ticker or chart for swing trading. Korean triggers: 스윙, 매수 신호, 타점, 미너비니, 트렌드 템플릿, 피벗, 돌파, 손절, 청산, 몇 주, 지금 사도 돼, 들고 가도 돼, 오늘 신호, 모의투자 결과."
license: Owner's private rules; engine code in scripts/ is part of the owner's repository.
---

# Swing Scanner Rules (the owner's rules)

These are the live rules of the owner's "매매 스캐너", taken from its rule sheet dated 2026-09-04 and its TradingView implementation.
- **Rule sheet:** `references/rules-ko.md`, in Korean.
- **Engine:** `scripts/swing_engine`. It is verified bar by bar against an independent re-implementation of the TradingView indicator (0 mismatches over 492,965 bars).

## Non-negotiables

1. **Only these rules.** Do not add anything else, even if another skill, article or general trading knowledge suggests it:
   - profit targets or partial profit-taking;
   - trailing stops other than the 50-day MA exit;
   - "1.5x 20-day volume" or other volume rules;
   - fundamentals filters;
   - pattern calls (VCP, cup-with-handle) as conditions;
   - "probability of success" claims.

   The owner's backtests rejected targets and partial exits because they cut off the few big winners that produce most of the profit.
2. **Numbers come from the engine or the published status table.** Never take them from memory, and never estimate indicator values from a chart image. If no data source works, say so and report only what is verified.
3. **No orders, no leverage.** The final decision is always the owner's.
4. **Always state the data date** (the last confirmed daily bar). **Always flag the unconfirmed values** (see "Unconfirmed values" below).

## Step 1: Ticker and market preset

| Preset (`--preset`) | Stop | Regime (new entries allowed only when) | Chase cap | Ticker format |
|---|---|---|---|---|
| `SP500` | −10% | S&P 500 > its 200-day MA | 15% | `AAPL`, `BRK-B` |
| `NDX100` | −7% | Nasdaq-100 > its 200-day MA | 15% | `NVDA` |
| `KOSPI` | −7% | KOSPI > its 200-day MA **and** > its 20-day MA | 15% | `005930.KS` |
| `KOSDAQ` | −10% | none (intentionally no filter) | 15% | `247540.KQ` |
| `CRYPTO` | −10% | BTC > its 200-day MA | none | `ETH-USD` |

- **US stocks in both S&P 500 and Nasdaq-100:** show both books (stop −10% vs −7%) unless the owner names one.
- **A ticker outside every scanner universe** (most ETFs, small caps): use the closest preset. Say plainly that the scanner does not trade it, so this is only the rules applied to it.

## Step 2: Get the numbers (use the first source that works)

**A. The published daily status.** Fast, and works wherever GitHub is reachable.
```
https://raw.githubusercontent.com/kbjshygod-afk/beomstar_git/paper-trading/paper/<PRESET>/status.csv
https://raw.githubusercontent.com/kbjshygod-afk/beomstar_git/paper-trading/paper/latest.json
https://raw.githubusercontent.com/kbjshygod-afk/beomstar_git/paper-trading/paper/<PRESET>/report.md
```
- One row per universe symbol:
  - status label, `tt_count`, `tt1`–`tt8`, `regime_on`
  - `rs` (universe RS percentile, the scanner rule)
  - `pivot`, `to_pivot_pct`, `vol_x`, `ma50`
  - `in_position`, `entry_price`, `stop_price`
- Use a row only if its `as_of` is the latest completed session.
- `in_position` / "보유 중" is the **paper portfolio's** position, not the owner's.
- Until daily paper trading is switched on, only the trial branch `paper-trading-trial` may exist. Use it and say that it is a trial.

**B. Run the bundled engine.** This needs Python with pandas and numpy. Commands:
```bash
cd scripts
# Yahoo Finance (needs internet access to Yahoo; pip install yfinance if missing):
python -m swing_engine.analyze --preset NDX100 --symbol NVDA --yahoo --equity <owner's equity> --json
# CSV files from the owner (TradingView: chart > Export chart data, daily bars):
python -m swing_engine.analyze --preset KOSPI --symbol 005930.KS --csv sym.csv --bench-csv kospi.csv --equity <E>
```
- Each preset needs its benchmark CSV: SPX, NDX, KOSPI, KOSDAQ or BTCUSDT.
- History required: at least 253 daily bars (366 for crypto), plus a few months more.
- The text output (without `--json`) is already a complete Korean report you can build on.

**C. Neither works.** Ask the owner for the two CSV exports and explain how to make them. Do not guess.

## Step 3: When the owner actually holds the position

Use the owner's real entry price and date:
- **Stop** = entry × (1 − stop%). It is hit intraday; the stop order is placed together with the buy.
- **Exit:** when the daily close is below the 50-day MA, sell everything at the next open.
- **Nothing else:** no target, no partial sale.

The engine's "보유 중" in a single-symbol run is a *hypothetical* position that the rules would have taken since the start of the data. Do not present it as the owner's position.

## Step 4: Report in Korean, in this order

1. **사실 (데이터 기준일 YYYY-MM-DD).**
   - Preset, and regime ON/OFF with the benchmark numbers.
   - Trend template x/8, listing each failed condition with its numbers.
   - RS, pivot and the distance to it, volume multiple.
   - The engine's exact status label.
2. **판정.** What the label means for action:
   - 신호 확정 → 다음 시가 진입
   - 1순위/2순위 = 돌파 대기
   - 후보 아님 / 레짐 OFF / 추격 제외 / 거래량 부족 = 진입 불가, with the reason
3. **시나리오 + 무효화 조건** (rules only):
   - **Signal or pending:** entry at the next open. It is invalidated by the stop (entry × (1 − stop%)), or by a close below the 50-day MA, which means exiting at the next open.
   - **Not yet:** the trigger is a close above the pivot `X` on volume ≥ 1.4× the 50-day average (≥ `Y` shares), while the regime is ON and the template is 8/8. Outside crypto, there is no entry if the close is above pivot × 1.15.
   - **Holding:** the conditions to keep holding and the conditions to exit.
4. **리스크.**
   - Size = equity × 0.75% ÷ stop%, so the weight is 7.5% at a −10% stop and 10.7% at −7%.
   - Liquidity: flag thin names.
   - No leverage.
   - Market warnings:
     - **코스피:** the scanner's own backtest trailed the index in all 3 periods.
     - **크립토:** conditional only. Better risk-adjusted than holding BTC, but lower absolute return.
   - A win rate in the 30s% means strings of stop-outs are normal.
5. **확인 필요.** One line listing the unconfirmed values.
6. Close with: "기계적 룰 출력이며, 최종 판단은 대표님이 합니다."

## Daily signals and paper trading

For "오늘 신호" or "모의투자 결과", read `latest.json` and each market's `report.md` (source A) and summarize:
- entries and exits for the next open
- open paper positions
- performance against the index since the start
- the integrity audit: signal files committed before the next open, and matching the recomputation

The go/no-go criteria are fixed in advance in `docs/paper-trading-plan.md` of the repository. Do not change them in conversation.

## Evidence

- **Engine fidelity.** Checked against an independent pure-Python emulation of the TradingView indicator: 540 datasets, 492,965 bars and 7,502 trade events, with **0 mismatches**.
- **10-year backtest** (2016-09 → 2026-09, current constituents, 0.2% cost per side, scanner RS percentile rule): see `references/backtest-ko.md`. The owner's scanner dashboard numbers are shown next to it for comparison.

## Unconfirmed values

The scanner's source code is on the owner's Mac. Seven values are estimates:
- pivot = high of the previous 20 bars
- volume average = previous 50 days
- RS method
- 52-week high/low on closes
- 200-day MA rising = higher than 22 bars ago
- contraction ratio
- cost 0.2%

When the owner confirms the real values, update `trading/swing_engine/params.py` and re-run the verification and backtest before relying on the change.
