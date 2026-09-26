"""Bundle the extraction CSVs into one .xlsx for browsing or sharing.

The CSVs in ``data/`` are the source of truth; this workbook is a read-only
convenience copy and is gitignored. Edits made in it are NOT read by the
pipeline -- make them in the CSVs.

Usage::

    python build_workbook.py [output.xlsx]
"""

import sys
from pathlib import Path

import pandas as pd

from check_completeness import DIMENSIONS, grid, resolve_statuses
from lsff_utils.extraction import TABLES, load_extraction

DEFAULT_OUTPUT = Path(__file__).parent / "extraction_data_view.xlsx"


def main(output: Path = DEFAULT_OUTPUT) -> None:
    progress = resolve_statuses()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for table in TABLES:
            if table == "progress":
                continue
            df = load_extraction(table, validate=False)
            df.to_excel(writer, sheet_name=table[:31], index=False)
            sheet = writer.sheets[table[:31]]
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, len(df), len(df.columns) - 1)
            sheet.set_column(0, len(df.columns) - 1, 18)
        for table in DIMENSIONS:
            name = f"{table} status"[:31]
            grid(progress, table).fillna("").to_excel(writer, sheet_name=name)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT)
