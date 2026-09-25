# Swing Scanner Rules — Engine Specification

This is the single source of truth for the Python engine (`trading/swing_engine`) and the skill built on it.

It is derived from the owner's TradingView implementation of the scanner's live rules:
- branch `claude/minervini-swing-indicator-mdx0sy`, commit `94f779c`
- `minervini-swing-indicator/minervini_swing_watch.pine` (indicator, **the reference for signals and position state**)
- `minervini-swing-indicator/minervini_swing_watch_strategy.pine` (backtest)
- `minervini-swing-indicator/README.md` (rule sheet dated 2026-09-04)

When this spec and the Pine indicator disagree, the Pine indicator wins, and this spec must be fixed.

Everything here is a mechanical rule output, not investment advice. The engine never places orders.

---

## 1. Inputs

**Symbol bars.** Daily bars with `date, open, high, low, close, volume`, ascending by date with no duplicates.
- Stocks: prices split-adjusted but **not** dividend-adjusted, which is TradingView's default. With yfinance this means `auto_adjust=False` and the `Open/High/Low/Close` columns, not `Adj Close`.
- Volume can be missing (NaN). Missing volume means no volume confirmation.

**Benchmark bars.** Daily `date, close` for the market's benchmark.

**Market preset.** One of `SP500`, `NDX100`, `KOSPI`, `KOSDAQ`, `CRYPTO`, `CUSTOM`.

## 2. Parameters

| Name | Default | Notes |
|---|---|---|
| `pivot_len` | 20 | Trigger = highest high of the previous N bars. **Estimated** |
| `vol_len` | 50 | Volume average over the previous N bars, today excluded. **Estimated** |
| `vol_mult` | 1.4 | Today's volume must be at least this × average |
| `max_breakout_pct` | 15.0 | Chase cap in %; applied only when `cap_on` |
| `use_tt` | true | Trend template 8/8 required |
| `ma200_rise_bars` | 22 | 200-day MA must be higher than 22 bars ago. **Estimated** |
| `rs_min_diff` | 0.0 | RS proxy threshold in percentage points. **Estimated**: the scanner uses a universe percentile of 70 or more |
| `exit_ma_len` | 50 | Exit when the close is below this SMA |
| `risk_pct` | 0.75 | Percent of equity risked per trade |
| `use_value_filter` | false | Not a scanner rule; off by default |
| `min_trading_value` | 3e9 | Minimum close × volume when the value filter is on |

### Market presets

| Preset | Benchmark (TradingView → Yahoo) | Regime | `stop_pct` | `cap_on` | `year_bars` |
|---|---|---|---|---|---|
| `SP500` | `SP:SPX` → `^GSPC` | `MA200` | 10.0 | true | 252 |
| `NDX100` | `NASDAQ:NDX` → `^NDX` | `MA200` | 7.0 | true | 252 |
| `KOSPI` | `KRX:KOSPI` → `^KS11` | `MA200_AND_MA20` | 7.0 | true | 252 |
| `KOSDAQ` | `KRX:KOSDAQ` → `^KQ11` | `NONE` | 10.0 | true | 252 |
| `CRYPTO` | `BINANCE:BTCUSDT` → `BTC-USD` | `MA200` | 10.0 | **false** | 365 |
| `CUSTOM` | given | given | given | given | given |

## 3. Primitive semantics (match Pine exactly)

- `sma(x, n)[t]` is the mean of `x[t-n+1..t]`. It is NaN if any of those n values is missing or fewer than n bars exist.
- `x[k]` at bar t means the value at bar `t-k`, and NaN when `t-k < 0`.
- `highest(x, n)[t]` / `lowest(x, n)[t]` is the max/min of `x[t-n+1..t]`, and NaN when fewer than n bars exist.
- `pine_round(v) = floor(v + 0.5)`: ties round up. **Do not use Python's `round()`**, which rounds half to even.
- Any comparison involving NaN is **false**. Arithmetic with NaN gives NaN.
- Booleans are counted as 1 when true and 0 when false or NaN.

## 4. Per-bar indicators (bar t; all use data up to and including t unless noted)

### 4.1 Benchmark (computed on the benchmark's own bar series, then aligned)
```
b_ma200 = sma(b_close, 200)
b_ma20  = sma(b_close, 20)
b_perf  = weighted_perf(b_close, year_bars)          # section 4.4
```
Align to the symbol's dates by taking, for each symbol date d, the last benchmark bar with date ≤ d (forward fill; no lookahead). If there is none, the value is NaN.

### 4.2 Regime
```
MA200          : regime_on = b_close > b_ma200
MA200_AND_MA20 : regime_on = b_close > b_ma200 and b_close > b_ma20
NONE           : regime_on = true
```

