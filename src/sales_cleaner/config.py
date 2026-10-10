"""Configuration loading with defaults and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(ValueError):
    """Raised when the configuration file is missing, malformed or invalid."""


# Column header (normalised to lower_snake_case) -> canonical column name.
DEFAULT_ALIASES: dict[str, str] = {
    "orderid": "order_id",
    "order": "order_id",
    "order_number": "order_id",
    "order_no": "order_id",
    "order_date": "date",
    "sale_date": "date",
    "shop": "store",
    "branch": "store",
    "item": "product",
    "qty": "quantity",
    "units": "quantity",
    "price": "amount",
    "total": "amount",
    "ccy": "currency",
}

DEFAULT_ALLOWED_CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "CAD", "AUD"]
DEFAULT_REQUIRED_COLUMNS = ["order_id", "date", "store", "quantity", "amount"]


@dataclass
class RatesConfig:
    provider: str = "frankfurter"  # "frankfurter" (live API) or "fixed" (offline)
    base_url: str = "https://api.frankfurter.dev/v1"
    timeout: float = 10.0
    retries: int = 3
    backoff: float = 1.0
    # Only used by the "fixed" provider. Keys look like "EUR/USD" = USD per 1 EUR.
    fixed: dict[str, float] = field(default_factory=dict)


@dataclass
class Config:
    target_currency: str = "USD"
    allowed_currencies: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_CURRENCIES))
    required_columns: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_COLUMNS))
    dayfirst: bool = False  # how to read ambiguous dates such as 03/04/2026
    column_aliases: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ALIASES))
    rates: RatesConfig = field(default_factory=RatesConfig)


def load_config(path: str | Path | None = None) -> Config:
    """Load a YAML config file over the defaults. With no path, return the defaults."""
    cfg = Config()
    if path is None:
        return cfg

    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config file must contain a mapping of settings")

    data = dict(data)
    rates_data = data.pop("rates", {}) or {}
    unknown = set(data) - {
        "target_currency",
        "allowed_currencies",
        "required_columns",
        "dayfirst",
        "column_aliases",
    }
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")

    if "target_currency" in data:
        cfg.target_currency = str(data["target_currency"])
    if "allowed_currencies" in data:
        cfg.allowed_currencies = [str(c) for c in data["allowed_currencies"]]
    if "required_columns" in data:
        cfg.required_columns = [str(c) for c in data["required_columns"]]
    if "dayfirst" in data:
        cfg.dayfirst = bool(data["dayfirst"])
    if "column_aliases" in data:
        cfg.column_aliases.update({str(k).lower(): str(v) for k, v in data["column_aliases"].items()})

    if not isinstance(rates_data, dict):
        raise ConfigError("'rates' must be a mapping")
    unknown_rates = set(rates_data) - {"provider", "base_url", "timeout", "retries", "backoff", "fixed"}
    if unknown_rates:
        raise ConfigError(f"unknown rates keys: {sorted(unknown_rates)}")
    for key, value in rates_data.items():
        setattr(cfg.rates, key, value)

    validate_config(cfg)
    return cfg


def validate_config(cfg: Config) -> None:
    """Normalise and sanity-check a config. Raises ConfigError on problems."""
    cfg.target_currency = cfg.target_currency.strip().upper()
    cfg.allowed_currencies = [c.strip().upper() for c in cfg.allowed_currencies]
    if len(cfg.target_currency) != 3 or not cfg.target_currency.isalpha():
        raise ConfigError(f"target_currency must be a 3-letter code, got {cfg.target_currency!r}")
    if cfg.target_currency not in cfg.allowed_currencies:
        cfg.allowed_currencies.append(cfg.target_currency)
    if cfg.rates.provider not in {"frankfurter", "fixed"}:
        raise ConfigError("rates.provider must be 'frankfurter' or 'fixed'")
    if int(cfg.rates.retries) < 0:
        raise ConfigError("rates.retries cannot be negative")
    if float(cfg.rates.timeout) <= 0:
        raise ConfigError("rates.timeout must be positive")
