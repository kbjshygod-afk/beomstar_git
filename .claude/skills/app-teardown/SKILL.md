---
name: app-teardown
description: Analyze why a successful app works — its real mechanisms, not its surface — and turn that into a port plan for our app. Use when asked to copy, benchmark, reverse-engineer or "analyze" another product (Duolingo, Anki, Speak, etc.), or to explain why it succeeded, before building anything inspired by it.
---

# App teardown — copy the engine, not the paint

A teardown answers three questions with evidence: **what does the product really do, why does it
work, and what exactly should we build**. Copying visible features (streak flame, XP bar, league
table) without the machinery behind them gives the look without the result.

## Rules
1. **Primary sources first.** Research papers, the company's engineering/research blog, patents,
   talks, official statements, and observed product behaviour. Third-party summaries only to find
   primary sources. Every factual claim gets a link. Say "not public" instead of guessing numbers.
2. **Separate the layers.** For every feature, write down which layer it belongs to:
   - *Learning engine* — what gets taught when (scheduling, difficulty, item selection, feedback).
   - *Habit loop* — what brings the user back (streaks, goals, reminders, social).
   - *Business/growth* — metrics and experiments the company optimizes (retention, DAU model).
   - *Surface* — visuals and copy.
   Surface is the cheapest to copy and the least valuable. Start from the engine.
3. **Causal, not descriptive.** "Why it works" must name the mechanism and its evidence:
   *mechanism → behaviour it changes → measured effect → source*. If no effect was measured, say so.
4. **Diagnose our app against it** by reading the code, not the UI: find the functions that do
   scheduling, selection, grading, sessions; note what data is logged per item. List gaps as
   "they do X, we do Y, consequence Z".
5. **Port plan, smallest faithful version.** For each mechanism: the minimum data we must log,
   the formula or rule, default parameters (with the source or "our choice, because …"), what
   cannot be copied without a server/large data, and how we will test it. Rank by
   *learning impact ÷ effort*, and prefer changes that improve results for the learner over
   changes that only raise engagement numbers.
6. **Protect the learner.** Do not port dark patterns (guilt notifications, loss-aversion traps,
   paywalled hearts that block learning). Note them in the teardown and say why they are left out.
7. **Verify before claiming.** A ported mechanism is "done" only with a test that fails when the
   mechanism is removed (mutation check), and the usual cross-review before merge.

## Output: `docs/analysis/<product>-teardown.md`
1. One-paragraph summary: what makes it work, in plain Korean for the owner.
2. Mechanism table — layer · what they do · evidence (link) · effect.
3. Why it works — 5–10 causal mechanisms.
4. Our app today — engine diagnosis with file/function references.
5. Gaps — they / we / consequence.
6. Port plan — ranked; for each: data, rule, parameters, test, effort.
7. Left out on purpose — and why.
8. Unconfirmed claims.

Write the owner-facing parts in Korean; code identifiers and source titles stay as they are.
