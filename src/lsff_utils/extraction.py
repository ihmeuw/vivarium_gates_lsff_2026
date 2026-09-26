"""
===============
Extraction data
===============

Load the hand-extracted input data in ``0100_data_prep/extraction/data/``.

These tables used to live in tabs of ``Data Extraction Sheet.xlsx``. They are
now one CSV per table so that git can diff and merge them line by line. Each
row is a single data point; edit the CSVs directly (in a text editor or in
Excel -- if you use Excel, save as "CSV UTF-8" and check the diff before
committing, since Excel likes to reformat dates and numbers).

Use :func:`load_extraction` rather than ``pd.read_csv`` so that every reader
gets the same column types and the same validation.
"""

from pathlib import Path

import pandas as pd

from lsff_utils.data_processing import EXTRACTION_MAPPING
from lsff_utils.paths import REPO_ROOT

EXTRACTION_DATA_DIR = REPO_ROOT / "0100_data_prep" / "extraction" / "data"

# Columns parsed as numbers; every other column is read as text. A blank cell is
# missing (NaN) in either case.
NUMERIC_COLUMNS = {
    "country_vehicle": ["Year", "Value", "SE"],
    "country_vehicle_fortificant": ["Year", "Value", "CI"],
    "country": ["Year", "Value", "CI"],
    "vehicle": ["Value"],
    "universal": ["Year"],
    "scenario_definition": ["Value"],
    "data_sources": [],
    "progress": [],
}

# Columns every row must fill in.
REQUIRED_COLUMNS = {
    "country_vehicle": ["Country", "Vehicle", "Quintile", "Sex", "Data need", "Data point name", "Units", "Value"],
    "country_vehicle_fortificant": ["Country", "Vehicle", "Fortificant", "Quintile", "Data need", "Data point name", "Units", "Value"],
    "country": ["Country", "Quintile", "Data need"],
    "vehicle": ["Vehicle", "Data need", "Data point name", "Units", "Value"],
    "universal": ["Data need"],
    "scenario_definition": ["Country", "Vehicle", "Fortificant", "Scenario", "Data need", "Data point name", "Units", "Value"],
    "data_sources": ["Name"],
    "progress": ["Table", "Data need", "Status"],
}

ALLOWED_VALUES = {
    "Quintile": set(EXTRACTION_MAPPING) | {"All"},
    "Sex": {"Female", "Male", "Total", "All (assumed same)"},
}

IDENTIFIER_COLUMNS = [
    "Country", "Vehicle", "Fortificant", "Scenario", "Quintile", "Sex",
    "Data need", "Data point name", "Units", "Table", "Wealth", "Status",
]

TABLES = tuple(NUMERIC_COLUMNS)


def extraction_path(table: str) -> Path:
    if table not in NUMERIC_COLUMNS:
        raise KeyError(f"Unknown extraction table {table!r}; expected one of {TABLES}")
    return EXTRACTION_DATA_DIR / f"{table}.csv"


def load_extraction(table: str, validate: bool = True) -> pd.DataFrame:
    """Read one extraction table.

    Text columns come back as ``object`` columns of ``str`` and numeric columns
    as ``float64``; blank cells are NaN. Only blank cells count as missing --
    strings like ``"N/A"`` are kept as written.
    """
    df = pd.read_csv(
        extraction_path(table),
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )
    for column in NUMERIC_COLUMNS[table]:
        # astype(float) parses with Python's float(), which round-trips the
        # full-precision values in the CSV exactly (pd.to_numeric does not).
        df[column] = df[column].astype("float64")
    if validate:
        validate_extraction(table, df)
    return df


def validate_extraction(table: str, df: pd.DataFrame) -> None:
    """Raise ``ValueError`` listing every problem found in ``df``."""
    problems = []

    missing_columns = set(REQUIRED_COLUMNS[table]) - set(df.columns)
    if missing_columns:
        problems.append(f"missing columns {sorted(missing_columns)}")

    for column in REQUIRED_COLUMNS[table]:
        if column in df.columns:
            blank = df.index[df[column].isna()]
            if len(blank):
                problems.append(f"{column!r} is blank in rows {_csv_rows(blank)}")

    for column, allowed in ALLOWED_VALUES.items():
        if column in df.columns:
            bad = df[df[column].notna() & ~df[column].isin(allowed)]
            for idx, value in bad[column].items():
                problems.append(f"{column!r} has unexpected value {value!r} in row {_csv_rows([idx])}")

    # Stray spaces in the columns code filters on make rows silently not match.
    # (Not checked in `universal`, which indents sub-items on purpose.)
    for column in IDENTIFIER_COLUMNS if table != "universal" else []:
        if column in df.columns:
            text = df[column].dropna()
            padded = text[text != text.str.strip()]
            for idx, value in padded.items():
                problems.append(f"{column!r} has leading/trailing whitespace ({value!r}) in row {_csv_rows([idx])}")

    if problems:
        raise ValueError(f"{extraction_path(table).name}:\n  " + "\n  ".join(problems))


def _csv_rows(index) -> str:
    # +2: one for the header line, one because editors number lines from 1.
    return ", ".join(str(i + 2) for i in index)