### 4.3 Trend template
```
ma50   = sma(close, 50)
ma150  = sma(close, 150)
ma200  = sma(close, 200)
exit_ma = sma(close, exit_ma_len)
hi52   = highest(close, year_bars)          # close-based, includes bar t
lo52   = lowest(close, year_bars)
rs_diff = (weighted_perf(close, year_bars) - b_perf_aligned) * 100

tt1 = close > ma150 and close > ma200
tt2 = ma150 > ma200
tt3 = ma200 > ma200[ma200_rise_bars]
tt4 = ma50 > ma150 and ma50 > ma200
tt5 = close > ma50
tt6 = close >= lo52 * 1.30
tt7 = close >= hi52 * 0.75
tt8 = rs_diff >= rs_min_diff
tt_count = number of true among tt1..tt8
tt_pass  = (not use_tt) or tt_count == 8
```

### 4.4 Weighted performance (IBD-style RS proxy)
```
weighted_perf(c, n):
  q = pine_round(n / 4); h = pine_round(n / 2); t3 = pine_round(n * 3 / 4)
  return 0.4*(c/c[q] - 1) + 0.2*(c/c[h] - 1) + 0.2*(c/c[t3] - 1) + 0.2*(c/c[n] - 1)
```
For n = 252 the lags are 63, 126, 189 and 252. For n = 365 they are 91, **183**, 274 and 365, because 182.5 rounds up.

### 4.5 Trigger, volume, chase cap
```
pivot        = highest(high[1], pivot_len)      # previous pivot_len bars' highs, bar t excluded
vol_avg      = sma(volume, vol_len)[1]          # previous vol_len bars, bar t excluded
vol_x        = volume / vol_avg if vol_avg > 0 else NaN
breakout_pct = (close / pivot - 1) * 100
to_pivot_pct = (pivot / close - 1) * 100

breakout = close > pivot
vol_ok   = vol_x >= vol_mult
cap_ok   = (not cap_on) or breakout_pct <= max_breakout_pct
liquidity_ok = (not use_value_filter) or close * volume >= min_trading_value
candidate    = tt_pass and liquidity_ok
full_signal  = breakout and vol_ok and cap_ok and candidate and regime_on
```

### 4.6 Display-only
```
contraction  = sma(tr, 10) / sma(tr, 40)   # tr = max(high-low, |high-close[1]|, |low-close[1]|); tr = high-low on the first bar
dry_up       = sma(volume, 10) / sma(volume, 50)
from_high52  = (close / hi52 - 1) * 100
```

## 5. Position state machine (indicator semantics; one symbol)

State: `entry_pending`, `exit_pending`, `entry_price` (NaN when flat), `stop_price`.
Every bar is a confirmed daily bar. Process bars in order; within bar t, in this exact order:

```
events = []
1. if exit_pending:
       exit_pending = false
       exit fill at open[t]  → pnl% = (open/entry_price - 1)*100; record EXIT_MA
       entry_price = stop_price = NaN
2. if entry_pending:
       entry_pending = false
       entry_price = open[t]; stop_price = open[t] * (1 - stop_pct/100); record ENTRY
3. if entry_price is not NaN:                      # includes the entry bar itself
       if low[t] <= stop_price:
           fill = min(open[t], stop_price)           # gap below the stop fills at the open
           record STOP with pnl% = (fill/entry_price - 1)*100
           entry_price = stop_price = NaN
       elif close[t] < exit_ma[t]:
           exit_pending = true; record EXIT_SIGNAL
4. if entry_price is NaN:                          # flat after steps 1–3 (a stop can re-arm the same bar)
       signal = full_signal[t]
       entry_pending = signal; if signal: record SIGNAL
```

A signal on the last available bar leaves `entry_pending = true`: the entry happens at the next session's open.

## 6. Status label (Korean, same order as the Pine `statusTxt`)

Evaluate after step 4 of the last bar:
```
in_pos                         → "보유 중 — {exit_ma_len}일선 종가 이탈 시 청산"
entry_pending                  → "신호 확정 → 다음 시가 진입"
not tt_pass                    → "후보 아님 (트렌드 템플릿 {tt_count}/8)"
not liquidity_ok               → "후보 아님 (거래대금 부족)"
not regime_on                  → "레짐 OFF — 신규 진입 금지"
breakout and not cap_ok        → "추격 제외 (돌파폭 +x.x%)"
breakout and not vol_ok        → "돌파 · 거래량 부족"
to_pivot_pct <= 1              → "1순위 · 임박 (피벗 1% 이내)"
to_pivot_pct <= 3              → "2순위 · 근접 (피벗 3% 이내)"
otherwise                      → "3순위 · 관찰"
```
If `in_pos` is true and `exit_pending` is also true, the label is still "보유 중 …". The report must also say that an exit at the next open is pending.

