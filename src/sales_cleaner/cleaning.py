"""Row-level cleaning: normalise headers, text, dates, numbers and currencies."""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from sales_cleaner.config import Config

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
BUSINESS_COLUMNS = ["order_id", "date", "store", "product", "quantity", "amount", "currency"]
TRACE_COLUMNS = ["source_file", "source_row"]

_ISO_FORMATS = ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"]
_NAMED_MONTH_FORMATS = ["%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y"]
_DOT_FORMATS = ["%d.%m.%Y"]
_NUMBER = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?|\d+(\.\d+)?|\.\d+")


class SchemaError(ValueError):
    """Raised when a file's columns cannot be mapped to the expected schema."""


def normalize_column_name(name: str, aliases: dict[str, str]) -> str:
    """'Order ID ' -> 'order_id', then apply the alias table ('Qty' -> 'quantity')."""
    key = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return aliases.get(key, key)


def normalize_columns(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Rename columns to canonical names and check that the required ones exist."""
    mapping = {col: normalize_column_name(col, cfg.column_aliases) for col in df.columns}
    renamed = list(mapping.values())
    duplicates = sorted({c for c in renamed if renamed.count(c) > 1})
    if duplicates:
        raise SchemaError(f"several columns map to the same field: {duplicates}")
    df = df.rename(columns=mapping)
    missing = [c for c in cfg.required_columns if c not in df.columns]
    if missing:
        raise SchemaError(f"missing required columns: {missing}")
    return df


def _text(value: object) -> str:
    """Trim a cell and collapse inner whitespace. Missing values become ''."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def parse_amount(text: str) -> tuple[float | None, str | None]:
    """Parse '$1,200.50', '(15.00)' or '-20' into (value, currency inferred from a symbol).

    Returns (None, symbol_currency) when the text is not a safe number. Ambiguous
    European formats such as '90,50' are rejected instead of being guessed.
    """
    raw = _text(text)
    if not raw:
        return None, None

    currency = next((code for sym, code in CURRENCY_SYMBOLS.items() if sym in raw), None)
    body = raw
    for sym in CURRENCY_SYMBOLS:
        body = body.replace(sym, "")
    body = body.replace(" ", "")

    negative = False
    if body.startswith("(") and body.endswith(")"):
        negative, body = True, body[1:-1]
    if body.startswith("-"):
        negative, body = True, body[1:]
    if body.startswith("+"):
        body = body[1:]

    if not _NUMBER.fullmatch(body):
        return None, currency
    value = float(body.replace(",", ""))
    return (-value if negative else value), currency


def parse_quantity(text: str) -> int | None:
    """Parse '3' or '3.0' into 3. Anything else (including '2.5' or 'one') is None."""
    raw = _text(text)
    if not raw:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number == int(number) else None


def parse_date(text: str, dayfirst: bool = False) -> str | None:
    """Parse common date formats into 'YYYY-MM-DD'. Returns None if nothing matches."""
    raw = _text(text)
    if not raw:
        return None
    slash = ["%d/%m/%Y", "%d-%m-%Y"] if dayfirst else ["%m/%d/%Y", "%m-%d-%Y"]
    for fmt in _ISO_FORMATS + slash + _NAMED_MONTH_FORMATS + _DOT_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def clean_row(row: dict, cfg: Config) -> dict:
    """Clean one raw row. Unparseable values become None and are listed in ``issues``."""
    issues: list[str] = []

    raw_date = _text(row.get("date"))
    date = parse_date(raw_date, cfg.dayfirst)
    if raw_date and date is None:
        issues.append(f"invalid date '{raw_date}'")

    raw_qty = _text(row.get("quantity"))
    quantity = parse_quantity(raw_qty)
    if raw_qty and quantity is None:
        issues.append(f"invalid quantity '{raw_qty}'")

    raw_amount = _text(row.get("amount"))
    amount, symbol_currency = parse_amount(raw_amount)
    if raw_amount and amount is None:
        issues.append(f"invalid amount '{raw_amount}'")

    currency = _text(row.get("currency")).upper()
    currency = CURRENCY_SYMBOLS.get(currency, currency) or symbol_currency

    return {
        "order_id": _text(row.get("order_id")) or None,
        "date": date,
        "store": _text(row.get("store")).title() or None,
        "product": _text(row.get("product")) or None,
        "quantity": quantity,
        "amount": amount,
        "currency": currency,
        "source_file": row.get("source_file"),
        "source_row": row.get("source_row"),
        "issues": issues,
    }


def clean_dataframe(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Clean every row of a DataFrame that already has canonical column names."""
    rows = [clean_row(rec, cfg) for rec in df.to_dict(orient="records")]
    out = pd.DataFrame(rows, columns=BUSINESS_COLUMNS + TRACE_COLUMNS + ["issues"])
    out["quantity"] = out["quantity"].astype("Int64")
    out["amount"] = out["amount"].astype("float64")
    return out


def drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove rows identical in every business column. Returns (frame, rows removed).

    Rows with different parse problems are never merged, so no rejected row is lost.
    """
    key = df.copy()
    key["_issues"] = key["issues"].map("|".join)
    kept = key.drop_duplicates(subset=BUSINESS_COLUMNS + ["_issues"], keep="first")
    kept = kept.drop(columns="_issues")
    return kept.reset_index(drop=True), len(df) - len(kept)
