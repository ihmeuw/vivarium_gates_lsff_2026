# Building the extraction tables

This folder builds the generated extraction tables (`../generated/*.csv`, which the data prep
notebooks read) from:

- the base tables, `../data/*.csv`: hand-entered values with no other source;
- the literature extraction, a snapshot in `lit_long.csv`;
- the Gates Foundation (GF) background data, a snapshot in `gf_long.csv`;
- `decisions.csv` (choices), edited by hand;
- the model config's list of arms, `0050_config/location_fortificant_vehicles.csv` (scope).

```
python extract_lit.py --lit <LSFF_effect_sizes.xlsx>   # literature workbook -> lit_long.csv
python extract_gf.py --gf <Nutrition PST Background Data.xlsx>   # GF workbook -> gf_long.csv
python build_extraction.py           # -> ../generated/*.csv, STATUS.md, review.csv,
                                     #    changelog.csv, comparison.csv (and .xlsx)
python build_extraction.py --check   # exit 1 if ../generated/ is out of date
```

Rebuild whenever a base table, a snapshot, `decisions.csv` or the model's list of arms
changes, and commit the generated tables and reports with the change: their git diffs show
exactly what changed. The build also prints every value that differs from the generated
tables on disk before overwriting them.
Snakemake doesn't run the build: before data prep (unless `skip_data_prep=true`), its rule
`check_extraction` runs `build_extraction.py --check` and stops the run if the committed
tables are out of date. `tests/test_extraction_build.py` makes the same check.
`build_extraction.py --lit-long <file>` lets you try a draft snapshot without replacing
`lit_long.csv`.

Other documents here:
- `GF_DATA_MAPPING.md`: how GF's terms map onto ours, which extraction rows the model
  reads, the rules built into the GF defaults, questions to raise with GF, and open issues.
- `CONSUMPTION_DISTRIBUTION.md`: why survey consumption SDs can't be used directly, the
  interim fix, and a proposed redesign of the consumption model.

Terms used in the outputs:
- **base**: the hand-edited tables in `../data/`.
- **output**: the generated tables in `../generated/`.
- **tab** and **row**: the table and the row's position in it (header = row 1, as in Excel),
  which is the same in both layers.

## Source workbooks and snapshots

The two source workbooks are not kept in the repo. The literature workbook is a working
document on SharePoint; the GF workbook is a partner deliverable, archived there as received.
The repo holds their extracts, `lit_long.csv` and `gf_long.csv`, which are what the build
reads. `sources.csv` records, for each snapshot, the source file's name, its saved date and
SHA-256, and when it was extracted. The extract scripts update it.

To take in a new version of either workbook: download it, run its extract script with the
file's path, rebuild, and review the diffs of the snapshot, `STATUS.md` and `../generated/`.
The extract scripts need `openpyxl`; the build itself needs only pandas and numpy.

## Where to start: STATUS.md

`STATUS.md` is regenerated on every build. It lists:
- **Automatic choices made by the build**: rows where a rule built into the GF defaults
  (not a decision) stopped a GF number being used;
- for each arm the model runs: the decisions in effect (what each targets, the
  value it sets, where the value comes from, and its rationale), proposed decisions with what
  they would set, and what is still open, with output and literature values side by side.

No IDs need looking up. It is the current state of the build, so this README doesn't repeat it.

## How a value gets into the output

Each input file has one job:
- the base tables hold **values with no other source**;
- the model's list of arms is **scope**: which arms take default values and are checked;
- `build_extraction.py` holds the **methods**: how values are converted or computed;
- `decisions.csv` holds the **choices**: which value or method applies where, and why.

The build has four phases. Each phase can override the one before it, and a row no phase
touches keeps its base value.

