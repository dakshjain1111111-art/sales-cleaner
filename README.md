# Sales Cleaner

![tests](https://github.com/dakshjain1111111-art/sales-cleaner/actions/workflows/tests.yml/badge.svg)

A small command-line tool that automates a repetitive data-processing job: it takes messy weekly
sales exports (CSV or Excel), cleans and validates every row, converts all amounts to one currency
using an exchange-rate API, and writes tidy output files plus a summary report.

**What you get from one run**

| File | Contents |
|---|---|
| `clean_<date>.csv` | Valid rows, normalised, with the converted amount |
| `rejects_<date>.csv` | Rows that failed validation, each with a `reject_reason` and its original file and row number |
| `summary_<date>.xlsx` | Overview, totals by store, totals by month, and a count of reject reasons |
| `sales_cleaner.log` | Log of the run |

## Install

Requires Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Try it in one minute (no internet needed)

```bash
sales-cleaner run --input sample_data --output output --config sample_data/config.offline.yaml
```

The sample files contain 18 rows with 10 kinds of problems. Expected result:

```
Run summary: files=2 rows_in=18 clean=8 rejected=8 duplicates_removed=2
```

Open `output/clean_<date>.csv` and `output/rejects_<date>.csv` to see what happened to each row.

## Usage

```bash
sales-cleaner run --input input/ --output output/ [options]
```

| Option | Meaning |
|---|---|
| `--config FILE` | YAML settings file (see `config.example.yaml`) |
| `--target-currency USD` | Convert all amounts to this currency (overrides the config) |
| `--dry-run` | Process everything and print the summary, but write no files |
| `-v`, `--verbose` | Debug logging |

With no `--config`, the tool uses the live [Frankfurter](https://frankfurter.dev) API
(free, no key) for exchange rates. Use `provider: fixed` in the config for offline rates.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Bad config, missing input folder, or no input files |
| 2 | At least one input file could not be processed (the others still are) |
| 3 | Exchange-rate service unavailable after retries (no output files written) |

## What gets cleaned and checked

**Cleaning**
- Header names are normalised (`Order ID`, `order_id`, `OrderID` all work) and aliased (`Qty` becomes `quantity`, `Price` becomes `amount`). Add your own aliases in the config.
- Text is trimmed and inner spaces collapsed; store names are title-cased.
- Dates in many formats become `YYYY-MM-DD`. Ambiguous `03/04/2026` follows the `dayfirst` setting.
- Amounts such as `$1,200.00`, `€ 90.50` and `(15.00)` become numbers. A currency symbol fills in a blank currency. Ambiguous text such as `90,50` is rejected, never guessed.
- Rows that are identical after cleaning are dropped, including across files.

**Validation** (a row can fail several rules; all reasons are listed)
- required values present: order id, date, store, quantity, amount, currency
- amount greater than zero, quantity at least 1
- currency in the allowed list
- date not in the future

**Currency conversion**
- One API call per currency per run, cached for the day (on disk too).
- Timeouts, HTTP 429 and 5xx responses are retried with exponential backoff.
- A currency the API does not know sends its rows to the rejects file.

Every input row ends up in exactly one place, and the run checks this: `rows_in = duplicates_removed + clean + rejected`.

## Project layout

```
src/sales_cleaner/
  cli.py          command-line entry point, logging, exit codes
  config.py       settings, defaults and validation
  loaders.py      read CSV / Excel as text, add source file and row
  cleaning.py     header, text, date, amount and currency cleaning
  validation.py   rules that split rows into valid and rejected
  rates.py        exchange-rate API client (retries, cache) and offline provider
  reports.py      summary workbook
  pipeline.py     ties the steps together
tests/            85 tests, one file per module plus end-to-end runs
sample_data/      deliberately messy example files and an offline config
```

## Tests

```bash
pytest -q
```

The suite needs no internet: the API client is tested against a fake HTTP session, covering
success, caching, retries with backoff, timeouts, unknown currencies and malformed responses.
End-to-end tests run the pipeline on `sample_data/` and check the counts, the rejection reasons,
re-run safety, dry-run behaviour and failed-file handling.

## Design notes and known limits

- Rates are the latest available rates, not the rate for each sale date. Using historical rates is a natural next step.
- European number formats (`1.200,50`) are rejected on purpose rather than guessed.
- `source_row` is the row number in the file with the header as row 1.
- The Frankfurter v1 API is described by its maintainers as superseded by v2 but still working; the base URL is configurable if you move to a newer version.
- Output file names use the run date, so running twice on the same day replaces that day's files.

## Adapting it to your data

The three places to change are the alias table and required columns in the config (your column names), the rules in `validation.py` (your business rules), and `CLEAN_COLUMNS` in `pipeline.py` (your output layout).
