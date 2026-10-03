# Combining GF data and literature extractions (prototype)

This builds `Data Extraction Sheet (integrated).xlsx` from three inputs:

- the GF background data (`../Nutrition PST Background Data.xlsx`);
- Juhi's hand extractions (`../LSFF_effect_sizes.xlsx`);
- a small, hand-edited file of decisions (`decisions.csv`).

It never modifies the base workbook (`../Data Extraction Sheet.xlsx`). With no decisions, it
produces exactly the values of the earlier one-off GF import script, which it replaces.
`GF_DATA_MAPPING.md` documents how GF's terms map onto ours, and which extraction-sheet rows
the model actually reads.

```
python extract_gf.py        # GF workbook   -> gf_long.csv   (every typed-in value, GF's terms)
python extract_lit.py       # Juhi workbook -> lit_long.csv  (our terms, our units, stable IDs)
python build_extraction.py  # + arms.csv + decisions.csv -> workbook, changelog.csv, review.csv,
                            #   comparison.xlsx / comparison.csv
```

Some terms used in the outputs:
- **extraction sheet**: the base `../Data Extraction Sheet.xlsx`, which is never modified.
- **output**: the workbook the build writes, `../Data Extraction Sheet (integrated).xlsx`.
- **tab** and **row**: a row's position, which is the same in both workbooks.

Run all three whenever either source workbook changes. Commit the CSVs: their git diffs
show exactly what changed in GF's or Juhi's data.

## How a value gets into the workbook

Each file has one job:
- `arms.csv` is **scope**: which arms the build manages, and where their data come from.
- `build_extraction.py` holds the **methods**: how values are converted or computed.
- `decisions.csv` holds the **choices**: which value or method applies where, and why.

The build has four phases. Each phase can override the one before it.

1. **GF defaults**, for arms with `apply_gf = yes` in `arms.csv`. GF values are used as
   published, following the mapping in `GF_DATA_MAPPING.md`.
2. **Value decisions**: active decisions whose source is `lit:`, `value:`, `gf` or `keep`.
   Those with `transform = times_coverage` run last, once coverage is final.
3. **Method decisions**: active decisions whose source is `method:<name>`. These compute a
   value from others already in place, e.g. consumption SDs from the literature's CV (see
   `CONSUMPTION_DISTRIBUTION.md`).