1. **Defaults**, for the arms the model runs, from two sources whose order depends on the
   kind of data:
   - **Measurements** (consumption, baseline fortification, concentrations): the literature
     first, then GF for rows the literature leaves unset. The literature cites the primary
     sources, which GF often rounds.
   - **2035 targets** (fortifiability, intervention coverage and effectiveness): GF first,
     then the literature. GF's consolidation and compliance targets define the scenarios;
     the literature's values for these describe the current state.

   GF values are used as published, following the mapping in `GF_DATA_MAPPING.md`, apart
   from a few built-in rules listed there under "Automatic rules". A literature value is used
   only if its candidates agree: candidates marked `Use in model` = no are ignored, and if
   any are marked yes only those count. If the rest disagree, the build fails (phase 4)
   unless a decision covers the row, so a row never switches source silently because a
   candidate was added.

   Arms the model doesn't run take no defaults and aren't checked, so a half-extracted arm
   can't break the build; decisions that target them still apply (STATUS.md lists those
   arms too), and `comparison.csv` shows GF's and the literature's values for them. Adding
   an arm to `0050_config/location_fortificant_vehicles.csv` fills it in on the next build.
   Effect sizes (`vehicle.csv`) take no defaults; they change only through decisions. For
   India rice, whose consumption, fortifiability and PDS shares come from HCES microdata,
   only intervention rows and GF's baseline split take defaults (`HCES_ARMS` in
   `build_extraction.py`; see `GF_DATA_MAPPING.md`).
2. **Value decisions**: active decisions whose source is `lit:`, `value:`, `gf` or `keep`.
   Those with `transform = times_coverage` run last, once coverage is final.
3. **Method decisions**: active decisions whose source is `method:<name>`. These compute a
   value from others already in place.
