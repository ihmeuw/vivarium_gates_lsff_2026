# Proposal: build the extraction tables from GF and the literature only

Status: agreed; being implemented in steps (see "Implementation plan"). Companion files in
this folder: `data_needs_spec.csv` (draft spec of what the pipeline reads; to be replaced by a
Python module in step 3) and `old_values_in_use.csv` (values the model still took from the old
extraction sheet in October 2026).

## Summary

Today `build_extraction.py` starts from the old extraction sheet (the "base" tables in
`../data/`) and overwrites rows with literature, GF and decision values. Anything not
overwritten passes through unchanged. That makes it hard to tell whether an old or DUMMY
value is reaching the model, and the old sheet's layout decides which rows exist.

Proposal: build the tables from three inputs only, the literature extraction, the GF
workbook and `decisions.csv`, with the rows defined by a spec of what the pipeline reads. A
row that none of them fills stops the build. The old sheet stops being an input and is
deleted (it stays in git history).

## Why

1. **Old values reach the model without anyone choosing them.** In the current build, 14
   values the model reads come from the old tables (`old_values_in_use.csv`, `used_by_model
   = yes`). Most are reasonable, but nothing marks them as old except a column in
   `comparison.csv`.
2. **DUMMY values can survive.** They are reported as "placeholder remains" in `review.csv`
   but don't fail the build. The wheat hemoglobin effect is the rice value copied as a
   DUMMY. Decision D009 keeps it "until a wheat-specific estimate is available", and the
   literature workbook now has one (Dorbu, 2.08 g/L, vs 3.25 used).
3. **The old layout decides the shape of the data.** Ethiopia wheat's DUMMY rows copied
   India's quintile split, so GF's national coverage had nowhere to go and the build
   failed. Each new arm brings the same risk.
4. **Three-way merges are hard to review.** Every output value has to be explained as
   "base, unless the literature, unless GF, unless a decision". With two sources and
   decisions, the explanation is shorter and the missing cases are explicit.

## What the old tables do today

| Role | Detail | Needed? |
|---|---|---|
| Values for arms the model runs | 14 rows read by the model: effect sizes for rice and bouillon (4), Nigeria rice baseline "no fortification" (6), India rice baseline and intervention concentrations (3, one via decision D031 `keep`), Ethiopia salt WRA SD (1). See `old_values_in_use.csv`. | Values yes, source no: move them into the literature workbook or `decisions.csv`. |
| Values the model doesn't read | U5 "any" rows, Ethiopia salt U5 amounts, Nigeria salt NRV concentrations (scenarios not configured), salt hemoglobin effect (India salt iron is at `none`). | No. |
| DUMMY placeholders | Wheat effect sizes, Ethiopia wheat SD, India wheat and salt consumption, etc. | No: missing data should fail, not borrow. |
| Which rows exist and their split (quintile, sex, Total) | Copied from the old sheet, including from DUMMY rows. | Yes, but it belongs in a spec. |
| Arms the model doesn't run | Passed through unchanged. | No. |
| `country.csv`, `universal.csv`, `data_sources.csv`, `progress.csv` | Not read by the pipeline (only by `check_completeness.py` and validation). | No. |

## Proposed design

### Inputs

- `lit_long.csv`, `gf_long.csv`: unchanged (from `extract_lit.py`, `extract_gf.py`).
- `decisions.csv`: unchanged format. Also the home for assumptions with no literature
  source (e.g. "Nigeria rice has no baseline fortification", `value:0`), each with a
  rationale.
