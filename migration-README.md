# Migration reconciliation — synthetic demonstration

This T-SQL example compares source and target records and returns discrepancy details alongside row counts, duplicate checks, null-aware field comparisons and exact amount totals.

## Verification status

**Fixture verified; SQL Server execution pending.**

The independent Node.js verifier reconstructs the fixed source and target records from the SQL fixture and compares the calculated result with `migration-expected-results.json`. It does not parse or execute T-SQL. The expected JSON is not a SQL Server runtime result.

```sh
node migration-verify-fixtures.cjs
```

## Expected fixture outcome

- 25 source rows and 26 target rows.
- One duplicate target key, one missing key and one unexpected key.
- Seven field differences; an ID can have multiple field differences.
- 10 discrepancy entries, not necessarily 10 distinct affected records.
- Source total `17586.87`; target total `17036.88`; target minus source `-549.99`.

The expected reconciliation status is `FAIL`: the synthetic target deliberately contains problems. That result is correct for this fixture and is not a failed verifier test.

## Run in a development instance

Use SQL Server 2016 or later and a disposable development connection with permission to create local temporary tables. Open `migration-demo.sql` in SSMS and execute the complete script in one session. It returns JSON to compare with `migration-expected-results.json`.

SQL writes affect session-local `#mr_*` demonstration tables only. The initial reset statements apply only to those session-local temporary tables. No permanent database or table is created, changed or deleted.

Field comparisons exclude keys duplicated on either side so a duplicate does not multiply a comparison join. Nulls differ from zeros and empty strings; text comparisons detect case and trailing-space differences. Totals include duplicate rows and separate null counts are reported.

This sample checks data; it does not migrate records, repair differences or approve a production cutover. Real work first requires agreement on keys, mappings, text normalization, currencies, tolerances, cut-off times and consistent snapshots. All data is synthetic; no client engagement or production outcome is claimed.
