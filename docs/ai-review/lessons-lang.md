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
