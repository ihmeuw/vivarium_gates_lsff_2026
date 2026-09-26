# Extraction data

Hand-extracted inputs (from reports, papers, emails, assumptions) live in
`data/`, one CSV per table, one data point per row. They replace the old
`Data Extraction Sheet.xlsx`, which git could neither diff nor merge.

| File | Was tab | Read by |
|---|---|---|
| `country_vehicle.csv` | Country-Vehicle Extraction | `prep_extracted.ipynb` |
| `country_vehicle_fortificant.csv` | Country-Vehicle-Fort Extraction | `prep_extracted.ipynb` |
| `scenario_definition.csv` | Scenario Definition Extraction | `prep_extracted.ipynb` |
| `vehicle.csv` | Vehicle Extraction | `prep_vehicle.ipynb` |
| `country.csv` | Country Extraction | (reference only) |
| `universal.csv` | Universal | (reference only) |
| `data_sources.csv` | Data Sources | (reference only) |
| `progress.csv` | the five "Progress" tabs | `check_completeness.py` |

## Editing

- Edit the CSVs in a text editor, or in Excel. If you use Excel, save with
  **File > Save As > CSV UTF-8** and look at `git diff` before committing: Excel
  may turn values into dates, drop precision or change quoting.
- Put new rows next to related ones (same country / vehicle / data need) so
  diffs stay readable and two people's additions rarely touch the same lines.
- Enter values, not formulas. If a value was derived (e.g. SD = IQR / 1.35, or a
  mean among consumers multiplied by coverage), write the calculation in the
  `Derivation` column (`country_vehicle.csv`) or in `Notes`.
- Read tables in code with `lsff_utils.extraction.load_extraction("<table>")`,
  never `pd.read_csv` directly. It fixes column types and validates required
  columns, allowed `Quintile`/`Sex` values, and stray whitespace in the columns
  the notebooks filter on. `pytest tests/test_extraction.py` runs the same checks.

## Tracking progress

`progress.csv` lists every data need we track, per country / vehicle /
fortificant / scenario and wealth level. `Status` is either a label typed by
hand (`Not modeled`, `Microdata: HCES`, `GBD`, `Zero`, ...) or `auto`, which
`check_completeness.py` resolves to `Complete` or `Missing` from the data:

```
cd 0100_data_prep/extraction
python check_completeness.py            # print the grids
python check_completeness.py --strict   # exit 1 if anything is Missing
```

## A workbook for browsing

`python build_workbook.py` writes `extraction_data_view.xlsx` (gitignored) with
every table on its own tab plus the progress grids, for reading or sending to
collaborators. Changes made in that file are not read by the pipeline.
