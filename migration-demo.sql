/*
  Synthetic migration reconciliation portfolio demo. SQL Server 2016+.
  All data lives in local #temp tables belonging to this session in tempdb.
  No permanent tables, production connections, database changes, or migrations.
  The fixture deliberately contains discrepancies; reconciliationStatus = FAIL
  is the correct business result, while the demo assertions should pass.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DROP TABLE IF EXISTS #mr_source;
DROP TABLE IF EXISTS #mr_target;
DROP TABLE IF EXISTS #mr_keys;
DROP TABLE IF EXISTS #mr_discrepancies;

CREATE TABLE #mr_source (
    CustomerID int NOT NULL,
    CustomerName nvarchar(100) NULL,
    Region nvarchar(30) NULL,
    Amount decimal(18,2) NULL
);
CREATE TABLE #mr_target (
    CustomerID int NOT NULL,
    CustomerName nvarchar(100) NULL,
    Region nvarchar(30) NULL,
    Amount decimal(18,2) NULL
);

-- No unique constraint: reconciliation must detect duplicate business keys.
-- SOURCE_FIXTURE_START
INSERT INTO #mr_source (CustomerID, CustomerName, Region, Amount) VALUES
 (1001, N'Acorn Stores', N'North', 1200.00),
 (1002, N'Bluebird Books', N'South', 850.50),
 (1003, N'Cedar Foods', N'East', 0.00),
 (1004, N'Delta Tools', N'North', 430.25),
 (1005, N'Kite Labs', N'West', 1999.99),
 (1006, N'Elm Traders', NULL, 125.00),
 (1007, N'Fable Crafts', N'South', 300.00),
 (1008, N'Grove Retail', N'West', 675.75),
 (1009, N'Harbor Tea', N'East', 50.00),
 (1010, N'Iris Textiles', NULL, 1120.00),
 (1011, N'Juniper Works', N'North', 980.10),
 (1012, N'Lake Supplies', N'South', 2400.00),
 (1013, N'Maple Studio', N'East', 555.55),
 (1014, N'Nova Hardware', N'West', 740.00),
 (1015, N'Oak Services', N'North', 160.80),
 (1016, N'Pine Stationers', N'South', 90.00),
 (1017, N'Quartz Goods', N'East', 1500.00),
 (1018, N'Aster & Co', N'West', 305.25),
 (1019, N'River Market', N'North', 810.00),
 (1020, N'Spruce Cafe', N'', 45.99),
 (1021, N'Terra Logistics', NULL, 1300.00),
 (1022, N'Union Fabrics', N'South', 250.00),
 (1023, N'Vale Electronics', N'East', 620.00),
 (1024, N'Willow Bakery', N'West', 77.70),
 (1025, N'Zenith Parts', N'North', 999.99);
-- SOURCE_FIXTURE_END

INSERT INTO #mr_target (CustomerID, CustomerName, Region, Amount)
SELECT CustomerID, CustomerName, Region, Amount FROM #mr_source;

-- TARGET_CHANGES_START
UPDATE #mr_target SET Amount = NULL WHERE CustomerID = 1003;
UPDATE #mr_target SET Region = NULL WHERE CustomerID = 1004;
UPDATE #mr_target SET CustomerName = N'Kite Lab' WHERE CustomerID = 1005;
UPDATE #mr_target SET Region = N'West' WHERE CustomerID = 1006;
UPDATE #mr_target SET Amount = 2450.00 WHERE CustomerID = 1012;
UPDATE #mr_target SET CustomerName = N'Aster and Co' WHERE CustomerID = 1018;
UPDATE #mr_target SET Region = NULL WHERE CustomerID = 1020;
DELETE FROM #mr_target WHERE CustomerID = 1025;
INSERT INTO #mr_target (CustomerID, CustomerName, Region, Amount) VALUES
 (1026, N'Extra Outlet', N'South', 100.00);
INSERT INTO #mr_target (CustomerID, CustomerName, Region, Amount)
SELECT CustomerID, CustomerName, Region, Amount FROM #mr_source
WHERE CustomerID = 1007;
-- TARGET_CHANGES_END

SELECT CustomerID,
       SUM(SourceRows) AS SourceRows,
       SUM(TargetRows) AS TargetRows
INTO #mr_keys
FROM (
    SELECT CustomerID, 1 AS SourceRows, 0 AS TargetRows FROM #mr_source
    UNION ALL
    SELECT CustomerID, 0 AS SourceRows, 1 AS TargetRows FROM #mr_target
) AS AllKeys
GROUP BY CustomerID;

CREATE TABLE #mr_discrepancies (
    IssueType varchar(30) NOT NULL,
    CustomerID int NOT NULL,
    ColumnName nvarchar(128) NULL,
    SourceValue nvarchar(200) NULL,
    TargetValue nvarchar(200) NULL
);

INSERT INTO #mr_discrepancies
SELECT 'DUPLICATE_SOURCE', CustomerID, N'rowCount',
       CONVERT(nvarchar(200), SourceRows), CONVERT(nvarchar(200), TargetRows)
FROM #mr_keys WHERE SourceRows > 1
UNION ALL
SELECT 'DUPLICATE_TARGET', CustomerID, N'rowCount',
       CONVERT(nvarchar(200), SourceRows), CONVERT(nvarchar(200), TargetRows)
FROM #mr_keys WHERE TargetRows > 1
UNION ALL
SELECT 'MISSING_TARGET', CustomerID, N'CustomerID',
       CONVERT(nvarchar(200), CustomerID), NULL
FROM #mr_keys WHERE SourceRows > 0 AND TargetRows = 0
UNION ALL
SELECT 'EXTRA_TARGET', CustomerID, N'CustomerID',
       NULL, CONVERT(nvarchar(200), CustomerID)
FROM #mr_keys WHERE SourceRows = 0 AND TargetRows > 0;

-- Compare fields only when the key is unique on BOTH sides. A duplicate ID is
-- already an exception and must not cause a many-to-many join or arbitrary pick.
-- Decimal values use their exact two-decimal representation, never FLOAT.
INSERT INTO #mr_discrepancies
SELECT 'FIELD_MISMATCH', s.CustomerID, v.ColumnName,
       v.SourceValue, v.TargetValue
FROM #mr_source AS s
JOIN #mr_target AS t ON t.CustomerID = s.CustomerID
JOIN #mr_keys AS k ON k.CustomerID = s.CustomerID
                 AND k.SourceRows = 1 AND k.TargetRows = 1
CROSS APPLY (VALUES
    (N'CustomerName', CONVERT(nvarchar(200), s.CustomerName), CONVERT(nvarchar(200), t.CustomerName)),
    (N'Region',       CONVERT(nvarchar(200), s.Region),       CONVERT(nvarchar(200), t.Region)),
    (N'Amount',       CONVERT(nvarchar(200), s.Amount),       CONVERT(nvarchar(200), t.Amount))
) AS v(ColumnName, SourceValue, TargetValue)
WHERE (v.SourceValue IS NULL AND v.TargetValue IS NOT NULL)
   OR (v.SourceValue IS NOT NULL AND v.TargetValue IS NULL)
   OR DATALENGTH(v.SourceValue) <> DATALENGTH(v.TargetValue)
   OR v.SourceValue COLLATE Latin1_General_100_BIN2
      <> v.TargetValue COLLATE Latin1_General_100_BIN2;
-- NULL vs NULL is equal; NULL vs zero/empty string is different. Binary
-- collation plus DATALENGTH also detects case and trailing-space changes.

-- Leave precision headroom for subtraction: DECIMAL(38,2) minus itself can
-- reduce the result scale in SQL Server. This fixture fits DECIMAL(28,2).
DECLARE @SourceAmount decimal(28,2) =
    (SELECT COALESCE(SUM(Amount), 0) FROM #mr_source);
DECLARE @TargetAmount decimal(28,2) =
    (SELECT COALESCE(SUM(Amount), 0) FROM #mr_target);
DECLARE @DifferenceCount int = (SELECT COUNT(*) FROM #mr_discrepancies);

-- These assertions validate THIS synthetic demonstration, not a client dataset.
IF (SELECT COUNT(*) FROM #mr_source) <> 25
 OR (SELECT COUNT(*) FROM #mr_target) <> 26
 OR (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows = 1 AND TargetRows = 1) <> 23
 OR @SourceAmount <> CAST(17586.87 AS decimal(38,2))
 OR @TargetAmount <> CAST(17036.88 AS decimal(38,2))
 OR (SELECT COUNT(*) FROM #mr_discrepancies WHERE IssueType = 'FIELD_MISMATCH') <> 7
 OR @DifferenceCount <> 10
    THROW 51000, 'Synthetic fixture assertion failed; investigate the demo.', 1;

-- Single JSON result: exact decimal totals are strings for lossless handoff.
-- SUM ignores NULL amounts, so null counts are reported separately.
SELECT JSON_QUERY((
    SELECT
        (SELECT COUNT(*) FROM #mr_source) AS sourceRowCount,
        (SELECT COUNT(*) FROM #mr_target) AS targetRowCount,
        (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows > 0) AS sourceDistinctIDs,
        (SELECT COUNT(*) FROM #mr_keys WHERE TargetRows > 0) AS targetDistinctIDs,
        (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows = 1 AND TargetRows = 1) AS uniquePairsCompared,
        CONVERT(varchar(50), @SourceAmount) AS sourceAmountTotal,
        CONVERT(varchar(50), @TargetAmount) AS targetAmountTotal,
        CONVERT(varchar(50), CAST(@TargetAmount - @SourceAmount AS decimal(38,2))) AS amountDeltaTargetMinusSource,
        (SELECT COUNT(*) FROM #mr_source WHERE Amount IS NULL) AS sourceNullAmountRows,
        (SELECT COUNT(*) FROM #mr_target WHERE Amount IS NULL) AS targetNullAmountRows,
        (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows > 1) AS sourceDuplicateIDs,
        (SELECT COUNT(*) FROM #mr_keys WHERE TargetRows > 1) AS targetDuplicateIDs,
        (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows > 0 AND TargetRows = 0) AS missingTargetIDs,
        (SELECT COUNT(*) FROM #mr_keys WHERE SourceRows = 0 AND TargetRows > 0) AS extraTargetIDs,
        (SELECT COUNT(*) FROM #mr_discrepancies WHERE IssueType = 'FIELD_MISMATCH') AS fieldDifferences,
        @DifferenceCount AS discrepancyCount,
        CASE WHEN @DifferenceCount = 0 AND @SourceAmount = @TargetAmount
             THEN 'PASS' ELSE 'FAIL' END AS reconciliationStatus
    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
)) AS summary,
JSON_QUERY((
    SELECT IssueType AS issueType, CustomerID AS customerID,
           ColumnName AS columnName, SourceValue AS sourceValue,
           TargetValue AS targetValue
    FROM #mr_discrepancies
    ORDER BY IssueType, CustomerID, ColumnName
    FOR JSON PATH, INCLUDE_NULL_VALUES
)) AS discrepancies
FOR JSON PATH, WITHOUT_ARRAY_WRAPPER;
