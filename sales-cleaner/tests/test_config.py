import tempfile
import unittest
from pathlib import Path

from sales_cleaner.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text: str) -> Path:
        path = self.dir / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_when_no_path(self):
        cfg = load_config(None)
        self.assertEqual(cfg.target_currency, "USD")
        self.assertFalse(cfg.dayfirst)
        self.assertEqual(cfg.rates.provider, "frankfurter")

    def test_file_overrides_defaults(self):
        cfg = load_config(self.write("target_currency: eur\ndayfirst: true\n"))
        self.assertEqual(cfg.target_currency, "EUR")
        self.assertTrue(cfg.dayfirst)
        self.assertIn("EUR", cfg.allowed_currencies)

    def test_target_currency_is_always_allowed(self):
        cfg = load_config(self.write("target_currency: CHF\nallowed_currencies: [USD]\n"))
        self.assertIn("CHF", cfg.allowed_currencies)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(self.dir / "nope.yaml")

    def test_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "unknown config keys"):
            load_config(self.write("target_curency: USD\n"))

    def test_invalid_yaml(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("target_currency: [unclosed\n"))

    def test_bad_provider(self):
        with self.assertRaisesRegex(ConfigError, "provider"):
            load_config(self.write("rates:\n  provider: magic\n"))

    def test_bad_target_currency(self):
        with self.assertRaisesRegex(ConfigError, "3-letter"):
            load_config(self.write("target_currency: DOLLARS\n"))

    def test_custom_alias_is_added(self):
        cfg = load_config(self.write("column_aliases:\n  customer_branch: store\n"))
        self.assertEqual(cfg.column_aliases["customer_branch"], "store")
        self.assertEqual(cfg.column_aliases["qty"], "quantity")  # defaults kept


if __name__ == "__main__":
    unittest.main()
