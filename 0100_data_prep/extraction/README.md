# Extraction data

The extraction tables hold the inputs the data prep notebooks read: consumption,
fortifiability, baseline and intervention fortification, and effect sizes. They come in
two layers, one CSV per table and one data point per row:

```
data/*.csv (base, hand-edited)                  ─┐
integration/lit_long.csv (literature snapshot)  ─┤
integration/gf_long.csv (GF snapshot)           ─┼─► integration/build_extraction.py ─► generated/*.csv ─► prep notebooks
integration/decisions.csv                       ─┤   (run by hand; Snakemake checks it)  (never edit)
0050_config/location_fortificant_vehicles.csv   ─┘
```

- **`data/`, the base layer**: hand-entered values that have no other source (effect sizes,
  concentrations, HCES-related values, assumptions), plus the tables nothing builds.
- **`generated/`, the generated layer**: the four tables the notebooks read, written only by
  the build. For the arms the model runs, it starts from the base tables, fills in values
  from the literature extraction and GF (literature first for measurements, GF first for
  the 2035 targets), then applies `decisions.csv`.
  See `integration/README.md`.

| File | Layer | Was tab | Read by |
|---|---|---|---|
| `country_vehicle.csv` | base → generated | Country-Vehicle Extraction | `prep_extracted.ipynb` |
| `country_vehicle_fortificant.csv` | base → generated | Country-Vehicle-Fort Extraction | `prep_extracted.ipynb` |
| `scenario_definition.csv` | base → generated | Scenario Definition Extraction | `prep_extracted.ipynb` |
| `vehicle.csv` | base → generated | Vehicle Extraction | `prep_vehicle.ipynb` |
| `country.csv` | base only | Country Extraction | (reference only) |
| `universal.csv` | base only | Universal | (reference only) |
| `data_sources.csv` | base only | Data Sources | (reference only) |
| `progress.csv` | base only | the five "Progress" tabs | `check_completeness.py` |

## Changing a value

- **A value from the literature or GF:** don't edit any table. Update the source and its
  snapshot, or record a choice in `integration/decisions.csv`, then rebuild (below).
- **A value with no other source:** edit the table in `data/`, then rebuild.
- **Never edit `generated/`.** `tests/test_extraction_build.py` fails if it differs from a
  fresh build.

To rebuild:

    cd integration && python build_extraction.py

The build prints every value that changed. Review the diffs, then commit the generated
tables and the build's reports together with the change that caused them. Snakemake doesn't
run the build; before data prep (unless `skip_data_prep=true`) it checks that the committed
tables are up to date, and stops with a message if they aren't.

## Editing the CSVs

- Edit them in a text editor, or in Excel. If you use Excel, save with
  **File > Save As > CSV UTF-8** and look at `git diff` before committing: Excel
  may turn values into dates, drop precision or change quoting.
- Put new rows next to related ones (same country / vehicle / data need) so
  diffs stay readable and two people's additions rarely touch the same lines.
- Enter values, not formulas. If a value was derived (e.g. SD = IQR / 1.35, or a
  mean among consumers multiplied by coverage), write the calculation in the
  `Derivation` column (`country_vehicle.csv`) or in `Notes`.
- Read tables in code with `lsff_utils.extraction.load_extraction("<table>")`,
  never `pd.read_csv` directly. It reads the generated version of built tables (pass
  `base=True` for the base version), fixes column types, and validates required
  columns, allowed `Quintile`/`Sex` values, and stray whitespace in the columns
  the notebooks filter on. `pytest tests/test_extraction.py` runs the same checks
  on both layers.

## Tracking progress

`progress.csv` lists every data need we track, per country / vehicle /
fortificant / scenario and wealth level. `Status` is either a label typed by
hand (`Not modeled`, `Microdata: HCES`, `GBD`, `Zero`, ...) or `auto`, which
`check_completeness.py` resolves to `Complete` or `Missing` from the generated tables:

```
python check_completeness.py            # print the grids
python check_completeness.py --strict   # exit 1 if anything is Missing
```

## A workbook for browsing

`python build_workbook.py` writes `extraction_data_view.xlsx` (gitignored) with
every table (generated versions where they exist) on its own tab, plus the progress grids,
for reading or sending to collaborators. Changes made in that file are not read by the
pipeline.
