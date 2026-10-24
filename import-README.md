# Repeatable import — synthetic demonstration

The saved executed report is `import-report.html`. Its CSV and JSON outputs are `import-accepted.csv`, `import-rejected.csv` and `import-run-summary.json`. The input fixture is `import-sample-orders.csv`.

Recorded outcome: 12 input rows, five accepted and seven rejected. Parseable source total 1492.21 equals 1357.35 accepted plus 134.86 rejected. All five reconciliation checks pass. Seven automated tests pass.

## Run locally

Requires Python 3.10 or later with standard SQLite support. No third-party packages or internet connection are required. Keep `main.py` and `test_main.py` in the same folder.

```sh
python main.py
python -m unittest -v
```

The default run regenerates the fixed synthetic fixture inside `data/` and creates its database and new exports inside `results/`. Open `results/report.html` to inspect a new run. These runtime folders are created by the program; the supplied website deployment remains flat. An identical rerun inserts no duplicate orders.

To run the supplied flat input fixture explicitly:

```sh
python main.py --input import-sample-orders.csv
```

## Validation rules

The exact CSV header is `record_id,customer,order_date,quantity,unit_price,line_total`. IDs follow ORD-0000. Customers must be present, dates must be valid, quantities must be positive integers within the documented limit, and amounts use at most two decimal places. Each line total must equal quantity times unit price. Amounts are stored as integer cents.

The first source occurrence reserves an ID, even if rejected. Existing identical records are accepted as already loaded; changed values under an existing ID are rejected without overwriting the database.

This small-file workflow uses SQLite and is not a live SQL Server connector or production migration. Client work requires agreed keys, mappings, volumes, security and acceptance rules. All data is synthetic; amounts use one unspecified demonstration currency.
