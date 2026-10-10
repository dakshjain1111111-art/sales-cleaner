"""Shared test helpers."""
from __future__ import annotations

from pathlib import Path

from sales_cleaner.config import Config

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "sample_data"

HEADER = "order_id,date,store,product,quantity,amount,currency\n"


def make_cfg(**overrides) -> Config:
    """A config that never touches the network (fixed rates)."""
    cfg = Config()
    cfg.rates.provider = "fixed"
    cfg.rates.fixed = {"EUR/USD": 1.10, "GBP/USD": 1.25, "USD/EUR": 0.90}
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def write_csv(path: Path, body: str, header: str = HEADER) -> Path:
    path.write_text(header + body, encoding="utf-8")
    return path


class FakeResponse:
    def __init__(self, status: int = 200, payload=None, bad_json: bool = False):
        self.status_code = status
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def rate_response(target: str, value: float) -> FakeResponse:
    return FakeResponse(200, {"amount": 1.0, "base": "X", "date": "2026-10-09",
                              "rates": {target: value}})


class FakeSession:
    """Plays back a list of responses (or exceptions) and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
