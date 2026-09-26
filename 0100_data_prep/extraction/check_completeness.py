"""Report which extraction data needs are filled in.

Replaces the "... Progress" tabs of the old Data Extraction Sheet.xlsx.

``data/progress.csv`` lists every (table, country, vehicle, fortificant,
scenario, wealth level, data need) cell we track. Its ``Status`` column is
either a hand-written label (``Not modeled``, ``Microdata: HCES``, ``GBD``,
``Zero``, ...) or ``auto``. For ``auto`` cells this script looks in the
matching extraction table and reports ``Complete`` or ``Missing``:

* ``Overall``: a row for the whole population (Quintile ``Total``, or ``All``
  in the country table, or ``All (assumed same)``) with a value.
* ``Quintile``: a row with a value for each of the five wealth quintiles, or a
  single ``All (assumed same)`` row.
* Tables without a wealth dimension (vehicle, scenario definition): any row with
  a value.

Usage::

    python check_completeness.py            # print one grid per table
    python check_completeness.py --strict   # also exit 1 if anything is Missing
"""

import argparse
import sys

import pandas as pd

from lsff_utils.extraction import load_extraction

QUINTILES = {"Lowest", "Second", "Middle", "Fourth", "Highest"}
ASSUMED_SAME = "All (assumed same)"

# Dimensions each table is keyed on, in the order the grids show them.
DIMENSIONS = {
    "country_vehicle": ["Country", "Vehicle", "Wealth"],
    "country_vehicle_fortificant": ["Country", "Vehicle", "Fortificant", "Wealth"],
    "country": ["Country", "Wealth"],
    "vehicle": ["Vehicle"],
    "scenario_definition": ["Country", "Vehicle", "Fortificant", "Scenario"],
}


def auto_status(data: pd.DataFrame, table: str, cell: pd.Series) -> str:
    rows = data[data["Data need"] == cell["Data need"]]
    for dim in DIMENSIONS[table]:
        if dim != "Wealth":
            rows = rows[rows[dim] == cell[dim]]
    if "Value" in rows.columns:
        rows = rows[rows["Value"].notna()]

    wealth = cell.get("Wealth")
    if pd.isna(wealth):
        complete = len(rows) > 0
    elif wealth == "Overall":
        complete = rows["Quintile"].isin({"Total", "All", ASSUMED_SAME}).any()
    elif wealth == "Quintile":
        quintiles = set(rows["Quintile"])
        complete = ASSUMED_SAME in quintiles or QUINTILES <= quintiles
    else:
        raise ValueError(f"Unexpected Wealth value {wealth!r} in progress.csv")
    return "Complete" if complete else "Missing"


def resolve_statuses() -> pd.DataFrame:
    progress = load_extraction("progress")
    data = {table: load_extraction(table) for table in progress["Table"].unique()}
    progress["Status"] = [
        auto_status(data[cell["Table"]], cell["Table"], cell) if cell["Status"] == "auto" else cell["Status"]
        for _, cell in progress.iterrows()
    ]
    return progress


def grid(progress: pd.DataFrame, table: str) -> pd.DataFrame:
    cells = progress[progress["Table"] == table]
    dims = DIMENSIONS[table]
    return cells.pivot_table(
        index="Data need", columns=dims, values="Status", aggfunc="first", sort=False
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="exit 1 if any data need is Missing")
    args = parser.parse_args()

    progress = resolve_statuses()
    with pd.option_context("display.max_columns", None, "display.width", 250, "display.max_colwidth", 60):
        for table in DIMENSIONS:
            print(f"\n=== {table} ===")
            print(grid(progress, table).fillna("").to_string())

    missing = progress[progress["Status"] == "Missing"]
    print(f"\n{len(missing)} of {len(progress)} tracked cells are Missing.")
    return 1 if args.strict and len(missing) else 0


if __name__ == "__main__":
    sys.exit(main())
