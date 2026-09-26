---
name: google-apps-script
description: "Build Google Apps Script automation for Sheets and Workspace. Custom menus, triggers (onEdit / time-driven / form submit), dialogs, sidebars, email batches, PDF export, Slack/Chat notifications, external API, and changes to existing team web apps (doGet / google.script.run). Use whenever the user wants to automate a Google Sheet, build a Sheets menu / sidebar / dialog, hit a Sheets row from email or a webhook, schedule a Sheets workflow, or asks 'how do I script this in Sheets'. Also use for install, setup, or trigger instructions on an existing sheet, even when no code is requested. Korean triggers: 구글 시트 자동화, 앱스 스크립트, Apps Script, 시트 트리거, 시트 메뉴, 시트에서 메일 보내기, 웹앱 수정."
license: MIT (see LICENSE)
---

# Google Apps Script

Build automation for Google Sheets and Workspace. Scripts run on Google's servers, on a schedule or on events, with no AI in the loop, so one good script saves time every week.

## Reference files

| File | Read when |
|---|---|
| `references/patterns.md` | Writing code: helpers, menus, dialogs, sidebars, onEdit, triggers, email, PDF, API, Slack, archive, batch email, jobs over 6 minutes, minimal web app |
| `references/team-web-app-safety.md` (Korean) | Changing a sheet or web app other people already use: locking, deployments, bulk-delete guards |

## Workflow

### Step 1: Understand the automation

Ask only what would change the result. Otherwise state the assumption and proceed, and deliver working code in the same reply.
- **What** should happen, and **when** (menu click, edit, form submit, schedule)?
- **Which sheet and columns?** Use the header row if the user gave it. If not, don't stop to ask: look columns up by header text at runtime (`columnIndexes_`), list the sheet and header names you assumed in the CONFIG block, and tell the user to adjust them. Never hard-code column numbers you haven't seen.
- **Defaults when unstated:** the user's local time zone (e.g. `Asia/Seoul`); secrets and webhook URLs in Script Properties; a summary of the obvious totals, with the choice stated.
- **Bound or standalone?** Bound (Extensions > Apps Script from the sheet) is the default.
- **Existing project?** If the sheet already has scripts or a team web app, apply Step 3a.
- **Is the sheet a mirror** of another source (an imported or synced Excel file, for example)? Then don't write to it unless asked, and remember that `onEdit` does not fire for imports or sync.

### Step 2: Generate the script

- Start from the template below and the matching sections of `references/patterns.md`.
- Put shared helpers (`getSheetOrThrow_`, `columnIndexes_`, `escapeHtml_`, `getSecret_`, `removeTriggers_`) in one `helpers.gs` per project.
- Write user-facing text (menus, dialogs, emails, error messages) in the user's language. Code and comments can stay in English.

### Step 3: Installation instructions

1. Open the Google Sheet. For a sheet people already use, **make a copy first** and install there until tested.
2. **Extensions > Apps Script**
3. Click **+ > Script** to add a **new** file (e.g. `weeklyReport.gs`). **Never delete or replace existing files**: the project may already hold the team's web app or triggers.
4. Paste the script into the new file and click **Save**.
5. If the script uses secrets (API keys, webhook URLs), add them under **Project Settings > Script Properties**.
6. For installable triggers: select `installTriggers` in the function dropdown and click **Run** once.
7. Reload the spreadsheet so `onOpen()` adds the menu.

If the project already has `onOpen()`, `onEdit()`, `doGet()` or `doPost()`, **do not add a second one**. A second definition silently replaces the first. Merge the new code into the existing function and say so.

### Step 3a: Sheets and web apps people already use

- **Warn and get approval first** for anything that changes sheet structure (columns, sheet names, ranges other formulas reference), overwrites data, deletes rows, or changes a deployed web app. Explain what could break.
- Follow `references/team-web-app-safety.md` for web apps, concurrent writes, deployments and bulk deletes.

### Step 4: First-time authorisation

On the first run each user sees Google's consent screen. For unverified scripts they click **Advanced > Go to [project] (unsafe) > Allow**. Tell the user this is expected. A Google Workspace admin can block unverified scripts; if the button is missing, the admin has to allow the app.

### Step 5: Verify before calling it done

