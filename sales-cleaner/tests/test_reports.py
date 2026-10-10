import tempfile
import unittest
from pathlib import Path

import pandas as pd

from sales_cleaner.reports import Stats, build_sheets, summarize_rejects, write_summary_xlsx

STATS = Stats("2026-10-10", "USD", 2, 6, 1, 3, 2)


def clean_frame():
    return pd.DataFrame({
        "order_id": ["A", "B", "C"],
        "date": ["2026-09-01", "2026-09-15", "2026-10-02"],
        "store": ["North", "North", "South"],
        "quantity": [1, 2, 3],
        "amount_converted": [10.0, 20.5, 30.0],
    })


class ReportTests(unittest.TestCase):
    def test_overview_and_totals(self):
        sheets = build_sheets(clean_frame(), pd.DataFrame(columns=["reject_reason"]), STATS)
        overview = dict(zip(sheets["Overview"]["metric"], sheets["Overview"]["value"]))
        self.assertEqual(overview["Rows in"], 6)
        self.assertEqual(overview["Total sales (USD)"], 60.5)

    def test_by_store_and_month(self):
        sheets = build_sheets(clean_frame(), pd.DataFrame(columns=["reject_reason"]), STATS)
        store = sheets["By Store"].set_index("store")
        self.assertEqual(store.loc["North", "total_USD"], 30.5)
        self.assertEqual(store.loc["North", "units"], 3)
        month = sheets["By Month"].set_index("month")
        self.assertEqual(month.loc["2026-09", "orders"], 2)
        self.assertEqual(month.loc["2026-10", "total_USD"], 30.0)

    def test_reject_reasons_group_similar_text(self):
        rejected = pd.DataFrame({"reject_reason": [
            "invalid date 'x'", "invalid date 'y'; missing store", "missing store"]})
        counts = summarize_rejects(rejected).set_index("reason")["rows"].to_dict()
        self.assertEqual(counts, {"invalid date '...'": 2, "missing store": 2})

    def test_empty_results_do_not_break_the_report(self):
        empty = pd.DataFrame(columns=["order_id", "date", "store", "quantity", "amount_converted"])
        sheets = build_sheets(empty, pd.DataFrame(columns=["reject_reason"]), STATS)
        self.assertEqual(len(sheets["By Store"]), 0)

    def test_workbook_is_readable(self):
        sheets = build_sheets(clean_frame(), pd.DataFrame({"reject_reason": ["x"]}), STATS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.xlsx"
            write_summary_xlsx(path, sheets)
            loaded = pd.read_excel(path, sheet_name=None)
        self.assertEqual(list(loaded), ["Overview", "By Store", "By Month", "Reject Reasons"])


if __name__ == "__main__":
    unittest.main()
