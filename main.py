"""Synthetic CSV import, validation and reconciliation demo; Python standard library only."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

FIELDS = ["record_id", "customer", "order_date", "quantity", "unit_price", "line_total"]
MONEY_RE = re.compile(r"[0-9]{1,10}(?:\.[0-9]{1,2})?\Z")
ID_RE = re.compile(r"ORD-[0-9]{4}\Z")
BASE = Path(__file__).resolve().parent
NOTICE = "Synthetic portfolio demonstration. no client data or client results."

# Fixed source dates, names and amounts: no fabricated client measurements or random outcomes.
DEMO_ROWS = [
    ["ORD-1001", "Sample Alpha", "2026-10-01", "2", "125.00", "250.00"],
    ["ORD-1002", "Sample Beta", "2026-10-01", "3", "19.95", "59.85"],
    ["ORD-1003", "Sample Gamma", "2026-10-02", "4", "250.00", "1000.00"],
    ["ORD-1002", "Sample Beta", "2026-10-01", "3", "19.95", "59.85"],
    ["ORD-1004", "Sample Delta", "2026-02-30", "1", "10.00", "10.00"],
    ["ORD-1005", "Sample Epsilon", "2026-10-02", "two", "10.00", "20.00"],
    ["ORD-1006", "Sample Zeta", "2026-10-02", "2", "10.00", "25.00"],
    ["ORD-1007", "", "2026-10-02", "1", "5.00", "5.00"],
    ["ORD-1008", "Sample Eta", "2026-10-03", "5", "9.50", "47.50"],
    ["ORD-1009", "Sample Theta", "2026-10-03", "1", "NaN", "10.00"],
    ["ORD-1010", "Sample Iota", "2026-10-03", "1", "0.00", "0.00"],
    ["ORD-1011", "Sample Kappa", "2026-10-03", "1", "5.005", "5.01"],
]


def money(cents: int) -> str:
    """Format integer minor units without floating-point rounding."""
    return f"{Decimal(cents) / 100:.2f}"


def parse_money(value: str) -> int | None:
    if not MONEY_RE.fullmatch(value):
        return None
    return int(Decimal(value) * 100)


@dataclass(frozen=True)
class Order:
    record_id: str
    customer: str
    order_date: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int

    def values(self) -> tuple[Any, ...]:
        return (self.customer, self.order_date, self.quantity, self.unit_price_cents, self.line_total_cents)

    def csv_values(self) -> dict[str, str | int]:
        return dict(zip(FIELDS, [self.record_id, self.customer, self.order_date, self.quantity,
                                 money(self.unit_price_cents), money(self.line_total_cents)]))


def validate(row: dict[str, str]) -> tuple[Order | None, list[str]]:
    """Require one order per ID, valid calendar dates and exact line-total arithmetic."""
    errors: list[str] = []
    identifier = row["record_id"]
    if not ID_RE.fullmatch(identifier):
        errors.append("record_id_must_match_ORD_0000")
    if not row["customer"] or len(row["customer"]) > 80:
        errors.append("customer_required_max_80_characters")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["order_date"]):
            raise ValueError("date format")
        date.fromisoformat(row["order_date"])
    except ValueError:
        errors.append("order_date_must_be_valid_YYYY_MM_DD")
    quantity = None
    if re.fullmatch(r"[1-9][0-9]{0,6}", row["quantity"]):
        quantity = int(row["quantity"])
    if quantity is None or quantity > 1_000_000:
        errors.append("quantity_must_be_integer_1_to_1000000")
    unit = parse_money(row["unit_price"])
    total = parse_money(row["line_total"])
    if unit is None:
        errors.append("unit_price_must_be_nonnegative_money_max_2_decimals")
    if total is None:
        errors.append("line_total_must_be_nonnegative_money_max_2_decimals")
    if quantity is not None and unit is not None and total is not None and quantity * unit != total:
        errors.append("line_total_does_not_equal_quantity_times_unit_price")
    if errors:
        return None, errors
    assert quantity is not None and unit is not None and total is not None
    return Order(identifier, row["customer"], row["order_date"], quantity, unit, total), []


def create_demo_csv(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(DEMO_ROWS)
    return destination


def read_source(source: Path) -> list[tuple[int, dict[str, str]]]:
    """Fail closed for invalid headers; malformed data rows are rejected individually."""
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError("CSV header must exactly match: " + ",".join(FIELDS))
        rows = []
        for raw in reader:
            row = {key: (raw.get(key) or "").strip() for key in FIELDS}
            row["_structure_error"] = "wrong_number_of_columns" if None in raw or any(raw.get(k) is None for k in FIELDS) else ""
            rows.append((reader.line_num, row))
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_import(source: Path, database: Path, output_dir: Path) -> dict[str, Any]:
    source, database, output_dir = Path(source), Path(database), Path(output_dir)
    rows = read_source(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    input_total = rejected_total = new_total = 0
    input_unparseable = rejected_unparseable = 0
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS orders (
            record_id TEXT PRIMARY KEY, customer TEXT NOT NULL, order_date TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0), unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
            line_total_cents INTEGER NOT NULL CHECK(line_total_cents >= 0))""")
        connection.execute("BEGIN IMMEDIATE")
        before_count, before_total = connection.execute("SELECT COUNT(*), COALESCE(SUM(line_total_cents), 0) FROM orders").fetchone()
        for line, row in rows:
            amount = parse_money(row["line_total"])
            if amount is None:
                input_unparseable += 1
            else:
                input_total += amount
            order, errors = validate(row)
            if row["_structure_error"]:
                errors.append(row["_structure_error"])
            # The first source occurrence reserves the ID, even when it fails validation.
            if row["record_id"] in seen:
                errors.append("duplicate_id_in_file")
            seen.add(row["record_id"])
            status = "inserted"
            if not errors:
                assert order is not None
                existing = connection.execute("SELECT customer, order_date, quantity, unit_price_cents, line_total_cents FROM orders WHERE record_id = ?", (order.record_id,)).fetchone()
                if existing is not None:
                    if existing == order.values():
                        status = "already_loaded"
                    else:
                        errors.append("existing_id_has_conflicting_values_no_overwrite")
                else:
                    connection.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", (order.record_id, *order.values()))
                    new_total += order.line_total_cents
            if errors:
                rejected.append({**row, "source_line": line, "reasons": "; ".join(errors)})
                if amount is None:
                    rejected_unparseable += 1
                else:
                    rejected_total += amount
            else:
                assert order is not None
                accepted.append({**order.csv_values(), "source_line": line, "status": status})
        after_count, after_total = connection.execute("SELECT COUNT(*), COALESCE(SUM(line_total_cents), 0) FROM orders").fetchone()
        accepted_total = sum(parse_money(str(row["line_total"])) or 0 for row in accepted)
        inserted = sum(row["status"] == "inserted" for row in accepted)
        reconciliation = {
            "rows_balance": len(rows) == len(accepted) + len(rejected),
            "parseable_amounts_balance": input_total == accepted_total + rejected_total,
            "unparseable_amounts_all_rejected": input_unparseable == rejected_unparseable,
            "database_row_growth_matches_inserts": after_count == before_count + inserted,
            "database_total_growth_matches_inserts": after_total == before_total + new_total,
        }
        if not all(reconciliation.values()):
            raise RuntimeError("Reconciliation failed; database transaction rolled back")
    summary = {
        "notice": NOTICE,
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source.name,
        "database": database.name,
        "money_note": "Amounts use one unspecified demo currency and integer cents; no FX conversion or tax calculation.",
        "input_rows": len(rows), "accepted_rows": len(accepted), "rejected_rows": len(rejected),
        "inserted_rows": inserted, "already_loaded_rows": len(accepted) - inserted,
        "source_parseable_total": money(input_total), "source_unparseable_total_rows": input_unparseable,
        "accepted_total": money(accepted_total), "rejected_parseable_total": money(rejected_total),
        "inserted_total": money(new_total), "database_rows_before": before_count,
        "database_rows_after": after_count, "database_total_before": money(before_total),
        "database_total_after": money(after_total), "reconciliation": reconciliation,
        "all_checks_passed": all(reconciliation.values()),
    }
    write_csv(output_dir / "accepted.csv", FIELDS + ["source_line", "status"], accepted)
    write_csv(output_dir / "rejected.csv", FIELDS + ["source_line", "reasons"], rejected)
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_dir / "report.html").write_text(render_report(summary, accepted, rejected), encoding="utf-8")
    return summary


