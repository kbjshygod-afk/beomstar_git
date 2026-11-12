# Shared lessons (every reviewer reads this first)

Findings that were verified and accepted, and mistakes made in this repository, kept so the next
review starts from them. Claude appends an entry when a review finding is accepted or a mistake
is found. Each entry gives the date, the lesson, and where it came from. The newest entries go
last.

## Data and time
- **2026-10-31 / 11-06 / 11-09: KIS daily bars are not final on the trading day.** The KRX (J)
  bar carries the KRX+NXT combined close until KIS updates it during the next trading day. It is
  treated as final only after the next trading day's 20:00 KST (`kis.settles_at`). The lesson
  was learned twice: "wrong paper-server bars" and then "settled the next calendar day" were both
  wrong readings. Check timing hypotheses across a weekend before believing them. (#67, #68)
- **2026-11-04: a cache can freeze an incomplete download.** The partial ^KQ11 download was
  cached for 12 hours. A cache must check that its data is complete (the last bar is the expected
  date) before it is trusted. (#60)
- **2026-11-09: "past calendar day" is not "settled".** Fridays settle on Monday, and holidays
  shift this too. Use the benchmark's trading days, not the calendar.
- Yahoo's same-day Korean bar can be provisional for hours after the close, and on some
  evenings Yahoo drops the day entirely. Korean signals must be committed between 08:00 and
  15:00 UTC.

## Operations
- **2026-11-05: a check that says "no problem" while a flag is set is worse than no check.**
  `daily_check.py` now turns new judgment-criteria failures into PROBLEM (exit 1).
- **2026-11-03 / 11-08 / 11-10: scheduled cloud sessions can fail silently.** The dashboard
  refresh reported success while writing nothing, because the fresh session lacked the tool it
  needed. Every automated job needs a freshness check that an independent job reads.
- **Exit codes of smoke runs.** A probe outside market hours sees no ticks. Decide up front what
  "pass" means for an off-hours run (#66).

## Analysis
- **2026-11-06: one bad trade is not a rule.** The 041830 stop after a -17% gap-down open was
  checked against 1,796 backtest trades: gap-downs of more than 5% are only 1.1% of entries, too
  few to justify a new filter. Rule ideas from single cases go to the post-period review, never
  into code during the paper period.
- The backtest universe uses the current constituents, so it has survivorship bias (SPEC 8.1).
  Treat backtest win rates as optimistic.

## Review tooling (accepted from the first cross-review, PR #69, 2026-11-12)
- **Each CLI call is a fresh process.** A later round only knows what its prompt contains. Every
  round must carry the full context (brief, lessons, diff), not just the previous round's output.
  (Codex and Gemini agreed; reproduced.)
- **Apply trust checks on every trigger path.** `workflow_dispatch` skipped the same-repository
  check that `pull_request` had. Check the resolved PR's head repository before any secret is
  exposed. (Both reviewers found this.)
- **Treat model output as untrusted input.** `{"claim": null}` crashed the report. Normalise the
  types of every field before using it, and surface failures and non-JSON answers in the report
  instead of dropping them.
- **Time budgets must add up.** Four 15-minute calls in series did not fit a 45-minute job.
