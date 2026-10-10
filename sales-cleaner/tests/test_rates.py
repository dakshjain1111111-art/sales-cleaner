import tempfile
import unittest
from pathlib import Path

import pandas as pd
import requests

from sales_cleaner.rates import (
    FixedRateProvider,
    RateClient,
    RateServiceError,
    UnknownCurrencyError,
    add_converted_amounts,
)
from tests.helpers import FakeResponse, FakeSession, rate_response


def client(session, **kw) -> tuple[RateClient, list[float]]:
    sleeps: list[float] = []
    kw.setdefault("retries", 3)
    return RateClient("https://api.example/v1/", session=session, backoff=1.0,
                      sleep=sleeps.append, **kw), sleeps


class RateClientTests(unittest.TestCase):
    def test_success_builds_the_right_request(self):
        session = FakeSession([rate_response("USD", 1.08)])
        rc, _ = client(session)
        self.assertEqual(rc.get_rate("EUR", "USD"), 1.08)
        url, params, timeout = session.calls[0]
        self.assertEqual(url, "https://api.example/v1/latest")
        self.assertEqual(params, {"base": "EUR", "symbols": "USD"})
        self.assertEqual(timeout, 10.0)

    def test_same_currency_needs_no_request(self):
        session = FakeSession([])
        rc, _ = client(session)
        self.assertEqual(rc.get_rate("USD", "USD"), 1.0)
        self.assertEqual(session.calls, [])

    def test_pair_is_fetched_once_per_run(self):
        session = FakeSession([rate_response("USD", 1.08)])
        rc, _ = client(session)
        rc.get_rate("EUR", "USD")
        rc.get_rate("EUR", "USD")
        self.assertEqual(len(session.calls), 1)

    def test_retries_server_errors_with_backoff(self):
        session = FakeSession([FakeResponse(500), FakeResponse(503), rate_response("USD", 1.2)])
        rc, sleeps = client(session)
        self.assertEqual(rc.get_rate("EUR", "USD"), 1.2)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_retries_timeouts(self):
        session = FakeSession([requests.Timeout("slow"), rate_response("USD", 1.2)])
        rc, _ = client(session)
        self.assertEqual(rc.get_rate("EUR", "USD"), 1.2)

    def test_gives_up_after_retries(self):
        session = FakeSession([FakeResponse(500)] * 4)
        rc, _ = client(session, retries=3)
        with self.assertRaisesRegex(RateServiceError, "after 4 attempts"):
            rc.get_rate("EUR", "USD")
        self.assertEqual(len(session.calls), 4)

    def test_unknown_currency_is_not_retried(self):
        session = FakeSession([FakeResponse(404, {"message": "not found"})])
        rc, _ = client(session)
        with self.assertRaises(UnknownCurrencyError):
            rc.get_rate("XXX", "USD")
        self.assertEqual(len(session.calls), 1)

    def test_other_client_errors_fail_immediately(self):
        session = FakeSession([FakeResponse(403)])
        rc, _ = client(session)
        with self.assertRaisesRegex(RateServiceError, "HTTP 403"):
            rc.get_rate("EUR", "USD")
        self.assertEqual(len(session.calls), 1)

    def test_malformed_response(self):
        for bad in (FakeResponse(200, bad_json=True), FakeResponse(200, {"oops": 1})):
            rc, _ = client(FakeSession([bad]))
            with self.assertRaises(RateServiceError):
                rc.get_rate("EUR", "USD")

    def test_response_without_the_requested_rate(self):
        rc, _ = client(FakeSession([FakeResponse(200, {"rates": {}})]))
        with self.assertRaises(UnknownCurrencyError):
            rc.get_rate("EUR", "USD")

    def test_disk_cache_is_shared_between_runs_on_the_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = client(FakeSession([rate_response("USD", 1.5)]), cache_dir=Path(tmp))
            first.get_rate("EUR", "USD")
            second_session = FakeSession([])
            second, _ = client(second_session, cache_dir=Path(tmp))
            self.assertEqual(second.get_rate("EUR", "USD"), 1.5)
            self.assertEqual(second_session.calls, [])


class ConversionTests(unittest.TestCase):
    def frame(self, currencies):
        return pd.DataFrame({"amount": [10.0] * len(currencies), "currency": currencies})

    def test_fixed_provider(self):
        provider = FixedRateProvider({"eur/usd": 1.1})
        self.assertEqual(provider.get_rate("EUR", "USD"), 1.1)
        self.assertEqual(provider.get_rate("USD", "USD"), 1.0)
        with self.assertRaises(UnknownCurrencyError):
            provider.get_rate("GBP", "USD")

    def test_amounts_are_converted_and_rounded(self):
        provider = FixedRateProvider({"EUR/USD": 1.0833})
        done, rejected = add_converted_amounts(self.frame(["EUR", "USD"]), provider, "USD")
        self.assertEqual(list(done["amount_converted"]), [10.83, 10.0])
        self.assertEqual(list(done["target_currency"]), ["USD", "USD"])
        self.assertTrue(rejected.empty)

    def test_currency_without_rate_is_rejected(self):
        provider = FixedRateProvider({"EUR/USD": 1.1})
        done, rejected = add_converted_amounts(self.frame(["EUR", "GBP"]), provider, "USD")
        self.assertEqual(len(done), 1)
        self.assertEqual(rejected.loc[0, "reject_reason"], "no exchange rate for GBP")

    def test_api_is_called_once_per_currency(self):
        session = FakeSession([rate_response("USD", 1.1), rate_response("USD", 1.3)])
        rc, _ = client(session)
        add_converted_amounts(self.frame(["EUR", "EUR", "GBP", "EUR", "USD"]), rc, "USD")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual({c[1]["base"] for c in session.calls}, {"EUR", "GBP"})


if __name__ == "__main__":
    unittest.main()
