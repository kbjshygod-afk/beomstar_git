# Apps Script Patterns

Copy-ready code for common Sheets automations. Read the section you need.

**Combining recipes in one project.** All `.gs` files share one global scope:
- Put the shared helpers below in one file (e.g. `helpers.gs`) once per project.
- Top-level `const` names must be unique across files, or the project fails to load with "Identifier has already been declared".
- A second `function onOpen()` / `onEdit()` / `doGet()` silently replaces the first. Merge into the existing one instead.

## Contents

- [Shared helpers](#shared-helpers)
- [Custom menu](#custom-menu)
- [Modal progress dialog](#modal-progress-dialog)
- [Toast, alert and prompt](#toast-alert-and-prompt)
- [Sidebar form](#sidebar-form)
- [onEdit timestamp](#onedit-timestamp)
- [Installable triggers (idempotent)](#installable-triggers-idempotent)
- [Email a sheet as an HTML table](#email-a-sheet-as-an-html-table)
- [PDF export](#pdf-export)
- [External API calls](#external-api-calls)
- [Slack notification](#slack-notification)
- [Data validation dropdowns](#data-validation-dropdowns)
- [Archive completed rows](#archive-completed-rows)
- [Highlight duplicates](#highlight-duplicates)
- [Batch email sender](#batch-email-sender)
- [Jobs longer than 6 minutes](#jobs-longer-than-6-minutes)
- [Minimal web app](#minimal-web-app)
- [Summary dashboard](#summary-dashboard)

## Shared helpers

```javascript
// @prelude  (helpers.gs: add once per project)

/** Returns the named sheet or throws a clear error. Never rely on the active sheet in triggers. */
function getSheetOrThrow_(name) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sheet) throw new Error('Sheet not found: ' + name);
  return sheet;
}

/** Escapes text before it goes into HTML (emails, dialogs, sidebars). */
function escapeHtml_(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Reads a secret from Project Settings > Script Properties. Never hardcode keys or webhook URLs. */
function getSecret_(key) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) throw new Error('Missing Script Property: ' + key);
  return value;
}

/**
 * Maps header names to 0-based column indexes, so code keeps working when someone inserts
 * or moves a column. Throws with the actual headers if a name is missing.
 */
function columnIndexes_(headerRow, names) {
  const map = {};
  names.forEach(function (name) {
    const i = headerRow.findIndex(function (h) { return String(h).trim() === name; });
    if (i < 0) throw new Error('Column not found: "' + name + '". Headers: ' + headerRow.join(', '));
    map[name] = i;
  });
  return map;
}

/** Deletes this user's triggers for a handler so an installer can run twice without duplicates. */
function removeTriggers_(handlerName) {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === handlerName; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
}
```

Usage: `const col = columnIndexes_(values[0], ['Date', 'Amount']); row[col.Amount]`.

`getActiveSpreadsheet()` works in bound scripts (created from the sheet), including their triggers. A standalone script must use `SpreadsheetApp.openById(id)`.

## Custom menu

```javascript
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Automation')
    .addItem('Send weekly report now', 'sendWeeklyReport')
    .addSeparator()
    .addSubMenu(SpreadsheetApp.getUi().createMenu('Setup')
      .addItem('Install triggers', 'installTriggers'))
    .addToUi();
}
```

Menu items must name public functions (no trailing `_`). A missing or private name fails with "Script function not found".

## Modal progress dialog

Blocks the sheet during a long operation and closes itself. Flow: menu function > `showProgress()` > the dialog calls the worker > it closes itself.

```javascript
function showProgress(message, serverFn) {
  if (!/^[A-Za-z$][\w$]*$/.test(serverFn) || /_$/.test(serverFn)) {
    throw new Error('serverFn must be a public function name (no trailing _): ' + serverFn);
  }
  const html = HtmlService.createHtmlOutput(`
    <style>
      body { font-family: 'Google Sans', Arial, sans-serif; display: flex;
        flex-direction: column; align-items: center; justify-content: center;
        height: 100%; margin: 0; padding: 20px; box-sizing: border-box; }
      .spinner { width: 36px; height: 36px; border: 4px solid #e0e0e0;
        border-top: 4px solid #1a73e8; border-radius: 50%;
        animation: spin 0.8s linear infinite; margin-bottom: 16px; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .message { font-size: 14px; color: #333; text-align: center; }
      .done { color: #1e8e3e; font-weight: 500; }
      .error { color: #d93025; font-weight: 500; }
    </style>
    <div class="spinner" id="spinner"></div>
    <div class="message" id="msg">${escapeHtml_(message)}</div>
    <script>
      function finish(text, cls, ms) {
        document.getElementById('spinner').style.display = 'none';
        var m = document.getElementById('msg');
        m.className = 'message ' + cls;
        m.textContent = text;
        setTimeout(function () { google.script.host.close(); }, ms);
      }
      google.script.run
        .withSuccessHandler(function (r) { finish('Done! ' + (r || ''), 'done', 1200); })
        .withFailureHandler(function (err) { finish('Error: ' + err.message, 'error', 4000); })
        .${serverFn}();
    </script>
  `).setWidth(320).setHeight(140);
  SpreadsheetApp.getUi().showModalDialog(html, 'Working...');
}

function menuDoWork() {
  showProgress('Processing data...', 'doTheWork');
}

// Must be public (no trailing underscore) so the dialog can call it.
function doTheWork() {
  // ... do the work ...
  SpreadsheetApp.flush();
  return 'Processed 50 rows';
}
```

## Toast, alert and prompt

```javascript
function confirmAndClear() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();   // only works when a person runs this from the sheet

  const answer = ui.alert('Clear the input sheet?', 'This cannot be undone.', ui.ButtonSet.YES_NO);
  if (answer !== ui.Button.YES) return;

  const reply = ui.prompt('Type your name to confirm:', ui.ButtonSet.OK_CANCEL);
  if (reply.getSelectedButton() !== ui.Button.OK || !reply.getResponseText().trim()) return;

  // ... clear the data ...
  ss.toast('Cleared by ' + reply.getResponseText().trim(), 'Done', 5);   // seconds; -1 = until dismissed
}
```

`SpreadsheetApp.getUi()` throws in time-driven triggers and web apps ("Cannot call SpreadsheetApp.getUi() from this context"). In code that can run from a trigger, throw an error or log instead of showing an alert.

## Sidebar form

```javascript
const JOB_SHEET = 'Jobs';

function showSidebar() {
  const html = HtmlService.createHtmlOutput(`
    <h3>Quick Entry</h3>
    <select id="worker"><option>Kim</option><option>Lee</option></select>
    <input id="place" placeholder="Place">
    <button id="add" onclick="submitJob()">Add Job</button>
    <div id="status"></div>
    <script>
      function submitJob() {
        var btn = document.getElementById('add');
        btn.disabled = true;
        google.script.run
          .withSuccessHandler(function () {
            document.getElementById('status').textContent = 'Added';
            document.getElementById('place').value = '';
            btn.disabled = false;
          })
          .withFailureHandler(function (e) {
            document.getElementById('status').textContent = 'Error: ' + e.message;
            btn.disabled = false;
          })
          .addJob(document.getElementById('worker').value, document.getElementById('place').value);
      }
    </script>
  `).setTitle('Job Entry');
  SpreadsheetApp.getUi().showSidebar(html);
}

// Public so the sidebar can call it. Writes to a named sheet, never the active one.
function addJob(worker, place) {
  if (!String(worker).trim() || !String(place).trim()) throw new Error('Worker and place are required');
  getSheetOrThrow_(JOB_SHEET).appendRow([new Date(), worker, place]);
}
```

Sidebars have a fixed width; `setWidth()` has no effect on them.

## onEdit timestamp

Stamps column D whenever column C changes, including multi-row pastes.

```javascript
const STAMP_SHEET = 'Data';
const STAMP_WATCH_COL = 3;   // C
const STAMP_TARGET_COL = 4;  // D

function onEdit(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== STAMP_SHEET) return;

  const firstCol = range.getColumn();
  const lastCol = firstCol + range.getNumColumns() - 1;
  if (STAMP_WATCH_COL < firstCol || STAMP_WATCH_COL > lastCol) return;

  const firstRow = Math.max(range.getRow(), 2);                 // skip the header row
  const lastRow = range.getRow() + range.getNumRows() - 1;
  if (lastRow < firstRow) return;

  const now = new Date();
  const stamps = [];
  for (let r = firstRow; r <= lastRow; r++) stamps.push([now]);
  sheet.getRange(firstRow, STAMP_TARGET_COL, stamps.length, 1).setValues(stamps);
}
```

Simple `onEdit` fires only for edits a person makes in the Sheets UI. Edits by scripts, the Sheets API, imports, or sync tools do not fire it. It must finish within 30 seconds and cannot send email or call URLs.

## Installable triggers (idempotent)

Run `installTriggers` once from the editor. Running it again replaces the triggers instead of duplicating them. Duplicate triggers are the most common cause of "the report was sent twice".

```javascript
function installTriggers() {
  const ss = SpreadsheetApp.getActive();

  removeTriggers_('sendWeeklyReport');
  ScriptApp.newTrigger('sendWeeklyReport')
    .timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();

  removeTriggers_('handleEditWithAuth');
  ScriptApp.newTrigger('handleEditWithAuth').forSpreadsheet(ss).onEdit().create();

  removeTriggers_('handleFormSubmit');
  ScriptApp.newTrigger('handleFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
}

function uninstallTriggers() {
  ['sendWeeklyReport', 'handleEditWithAuth', 'handleFormSubmit'].forEach(removeTriggers_);
}

function sendWeeklyReport() { /* ... */ }
function handleEditWithAuth(e) { /* can send email, fetch URLs */ }
function handleFormSubmit(e) { /* e.values holds the submitted row */ }
```

- **Never name an installable handler `onEdit` or `onOpen`.** The simple trigger also fires, so the code runs twice.
- **Time:** `atHour(8)` runs sometime between 8 and 9 o'clock in the **script's** time zone (`appsscript.json` > `timeZone`, e.g. `Asia/Seoul`), not at an exact minute.
- **Owner:** installable triggers run as the person who created them. If that account leaves or loses access, the triggers stop. `getProjectTriggers()` only sees the current user's triggers, so check the Triggers page for ones created by teammates.

## Email a sheet as an HTML table

```javascript
const SCHEDULE_SHEET = 'Schedule';
const SCHEDULE_TO = 'team@example.com';

function emailWeeklySchedule() {
  const values = getSheetOrThrow_(SCHEDULE_SHEET).getDataRange().getDisplayValues();
  if (values.length < 2) return 0;                          // header only: nothing to send
  const header = values[0];
  const rows = values.slice(1).filter(function (r) { return r[0] !== ''; });
  if (rows.length === 0) return 0;

  const cells = function (tag, row) {
    return row.map(function (v) { return '<' + tag + '>' + escapeHtml_(v) + '</' + tag + '>'; }).join('');
  };
  const body = '<h2>Weekly Schedule</h2><table border="1" cellpadding="6" style="border-collapse:collapse">'
    + '<tr>' + cells('th', header) + '</tr>'
    + rows.map(function (r) { return '<tr>' + cells('td', r) + '</tr>'; }).join('')
    + '</table>';

  const today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  MailApp.sendEmail({ to: SCHEDULE_TO, subject: 'Schedule - ' + today, htmlBody: body });
  return rows.length;
}
```

The header comes from the sheet, so the columns always line up. `getDisplayValues()` sends numbers and dates exactly as the sheet shows them.

## PDF export

```javascript
function exportSheetAsPdf(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = getSheetOrThrow_(sheetName);
  SpreadsheetApp.flush();                                   // include writes made earlier in this run

  const url = 'https://docs.google.com/spreadsheets/d/' + ss.getId() + '/export'
    + '?format=pdf&size=A4&portrait=true&fitw=true'
    + '&sheetnames=false&printtitle=false&gridlines=false'
    + '&gid=' + sheet.getSheetId();
  const response = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('PDF export failed: HTTP ' + response.getResponseCode());
  }
  const stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd');
  return response.getBlob().setName(sheetName + '_' + stamp + '.pdf');
}

function emailPdf() {
  MailApp.sendEmail({
    to: 'boss@example.com',
    subject: 'Weekly Report PDF',
    body: 'Attached.',
    attachments: [exportSheetAsPdf('Report')],
  });
}
```

- The `/export` parameters are not officially documented and may change without notice.
- Exporting many sheets in a row can return HTTP 429. Add `Utilities.sleep(2000)` between exports.
- If the export returns 401 or 403, the token lacks Drive access. Referencing `DriveApp` anywhere in the project (e.g. `DriveApp.getRootFolder();` in an unused function) makes Apps Script request that scope at the next authorisation.

## External API calls

```javascript
/** GET/POST JSON with a 2xx check. Retries 429, and 5xx for GET only (a POST retry could duplicate). */
function fetchJson_(url, options) {
  const params = Object.assign({ muteHttpExceptions: true }, options || {});
  const method = String(params.method || 'get').toLowerCase();
  for (let attempt = 1; attempt <= 3; attempt++) {
    const response = UrlFetchApp.fetch(url, params);
    const code = response.getResponseCode();
    if (code >= 200 && code < 300) {
      const text = response.getContentText();
      return text ? JSON.parse(text) : null;
    }
    const retryable = code === 429 || (code >= 500 && method === 'get');
    if (!retryable || attempt === 3) {
      throw new Error('HTTP ' + code + ' from ' + url + ': ' + response.getContentText().slice(0, 300));
    }
    Utilities.sleep(1000 * Math.pow(2, attempt));           // 2s, then 4s
  }
}

function fetchData() {
  return fetchJson_('https://api.example.com/data', {
    headers: { Authorization: 'Bearer ' + getSecret_('API_KEY') },
  });
}

function postData(payload) {
  return fetchJson_('https://api.example.com/submit', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + getSecret_('API_KEY') },
    payload: JSON.stringify(payload),
  });
}
```

Set `API_KEY` under Project Settings > Script Properties. Never put keys in code or in the sheet.

## Slack notification

Uses a Slack incoming webhook. Store its URL as the Script Property `SLACK_WEBHOOK_URL`.

```javascript
function notifySlack(text) {
  const response = UrlFetchApp.fetch(getSecret_('SLACK_WEBHOOK_URL'), {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ text: text }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('Slack webhook failed: HTTP ' + response.getResponseCode() + ' ' + response.getContentText());
  }
}
```

Google Chat works the same way: POST `{ text: ... }` to the space's webhook URL.

## Data validation dropdowns

```javascript
function setupDropdowns() {
  const sheet = getSheetOrThrow_('Data');

  const fromList = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Draft', 'Review', 'Done'], true)
    .setAllowInvalid(false)
    .setHelpText('Choose a status')
    .build();
  sheet.getRange('C2:C500').setDataValidation(fromList);

  const fromRange = SpreadsheetApp.newDataValidation()
    .requireValueInRange(getSheetOrThrow_('Lookups').getRange('A2:A200'), true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange('B2:B500').setDataValidation(fromRange);
}
```

## Archive completed rows

Copies rows whose status is "Complete" to an Archive sheet in their original order, then deletes them from the source.

```javascript
const ARCHIVE_SOURCE = 'Active';
const ARCHIVE_TARGET = 'Archive';
const ARCHIVE_STATUS_COL = 5;              // column E (1-based)
const ARCHIVE_DONE = 'Complete';

function archiveCompleted() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) throw new Error('Another archive run is in progress');
  try {
    const source = getSheetOrThrow_(ARCHIVE_SOURCE);
    const archive = getSheetOrThrow_(ARCHIVE_TARGET);
    const values = source.getDataRange().getValues();
    const doneRows = [];                   // 1-based sheet row numbers, ascending
    for (let i = 1; i < values.length; i++) {
      if (values[i][ARCHIVE_STATUS_COL - 1] === ARCHIVE_DONE) doneRows.push(i + 1);
    }
    if (doneRows.length === 0) return 0;

    // 1) Copy first, in one write.
    const copied = doneRows.map(function (r) { return values[r - 1]; });
    archive.getRange(archive.getLastRow() + 1, 1, copied.length, values[0].length).setValues(copied);

    // 2) Then delete bottom-up in contiguous blocks. Formulas in the remaining rows stay intact.
    let end = doneRows.length - 1;
    while (end >= 0) {
      let start = end;
      while (start > 0 && doneRows[start - 1] === doneRows[start] - 1) start--;
      source.deleteRows(doneRows[start], end - start + 1);
      end = start - 1;
    }
    SpreadsheetApp.flush();
    return doneRows.length;
  } finally {
    lock.releaseLock();
  }
}
```

Archived rows are copied as values, so formulas become their results. Deleting rows (rather than rewriting the sheet with `setValues`) keeps formulas and formatting in the rows that stay. If a run fails between the copy and the delete, the archive can hold duplicates but no data is lost.

## Highlight duplicates

```javascript
function highlightDuplicates(sheetName, column) {
  const sheet = getSheetOrThrow_(sheetName);
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return 0;
  const range = sheet.getRange(2, column, lastRow - 1, 1);
  const keys = range.getDisplayValues().map(function (r) { return r[0].trim(); });

  const counts = new Map();
  keys.forEach(function (k) { if (k) counts.set(k, (counts.get(k) || 0) + 1); });

  // One write for the whole column; null clears the color.
  range.setBackgrounds(keys.map(function (k) { return [k && counts.get(k) > 1 ? '#f4cccc' : null]; }));
  return Array.from(counts.values()).filter(function (n) { return n > 1; }).length;
}
```

## Batch email sender

Columns: A Email, B Name, C Status.

```javascript
const RECIPIENT_SHEET = 'Recipients';

function sendBatchEmails() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) throw new Error('Another send is already running');
  try {
    const sheet = getSheetOrThrow_(RECIPIENT_SHEET);
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) return 0;                             // header only
    const rows = sheet.getRange(2, 1, lastRow - 1, 3).getValues();

    const pending = [];
    rows.forEach(function (r, i) {
      if (String(r[0]).trim() && r[2] !== 'Sent') pending.push(i);
    });
    const remaining = MailApp.getRemainingDailyQuota();
    if (pending.length > remaining) {
      throw new Error('Email quota: ' + remaining + ' left today, ' + pending.length + ' needed');
    }

    let sent = 0;
    pending.forEach(function (i) {
      const statusCell = sheet.getRange(i + 2, 3);
      try {
        MailApp.sendEmail({
          to: String(rows[i][0]).trim(),
          subject: 'Your Weekly Update',
          htmlBody: '<p>Hi ' + escapeHtml_(rows[i][1]) + ',</p><p>Here is your update...</p>',
        });
        statusCell.setValue('Sent');
        sent++;
      } catch (e) {
        statusCell.setValue('Error: ' + e.message);
      }
      SpreadsheetApp.flush();                              // record status before the next send
    });
    return sent;
  } finally {
    lock.releaseLock();
  }
}
```

- The lock stops two people (or a person and a trigger) from sending the same batch twice.
- Status is written right after each send, so a run that times out can be restarted without re-sending.
- The quota counts recipients, not emails: an email to 3 people uses 3.

## Jobs longer than 6 minutes

Processes rows in batches, saves a cursor, and schedules itself to continue.

```javascript
const BIGJOB_SHEET = 'Data';
const BIGJOB_BATCH = 200;
const BIGJOB_CURSOR = 'bigJob.cursor';

function startBigJob() {
  PropertiesService.getScriptProperties().setProperty(BIGJOB_CURSOR, '2');
  removeTriggers_('continueBigJob');
  continueBigJob();
}

function continueBigJob() {
  const started = Date.now();
  const props = PropertiesService.getScriptProperties();
  const sheet = getSheetOrThrow_(BIGJOB_SHEET);
  const lastRow = sheet.getLastRow();
  let row = Number(props.getProperty(BIGJOB_CURSOR) || 2);

  while (row <= lastRow && Date.now() - started < 4.5 * 60 * 1000) {   // stop well before 6 min
    const count = Math.min(BIGJOB_BATCH, lastRow - row + 1);
    const block = sheet.getRange(row, 1, count, sheet.getLastColumn()).getValues();
    // ... process block, then write results back with one setValues() ...
    row += count;
    props.setProperty(BIGJOB_CURSOR, String(row));
  }

  removeTriggers_('continueBigJob');
  if (row <= lastRow) {
    ScriptApp.newTrigger('continueBigJob').timeBased().after(60 * 1000).create();
  } else {
    props.deleteProperty(BIGJOB_CURSOR);
  }
}
```

## Minimal web app

```javascript
function doGet() {
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Team App')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** Used inside templates: <?!= include('Styles') ?> */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
```

In templates, `<?= value ?>` escapes HTML and `<?!= value ?>` does not. Use `<?!= ?>` only for trusted HTML such as `include()`. Before changing a web app that people already use, read `team-web-app-safety.md`.

## Summary dashboard

Loop over the source tabs with `getSheetByName()`, read each tab's summary cells with one `getValues()`, and collect the rows in an array. Create the Summary sheet with `ss.insertSheet('Summary')` only if it doesn't exist. Write everything with one `setValues()`, then call `autoResizeColumns()` and `SpreadsheetApp.flush()`.
