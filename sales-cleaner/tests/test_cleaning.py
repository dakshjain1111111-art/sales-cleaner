import unittest

import pandas as pd

from sales_cleaner.cleaning import (
    SchemaError,
    clean_dataframe,
    clean_row,
    drop_duplicates,
    normalize_column_name,
    normalize_columns,
    parse_amount,
    parse_date,
    parse_quantity,
)
from tests.helpers import make_cfg


class ColumnTests(unittest.TestCase):
    def test_names_are_normalised_and_aliased(self):
        aliases = make_cfg().column_aliases
        self.assertEqual(normalize_column_name(" Order ID ", aliases), "order_id")
        self.assertEqual(normalize_column_name("Qty", aliases), "quantity")
        self.assertEqual(normalize_column_name("PRICE", aliases), "amount")

    def test_missing_required_column(self):
        df = pd.DataFrame({"order_id": ["1"], "date": ["2026-01-01"]})
        with self.assertRaisesRegex(SchemaError, "missing required columns"):
            normalize_columns(df, make_cfg())

    def test_two_columns_mapping_to_same_field(self):
        df = pd.DataFrame(columns=["price", "amount"])
        with self.assertRaisesRegex(SchemaError, "same field"):
            normalize_columns(df, make_cfg())


class ParsingTests(unittest.TestCase):
    def test_amount_formats(self):
        self.assertEqual(parse_amount("$1,200.50"), (1200.5, "USD"))
        self.assertEqual(parse_amount("€ 90.50"), (90.5, "EUR"))
        self.assertEqual(parse_amount("(15.00)"), (-15.0, None))
        self.assertEqual(parse_amount("-20"), (-20.0, None))
        self.assertEqual(parse_amount("1000"), (1000.0, None))

    def test_amount_rejects_ambiguous_or_garbage_text(self):
        self.assertEqual(parse_amount("90,50")[0], None)  # could be 90.50 or 9050
        self.assertEqual(parse_amount("abc")[0], None)
        self.assertEqual(parse_amount("1.2.3")[0], None)
        self.assertEqual(parse_amount(""), (None, None))

    def test_quantity(self):
        self.assertEqual(parse_quantity("3"), 3)
        self.assertEqual(parse_quantity("3.0"), 3)
        self.assertIsNone(parse_quantity("2.5"))
        self.assertIsNone(parse_quantity("one"))
        self.assertIsNone(parse_quantity(""))

    def test_date_formats(self):
        self.assertEqual(parse_date("2026-09-01"), "2026-09-01")
        self.assertEqual(parse_date("2026-09-01 00:00:00"), "2026-09-01")
        self.assertEqual(parse_date("03-Sep-2026"), "2026-09-03")
        self.assertEqual(parse_date("Sep 3, 2026"), "2026-09-03")
        self.assertEqual(parse_date("03.09.2026"), "2026-09-03")

    def test_slash_dates_respect_dayfirst(self):
        self.assertEqual(parse_date("03/04/2026", dayfirst=False), "2026-03-04")
        self.assertEqual(parse_date("03/04/2026", dayfirst=True), "2026-04-03")

    def test_invalid_dates(self):
        self.assertIsNone(parse_date("not a date"))
        self.assertIsNone(parse_date("31/02/2026", dayfirst=True))
        self.assertIsNone(parse_date(""))


class CleanRowTests(unittest.TestCase):
    def row(self, **kw):
        base = {"order_id": " A-1 ", "date": "2026-09-01", "store": "  nORTH   store ",
                "product": " Wide   Widget ", "quantity": "2", "amount": "$1,200.00",
                "currency": "", "source_file": "f.csv", "source_row": 2}
        base.update(kw)
        return clean_row(base, make_cfg())

    def test_text_is_trimmed_and_store_title_cased(self):
        out = self.row()
        self.assertEqual(out["order_id"], "A-1")
        self.assertEqual(out["store"], "North Store")
        self.assertEqual(out["product"], "Wide Widget")

    def test_currency_inferred_from_symbol_when_blank(self):
        self.assertEqual(self.row()["currency"], "USD")

    def test_explicit_currency_wins_and_is_uppercased(self):
        self.assertEqual(self.row(currency="eur")["currency"], "EUR")

    def test_problems_are_recorded_not_raised(self):
        out = self.row(date="nope", quantity="x", amount="abc")
        self.assertIsNone(out["date"])
        self.assertEqual(len(out["issues"]), 3)
        self.assertTrue(out["issues"][0].startswith("invalid date"))


class DuplicateTests(unittest.TestCase):
    def frame(self, rows):
        cfg = make_cfg()
        df = pd.DataFrame(rows)
        return clean_dataframe(df, cfg)

    def base(self, **kw):
        row = {"order_id": "A-1", "date": "2026-09-01", "store": "North", "product": "Pen",
               "quantity": "1", "amount": "10", "currency": "USD",
               "source_file": "f.csv", "source_row": 2}
        row.update(kw)
        return row

    def test_identical_rows_after_cleaning_are_removed(self):
        df = self.frame([self.base(), self.base(store=" north ", amount="10.00", source_row=3)])
        kept, removed = drop_duplicates(df)
        self.assertEqual((len(kept), removed), (1, 1))

    def test_different_rows_are_kept(self):
        df = self.frame([self.base(), self.base(order_id="A-2", source_row=3)])
        kept, removed = drop_duplicates(df)
        self.assertEqual((len(kept), removed), (2, 0))

    def test_rows_with_different_problems_are_not_merged(self):
        df = self.frame([self.base(amount="abc"), self.base(amount="xyz", source_row=3)])
        kept, removed = drop_duplicates(df)
        self.assertEqual((len(kept), removed), (2, 0))


if __name__ == "__main__":
    unittest.main()