- Run the main function once from the editor on the copy, then check **Executions** for errors.
- For triggers, open **Triggers** (clock icon). Confirm there is exactly one trigger per handler, then set failure notifications to "Notify me immediately".
- Check the result in the sheet, mailbox or Slack. Don't assume the script worked.

---

## Script template

```javascript
/**
 * [Project name] - [what it does]
 * Trigger: [menu / onEdit / every Monday 08:00 Asia/Seoul / ...]
 * INSTALL: Extensions > Apps Script > + > Script (new file) > paste > Save > reload the sheet
 */

// --- CONFIGURATION (top-level const names must be unique across all .gs files) ---
const REPORT_SHEET = 'Report';

// --- MENU (merge into an existing onOpen if the project has one) ---
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Automation')
    .addItem('Run report', 'runReport')
    .addToUi();
}

// --- ENTRY POINTS (public: callable from menus, triggers and dialogs) ---
function runReport() {
  const sheet = getSheetOrThrow_(REPORT_SHEET);
  const values = sheet.getDataRange().getValues();   // one read
  // ... compute ...
  SpreadsheetApp.flush();
}
```

---

## Critical rules

### Name sheets explicitly
Use `getSheetByName()` (or `getSheetOrThrow_`), never `getActiveSheet()`, in anything that runs from a trigger, a web app or a dialog. In a time-driven trigger there is no user, so the "active" sheet is simply the first tab.

### Batch reads and writes
Read with one `getValues()` and write with one `setValues()` or `setBackgrounds()`. Cell-by-cell loops are often 50–100× slower and hit the 6-minute limit.

### One global scope
All `.gs` files share one scope. Duplicate top-level `const` names stop the whole project from loading. Duplicate function names make the last file win, silently.

### Public vs private functions
Functions ending in `_` are private. Menus fail with "Script function not found", and `google.script.run.fn_()` fails with "is not a function" in the browser console. Anything called from a menu, trigger or HTML must be public.

### UI only when a person runs it
`SpreadsheetApp.getUi()` (alert, prompt, dialog, sidebar) throws in time-driven triggers and web apps. Code that can run from a trigger should throw or log instead of showing an alert.

### Time zones and dates
- Triggers and `Utilities.formatDate()` use the **script** time zone (`appsscript.json` > `timeZone`, e.g. `Asia/Seoul`). The spreadsheet has its own zone under File > Settings, and they can differ. Use `Session.getScriptTimeZone()` when formatting.
- `getValues()` returns `Date` objects and numbers. `getDisplayValues()` returns the text the sheet shows. Use display values for emails and reports.

### Triggers
| | Simple (`onOpen`, `onEdit`) | Installable (`ScriptApp.newTrigger`) |
|---|---|---|
| Authorisation | None | Required once |
| Email, URL fetch, other files | No | Yes |
| Runs as | The person using the sheet | The person who created the trigger |
| Time limit | 30 seconds | 6 minutes |

- `onEdit` fires only for edits a person makes in the Sheets UI. It does not fire for script, API, import or sync changes.
- Installers must be idempotent: delete existing triggers for the handler before creating one (`removeTriggers_`). Otherwise every re-run adds a duplicate, and reports go out twice.
- Never name an installable handler `onEdit` or `onOpen`. The simple trigger also fires, so the code runs twice.
- `atHour(8)` runs sometime between 8 and 9 o'clock, not at an exact minute.
- Triggers stop working when their creator's account loses access. Note in the handover who owns them.

### Concurrency
Two people, or a person and a trigger, can run the same function at the same moment. Wrap writes that must not interleave (sending batches, archiving, numbering, saving from a web app) in `LockService.getScriptLock()` with `tryLock` and release it in `finally`. `appendRow()` on its own is atomic.

### Secrets and HTML
- API keys and webhook URLs go in Script Properties (`getSecret_`), never in code or in cells.
- Escape anything from cells or users before it goes into HTML (`escapeHtml_`, or `<?= ?>` in templates). Unescaped `<`, `&` or quotes break emails and dialogs, and can inject markup.

### HTTP
Use `muteHttpExceptions: true` and treat any 2xx as success, not just 200. Retry 429, plus 5xx for GETs only. `fetchJson_` in the patterns file does this.

### V8 runtime
V8 is the only runtime. It supports modern JavaScript (`const`, arrow functions, classes, `Map`, destructuring) but not browser APIs:

