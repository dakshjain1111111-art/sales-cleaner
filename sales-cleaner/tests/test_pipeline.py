import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from sales_cleaner.pipeline import run_pipeline
from sales_cleaner.rates import FixedRateProvider
from tests.helpers import SAMPLE_DIR, make_cfg, write_csv

TODAY = date(2026, 10, 10)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input = self.root / "input"
        self.output = self.root / "output"
        self.input.mkdir()
        self.cfg = make_cfg()
        self.provider = FixedRateProvider(self.cfg.rates.fixed)

    def run_it(self, **kw):
        return run_pipeline(self.input, self.output, self.cfg, self.provider, today=TODAY, **kw)

    def use_sample_data(self):
        for name in ("store_north.csv", "store_south.xlsx"):
            shutil.copy(SAMPLE_DIR / name, self.input / name)

    def test_sample_data_counts_add_up(self):
        self.use_sample_data()
        result = self.run_it()
        self.assertEqual(result.rows_in, 18)
        self.assertEqual(result.duplicates_removed, 2)
        self.assertEqual(result.rows_clean, 8)
        self.assertEqual(result.rows_rejected, 8)
        self.assertTrue(result.balanced)
        self.assertEqual(result.failed_files, {})

    def test_sample_data_outputs(self):
        self.use_sample_data()
        result = self.run_it()
        names = sorted(p.name for p in result.output_files)
        self.assertEqual(names, ["clean_2026-10-10.csv", "rejects_2026-10-10.csv",
                                 "summary_2026-10-10.xlsx"])

        clean = pd.read_csv(self.output / "clean_2026-10-10.csv").set_index("order_id")
        self.assertEqual(clean.loc["S-2001", "amount_converted"], 110.0)  # 100 EUR x 1.10
        self.assertEqual(clean.loc["N-1002", "amount"], 1200.0)           # "$1,200.00"
        self.assertEqual(clean.loc["N-1010", "currency"], "EUR")          # inferred from the symbol
        self.assertEqual(clean.loc["N-1003", "store"], "North Store")

        rejects = pd.read_csv(self.output / "rejects_2026-10-10.csv", keep_default_na=False)
        reasons = set(rejects["reject_reason"])
        for expected in ["missing amount", "amount must be greater than zero",
                         "date is in the future", "invalid date 'not a date'",
                         "currency 'XXX' is not allowed", "missing order_id",
                         "invalid quantity 'one'", "quantity must be at least 1"]:
            self.assertIn(expected, reasons)
        self.assertEqual(set(rejects["source_file"]), {"store_north.csv", "store_south.xlsx"})

    def test_summary_workbook_matches_the_csv(self):
        self.use_sample_data()
        self.run_it()
        clean = pd.read_csv(self.output / "clean_2026-10-10.csv")
        overview = pd.read_excel(self.output / "summary_2026-10-10.xlsx", sheet_name="Overview")
        values = dict(zip(overview["metric"], overview["value"]))
        self.assertEqual(values["Rows clean"], len(clean))
        self.assertAlmostEqual(values["Total sales (USD)"], clean["amount_converted"].sum(), 2)

    def test_running_twice_gives_identical_output(self):
        self.use_sample_data()
        self.run_it()
        first = (self.output / "clean_2026-10-10.csv").read_bytes()
        first_rejects = (self.output / "rejects_2026-10-10.csv").read_bytes()
        self.run_it()
        self.assertEqual((self.output / "clean_2026-10-10.csv").read_bytes(), first)
        self.assertEqual((self.output / "rejects_2026-10-10.csv").read_bytes(), first_rejects)
        self.assertEqual(len(list(self.output.glob("clean_*.csv"))), 1)

    def test_dry_run_writes_nothing_but_reports_counts(self):
        self.use_sample_data()
        result = self.run_it(dry_run=True)
        self.assertFalse(self.output.exists())
        self.assertEqual(result.output_files, [])
        self.assertEqual(result.rows_clean, 8)

    def test_duplicates_across_files_are_removed(self):
        row = "A-1,2026-09-01,North,Pen,1,10,USD\n"
        write_csv(self.input / "a.csv", row)
        write_csv(self.input / "b.csv", row)
        result = self.run_it()
        self.assertEqual((result.rows_in, result.duplicates_removed, result.rows_clean), (2, 1, 1))

    def test_missing_column_fails_that_file_only(self):
        write_csv(self.input / "good.csv", "A-1,2026-09-01,North,Pen,1,10,USD\n")
        (self.input / "bad.csv").write_text("order_id,date\nB-1,2026-09-01\n")
        result = self.run_it()
        self.assertEqual(result.files_processed, ["good.csv"])
        self.assertIn("missing required columns", result.failed_files["bad.csv"])
        self.assertEqual(result.rows_clean, 1)
        self.assertTrue(result.balanced)

    def test_corrupt_file_is_reported(self):
        write_csv(self.input / "good.csv", "A-1,2026-09-01,North,Pen,1,10,USD\n")
        (self.input / "broken.xlsx").write_bytes(b"garbage")
        result = self.run_it()
        self.assertIn("cannot read broken.xlsx", result.failed_files["broken.xlsx"])
        self.assertEqual(result.rows_clean, 1)

    def test_all_files_failing_writes_nothing(self):
        (self.input / "bad.csv").write_text("foo,bar\n1,2\n")
        result = self.run_it()
        self.assertEqual(result.rows_in, 0)
        self.assertEqual(result.output_files, [])
        self.assertFalse(self.output.exists())

    def test_header_variants_are_understood(self):
        (self.input / "odd.csv").write_text(
            "Order No, Order Date ,Shop,Item,Qty,Price,CCY\nA-1,03.09.2026,x,Pen,1,5,gbp\n")
        result = self.run_it()
        self.assertEqual(result.rows_clean, 1)
        clean = pd.read_csv(self.output / "clean_2026-10-10.csv")
        self.assertEqual(clean.loc[0, "amount_converted"], 6.25)

    def test_unknown_rate_currency_is_rejected_and_counted(self):
        self.cfg.allowed_currencies.append("CHF")  # allowed, but no fixed rate for it
        write_csv(self.input / "a.csv", "A-1,2026-09-01,North,Pen,1,10,CHF\n")
        result = self.run_it()
        self.assertEqual((result.rows_clean, result.rows_rejected), (0, 1))
        rejects = pd.read_csv(self.output / "rejects_2026-10-10.csv")
        self.assertEqual(rejects.loc[0, "reject_reason"], "no exchange rate for CHF")
        self.assertTrue(result.balanced)


if __name__ == "__main__":
    unittest.main()
