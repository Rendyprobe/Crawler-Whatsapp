const SHEET_NAME = 'Grup';
const HEADERS = ['timestamp', 'platform', 'group_name', 'url', 'status'];

function doPost(e) {
  try {
    const payload = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const sheet = getTargetSheet_();
    ensureHeaders_(sheet);
    const inserted = appendUniqueRows_(sheet, rows);
    return jsonResponse_({ ok: true, inserted: inserted, sheet: SHEET_NAME });
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error) });
  }
}

function getTargetSheet_() {
  const spreadsheetId = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
  const spreadsheet = spreadsheetId
    ? SpreadsheetApp.openById(spreadsheetId)
    : SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet) {
    throw new Error('Spreadsheet tidak ditemukan. Bind script ke spreadsheet atau set SPREADSHEET_ID.');
  }
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }
  return sheet;
}

function ensureHeaders_(sheet) {
  const firstRow = sheet.getRange(1, 1, 1, HEADERS.length).getValues()[0];
  const hasHeaders = HEADERS.every(function(header, index) {
    return firstRow[index] === header;
  });
  if (!hasHeaders) {
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
  }
}

function appendUniqueRows_(sheet, rows) {
  if (!rows.length) {
    return 0;
  }

  const lastRow = sheet.getLastRow();
  const existingValues = lastRow > 1
    ? sheet.getRange(2, 1, lastRow - 1, HEADERS.length).getValues()
    : [];
  const seen = new Set(
    existingValues.map(function(row) {
      return String(row[1] || '') + '|' + String(row[3] || '');
    })
  );

  const prepared = [];
  rows.forEach(function(row) {
    const platform = String(row.platform || '').trim();
    const url = String(row.url || '').trim();
    if (!platform || !url) {
      return;
    }
    const dedupeKey = platform + '|' + url;
    if (seen.has(dedupeKey)) {
      return;
    }
    seen.add(dedupeKey);
    prepared.push([
      String(row.timestamp || ''),
      platform,
      String(row.group_name || ''),
      url,
      String(row.status || 'active'),
    ]);
  });

  if (!prepared.length) {
    return 0;
  }

  sheet.getRange(sheet.getLastRow() + 1, 1, prepared.length, HEADERS.length).setValues(prepared);
  return prepared.length;
}

function jsonResponse_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