| Missing | Use instead |
|---|---|
| `setTimeout` / `setInterval` | `Utilities.sleep(ms)` (blocking); time-driven triggers for later work |
| `fetch` | `UrlFetchApp.fetch()` |
| `URL`, `FormData` | String building, or `payload` objects |
| `crypto` | `Utilities.computeDigest()`, `Utilities.getUuid()` |

### Flush
Call `SpreadsheetApp.flush()` before returning to a dialog and before exporting a PDF, so the writes are visible.

### Custom functions (`=MY_FUNCTION()`)
Custom functions need the `@customfunction` JSDoc tag. They have 30 seconds and cannot use services that need authorisation (MailApp, UrlFetchApp, `getUi()`, other files). They are recalculated whenever Sheets decides, so keep them pure.

---

## Quotas (per user; check the official quotas page for current values)

| Resource | Consumer (gmail.com) | Google Workspace |
|---|---|---|
| Script runtime | 6 min / execution | 6 min / execution |
| Custom function / simple trigger runtime | 30 s | 30 s |
| Triggers total runtime | 90 min / day | 6 h / day |
| Triggers | 20 per user per script | 20 per user per script |
| Email recipients | 100 / day | 1,500 / day |
| URL fetch calls | 20,000 / day | 100,000 / day |
| Properties | 9 KB per value, 500 KB per store | 9 KB per value, 500 KB per store |
| Simultaneous executions | 30 | 30 |

---

## Error prevention

| Symptom | Cause and fix |
|---|---|
| Report sent twice | Duplicate triggers (installer ran twice) or an installable handler named `onEdit`. Use `removeTriggers_`; rename the handler |
| Trigger wrote to the wrong tab | `getActiveSheet()` in trigger code. Use `getSheetByName()` |
| "Cannot call SpreadsheetApp.getUi() from this context" | `alert()` in trigger or web-app code. Throw or log instead |
| "Identifier has already been declared" | Same top-level `const` in two files. Rename one |
| Old menu or onEdit stopped working | A second `onOpen`/`onEdit` replaced it. Merge them |
| Dialog button does nothing | Server function is private (`_`) or throws with no failure handler. Make it public; add `withFailureHandler` |
| onEdit doesn't fire | The change came from a script, import or sync, not a person. Use a time-driven trigger |
| Wrong time or date | Script time zone differs from the sheet. Set `timeZone` in `appsscript.json` |
| Slow or "Exceeded maximum execution time" | Cell-by-cell calls. Batch; for real volume, split the work (see patterns) |
| Email breaks with `<` or `&` in data | Unescaped HTML. Use `escapeHtml_` |
| HTTP 201/204 treated as failure | Check for 2xx, not `=== 200` |
| Auth screen missing "Advanced" | Workspace admin blocks unverified apps. Ask the admin |

## Debugging

- `console.log()` output: Apps Script editor > **Executions** (click a run).
- Run one function: pick it in the function dropdown > **Run**.
- Trigger failures: **Triggers** page > failure notifications, plus **Executions** filtered by trigger.
- Always test on a copy of the sheet.

## Delivery checklist

- [ ] New file only; existing files and functions untouched or explicitly merged
- [ ] Sheet names are constants; columns are found by header name (`columnIndexes_`) or checked against the real header row
- [ ] No `getActiveSheet()` or `getUi()` in trigger or web-app code
- [ ] Batch reads and writes; nothing cell-by-cell inside large loops
- [ ] Installers are idempotent; handlers aren't named `onEdit`/`onOpen`
- [ ] Locks around writes that two runs could interleave
- [ ] Secrets in Script Properties; HTML escaped
- [ ] 2xx check and `muteHttpExceptions` on every fetch
- [ ] User-facing text in the user's language
- [ ] Tested on a copy: Executions clean, one trigger per handler, result checked

## Look up in the Apps Script docs when needed

- Row/column show and hide: `hideRows()`, `showRows()`, `isRowHiddenByUser()`
- Formatting: `setNumberFormat()`, `setFontWeight()`, `setBorder()`, conditional format rules
- Protection: `range.protect()`, `setUnprotectedRanges()`, editor lists
- Sheets: `copyTo()`, `insertSheet()`, `getSheets()`
- Drive files and folders: `DriveApp`; converting Excel files needs the Drive advanced service
