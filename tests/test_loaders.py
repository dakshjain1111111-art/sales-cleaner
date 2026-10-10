import tempfile
import unittest
from pathlib import Path

from sales_cleaner.loaders import LoadError, NoInputError, find_input_files, load_file
from tests.helpers import write_csv


class LoaderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_find_input_files_filters_and_sorts(self):
        write_csv(self.dir / "b.csv", "")
        write_csv(self.dir / "a.csv", "")
        (self.dir / "notes.txt").write_text("x")
        (self.dir / "~$lock.xlsx").write_text("x")
        (self.dir / ".hidden.csv").write_text("x")
        names = [p.name for p in find_input_files(self.dir)]
        self.assertEqual(names, ["a.csv", "b.csv"])

    def test_missing_folder(self):
        with self.assertRaisesRegex(NoInputError, "not found"):
            find_input_files(self.dir / "missing")

    def test_folder_without_supported_files(self):
        (self.dir / "notes.txt").write_text("x")
        with self.assertRaisesRegex(NoInputError, "no .csv or .xlsx"):
            find_input_files(self.dir)

    def test_load_csv_adds_source_columns_and_keeps_text(self):
        path = write_csv(self.dir / "a.csv", "A-1,2026-01-01,Shop,Pen,1,001.50,USD\n")
        df = load_file(path)
        self.assertEqual(df.loc[0, "amount"], "001.50")  # not converted to a number
        self.assertEqual(df.loc[0, "source_file"], "a.csv")
        self.assertEqual(df.loc[0, "source_row"], 2)

    def test_csv_with_bom(self):
        path = self.dir / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbforder_id,amount\nA-1,5\n")
        self.assertIn("order_id", load_file(path).columns)

    def test_empty_csv_is_a_load_error(self):
        path = self.dir / "empty.csv"
        path.write_text("")
        with self.assertRaises(LoadError):
            load_file(path)

    def test_corrupt_excel_is_a_load_error(self):
        path = self.dir / "broken.xlsx"
        path.write_bytes(b"this is not a zip file")
        with self.assertRaisesRegex(LoadError, "cannot read broken.xlsx"):
            load_file(path)

    def test_load_excel_sample(self):
        from tests.helpers import SAMPLE_DIR

        df = load_file(SAMPLE_DIR / "store_south.xlsx")
        self.assertEqual(len(df), 6)
        self.assertEqual(df.loc[0, "date"], "2026-09-03 00:00:00")


if __name__ == "__main__":
    unittest.main()
