"""Validation rules: split cleaned rows into valid rows and rejects with reasons."""
from __future__ import annotations

from datetime import date

import pandas as pd

from sales_cleaner.config import Config

REQUIRED_VALUES = ["order_id", "date", "store", "quantity", "amount", "currency"]


def row_reasons(row: pd.Series, cfg: Config, today: date) -> list[str]:
    """Return every reason this row fails validation (empty list = valid)."""
    reasons = list(row["issues"])

    for col in REQUIRED_VALUES:
        already_explained = any(r.startswith(f"invalid {col}") for r in reasons)
        if pd.isna(row[col]) and not already_explained:
            reasons.append(f"missing {col}")

    if pd.notna(row["amount"]) and row["amount"] <= 0:
        reasons.append("amount must be greater than zero")
    if pd.notna(row["quantity"]) and row["quantity"] < 1:
        reasons.append("quantity must be at least 1")
    if pd.notna(row["currency"]) and row["currency"] not in cfg.allowed_currencies:
        reasons.append(f"currency '{row['currency']}' is not allowed")
    if pd.notna(row["date"]) and row["date"] > today.isoformat():
        reasons.append("date is in the future")
    return reasons


def validate(df: pd.DataFrame, cfg: Config, today: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split df into (valid, rejected). Rejected rows get a ``reject_reason`` column."""
    reasons = [row_reasons(row, cfg, today) for _, row in df.iterrows()]
    is_bad = pd.Series([bool(r) for r in reasons], index=df.index, dtype=bool)

    valid = df[~is_bad].drop(columns="issues").reset_index(drop=True)
    rejected = df[is_bad].drop(columns="issues").copy()
    rejected["reject_reason"] = ["; ".join(r) for r in reasons if r]
    return valid, rejected.reset_index(drop=True)