4. **Checks**: the constraints the pipeline relies on. If any fail, the build stops without
   writing a workbook. The checks are:
   - percentages are in [0, 1];
   - consumer variance is > 0 (needed by the pregnancy sim);
   - each amount Total is within 10% of its quintile mean (prep_extracted's check);
   - intervention coverage × fortifiability ≥ baseline coverage (the coverage notebook's check).

`changelog.csv` lists every row the build planned. For each row it gives:
- `old_value` (from the extraction sheet) and `new_value` (in the output);
- `source`, where the number came from: GF, literature, typed value, literature CV applied
  to consumers, derived from <vehicle>, or existing extraction sheet;
- `step`, which phase set it (GF default, decision, or derived placeholder), plus the
  `decision_id` if there is one;
- `reference`, the exact GF cell or literature row;
- `overrides`, what it replaced, if anything.

## arms.csv

| column | meaning |
|---|---|
| `country`, `vehicle`, `fortificants` | The arm. Fortificants are separated by `;`. |
| `apply_gf` | `yes` to take GF defaults. `comparison.xlsx` shows GF values for every listed arm either way. |
| `consumption_source` | `sheet` (the default), or `hces` when consumption and baseline coverage come from HCES microdata instead (India rice). For `hces` arms, only intervention rows take GF values. |
| `notes` | Free text. |

How to interpret data (per capita or among consumers, how to compute SDs) is not set here;
those are decisions.

## decisions.csv

One row per choice. Blank target fields match any value, so one decision can cover, for
example, all three Ethiopia scenarios.

| column | meaning |
|---|---|
| `decision_id` | Unique. By convention, `D…` for active decisions and `P…` for proposals. |
| `status` | `active` (applied), `proposed` (shown in review.csv with its effect, not applied), or `rejected` (kept for the record). |
| `need` | A short alias: `any`, `amount`, `u5_any`, `u5_amount`, `fortifiability`, `baseline_any`, `baseline_concentration`, `baseline_effectiveness`, `intervention_coverage`, `intervention_effectiveness`, `intervention_concentration`, `hb_effect` or `bw_effect`. The full data-need text also works. |
| `country` … `data_point_name` | Which workbook rows the decision targets. |
| `source` | One of: `lit:<id>` (a row of lit_long.csv); `value:<number>`; `gf` (the GF default; with no transform this just accepts it and stops the conflict being flagged); `keep` (leave the base workbook's value); `method:<name>` (compute the value; see below). |
| `transform` | Optional, for `lit:`, `value:` and `gf` sources: `sqrt` (√ rounded to 2 d.p., the compliance split) or `times_coverage` (× the row's WRA coverage, national for U5 rows; turns a mean among consumers into a mean over all women). |

Methods (`source = method:<name>`), implemented in `build_extraction.py`:

| method | applies to | computes |
|---|---|---|
| `consumer_cv` | amount and U5 amount SD rows | SD over all women when consumers get the literature's CV (Juhi's NFCMS mean and SD for the same quintile or sex). See `CONSUMPTION_DISTRIBUTION.md`, section 4. |
| `derive_from:<vehicle>` | amount SD rows, U5 mean rows | A placeholder borrowed from another vehicle: its consumer CV, or its U5/WRA ratio. Tagged `DERIVED (MIC-7549)` and reported as a placeholder. |

Methods run after all value decisions, in file order, so they see the final means and coverage.
| `rationale`, `decided_by`, `date` | Why. The rationale is copied into the workbook's Notes. |

A typical loop:
1. Open `review.csv` and pick a "literature disagrees" or "could replace placeholder" row.
2. Copy its `lit_id` into a new decision, starting as `proposed`.
3. Rebuild and look at what it would change.
4. Flip it to `active`.

If a decision's literature row disappears (for example, its key fields were edited), the
build stops and says which decision broke.

## STATUS.md

The easiest place to start. It is regenerated on every build, with one section per arm
listing:
- the decisions in effect: what each one targets, the value it sets, where that value comes
  from (for literature, the value, source and row in Juhi's sheet), and its rationale;
- proposed decisions, with what they would set;
- what is still open, with output and literature values side by side.

No IDs need looking up.

## review.csv

Each row spells out its `arm`, `item` (the data need in plain words), `where` (scenario,
quintile or sex), `output_value`, `literature` (value, source, and row in Juhi's sheet), the
`decision` (ID, status and rationale) and a `what_to_do` hint. The IDs and positions are kept
at the end for filtering. Rows are sorted by arm, then issue.

| issue | what to do |
|---|---|
| literature disagrees with output | The output value differs from Juhi's. The detail says whether the output value is unchanged from the extraction sheet, a GF default, a derived placeholder, or a decision. For rice amounts, the literature value has been put on the arm's basis (× coverage) before comparing. |
| literature could replace placeholder | Usually make it a decision. |
| several literature candidates | Juhi has more than one value for the same thing; pick one. Any she marked `Use in model` are listed first and tagged [recommended] or [not recommended]. |
| recommended literature value differs from output | Juhi marked this value `Use in model` = yes, but the output uses something else. Either add a decision that adopts it, or record why not (e.g. with source `keep` or `gf`). |
| conflicting literature recommendations | More than one candidate with different values is marked yes. Ask Juhi which she means. |
| proposed decision (not applied) | Shows the value it would set next to the current value. |
| literature row needs attention | Fix the source row, or add a typo fix to `common.py`. |
| literature value has no row in the extraction sheet | There's nowhere to put it (e.g. U5 SDs by sex for Nigeria salt, where the sheet has only a Total row). |
| placeholder remains | A `DUMMY`/`DERIVED` value is still in an arm listed in `arms.csv`. |

## Three-way comparison: comparison.xlsx

`comparison.xlsx` has one row per data row of the extraction sheet, with these columns side
by side:
- `existing_value` and `existing_source`: the extraction sheet as it is today;
- `gf_value` and `gf_reference`: what the GF mapping gives. This is shown for every arm in
  `arms.csv`, including those with `apply_gf = no`, so you can see GF's numbers before
  switching an arm on;
- `lit_value`, `lit_as_published` and `lit_ids`: Juhi's matching value(s). `lit_value` is on
  the sheet's basis (rice amounts × coverage, % as fractions); several candidates are listed
  separated by `;`, with `*` marking the one she recommends;
- `lit_recommended_value` and `lit_recommended_id`: her pick, if exactly one value is marked
  `Use in model` = yes. Otherwise these are blank;
- `gf_vs_existing`, `lit_vs_existing` and `lit_vs_gf`: `same` (within 1%) or
  `differs (±x%)`. Cells are shaded green or red. `gf_value` is GF as published, so
  `lit_vs_gf` compares the two sources as published. `lit_vs_existing` puts the literature on
  the sheet's basis first (e.g. × coverage where a decision converts that arm's amounts). The literature comparisons use her
  recommended value if there is one, and otherwise compare only when there is a single
  candidate;
- `output_value`, `output_source` and `decision_id`: what the build actually wrote.

Juhi's values that have no row in the sheet are listed at the bottom. The sheet has filters
turned on, so you can filter, for example, to `lit_vs_existing = differs*`, or to one
country and vehicle. `comparison.csv` holds the same data in a form that diffs well in git.

## Adopting the output

When you're happy with the output, copy it over `../Data Extraction Sheet.xlsx` yourself.
Then regenerate the sheet's text projection: `tests/test_extraction_projection.py` checks
that it's in sync.

    python -m lsff_utils.extraction_projection

## Robustness to Juhi's sheet changing

- **Sheets:** any sheet with `Value` and `Data need` columns is read. Sheets named `OLD…` or
  `Sheet1` are skipped.
- **Columns:** found by header name. Synonyms are in `COLUMN_SYNONYMS` in `extract_lit.py`.
- **Labels:** normalised to our vocabulary. Typo fixes are in `TYPO_FIXES` in `common.py`.
- **Units:** `%` on a 0–100 scale becomes a fraction, `ppm` becomes mcg/g, and `g/dL`
  becomes g/L (flagged for checking).
- **IDs:** without an ID column, each row's ID is a hash of its key fields and data source.
  Editing those fields changes the ID. **Asking Juhi to add an `ID` column (any unique
  text) makes the IDs permanent.**

## Juhi's recommendations: the `Use in model` column

This column is optional; until it exists, everything works as before. It goes on any
sheet of `LSFF_effect_sizes.xlsx`, and the header may be `Use in model`, `Use in model?` or
`use_in_model`. The values are:
- `yes` (also `y`, `true`, `1`, `x`): her recommended candidate;
- `no` (also `n`, `false`, `0`): a candidate she considered and doesn't recommend;
- blank: no view.

Anything else makes the row "needs attention".

It is **advisory only**: it never changes the output workbook. Values still get there only
through `decisions.csv`. In practice:
- **review.csv:** her pick is listed first among candidates. If it differs from the output,
  that's reported as "recommended literature value differs from output". Candidates she
  marked `no` are not reported as separate disagreements when she has marked another
  candidate `yes`.
- **comparison.xlsx:** shows her pick in `lit_recommended_value` and compares against it.

To adopt a recommendation, add a decision with `source = lit:<the recommended lit_id>`. The
ID is shown in review.csv.

## Current state (2 Oct 2026)

Nigeria wheat:
- **Active decisions:** intervention concentrations from the national standard (iron 40,
  folic acid 2.6 mcg/g), and U5 intake from NFCMS Table 148.
- **Consumption** is per capita (the GF default, as published), with SDs from the NFCMS CV
  applied to consumers (D007, D008).

Nigeria rice is unchanged on purpose (among consumers, original SDs; D006), so that its results
stay comparable with earlier runs. To switch it, reject D006 and activate P007 and P008. P008
currently reports as invalid, because Juhi has two candidate rice national means (NFCMS 61.2
and M4N 38). Marking one `Use in model` = yes fixes that.

Proposed, needing your call:
- **P001 Folate baseline:** set to 0, because Nigerian wheat flour isn't fortified with folic acid now.
- **P002 Iron baseline coverage:** 12.6% (NFCMS) vs 79% (GF-derived).
- **P003 Baseline concentration:** 53.9 mcg/g.
- **P004 Compliance:** 73% (NFCMS) vs 63% (M4N).
- **P006 Intervention split:** Juhi's 100%/100% vs √0.85.

Rejected: P005 (NFCMS SDs used as they are). It fails the variance check and is
superseded by D007/D008.
