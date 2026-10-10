"""Command-line interface: ``sales-cleaner run --input input/ --output output/``."""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from sales_cleaner import __version__
from sales_cleaner.config import ConfigError, load_config, validate_config
from sales_cleaner.loaders import NoInputError
from sales_cleaner.pipeline import run_pipeline
from sales_cleaner.rates import RateServiceError, build_rate_provider

EXIT_OK = 0
EXIT_USAGE = 1  # bad config, missing input folder, no input files
EXIT_FILE_FAILED = 2  # at least one input file could not be processed
EXIT_RATE_SERVICE = 3  # exchange-rate service unavailable

log = logging.getLogger("sales_cleaner")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sales-cleaner", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="clean every CSV/XLSX file in a folder")
    run.add_argument("--input", required=True, help="folder with .csv / .xlsx files")
    run.add_argument("--output", required=True, help="folder for clean/rejects/summary files")
    run.add_argument("--config", help="path to a YAML config file")
    run.add_argument("--target-currency", help="convert all amounts to this currency (e.g. USD)")
    run.add_argument("--dry-run", action="store_true", help="process everything but write nothing")
    run.add_argument("-v", "--verbose", action="store_true", help="show debug output")
    return parser


def setup_logging(output_dir: Path, verbose: bool, dry_run: bool) -> None:
    """Log to the console, and to output/sales_cleaner.log unless this is a dry run."""
    logger = logging.getLogger("sales_cleaner")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(output_dir / "sales_cleaner.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output)
    setup_logging(output_dir, args.verbose, args.dry_run)

    try:
        cfg = load_config(args.config)
        if args.target_currency:
            cfg.target_currency = args.target_currency
            validate_config(cfg)
        provider = build_rate_provider(
            cfg.rates, cache_dir=None if args.dry_run else output_dir / ".cache"
        )
        result = run_pipeline(args.input, output_dir, cfg, provider, dry_run=args.dry_run)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return EXIT_USAGE
    except NoInputError as exc:
        log.error("%s", exc)
        return EXIT_USAGE
    except RateServiceError as exc:
        log.error("exchange-rate service problem: %s (no output files written)", exc)
        return EXIT_RATE_SERVICE

    log.info(
        "Run summary: files=%d rows_in=%d clean=%d rejected=%d duplicates_removed=%d%s",
        len(result.files_processed),
        result.rows_in,
        result.rows_clean,
        result.rows_rejected,
        result.duplicates_removed,
        " (dry run)" if result.dry_run else "",
    )
    for path in result.output_files:
        log.info("wrote %s", path)
    if result.failed_files:
        for name, reason in result.failed_files.items():
            log.error("FAILED %s: %s", name, reason)
        return EXIT_FILE_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
