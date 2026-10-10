"""Exchange-rate providers (live API with retries and caching, or fixed offline rates)."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from sales_cleaner.config import RatesConfig

log = logging.getLogger("sales_cleaner")


class UnknownCurrencyError(Exception):
    """The provider has no rate for this currency pair."""


class RateServiceError(Exception):
    """The rate service could not be reached or returned unusable data."""


class RateClient:
    """Fetch rates from a Frankfurter-compatible API.

    * retries timeouts, connection errors, HTTP 429 and 5xx with exponential backoff
    * treats HTTP 400/404/422 as "unknown currency" (no retry)
    * caches each pair for the day, in memory and optionally on disk
    """

    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        retries: int = 3,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        cache_dir: Path | None = None,
        today: date | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self._today = today or date.today()
        self._cache_file = (
            Path(cache_dir) / f"rates_{self._today.isoformat()}.json" if cache_dir else None
        )
        self._cache: dict[str, float] = self._load_cache()

    def _load_cache(self) -> dict[str, float]:
        if self._cache_file and self._cache_file.is_file():
            try:
                return {k: float(v) for k, v in json.loads(self._cache_file.read_text()).items()}
            except (ValueError, OSError):
                log.warning("ignoring unreadable rate cache %s", self._cache_file)
        return {}

    def _save_cache(self) -> None:
        if self._cache_file:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._cache, indent=2))

    def get_rate(self, base: str, target: str) -> float:
        """Return how many ``target`` units one ``base`` unit is worth."""
        if base == target:
            return 1.0
        key = f"{base}/{target}"
        if key not in self._cache:
            self._cache[key] = self._fetch(base, target)
            self._save_cache()
        return self._cache[key]

    def _fetch(self, base: str, target: str) -> float:
        url = f"{self.base_url}/latest"
        params = {"base": base, "symbols": target}
        last_problem = "unknown error"

        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                status = resp.status_code
                if status == 200:
                    return self._parse(resp, base, target)
                if status in (400, 404, 422):
                    raise UnknownCurrencyError(f"no exchange rate for {base}->{target}")
                last_problem = f"HTTP {status}"
                if status != 429 and status < 500:
                    raise RateServiceError(f"rate service returned {last_problem}")

            if attempt < self.retries:
                delay = self.backoff * (2**attempt)
                log.warning(
                    "rate request %s->%s failed (%s); retry %d/%d in %.1fs",
                    base, target, last_problem, attempt + 1, self.retries, delay,
                )
                self._sleep(delay)

        raise RateServiceError(
            f"rate service unavailable after {self.retries + 1} attempts ({last_problem})"
        )

    @staticmethod
    def _parse(resp: requests.Response, base: str, target: str) -> float:
        try:
            rates = resp.json()["rates"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RateServiceError("rate service returned an unexpected response") from exc
        if target not in rates:
            raise UnknownCurrencyError(f"no exchange rate for {base}->{target}")
        try:
            return float(rates[target])
        except (TypeError, ValueError) as exc:
            raise RateServiceError("rate service returned a non-numeric rate") from exc


class FixedRateProvider:
    """Offline provider driven by config, e.g. {'EUR/USD': 1.08}."""

    def __init__(self, rates: dict[str, float]):
        self.rates = {k.upper(): float(v) for k, v in rates.items()}

    def get_rate(self, base: str, target: str) -> float:
        if base == target:
            return 1.0
        try:
            return self.rates[f"{base}/{target}"]
        except KeyError:
            raise UnknownCurrencyError(f"no fixed rate for {base}->{target}") from None


def build_rate_provider(
    cfg: RatesConfig, cache_dir: Path | None = None, today: date | None = None
) -> RateClient | FixedRateProvider:
    """Create the provider named in the config."""
    if cfg.provider == "fixed":
        return FixedRateProvider(cfg.fixed)
    return RateClient(
        base_url=cfg.base_url,
        timeout=float(cfg.timeout),
        retries=int(cfg.retries),
        backoff=float(cfg.backoff),
        cache_dir=cache_dir,
        today=today,
    )


def add_converted_amounts(
    df: pd.DataFrame, provider: RateClient | FixedRateProvider, target: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add rate / amount_converted / target_currency to df.

    Rows whose currency has no rate are returned separately as rejects.
    A service outage raises RateServiceError and stops the run.
    """
    rates: dict[str, float] = {}
    unknown: set[str] = set()
    for currency in sorted(df["currency"].dropna().unique()):
        try:
            rates[currency] = provider.get_rate(currency, target)
        except UnknownCurrencyError:
            unknown.add(currency)

    no_rate = df["currency"].isin(unknown)
    rejected = df[no_rate].copy()
    rejected["reject_reason"] = rejected["currency"].map(lambda c: f"no exchange rate for {c}")

    converted = df[~no_rate].copy()
    converted["rate"] = converted["currency"].map(rates)
    converted["amount_converted"] = (converted["amount"] * converted["rate"]).round(2)
    converted["target_currency"] = target
    return converted.reset_index(drop=True), rejected.reset_index(drop=True)
