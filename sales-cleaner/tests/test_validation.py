import unittest
from datetime import date

import pandas as pd

from sales_cleaner.cleaning import clean_dataframe
from sales_cleaner.validation import validate
from tests.helpers import make_cfg

TODAY = date(2026, 10, 10)


def run(**overrides):
    row = {"order_id": "A-1", "date": "2026-09-01", "store": "North", "product": "Pen",
           "quantity": "1", "amount": "10", "currency": "USD",
           "source_file": "f.csv", "source_row": 2}
    row.update(overrides)
    cfg = make_cfg()
    return validate(clean_dataframe(pd.DataFrame([row]), cfg), cfg, TODAY)


class ValidationTests(unittest.TestCase):
    def reason(self, **overrides) -> str:
        valid, rejected = run(**overrides)
        self.assertEqual((len(valid), len(rejected)), (0, 1))
        return rejected.loc[0, "reject_reason"]

    def test_good_row_is_valid(self):
        valid, rejected = run()
        self.assertEqual((len(valid), len(rejected)), (1, 0))
        self.assertNotIn("issues", valid.columns)

    def test_missing_fields(self):
        for field in ["order_id", "date", "store", "amount"]:
            self.assertEqual(self.reason(**{field: ""}), f"missing {field}")

    def test_missing_currency_without_symbol(self):
        self.assertEqual(self.reason(currency=""), "missing currency")

    def test_non_positive_amount(self):
        self.assertEqual(self.reason(amount="0"), "amount must be greater than zero")
        self.assertEqual(self.reason(amount="-5"), "amount must be greater than zero")

    def test_quantity_below_one(self):
        self.assertEqual(self.reason(quantity="0"), "quantity must be at least 1")

    def test_unknown_currency(self):
        self.assertEqual(self.reason(currency="xxx"), "currency 'XXX' is not allowed")

    def test_future_date(self):
        self.assertEqual(self.reason(date="2026-10-11"), "date is in the future")

    def test_today_is_allowed(self):
        valid, _ = run(date="2026-10-10")
        self.assertEqual(len(valid), 1)

    def test_unparseable_value_reported_once(self):
        self.assertEqual(self.reason(date="nope"), "invalid date 'nope'")

    def test_multiple_reasons_are_all_listed(self):
        text = self.reason(amount="-1", currency="xxx", order_id="")
        self.assertIn("missing order_id", text)
        self.assertIn("amount must be greater than zero", text)
        self.assertIn("currency 'XXX' is not allowed", text)


if __name__ == "__main__":
    unittest.main()
