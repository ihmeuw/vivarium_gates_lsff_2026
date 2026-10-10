"""
===============
Extraction data
===============

Load the extraction tables in ``0100_data_prep/extraction/``.

There are two layers (see ``0100_data_prep/extraction/README.md``):

- ``data/``: the base tables, edited by hand. They hold values that have no
  other source, and every table not listed in ``GENERATED_TABLES``.
- ``generated/``: the tables the data prep notebooks read, written by
  ``integration/build_extraction.py`` from the base tables, the literature and
  GF snapshots, and ``integration/decisions.csv``. Never edit these by hand.

Use :func:`load_extraction` rather than ``pd.read_csv`` so that every reader
gets the right layer, the same column types and the same validation.
"""

from pathlib import Path

import pandas as pd

from lsff_utils.data_processing import EXTRACTION_MAPPING
from lsff_utils.paths import REPO_ROOT

EXTRACTION_DIR = REPO_ROOT / "0100_data_prep" / "extraction"
EXTRACTION_DATA_DIR = EXTRACTION_DIR / "data"
EXTRACTION_GENERATED_DIR = EXTRACTION_DIR / "generated"

# Tables the build writes to generated/. load_extraction reads these from there.
GENERATED_TABLES = ("country_vehicle", "country_vehicle_fortificant", "scenario_definition", "vehicle")

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

# Columns that identify a data point in the tables the build manages
KEY_COLUMNS = ["Country", "Vehicle", "Fortificant", "Scenario", "Quintile", "Sex", "Data need", "Data point name"]


def extraction_path(table: str, base: bool = False) -> Path:
    """The file a table is read from: generated/ for built tables, unless base=True."""
    if table not in NUMERIC_COLUMNS:
        raise KeyError(f"Unknown extraction table {table!r}; expected one of {TABLES}")
    if table in GENERATED_TABLES and not base:
        return EXTRACTION_GENERATED_DIR / f"{table}.csv"
    return EXTRACTION_DATA_DIR / f"{table}.csv"


def load_extraction(table: str, validate: bool = True, base: bool = False) -> pd.DataFrame:
    """Read one extraction table (the generated version, unless ``base=True``).

    Text columns come back as ``object`` columns of ``str`` and numeric columns
    as ``float64``; blank cells are NaN. Only blank cells count as missing --
    strings like ``"N/A"`` are kept as written.
    """
    path = extraction_path(table, base)
    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )
    for column in NUMERIC_COLUMNS[table]:
        # astype(float) parses with Python's float(), which round-trips the
        # full-precision values in the CSV exactly (pd.to_numeric does not).
        df[column] = df[column].astype("float64")
    if validate:
        validate_extraction(table, df, path)
    return df


def validate_extraction(table: str, df: pd.DataFrame, path: Path | None = None) -> None:
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

    # Each data point must appear once in the tables the build manages (two rows with the
    # same key would be matched together by the build and the notebooks).
    if table in GENERATED_TABLES:
        key = [c for c in KEY_COLUMNS if c in df.columns]
        duplicated = df.index[df.duplicated(key, keep=False)]
        if len(duplicated):
            problems.append(f"rows {_csv_rows(duplicated)} share the same {', '.join(key)}")

    # Stray spaces in the columns code filters on make rows silently not match.
    # (Not checked in `universal`, which indents sub-items on purpose.)
    for column in IDENTIFIER_COLUMNS if table != "universal" else []:
        if column in df.columns:
            text = df[column].dropna()
            padded = text[text != text.str.strip()]
            for idx, value in padded.items():
                problems.append(f"{column!r} has leading/trailing whitespace ({value!r}) in row {_csv_rows([idx])}")

    if problems:
        name = path if path is not None else extraction_path(table)
        raise ValueError(f"{name}:\n  " + "\n  ".join(problems))


def _csv_rows(index) -> str:
    # +2: one for the header row, one because rows are numbered from 1 (as in Excel).
    return ", ".join(str(i + 2) for i in index)
