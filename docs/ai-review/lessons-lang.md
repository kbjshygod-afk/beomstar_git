# Shared lessons — language-learning app (every reviewer reads this first)

Findings that were verified and accepted, and mistakes made in the app, kept so the next review
starts from them. Claude appends an entry when a review finding is accepted or a mistake is found.
Each entry gives the date, the lesson, and where it came from. The newest entries go last.

## Process
- **2026-11-12: tests that live outside the repository get lost.** The earlier regression suite
  (29 scripts) was kept in a temporary folder and disappeared with the container. Every test goes
  in `tools/tests/` in the same PR as the code it checks. (#72)
- **2026-11-12: ask what a request means before building.** "Connect ChatGPT and Antigravity by
  CLI" meant cross-review during development, not an AI feature in the app. Three PRs were built
  on the wrong reading. When a request can be read two ways, ask first.
- **2026-11-12: say what was not run.** A fake AI response proves the app's handling, not that
  the real service answers. Reports list separately what ran against the real service.

## Code
- **2026-11-12: an emulator can hide a broken import.** `admin.firestore.FieldValue` is
  undefined in firebase-admin 13 (use `firebase-admin/firestore`); unit tests with a fake passed
  and only the emulator run showed that every call would fail. Run the real module once. (#72)
- **2026-11-12: the Firebase emulator allows every origin.** A CORS rule can only be checked in
  a unit test of the header function, not through the emulator. (#72)
- **2026-11-13: a setting kept outside the saved record must be added to "erase this device".**
  The tutor key is in its own `localStorage` entry so it is not synced; the sign-out wipe list has
  to name it explicitly. (#73)
- **2026-11-13: every network call needs a time limit.** A `fetch` that never answers left the
  tutor key check stuck on "확인 중" for the rest of the visit, and in the relay a stalled AI call
  could run past the function's 60-second limit before the fallback or the quota refund ran. Give
  each call its own limit, short enough that all retries and cleanup fit in the outer limit.
  (ChatGPT cross-review of #72/#73)
- **2026-11-13: a "busy" guard must not eat the input.** Pressing Enter while an answer was
  pending cleared the saved draft and then the send was refused, so the next render wiped what
  the learner had typed. Check "busy" before touching the draft. (ChatGPT cross-review of #73)
- **2026-11-13: the privacy notice must cover fallbacks.** The relay row said text goes only to
  the chosen AI, but the relay falls back to the other one. (ChatGPT cross-review of #72)
- **2026-11-13: a time limit must cover reading the body too.** The key check cleared its timer
  as soon as the headers arrived, so a stalled error body could still hang it. Keep the limit
  until the body is read. (ChatGPT, agreed by Gemini, second review of #72/#73)
- **2026-11-13: a draft restored after a failure must not overwrite newer text.** The learner can
  keep typing while waiting; on failure put the failed text back in front of the new text.
  (ChatGPT, agreed by Gemini)
- **2026-11-13: switching language must cancel the request in flight.** A global "busy" flag left
  the new language's tutor locked until the old request ended. Abort it and redraw. (Gemini,
  agreed by ChatGPT)
- **2026-11-13: the phone's back button must match the on-screen ←.** On a sub-screen (the key
  screen) both go back one step, not out of the feature. (Gemini, agreed by ChatGPT)
- **2026-11-13: `obj[userValue]` is not a membership test.** `LANGS['constructor']` is truthy;
  use `hasOwnProperty`. (ChatGPT, agreed by Gemini)
- **2026-11-13: give reviewers the tests with the code.** The review was limited with `--paths`
  and left out `tools/tests/`, so both reviewers reported "no tests" for flows that were tested.
  Always include the test files of the area under review.
- **2026-11-13: do not hard-code a provider's model names or assume one quota.** The tutor gave
  up when its first model returned 429, although the free quota is per model, and the names were
  fixed in the code. Ask the provider which models the key can use, fall through on 429/403/404/5xx,
  and rest a failing model for a while so the next message does not repeat the failure. (#79)
- **2026-11-13: a helper request must not spend the caller's whole time limit.** The model-list
  call shared the 35-second send limit; when it stalled, no answer was attempted. Give the helper
  its own short limit and a fallback. (ChatGPT, agreed by Gemini)
- **2026-11-13: decide "bad key" from all attempts, not the last one.** One model returning 403
  after others returned 404 sent a learner with a valid key to the key screen. (both reviewers)
- **2026-11-13: remember a setting only when it was chosen for the right reason.** A retry after
  a truncated answer pinned the slow no-thinking-control setting for the rest of the visit.
  (both reviewers)
- **2026-11-13: "send on release" must hold in every exit path.** The push-to-talk code sent the
  collected text when a restarted recognition ended quickly, although the button was still held.
  Each path that ends listening has to ask "is it still held?" first. (ChatGPT, agreed by Gemini, #81)
- **2026-11-13: a workaround for one browser must not change what others say.** The fix for
  Android's cumulative results dropped a word said twice ("no no"). Treat a result as cumulative
  only when it is longer than the previous one. (ChatGPT)
- **2026-11-13: write non-ASCII ranges in regular expressions as `\u` escapes.** A literal
  U+3040 is invisible, and a reviewer read the class as a different range. (Gemini's finding was
  wrong about behaviour but right that it could not be read.)
