"""Read CSV and Excel files into DataFrames of raw strings."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


class LoadError(Exception):
    """Raised when an input file cannot be read."""


class NoInputError(Exception):
    """Raised when the input folder is missing or has no supported files."""


def find_input_files(input_dir: str | Path) -> list[Path]:
    """Return supported files in input_dir (not recursive), sorted by name."""
    folder = Path(input_dir)
    if not folder.is_dir():
        raise NoInputError(f"input folder not found: {folder}")
    files = sorted(
        p
        for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_SUFFIXES
        and not p.name.startswith(("~$", "."))
    )
    if not files:
        raise NoInputError(f"no .csv or .xlsx files found in {folder}")
    return files


def load_file(path: str | Path) -> pd.DataFrame:
    """Read one file with every cell as text.

    Adds ``source_file`` and ``source_row`` (row number in the file, header = row 1)
    so every output row can be traced back to its origin.
    """
    path = Path(path)
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        elif path.suffix.lower() == ".xlsx":
            df = pd.read_excel(path, dtype=str, keep_default_na=False, engine="openpyxl")
        else:
            raise LoadError(f"unsupported file type: {path.name}")
    except LoadError:
        raise
    except Exception as exc:  # corrupt zip, bad encoding, empty file, parser errors...
        raise LoadError(f"cannot read {path.name}: {exc}") from exc

    if df.empty and len(df.columns) == 0:
        raise LoadError(f"{path.name} is empty")

    df["source_file"] = path.name
    df["source_row"] = range(2, len(df) + 2)
    return df
