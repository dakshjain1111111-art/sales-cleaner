"""Summary workbook with overview, per-store, per-month and reject-reason sheets."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class Stats:
    run_date: str
    target_currency: str
    files_processed: int
    rows_in: int
    duplicates_removed: int
    rows_clean: int
    rows_rejected: int


def summarize_rejects(rejected: pd.DataFrame) -> pd.DataFrame:
    """Count each distinct reason (quoted values are masked so similar reasons group)."""
    counts: dict[str, int] = {}
    for text in rejected.get("reject_reason", pd.Series(dtype=str)):
        for reason in str(text).split("; "):
            key = re.sub(r"'[^']*'", "'...'", reason)
            counts[key] = counts.get(key, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return pd.DataFrame(rows, columns=["reason", "rows"])


def build_sheets(clean: pd.DataFrame, rejected: pd.DataFrame, stats: Stats) -> dict[str, pd.DataFrame]:
    """Build the report tables as DataFrames (kept separate from file writing for testing)."""
    total_col = f"total_{stats.target_currency}"
    total_sales = round(float(clean["amount_converted"].sum()), 2) if len(clean) else 0.0

    overview = pd.DataFrame(
        [
            ("Run date", stats.run_date),
            ("Files processed", stats.files_processed),
            ("Rows in", stats.rows_in),
            ("Duplicates removed", stats.duplicates_removed),
            ("Rows clean", stats.rows_clean),
            ("Rows rejected", stats.rows_rejected),
            ("Target currency", stats.target_currency),
            (f"Total sales ({stats.target_currency})", total_sales),
        ],
        columns=["metric", "value"],
    )

    if len(clean):
        by_store = (
            clean.groupby("store")
            .agg(orders=("order_id", "count"), units=("quantity", "sum"),
                 total=("amount_converted", "sum"))
            .round(2)
            .reset_index()
            .rename(columns={"total": total_col})
        )
        months = clean.assign(month=clean["date"].str[:7])
        by_month = (
            months.groupby("month")
            .agg(orders=("order_id", "count"), total=("amount_converted", "sum"))
            .round(2)
            .reset_index()
            .rename(columns={"total": total_col})
        )
    else:
        by_store = pd.DataFrame(columns=["store", "orders", "units", total_col])
        by_month = pd.DataFrame(columns=["month", "orders", total_col])

    return {
        "Overview": overview,
        "By Store": by_store,
        "By Month": by_month,
        "Reject Reasons": summarize_rejects(rejected),
    }


def write_summary_xlsx(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    """Write the report tables to an Excel workbook with sensible column widths."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            for idx, col in enumerate(frame.columns, start=1):
                longest = max([len(str(col))] + [len(str(v)) for v in frame[col]])
                sheet.column_dimensions[sheet.cell(row=1, column=idx).column_letter].width = min(
                    longest + 2, 60
                )
