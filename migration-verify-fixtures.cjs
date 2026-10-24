// Independent fixture arithmetic and expected-output check; NOT a T-SQL engine.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const sql = fs.readFileSync(path.join(__dirname, 'migration-demo.sql'), 'utf8');
const expected = JSON.parse(fs.readFileSync(path.join(__dirname, 'migration-expected-results.json'), 'utf8'));
const block = name => {
  const match = sql.match(new RegExp(`-- ${name}_START([\\s\\S]*?)-- ${name}_END`));
  assert.ok(match, `Missing marked block ${name}`);
  return match[1];
};
const cents = value => {
  const match = /^(\d+)\.(\d{2})$/.exec(value);
  assert.ok(match, `Unexpected money literal ${value}`);
  return Number(match[1]) * 100 + Number(match[2]);
};
const money = value => `${value < 0 ? '-' : ''}${Math.floor(Math.abs(value) / 100)}.${String(Math.abs(value) % 100).padStart(2, '0')}`;
const literal = (value, column) => {
  if (value === 'NULL') return null;
  return column === 'Amount' ? cents(value) : value.slice(2, -1).replace(/''/g, "'");
};
const rows = text => [...text.matchAll(/\((\d+), (N'(?:[^']|'')*'), (NULL|N'(?:[^']|'')*'), (NULL|\d+\.\d{2})\)/g)]
  .map(m => ({ CustomerID: Number(m[1]), CustomerName: literal(m[2], 'CustomerName'), Region: literal(m[3], 'Region'), Amount: literal(m[4], 'Amount') }));
const source = rows(block('SOURCE_FIXTURE'));
assert.equal(source.length, 25, 'Expected to read every source fixture row');
let target = source.map(row => ({ ...row }));
const changes = block('TARGET_CHANGES');
const updates = [...changes.matchAll(/UPDATE #mr_target SET (CustomerName|Region|Amount) = (NULL|N'(?:[^']|'')*'|\d+\.\d{2}) WHERE CustomerID = (\d+);/g)];
assert.equal(updates.length, 7, 'Expected to read every fixture update');
for (const [, column, value, id] of updates) {
  const row = target.find(row => row.CustomerID === Number(id));
  assert.ok(row, `Update key ${id} must exist`);
  row[column] = literal(value, column);
}
const deleted = [...changes.matchAll(/DELETE FROM #mr_target WHERE CustomerID = (\d+);/g)];
assert.equal(deleted.length, 1);
for (const [, id] of deleted) target = target.filter(row => row.CustomerID !== Number(id));
const extraRows = rows(changes);
assert.equal(extraRows.length, 1);
target.push(...extraRows);
const duplicated = [...changes.matchAll(/SELECT CustomerID, CustomerName, Region, Amount FROM #mr_source\s+WHERE CustomerID = (\d+);/g)];
assert.equal(duplicated.length, 1);
for (const [, id] of duplicated) target.push({ ...source.find(row => row.CustomerID === Number(id)) });

const group = data => {
  const result = new Map();
  for (const row of data) result.set(row.CustomerID, [...(result.get(row.CustomerID) || []), row]);
  return result;
};
const sources = group(source), targets = group(target);
const discrepancies = [];
const add = (issueType, customerID, columnName, sourceValue, targetValue) => discrepancies.push({ issueType, customerID, columnName, sourceValue, targetValue });
for (const id of new Set([...sources.keys(), ...targets.keys()])) {
  const sr = sources.get(id) || [], tr = targets.get(id) || [];
  if (sr.length > 1) add('DUPLICATE_SOURCE', id, 'rowCount', String(sr.length), String(tr.length));
  if (tr.length > 1) add('DUPLICATE_TARGET', id, 'rowCount', String(sr.length), String(tr.length));
  if (sr.length && !tr.length) add('MISSING_TARGET', id, 'CustomerID', String(id), null);
  if (!sr.length && tr.length) add('EXTRA_TARGET', id, 'CustomerID', null, String(id));
  if (sr.length === 1 && tr.length === 1) {
    for (const column of ['CustomerName', 'Region', 'Amount']) {
      const s = sr[0][column], t = tr[0][column];
      if (s !== t) add('FIELD_MISMATCH', id, column, column === 'Amount' && s !== null ? money(s) : s, column === 'Amount' && t !== null ? money(t) : t);
    }
  }
}
discrepancies.sort((a, b) => a.issueType.localeCompare(b.issueType) || a.customerID - b.customerID || a.columnName.localeCompare(b.columnName));
const sum = data => data.reduce((total, row) => total + (row.Amount ?? 0), 0);
const sourceTotal = sum(source), targetTotal = sum(target);
const summary = {
  sourceRowCount: source.length,
  targetRowCount: target.length,
  sourceDistinctIDs: sources.size,
  targetDistinctIDs: targets.size,
  uniquePairsCompared: [...sources].filter(([id, data]) => data.length === 1 && (targets.get(id) || []).length === 1).length,
  sourceAmountTotal: money(sourceTotal),
  targetAmountTotal: money(targetTotal),
  amountDeltaTargetMinusSource: money(targetTotal - sourceTotal),
  sourceNullAmountRows: source.filter(row => row.Amount === null).length,
  targetNullAmountRows: target.filter(row => row.Amount === null).length,
  sourceDuplicateIDs: [...sources.values()].filter(data => data.length > 1).length,
  targetDuplicateIDs: [...targets.values()].filter(data => data.length > 1).length,
  missingTargetIDs: discrepancies.filter(row => row.issueType === 'MISSING_TARGET').length,
  extraTargetIDs: discrepancies.filter(row => row.issueType === 'EXTRA_TARGET').length,
  fieldDifferences: discrepancies.filter(row => row.issueType === 'FIELD_MISMATCH').length,
  discrepancyCount: discrepancies.length,
  reconciliationStatus: discrepancies.length === 0 && sourceTotal === targetTotal ? 'PASS' : 'FAIL'
};
assert.deepEqual({ summary, discrepancies }, expected);
console.log('PASS: exact SQL fixtures match all expected summary values and 10 discrepancies.');
console.log('T-SQL was not executed by this verifier.');
