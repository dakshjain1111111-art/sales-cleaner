import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sales_cleaner import cli
from sales_cleaner.rates import RateServiceError
from tests.helpers import SAMPLE_DIR, write_csv

OFFLINE_CONFIG = SAMPLE_DIR / "config.offline.yaml"


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input = self.root / "input"
        self.output = self.root / "output"
        self.input.mkdir()

    def run_cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["run", "--input", str(self.input), "--output", str(self.output), *args])
        return code, err.getvalue()

    def add_sample(self):
        for name in ("store_north.csv", "store_south.xlsx"):
            shutil.copy(SAMPLE_DIR / name, self.input / name)

    def test_success_exit_code_and_summary(self):
        self.add_sample()
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("rows_in=18 clean=8 rejected=8 duplicates_removed=2", log)
        self.assertEqual(len(list(self.output.glob("clean_*.csv"))), 1)

    def test_log_file_is_written(self):
        self.add_sample()
        self.run_cli("--config", str(OFFLINE_CONFIG))
        self.assertIn("Run summary", (self.output / "sales_cleaner.log").read_text())

    def test_dry_run_creates_nothing(self):
        self.add_sample()
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG), "--dry-run")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertFalse(self.output.exists())
        self.assertIn("(dry run)", log)

    def test_target_currency_option(self):
        write_csv(self.input / "a.csv", "A-1,2026-09-01,North,Pen,1,10,USD\n")
        config = self.root / "eur.yaml"
        config.write_text("rates:\n  provider: fixed\n  fixed:\n    USD/EUR: 0.90\n")
        code, _ = self.run_cli("--config", str(config), "--target-currency", "eur")
        self.assertEqual(code, cli.EXIT_OK)
        text = next(self.output.glob("clean_*.csv")).read_text()
        self.assertIn("9.0,EUR", text)  # 10 USD x 0.90

    def test_missing_input_folder(self):
        shutil.rmtree(self.input)
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG))
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("input folder not found", log)

    def test_empty_input_folder(self):
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG))
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("no .csv or .xlsx files", log)

    def test_bad_config(self):
        bad = self.root / "bad.yaml"
        bad.write_text("nonsense_key: 1\n")
        code, log = self.run_cli("--config", str(bad))
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("configuration error", log)

    def test_bad_target_currency_option(self):
        self.add_sample()
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG), "--target-currency", "dollars")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("3-letter", log)

    def test_failed_file_gives_nonzero_exit_but_other_files_are_processed(self):
        write_csv(self.input / "good.csv", "A-1,2026-09-01,North,Pen,1,10,USD\n")
        (self.input / "bad.csv").write_text("order_id,date\nB-1,2026-09-01\n")
        code, log = self.run_cli("--config", str(OFFLINE_CONFIG))
        self.assertEqual(code, cli.EXIT_FILE_FAILED)
        self.assertIn("FAILED bad.csv: missing required columns", log)
        self.assertNotIn("Traceback", log)
        self.assertEqual(len(list(self.output.glob("clean_*.csv"))), 1)

    def test_rate_service_outage(self):
        write_csv(self.input / "a.csv", "A-1,2026-09-01,North,Pen,1,10,EUR\n")
        broken = mock.Mock()
        broken.get_rate.side_effect = RateServiceError("rate service unavailable after 4 attempts")
        with mock.patch.object(cli, "build_rate_provider", return_value=broken):
            code, log = self.run_cli()
        self.assertEqual(code, cli.EXIT_RATE_SERVICE)
        self.assertIn("exchange-rate service problem", log)
        self.assertEqual(list(self.output.glob("clean_*.csv")), [])

    def test_version_flag(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
