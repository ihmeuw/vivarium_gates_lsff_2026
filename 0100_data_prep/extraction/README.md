# Extraction data

The extraction tables hold the inputs the data prep notebooks read: consumption,
fortifiability, baseline and intervention fortification, and effect sizes. One CSV per table,
one data point per row, all in `generated/`, all written by the build:

```
integration/lit_long.csv (literature snapshot)  ─┐
integration/gf_long.csv (GF snapshot)           ─┤
integration/decisions.csv                       ─┼─► integration/build_extraction.py ─► generated/*.csv ─► prep notebooks
integration/data_needs.py (which rows)          ─┤   (run by hand; Snakemake checks it)  (never edit)
0050_config/ (arms and scenarios)               ─┘
```

For the arms the model runs, the build lays out the rows each arm needs (`data_needs.py`;
readable version `integration/DATA_NEEDS.md`), fills them from the literature extraction and
GF (literature first for measurements, GF first for the 2035 targets), then applies
`decisions.csv`. A required value nothing provides stops the build. See
`integration/README.md`.

| File | Read by |
|---|---|
| `generated/country_vehicle.csv` | `prep_extracted.ipynb` |
| `generated/country_vehicle_fortificant.csv` | `prep_extracted.ipynb` |
| `generated/scenario_definition.csv` | `prep_extracted.ipynb` |
| `generated/vehicle.csv` | `prep_vehicle.ipynb` |

The old hand-edited tables (`data/`, the "base layer") and `check_completeness.py` were
removed in October 2026; they are in git history.

## Changing a value

- **A value from the literature or GF:** update the source and its snapshot, or record a
  choice in `integration/decisions.csv`, then rebuild (below).
- **A value with no published source** (an assumption): add it to the literature workbook,
  or as a `value:` decision with its rationale.
- **Never edit `generated/`.** `tests/test_extraction_build.py` fails if it differs from a
  fresh build.

To rebuild:

    cd integration && python build_extraction.py

The build prints every value that changed. Review the diffs, then commit the generated
tables and the build's reports together with the change that caused them. Snakemake doesn't
run the build; before data prep (unless `skip_data_prep=true`) it checks that the committed
tables are up to date, and stops with a message if they aren't.

## Reading the tables

Read tables in code with `lsff_utils.extraction.load_extraction("<table>")`, never
`pd.read_csv` directly. It fixes column types and validates required columns, allowed
`Quintile`/`Sex` values, duplicated data points and stray whitespace in the columns the
notebooks filter on. `pytest tests/test_extraction.py` runs the same checks.

## A workbook for browsing

`python build_workbook.py` writes `extraction_data_view.xlsx` (gitignored) with each
generated table on its own tab, for reading or sending to collaborators. Changes made in that
file are not read by the pipeline.

## AI use

The entire system for combining data sources was developed by Claude under human
direction. As such, the code in the following python files is completely AI-generated and
has not been carefully reviewed by a human:

- `0100_data_prep/extraction/build_workbook.py`
- `0100_data_prep/extraction/integration/`:
  - `build_extraction.py`, `common.py`, `data_needs.py`, `extract_gf.py`, `extract_lit.py`
    and `report.py`
- `src/lsff_utils/extraction.py`
- `tests/`:
  - `test_extraction.py`, `test_extraction_build.py` and `test_data_needs.py`

The following related markdown files are also AI-generated. They have been reviewed but not
thoroughly revised, and they may contain errors:

- `0100_data_prep/extraction/README.md`
- `0100_data_prep/extraction/integration/`:
  - `README.md`, `GF_DATA_MAPPING.md` and `CONSUMPTION_DISTRIBUTION.md`
