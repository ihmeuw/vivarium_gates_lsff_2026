"""Step 1a: GF background workbook -> gf_long.csv (everything, no judgment calls).

One row per typed-in cell of the GF tabs that hold source data:

    'Burden x Vehicle Matrix'   national values per country (stratum_type = national)
    '<Country> (stratified)'    sub-national strata (region, zone, residence, wealth quintile)
    'Coverage Over Time'        typed-in 2031/2035 targets (and any typed 'Current' cells)

Columns: source_sheet, source_cell, country, vehicle, stratum_type, stratum, metric, year,
value (numeric or empty), raw (the cell as typed, e.g. '32.0% (2022)').

Formula cells are skipped and counted: they only link to other cells we already read,
and their cached results may be stale. 'Reach over Time' and 'DFS Bouillon Standards'
are derived from the tabs above and are not extracted.

GF metric names are kept, lightly normalised (vehicle columns: consolidation, coverage,
g_per_capita, compliance). Translating them into our data needs is build_extraction's job.

The GF workbook is a partner deliverable and is not kept in the repo; archive each version
received (e.g. on SharePoint) and pass its path with --gf. The file's date and SHA-256 are
recorded in sources.csv next to the snapshot.
"""

import argparse
import pathlib
import re

import openpyxl
import pandas as pd

from common import GF_FILE, GF_LONG, VEHICLES, QUINTILE_LABELS, norm, record_source

VEHICLE_METRICS = {"cons": "consolidation", "cov": "coverage", "g/cap": "g_per_capita", "compl": "compliance"}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")


def is_formula(value):
    return isinstance(value, str) and value.startswith("=")


def as_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def header_row(ws):
    return next(r for r in range(1, 30) if norm(ws.cell(r, 1).value) in ("country", "stratum"))


def column_metrics(ws, sub_row):
    """col -> (vehicle or None, metric) from the two-row headers."""
    out, group = {}, None
    for col in range(2, ws.max_column + 1):
        if ws.cell(sub_row - 1, col).value is not None:
            group = ws.cell(sub_row - 1, col).value
        sub = ws.cell(sub_row, col).value
        if sub is None or norm(sub) == "tier":
            continue
        vehicle = VEHICLES.get(norm(group))
        if vehicle is not None:
            out[col] = (vehicle, VEHICLE_METRICS.get(norm(sub), slug(sub)))
        else:
            out[col] = (None, f"{slug(group)}:{slug(sub)}" if group else slug(sub))
    return out


def extract_matrix(wb, rows, skipped):
    ws = wb["Burden x Vehicle Matrix"]
    sub_row = header_row(ws)
    metrics = column_metrics(ws, sub_row)
    for r in range(sub_row + 1, ws.max_row + 1):
        country = ws.cell(r, 1).value
        if norm(ws.cell(r, 2).value) not in ("core", "moderate"):  # skips subtotals and notes
            continue
        for col, (vehicle, metric) in metrics.items():
            cell = ws.cell(r, col)
            if cell.value is None:
                continue
            if is_formula(cell.value):
                skipped.append(cell.coordinate)
                continue
            rows.append(dict(source_sheet=ws.title, source_cell=cell.coordinate, country=country,
                             vehicle=vehicle, stratum_type="national", stratum="National", metric=metric,
                             year="current", value=as_number(cell.value), raw=cell.value))


def extract_stratified(wb, rows, skipped):
    for ws in wb:
        if not ws.title.endswith("(stratified)"):
            continue
        country = ws.title.replace("(stratified)", "").strip()
        sub_row = header_row(ws)
        metrics = column_metrics(ws, sub_row)
        stratum_type = None
        for r in range(sub_row + 1, ws.max_row + 1):
            label = ws.cell(r, 1).value
            if label is None:
                continue
            values = [ws.cell(r, c).value for c in metrics]
            if all(v is None for v in values):  # a section label such as 'Wealth quintile'
                stratum_type = slug(label)
                continue
            if norm(label) == "national":  # links to the cover sheet; read there instead
                skipped.extend(ws.cell(r, c).coordinate for c in metrics if is_formula(ws.cell(r, c).value))
                continue
            stratum = label
            if stratum_type == "wealth_quintile":
                stratum = QUINTILE_LABELS[norm(label)]
            for col, (vehicle, metric) in metrics.items():
                cell = ws.cell(r, col)
                if cell.value is None:
                    continue
                if is_formula(cell.value):
                    skipped.append(f"{ws.title}!{cell.coordinate}")
                    continue
                rows.append(dict(source_sheet=ws.title, source_cell=cell.coordinate, country=country,
                                 vehicle=vehicle, stratum_type=stratum_type, stratum=stratum, metric=metric,
                                 year="current", value=as_number(cell.value), raw=cell.value))


def extract_coverage_over_time(wb, rows, skipped):
    ws = wb["Coverage Over Time"]
    hdr = next(r for r in range(1, 20) if norm(ws.cell(r, 1).value) == "country")
    columns = {}
    for col in range(3, ws.max_column + 1):
        label = norm(ws.cell(hdr, col).value)
        if not label:
            continue
        year, metric = label.split(" ", 1)
        columns[col] = (year, slug(metric))
    for r in range(hdr + 1, ws.max_row + 1):
        country, vehicle = ws.cell(r, 1).value, VEHICLES.get(norm(ws.cell(r, 2).value))
        if country is None or vehicle is None:
            continue
        for col, (year, metric) in columns.items():
            cell = ws.cell(r, col)
            if cell.value is None or metric == "effective_coverage":  # computed by GF, not data
                continue
            if is_formula(cell.value):
                skipped.append(f"{ws.title}!{cell.coordinate}")
                continue
            rows.append(dict(source_sheet=ws.title, source_cell=cell.coordinate, country=country,
                             vehicle=vehicle, stratum_type="national", stratum="National", metric=metric,
                             year=year, value=as_number(cell.value), raw=cell.value))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gf", type=pathlib.Path, default=GF_FILE, help="the GF background data workbook")
    args = parser.parse_args()
    wb = openpyxl.load_workbook(args.gf)  # formulas, not cached values
    rows, skipped = [], []
    extract_matrix(wb, rows, skipped)
    extract_stratified(wb, rows, skipped)
    extract_coverage_over_time(wb, rows, skipped)
    df = pd.DataFrame(rows)

    # The same national current value can be typed in two places (e.g. Coverage Over Time
    # E20 overrides the matrix for India wheat compliance). Report disagreements.
    key = ["country", "vehicle", "stratum_type", "stratum", "metric", "year"]
    dupes = df[df.duplicated(key, keep=False)]
    for _, group in dupes.groupby(key, dropna=False):
        if group["value"].nunique(dropna=False) > 1:
            cells = ", ".join(f"{s}!{c}={v}" for s, c, v in zip(group.source_sheet, group.source_cell, group.raw))
            print(f"WARNING: GF disagrees with itself: {cells}")

    df.to_csv(GF_LONG, index=False, lineterminator="\n")
    record_source(GF_LONG, args.gf)
    print(f"Wrote {GF_LONG.name}: {len(df)} values "
          f"({df.value.notna().sum()} numeric); skipped {len(skipped)} formula cells")


if __name__ == "__main__":
    main()