Percent format in labels, `fmt_pct(x)`, follows Pine's `"+#.#;-#.#"` pattern:
1. Round `abs(x)` to one decimal with `pine_round(abs(x) * 10) / 10`.
2. Drop a trailing `.0`.
3. Prefix `+` for x ≥ 0 and `-` otherwise, then append `%`.

Examples: 16.04 → `+16%`, 16.25 → `+16.3%`.

## 7. Position sizing

```
qty = equity * risk_pct/100 / (ref_price * stop_pct/100)
```
Here `ref_price` is the entry price when in a position, otherwise the signal bar's close.
- Weight = `risk_pct / stop_pct`: 10.7% at a 7% stop, 7.5% at a 10% stop.
- Whole shares for Korean stocks.
- Fractional quantities are allowed for US stocks and crypto, where the preset or the user allows them.

## 8. Portfolio simulation (approximates the scanner; assumptions flagged)

The scanner holds many positions and allocates cash in RS order. Its code is on the owner's Mac, so these are **assumptions**:

1. **Universe:** current index constituents, the same survivorship bias as the scanner.
   - SP500: S&P 500
   - NDX100: Nasdaq-100
   - KOSPI: top 200 KOSPI stocks by market cap, approximating KOSPI 200
   - KOSDAQ: top 150 KOSDAQ by market cap, approximating KOSDAQ 150
   - CRYPTO: top 30 coins by market cap, stablecoins excluded
2. **RS:**
   - `rs_mode = "proxy"` uses tt8 from section 4.3.
   - `rs_mode = "percentile"`: tt8 is true when the symbol's `weighted_perf` percentile rank in the universe that day is **≥ 70**, the scanner's rule. The percentile is computed across universe symbols with valid values that day, using `rank(pct=True)*100`.
   - The portfolio default is `percentile`; both modes are reported.
3. **Equity and sizing:** equity is marked to market at each close. For a signal on day t:
   - qty = equity_t × 0.75% / (close_t × stop%)
   - The fill comes at open_{t+1} and is limited by available cash, so there is no leverage.
   - When cash is short, signals are filled in descending RS order, the last one partially. Partial fills below 1 whole share (integer markets) are skipped.
4. **Costs:** 0.2% of traded value per side, the same as the Pine strategy's default commission.
5. **Exits** follow section 5 per position. A symbol cannot be re-entered while a position is open.
6. **Benchmark comparison** uses the benchmark's price-index CAGR over the same window.
7. **Reported metrics:**
   - CAGR and CAGR minus index CAGR
   - max drawdown
   - number of trades, win rate, average win and average loss
   - profit factor
   - share of gross profit coming from trades above +20%, and the share of trades above +20%
   - exposure (average invested %)
   - Periods: full 10 years, the last 1 year, and each calendar year

**Scanner dashboard numbers to compare against** (2026-09-04, CAGR minus index CAGR):

| Market | 10y | OOS | Last 1y |
|---|---|---|---|
| S&P500 | +1.1%p | +12.4%p | +42.8%p |
| NDX100 | +2.0%p | +23.5%p | +67.5%p |
| KOSPI | −2.1%p | −6.9%p | −74.1%p |
| KOSDAQ | +21.1%p (MDD −53.7%) | +49.6%p | +95.9%p |
| Crypto | −23.8%p | −42.0%p | +30.2%p |

Also from the rule sheet: win rate in the 30s %, and 77–84% of profit comes from trades above +20%, which are 8–9% of trades.

## 9. Unconfirmed values (must be shown wherever results are shown)

The scanner's source code is only on the owner's Mac. These values were estimated for the TradingView version:

| # | Item | Default here | Basis |
|---|---|---|---|
| 1 | Pivot period | previous 20 bars' high, today excluded | trigger often differs from the 52-week high |
| 2 | Volume average | previous 50 days, today excluded | Minervini's "+40% vs 50-day average" |
| 3 | RS | single chart: weighted 1y return vs index ≥ 0%p; portfolio: percentile ≥ 70 | scanner uses universe percentile ≥ 70 |
| 4 | 52-week high/low | close-based | matches the sheet's "vs 52-week high" values |
| 5 | 200-day MA rising | higher than 22 bars ago | template's "at least 1 month up" |
| 6 | Contraction ratio | 10-day avg TR / 40-day avg TR | display only |
| 7 | Cost | 0.2% per side | close to the scanner's 20bp slippage assumption |