def render_report(summary: dict[str, Any], accepted: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    def table(fields: list[str], entries: list[dict[str, Any]]) -> str:
        heading = "".join(f"<th>{esc(key.replace('_', ' '))}</th>" for key in fields)
        body = "".join("<tr>" + "".join(f"<td>{esc(row[key])}</td>" for key in fields) + "</tr>" for row in entries)
        return f"<div class='scroll'><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>" if entries else "<p>No rows.</p>"

    cards = "".join(f"<div class='card'><span>{label}</span><strong>{esc(summary[key])}</strong></div>" for label, key in [
        ("Source rows", "input_rows"), ("Accepted", "accepted_rows"), ("Rejected", "rejected_rows"),
        ("New inserts", "inserted_rows"), ("Already loaded", "already_loaded_rows")])
    checks = "".join(f"<li><b>{'PASS' if passed else 'FAIL'}</b> {esc(name.replace('_', ' '))}</li>" for name, passed in summary["reconciliation"].items())
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SQL Import Validation | Synthetic Demo</title><style>
body{{margin:0;background:#f3f6fa;color:#183247;font:16px/1.6 system-ui,sans-serif}} main{{max-width:1100px;margin:auto;padding:32px 20px 64px}}
h1{{font-size:36px;line-height:1.2;letter-spacing:-1px}} h2{{margin-top:32px}} .eyebrow{{color:#0b736e;font-weight:700;letter-spacing:2px;font-size:12px}}
.notice{{padding:14px 18px;border-left:4px solid #0b736e;background:#e1f1ef}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}}
.card{{background:white;padding:18px;border:1px solid #d6e2eb;border-radius:8px}} .card span{{display:block;font-size:13px;color:#4f687c}} .card strong{{font-size:30px}}
.scroll{{overflow:auto;background:white;border:1px solid #d6e2eb;border-radius:8px}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:12px;text-align:left;border-bottom:1px solid #e2eaf0;vertical-align:top}} th{{background:#eaf0f5;text-transform:capitalize}} li b{{color:#0b736e}} code{{overflow-wrap:anywhere}} .small{{font-size:13px;color:#4f687c}}
@media print{{body{{background:white}} main{{padding:0}} .scroll{{overflow:visible}} h2{{break-after:avoid}}}}
</style><main><div class="eyebrow">DATA OPERATIONS / PORTFOLIO DEMO</div><h1>Import once. Validate every row.</h1>
<p class="notice">{esc(NOTICE)}</p><p>A local, zero-dependency CSV → validation → SQLite workflow. SQLite keeps this demonstration runnable without SQL Server installation; this is not a SQL Server connector or deployment.</p>
<div class="cards">{cards}</div><h2>Reconciliation</h2>
<p>Parseable source total <b>{esc(summary['source_parseable_total'])}</b> = accepted <b>{esc(summary['accepted_total'])}</b> + rejected parseable total <b>{esc(summary['rejected_parseable_total'])}</b>. Invalid monetary values, when present, are counted separately rather than treated as zero.</p>
<p>Database: {esc(summary['database_rows_before'])} → <b>{esc(summary['database_rows_after'])} rows</b>; total {esc(summary['database_total_before'])} → <b>{esc(summary['database_total_after'])}</b>. Only new inserts change these totals.</p><ul>{checks}</ul>
<h2>Accepted records</h2>{table(['record_id','customer','order_date','quantity','line_total','status'], accepted)}
<h2>Rejected records and reasons</h2>{table(['source_line','record_id','line_total','reasons'], rejected)}
<h2>What this demonstrates</h2><p>Field validation, duplicate handling, exact monetary arithmetic, explicit rejection reasons, parameterized inserts, a transaction, rerun safety and control-total reconciliation. Existing IDs with changed values are rejected; existing records are never overwritten.</p>
<p class="small">Generated {esc(summary['run_utc'])}. {esc(summary['money_note'])} No production performance, business savings or client outcomes are claimed.</p></main></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="CSV matching the documented header; omit to regenerate the synthetic sample")
    parser.add_argument("--database", type=Path, default=BASE / "results" / "orders.sqlite3")
    parser.add_argument("--output", type=Path, default=BASE / "results")
    args = parser.parse_args()
    source = args.input if args.input is not None else create_demo_csv(BASE / "data" / "sample_orders.csv")
    try:
        summary = run_import(source, args.database, args.output)
    except (OSError, ValueError, csv.Error, sqlite3.Error, RuntimeError) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    print(json.dumps(summary, indent=2))
    print(f"\nOpen report: {(args.output / 'report.html').resolve()}")


if __name__ == "__main__":
    main()