4. **Checks**. If any fail, the build stops without writing the tables (`review.csv` is
   still written, except with `--check`). Before any phase, malformed input also stops the
   build: a duplicated data point in a base table, an unknown arm or fortificant in the
   model config, or a malformed decision (unknown status, need, source or transform). The
   checks are:
   - every row whose literature candidates disagree is resolved, by a `Use in model` mark
     or a decision;
   - percentages are in [0, 1] (every row the build sets);
   - for the arms the model runs, apart from India rice (HCES) and arms without amount rows:
     consumer variance is > 0 (needed by the pregnancy sim); each amount Total is within 10%
     of its quintile mean (prep_extracted's check); intervention coverage × fortifiability ≥
     baseline coverage (the coverage notebook's check; for India rice, intervention coverage
     ≥ the share of PDS rice fortified).

A row the build sets gets a `Data source` naming where its value came from, `Notes` with the
reference, the method or rationale and the base value, and (in `country_vehicle`) a
`Derivation` when the value was computed. This happens even when the value equals the base
value, so a placeholder label never survives on a real value. Its CI and SE are cleared if
the value moved by more than 1%, and a base `Derivation` is cleared if the value changed
without one. Every other cell is copied from the base table unchanged.

## decisions.csv

One row per choice. Status, transform and surrounding spaces are normalised, and anything
malformed stops the build. Blank target fields match any value, so one decision can cover,
for example, all three Ethiopia scenarios or both fortificants. For effect sizes
(`vehicle.csv`), only `vehicle` and `data_point_name` are used to match rows; other target
fields are ignored.

| column | meaning |
|---|---|
| `decision_id` | Unique. By convention, `D…` for decisions made as active and `P…` for proposals. |
| `status` | `active` (applied), `proposed` (shown in STATUS.md and review.csv with its effect, not applied), or `rejected` (kept for the record). |
| `need` | A short alias: `any`, `amount`, `u5_any`, `u5_amount`, `fortifiability`, `baseline_any`, `baseline_concentration`, `baseline_effectiveness`, `intervention_coverage`, `intervention_effectiveness`, `intervention_concentration`, `hb_effect` or `bw_effect`. The full data-need text also works. |
| `country` … `data_point_name` | Which rows the decision targets. |
| `source` | One of: `lit:<id>` (a row of lit_long.csv); `value:<number>`; `gf` (GF's value, even where the literature default differs; rows GF has no value for are left as they were); `keep` (the base value); `method:<name>` (compute the value; see below). |
| `transform` | Optional, for `lit:`, `value:` and `gf` sources: `sqrt` (√ rounded to 2 d.p., the compliance split) or `times_coverage` (× the row's WRA coverage, national for U5 rows; turns a mean among consumers into a mean over all women). |
| `rationale`, `decided_by`, `date` | Why. The rationale is copied into the output's Notes. |

Methods (`source = method:<name>`), implemented in `build_extraction.py`:

| method | applies to | computes |
|---|---|---|
| `consumer_cv` | amount and U5 amount SD rows | SD over all women when consumers get the literature's CV (the literature mean and SD for the same quintile or sex). See `CONSUMPTION_DISTRIBUTION.md`. |
| `scale_to_gf_total` | amount mean rows | Rescales the quintile means so they agree with GF's national g/cap, keeping the wealth gradient. |
| `derive_from:<vehicle>` | amount SD rows, U5 mean rows | A placeholder borrowed from another vehicle: its consumer CV, or its U5/WRA ratio. Tagged `DERIVED (MIC-7549)` and reported as a placeholder. |

Methods run after all value decisions, in file order, so they see the final means and coverage.

A typical loop:
1. In `STATUS.md` or `review.csv`, find an open item.
2. Add a decision for it, starting as `proposed`. For literature values, copy the `lit_id`
   from `review.csv`.
3. Rebuild and check what it would set in `STATUS.md`.
4. Change its status to `active` and rebuild.

Rejecting a decision and rebuilding restores whatever the earlier phases give that row; no
value outlives the decision that set it.

If a decision's literature row disappears (because its ID changed in the literature
workbook), the build stops, names the decision, and suggests the rows that could replace it.

Editing `decisions.csv` in Excel works. `.gitattributes` keeps its line endings consistent in
git, and the build tolerates the byte-order mark Excel adds when saving as "CSV UTF-8". Check
`git diff` before committing, since Excel can reformat values such as dates.

## Other outputs

**review.csv** has the open items from `STATUS.md` as a filterable table. Each row spells out
its `arm`, `item` (the data need in plain words), `where` (scenario, quintile or sex),
`output_value`, `literature` (value, source, and tab and row in the literature workbook), the
`decision` (ID, status and rationale) and a `what_to_do` hint. IDs and positions are at the
end. Rows are sorted by arm, then issue. Literature values for 2035 targets that GF supplies
(fortifiability, intervention coverage and effectiveness) aren't reported: they describe the
current state, so they're expected to differ.

| issue | what to do |
|---|---|
| placeholder remains | A `DUMMY`/`DERIVED` value is still in an arm the model runs, or in an effect size. Give it a real value, or a `keep` decision if the placeholder is deliberate. |
| GF national inconsistent with GF quintiles | The base Total was kept by the automatic rule. Rescale with `method:scale_to_gf_total`, or record a `keep` decision. |
| GF disagrees with literature default | The literature value is in use and GF's differs. Use GF with a `gf` decision, or confirm the literature with a `lit:` decision. |
| recommended literature value differs from output | A value marked `Use in model` = yes isn't what the output uses. Adopt it, or record why not. |
| literature could replace placeholder | Usually adopt it with a `lit:` decision. |
| literature disagrees with output | Decide which is right. The detail says whether the output value is the base value, a literature or GF default, a derived placeholder, or a decision. Where a decision converts an arm's amounts with `times_coverage`, the literature value is converted the same way before comparing. |
| several literature candidates | The literature has more than one value for the same thing (in an arm the model runs, the build fails until this is resolved, unless a decision covers the row). Pick one with a decision, or mark one `Use in model` in the literature workbook. Marked candidates are listed first and tagged [recommended] or [not recommended]. |
| conflicting literature recommendations | More than one candidate with different values is marked yes. |
| proposed decision (not applied) / is invalid | Set its status to active or rejected, or fix it. |
| literature row needs attention | Fix the row in the literature workbook, or add a typo fix to `common.py`. |
| literature row can't be matched | A literature row matches table rows but isn't used: its scenario is blank where the arm has several intervention scenarios, or its units differ from the table's. Fix it in the literature workbook. |
| literature value has no row in the extraction sheet | There's nowhere to put it (e.g. U5 SDs by sex where the table has only a Total row). |

**changelog.csv** lists every row the build planned: `old_value` (base) and `new_value`
(output); `source` (literature, GF, typed value, literature CV applied to consumers, derived
from <vehicle>, or base extraction table); `step` (literature default, GF default, decision,
or derived placeholder) and `decision_id`; `reference` (the exact GF cell or literature row);
and `overrides` (what it replaced).

**comparison.csv** (and `comparison.xlsx`, the same with colours, written when openpyxl is
installed; gitignored) has one row per data row of the extraction tables, with these side by
side:
- `base_value`, `base_source`: the base table;
- `arm_modeled`: whether the model runs this arm;
- `gf_value`, `gf_reference`: GF as published, through the GF mapping. Shown for every arm,
  including those the model doesn't run;
- `lit_value`, `lit_as_published`, `lit_ids`: the matching literature value(s). `lit_value`
  is on the table's basis (e.g. × coverage where a decision converts the arm's amounts; % as
  fractions). Several candidates are separated by `;`, with `*` on the recommended one;
- `lit_recommended_value`, `lit_recommended_id`: the candidate marked `Use in model` = yes,
  if exactly one is;
- `gf_vs_base`, `lit_vs_base`, `lit_vs_gf`: `same` (within 1%) or `differs (±x%)`.
  `lit_vs_gf` compares both sources as published. The literature comparisons use the
  recommended value if there is one, otherwise only a single candidate;
- `output_value`, `output_source`, `decision_id`: what the build wrote.

Literature values with no row in the tables are listed at the bottom.

## The literature workbook

`extract_lit.py` is built to survive the literature workbook being edited and reformatted:

- **Sheets:** any sheet with `Value` and `Data need` columns is read. Sheets named `OLD…` or
  `Sheet1` are skipped.
- **Columns:** found by header name. Synonyms are in `COLUMN_SYNONYMS` in `extract_lit.py`.
- **Labels:** normalised to our vocabulary. Typo fixes are in `TYPO_FIXES` in `common.py`.
  An unrecognised population (see `POPULATIONS` in `extract_lit.py`) makes the row "needs
  attention", so it isn't used.
- **Units:** `%` on a 0–100 scale becomes a fraction, `ppm` becomes mcg/g, and `g/dL`
  becomes g/L (flagged for checking).
- **Row IDs:** an `ID` column (any unique text, never reused; headed `ID`, `Lit ID` or
  `Row ID`) gives each row a permanent ID, `lit:<ID>`; a duplicated ID stops the extract.
  Without one, each row's ID is a hash of its key fields and data source, so editing those
  fields changes the ID and breaks the decisions that use it. Adding the `ID` column is
  recommended; when it is added, decisions that use hash IDs need updating once.
- **Matching to table rows:** by country, vehicle, fortificant, data need, data point name,
  quintile (a national value also matches an `All (assumed same)` row) and sex; by scenario
  for intervention rows. A row is not used if its scenario is blank and the arm has several
  intervention scenarios, or if its units differ from the table's ("literature row can't be
  matched" in `review.csv`).

### The `Use in model` column

The person doing the extraction can mark which candidate they recommend when there are
several values for the same thing. The column can go on any sheet, headed `Use in model`,
`Use in model?` or `use_in_model`, with values:
- `yes` (also `y`, `true`, `1`, `x`): the recommended candidate;
- `no` (also `n`, `false`, `0`): considered and not recommended;
- blank: no view.

Anything else makes the row "needs attention".

It decides the literature default when candidates disagree (see phase 1 above), and changes
what is reported: the recommended candidate is listed first, a recommendation that differs
from the output gets its own review item, and candidates marked `no` aren't reported as
separate disagreements when another candidate is marked `yes`. `comparison.csv` compares
against the recommended value. `method:consumer_cv` picks its literature mean and SD by the
same rules as the defaults, except that a row set by an active `lit:` decision uses that
decision's literature row.