- The data needs spec (new): one entry per data need the pipeline reads, with units,
  which arms need it, allowed quintile/sex layouts, default source order (including "from
  HCES") and the results file it feeds. It will be a Python module (`data_needs.py`), because
  rules like "Nigeria only" or "India rice: one Total row" are logic; a readable table is
  generated from it for the docs. The draft `data_needs_spec.csv` is the starting point.
- `0050_config/location_fortificant_vehicles.csv` and `config.yaml`: which arms,
  fortificants and scenarios to build (arms at `run_through = none` are skipped).

### Build

1. For each arm that runs, each fortificant and each configured scenario, list the rows
   the spec requires.
2. Fill each row: an active decision if one targets it, otherwise the spec's default
   order (literature, then GF for measurements; GF, then literature for 2035 targets).
   GF mapping rules (e.g. consolidation x sqrt(compliance)) stay as they are.
3. Choose the split from the data: five quintile rows if the chosen source has all five,
   otherwise one `All (assumed same)` row. A `Total` row is added only where the spec asks
   for it.
4. **Any row left empty fails the build**, with a message naming the arm, need and
   quintile, and the candidates that exist (e.g. a literature row for a different
   scenario name).
5. Run the existing checks (percentages in [0, 1], consumer variance, totals, intervention
   >= baseline) and write the same four generated tables, so the data prep notebooks don't
   change.

Every output value then has one of three origins: a literature row ID, a GF cell, or a
decision ID. `comparison.csv`, `review.csv` and `STATUS.md` keep working, minus the "base"
column (or with it as information only).

### What doesn't change

- The generated tables' format and the data prep notebooks.
- `decisions.csv`, the GF mapping rules and the checks.
- The workflow: extract, build, review, commit; Snakemake checks the committed tables.

## Decisions (October 2026)

1. **Effect sizes take literature defaults** like every other need. Nothing recorded why they
   didn't; the defaults loop was written per arm, and effect sizes aren't per arm. D009 and
   D010 (`keep` the DUMMY wheat effects) are deleted.
2. **U5 coverage is kept.** Not reading it is considered a bug in the anemia notebooks, to be
   fixed separately, so the spec requires it for the arms that will need it.
3. **Assumptions without a source go into `decisions.csv`** (`value:` with a rationale) until
   they are copied into the literature workbook. About five are needed: Nigeria rice baseline
   (share fortified 0, concentration 0, effectiveness 0.8) and the Ethiopia salt WRA SD
   (2.2 g/day). D031 (India rice folate intervention, 1.3 mcg/g) points at the literature's
   "2016 FA standard" row instead of `keep`.
4. **HCES: option A.** The spec marks which needs come from HCES for which arms; the build
   doesn't produce those rows, the Snakefile routes their results files to the HCES rule
   (from the spec, not a hard-coded India rice), and a check after data prep confirms every
   expected results file exists and is complete. India rice's own meanings of
   fortifiability and baseline coverage (government rice) stay as rules for that arm. The
   alternative, HCES as a third source the build reads, would need an age dimension in the
   extraction tables.
5. **The old tables are deleted** (they stay in git history).

## Implementation plan

Each step is its own commit. After each, the generated tables are diffed against the
previous build and `prep_extracted` is rerun on a copy; every difference should be an
intended one.

0. **Decisions only.** Delete D009 and D010; point D031 at the "2016 FA standard" literature
   row; add `value:` decisions for the Nigeria rice baseline and the Ethiopia salt SD.
   Expected diff: none (wheat's effects fall back to the old DUMMY until step 1).
1. **Effect sizes take literature defaults** (`default_scope`). Expected diff: wheat
   hemoglobin 3.25 -> 2.08, rice 3.25 -> 3.24, salt 4.40 -> 4.8 (salt unused).
2. **HCES covers consumption only.** India rice takes literature defaults for everything but
   consumption and the two needs whose meaning differs for government rice (fortifiability,
   baseline any); its GF rules for those stay.
   Expected diff: none (the India rice baseline concentrations come from the literature,
   same values).
3. **Spec-driven rows.** Add `data_needs.py`; generate the rows for each arm that runs from
   it instead of reading the old tables, choosing each row's layout from the source that
   fills it; an empty row fails the build. The old tables are read one last time as a
   cross-check. Expected diff: rows for arms at `none`, unconfigured scenarios and unneeded
   needs disappear; layouts follow the data; row order changes once.
4. **Remove the old tables** and what depended on them: the `keep` decision source,
   "placeholder remains", the base columns in the reports, `base=True` in
   `lsff_utils.extraction`, `check_completeness.py` / `progress.csv` (reworked from the spec
   or retired). Update the README, `GF_DATA_MAPPING.md` and tests.
5. **HCES, pipeline side.** Snakefile routing from the spec; a results-file check after data
   prep (Snakemake rule and pytest).
6. **Later.** `prep_extracted`'s `data_needs` and the Snakefile's file lists read the spec;
   the U5 coverage fix in the anemia notebooks.

Open points to settle along the way: which layout wins when sources differ in detail (keep the
precedence order, overridable by a decision); `comparison.csv` keeps showing GF and literature
values for arms at `none`; Ethiopia wheat's SD needs its own decision before the build passes.
