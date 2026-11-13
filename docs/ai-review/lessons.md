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

## Monitoring jobs (accepted from the review of the 2.6 KIS alerts, 2026-11-12)
- **An early "connected" line is not a completed run.** Forgive only an explicit "window completed,
  no data" result (its own exit status), never any failure that happens after a successful
  connection. (Both reviewers found this.)
- **Persist delivery, not detection.** Saving an alert as "sent" before it was actually posted
  silences it for the rest of the day when posting fails. (Both reviewers found this.)
- **A read failure is not an empty result.** "Could not read the ledger" must not look like
  "nothing held".
- **Validate persisted state.** Valid JSON with the wrong shape must fall back safely.

## Research (2026-11-13)
- **Check what already exists before proposing new work.** On 11-06 Claude proposed "rebuilding the
  backtest without survivorship bias" as new work. A point-in-time backtest had existed since
  2026-09-26 (`tools/robustness.py` part `pit`, `tools/krx_membership.py`); only the delisted
  members' prices were missing. Search the tools and docs (`grep -rn pit trading/tools docs`)
  before scoping a study.
- **Reproduce the published number first.** Before changing data, re-run the old study and match
  its figures (KOSDAQ pit CAGR 12.03%, warning lines to the decimal); only then is a difference
  attributable to the change.
- **Clip added data to the study window.** Built bars that ran past the snapshot's last day
  changed the test window and the benchmark figure; compare like for like.
- **A price made up for valuation must not become tradable.** Filling halted days with flat bars
  let the simulator fill exits during a suspension. Check how the consumer (here
  `portfolio.simulate`, `HAS`) reads the data before shaping it. (Codex and Gemini agreed;
  confirmed in the simulator code; results re-run.)
- **Reference-price adjustment needs complete consecutive history.** A missing source file must
  be an error, not a silent gap that looks like a corporate action.
- **GitHub's `schedule` is not a clock.** The first scheduled kis-ws run was 30+ minutes late
  (this repository already runs its 2-hourly ledger through a keeper chain for the same reason).
  Time-critical runs are started by a dispatcher; the schedule is only a backup.
- **A dedup marker must mean "done", not "started".** Saving the slot marker before listening
  would have locked the backup run out after an early failure. Write it only after success; let
  the concurrency group prevent overlap. (Both reviewers; round 2 of the 11-13 review.)
- **Measure a deadline-based duration when the timed step begins**, after setup, and with seconds.
- **KIS allows one WebSocket session per app key.** A second listener gets "ALREADY IN USE appkey"
  (2026-11-13, a push smoke run met the live listener). Never test against a key a live job is
  using; a refused listener stops at once (exit 4) instead of reconnecting.
- **A conclusion inherits the flaws of the baseline it was measured against.** When the delisted
  members were added, the baseline changed (KOSDAQ CAGR 12.0% -> 10.0%), and so did the study built
  on it: the breadth-50 filter no longer passes its pre-registered criteria (first-half excess
  +16.2pp -> +7.0pp). After correcting a dataset, re-run every study that used it, with the same
  tool, before the next decision that cites it. Thresholds re-derived after seeing the new results
  are reference only, never a verdict. (2026-11-13)
- **Measure the noise before quoting it.** "Path noise is 1-2pp of CAGR" was said for weeks from
  two anecdotes. Measured (tools/path_noise.py, 2 x 40 paired paths): the same rules give a 10-year
  CAGR between about 7% and 14% (sd about 1.9pp). Differences under about 3pp between two backtests
  were being read as findings. Any comparison of two backtests needs a paired noise run, and the
  reading rule is committed before the run. (2026-11-13)
- **Say what a filter robustly improves.** The breadth filter's CAGR edge is inside the noise, but
  its profit factor and drawdown were better in 80 of 80 paired paths. Report each metric's
  robustness separately instead of one headline number.
- **A self-restarting chain needs a brake.** A keeper whose loop fails at once would dispatch the
  next keeper immediately, forever. The hand-over waits 20 minutes when the loop did not end
  normally. (2026-11-13, added with the kis-ws slot dispatch.)
- **Test the workflow's shell as written.** The keeper loop is extracted from the YAML and run
  under `bash -e -o pipefail` with stub `date`/`sleep`/`gh` and a virtual clock
  (tests/test_keeper_workflow.py), so a 5 h 45 min run is checked in seconds.

