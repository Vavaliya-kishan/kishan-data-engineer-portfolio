"""Behavior checks use isolated temporary files and never touch the shipped sample database."""

import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from main import FIELDS, create_demo_csv, run_import


class ImportValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = create_demo_csv(self.base / "sample.csv")
        self.database = self.base / "orders.sqlite3"
        self.output = self.base / "results"

    def run_demo(self):
        return run_import(self.source, self.database, self.output)

    def write_rows(self, rows):
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def test_reconciliation_and_persisted_money_are_exact(self):
        summary = self.run_demo()
        self.assertEqual((summary["input_rows"], summary["accepted_rows"], summary["rejected_rows"]), (12, 5, 7))
        self.assertEqual(summary["source_parseable_total"], "1492.21")
        self.assertEqual(summary["accepted_total"], "1357.35")
        self.assertEqual(summary["rejected_parseable_total"], "134.86")
        self.assertTrue(summary["all_checks_passed"])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*), SUM(line_total_cents) FROM orders").fetchone(), (5, 135735))

    def test_identical_rerun_does_not_duplicate_rows_or_totals(self):
        self.run_demo()
        summary = self.run_demo()
        self.assertEqual(summary["inserted_rows"], 0)
        self.assertEqual(summary["already_loaded_rows"], 5)
        self.assertEqual(summary["database_rows_after"], 5)
        self.assertEqual(summary["inserted_total"], "0.00")
        self.assertEqual(summary["database_total_after"], "1357.35")

    def test_rejects_have_actionable_reasons_and_never_enter_database(self):
        self.run_demo()
        with (self.output / "rejected.csv").open(encoding="utf-8", newline="") as handle:
            rejected = list(csv.DictReader(handle))
        reasons = {row["record_id"]: row["reasons"] for row in rejected}
        self.assertIn("duplicate_id_in_file", reasons["ORD-1002"])
        self.assertIn("valid_YYYY_MM_DD", reasons["ORD-1004"])
        self.assertIn("quantity_must_be_integer", reasons["ORD-1005"])
        self.assertIn("does_not_equal", reasons["ORD-1006"])
        self.assertIn("customer_required", reasons["ORD-1007"])
        self.assertIn("unit_price_must", reasons["ORD-1009"])
        self.assertIn("max_2_decimals", reasons["ORD-1011"])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders WHERE record_id = 'ORD-1004'").fetchone()[0], 0)

    def test_conflicting_existing_id_is_rejected_without_overwrite(self):
        self.run_demo()
        self.write_rows([["ORD-1001", "Changed Customer", "2026-10-01", "1", "5.00", "5.00"]])
        summary = self.run_demo()
        self.assertEqual((summary["accepted_rows"], summary["rejected_rows"]), (0, 1))
        self.assertEqual(summary["database_total_after"], "1357.35")
        self.assertEqual(summary["rejected_parseable_total"], "5.00")
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT customer, line_total_cents FROM orders WHERE record_id = ?", ("ORD-1001",)).fetchone(), ("Sample Alpha", 25000))
        self.assertIn("existing_id_has_conflicting_values", (self.output / "rejected.csv").read_text(encoding="utf-8"))

    def test_unparseable_totals_are_reported_separately(self):
        self.write_rows([["ORD-2001", "Sample Test", "2026-10-01", "1", "1.00", "NaN"]])
        summary = self.run_demo()
        self.assertEqual(summary["source_unparseable_total_rows"], 1)
        self.assertEqual(summary["rejected_rows"], 1)
        self.assertEqual(summary["database_rows_after"], 0)
        self.assertTrue(summary["all_checks_passed"])

    def test_invalid_header_fails_before_database_creation(self):
        self.source.write_text("unexpected,header\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CSV header"):
            self.run_demo()
        self.assertFalse(self.database.exists())

    def test_malformed_column_count_is_rejected(self):
        self.write_rows([["ORD-2002", "Sample Test", "2026-10-01", "1", "1.00", "1.00", "unexpected"]])
        summary = self.run_demo()
        self.assertEqual(summary["rejected_rows"], 1)
        self.assertEqual(summary["database_rows_after"], 0)
        self.assertIn("wrong_number_of_columns", (self.output / "rejected.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
