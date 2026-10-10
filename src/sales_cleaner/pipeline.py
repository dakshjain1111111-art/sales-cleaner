"""Run the full pipeline: load -> clean -> de-duplicate -> validate -> convert -> write."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from sales_cleaner.cleaning import (
    BUSINESS_COLUMNS,
    TRACE_COLUMNS,
    SchemaError,
    clean_dataframe,
    drop_duplicates,
    normalize_columns,
)
from sales_cleaner.config import Config
from sales_cleaner.loaders import LoadError, find_input_files, load_file
from sales_cleaner.rates import FixedRateProvider, RateClient, add_converted_amounts
from sales_cleaner.reports import Stats, build_sheets, write_summary_xlsx
from sales_cleaner.validation import validate

log = logging.getLogger("sales_cleaner")

CLEAN_COLUMNS = BUSINESS_COLUMNS + ["rate", "amount_converted", "target_currency"] + TRACE_COLUMNS
REJECT_COLUMNS = BUSINESS_COLUMNS + ["reject_reason"] + TRACE_COLUMNS


@dataclass
class RunResult:
    files_processed: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)
    rows_in: int = 0
    duplicates_removed: int = 0
    rows_clean: int = 0
    rows_rejected: int = 0
    output_files: list[Path] = field(default_factory=list)
    dry_run: bool = False

    @property
    def balanced(self) -> bool:
        """Every input row must be accounted for exactly once."""
        return self.rows_in == self.duplicates_removed + self.rows_clean + self.rows_rejected


def _sorted_for_output(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    return df.sort_values(by, kind="stable").reset_index(drop=True)


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    cfg: Config,
    provider: RateClient | FixedRateProvider,
    today: date | None = None,
    dry_run: bool = False,
) -> RunResult:
    """Process every file in input_dir. Raises NoInputError / RateServiceError on fatal problems."""
    today = today or date.today()
    output_dir = Path(output_dir)
    result = RunResult(dry_run=dry_run)

    frames: list[pd.DataFrame] = []
    for path in find_input_files(input_dir):
        try:
            raw = normalize_columns(load_file(path), cfg)
            frames.append(clean_dataframe(raw, cfg))
        except (LoadError, SchemaError) as exc:
            log.error("skipping %s: %s", path.name, exc)
            result.failed_files[path.name] = str(exc)
            continue
        result.files_processed.append(path.name)
        log.info("loaded %s (%d rows)", path.name, len(raw))

    if not frames:
        log.error("no input file could be processed")
        return result

    combined = pd.concat(frames, ignore_index=True)
    result.rows_in = len(combined)

    deduped, result.duplicates_removed = drop_duplicates(combined)

    valid, rejected = validate(deduped, cfg, today)
    clean, no_rate = add_converted_amounts(valid, provider, cfg.target_currency)
    rejected = pd.concat([rejected, no_rate], ignore_index=True)

    clean = _sorted_for_output(clean, ["date", "order_id"])[CLEAN_COLUMNS]
    rejected = _sorted_for_output(rejected, ["source_file", "source_row"])[REJECT_COLUMNS]
    result.rows_clean, result.rows_rejected = len(clean), len(rejected)

    if dry_run:
        log.info("dry run: no files written")
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.isoformat()
    clean_path = output_dir / f"clean_{stamp}.csv"
    rejects_path = output_dir / f"rejects_{stamp}.csv"
    summary_path = output_dir / f"summary_{stamp}.xlsx"

    clean.to_csv(clean_path, index=False)
    rejected.to_csv(rejects_path, index=False)
    stats = Stats(
        run_date=stamp,
        target_currency=cfg.target_currency,
        files_processed=len(result.files_processed),
        rows_in=result.rows_in,
        duplicates_removed=result.duplicates_removed,
        rows_clean=result.rows_clean,
        rows_rejected=result.rows_rejected,
    )
    write_summary_xlsx(summary_path, build_sheets(clean, rejected, stats))
    result.output_files = [clean_path, rejects_path, summary_path]
    return result
