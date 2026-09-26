# Checklist: adding Nigeria / salt / folic acid to the results

The partner's top-priority triple. This document is the ordered, complete list
of what it takes; each step names who does it and how to know it's done. The
same sequence works for any future folate-only (location, vehicle) pair — only
the data sources change.

**Ported 2026-09-23** from `snakemake-monorepo-port` (d2dda7a + 851813b) onto
current main. Every extracted value was re-checked against the CURRENT
('Updated 22 Jan 2026') tabs of the GF Apr-2026 workbook — the plain-named
tabs are current, the "(2)" tabs are stale 7-Jan copies — and all intake,
coverage, and consolidation values confirm. The scenario compliance encoding
was updated to the 2035 equal-split convention (see step 1).

**Shape of the addition:** folic acid never enters the Vivarium simulations
(those model iron → hemoglobin only), so this triple touches only the
deterministic stages: data prep (0100), the NTD model (0500), and results
processing (5000). No new artifacts, no cluster runs, no changes to the
pregnancy or child sim packages.

## 0. Already in place (engineering — done)

- [x] Per-(location, vehicle) fortificant gating in
  `5000_analyze_results/Snakefile`. Previously the dalys/cases input functions
  gated on the *location's* fortificants, which would have demanded pregnancy
  and child simulation results for nigeria/salt (nigeria has iron via rice and
  bouillon). Verified DAG-identical for all existing combos, and verified with
  a trial `nigeria,folate,salt` row that the new combo schedules only
  `prep_extracted`, `calculate_effective_coverage_nigeria`,
  `neural_tube_defects_model`, `dalys_by_scenario`, `cases_by_scenario`, and
  the spreadsheet/plots — no simulations, no anemia model.
  *(Test run: true of the jobs this combo needs, but rerunning
  `prep_extracted` reschedules every sim through its other outputs; see T1.
  The gating logic itself now lives in `config_utils.get_combo_pathways`;
  see T5.)*
- [x] `folate_anemia_vehicles` knob in `0050_config/config.yaml`, encoding
  which folate-only combos carry an anemia pathway (today: ethiopia/salt).
  Nigeria/salt is deliberately not listed — see step 3.

## 1. Extract the Nigeria/salt data (research — the long pole)

All inputs live in `0100_data_prep/extraction/Data Extraction Sheet.xlsx`,
keyed by (Country, Vehicle[, Fortificant, Scenario]). The Ethiopia/Salt rows
are the template; `prep_extracted.ipynb` turns the sheet into every CSV the
pipeline needs and its `check_totals` guards the arithmetic.

**2026-08-28: extracted**, from the GF "Input data to IHME models" workbook
(2026-04-16), which lists Nigeria salt FA @ 25%/100% NRV as net-new scenarios
(#5/#6 in its grid). Three inputs remain assumptions pending GF confirmation
— see the sheet's Notes cells:

- [x] **"Country-Vehicle Extraction" sheet — Nigeria, Salt:** WRA any-coverage
  0.993 and intake 3.9 g/day (by quintile), U5 0.99 / 2.6 g/day, industry
  consolidation 0.95 (all GF workbook, NFCMS 2021). *Assumption:* intake SDs
  via the Ethiopia salt CV (~0.31) — no salt SD in the GF workbook.
- [x] **"Country-Vehicle-Fort Extraction" sheet — Nigeria, Salt, Folate:**
  baseline FA any/full coverage and concentration = 0 (Nigeria mandates
  iodization, not FA — recorded as data), effectiveness 0.8 (moot at zero
  baseline coverage, matching the sibling rows' convention).
- [x] **"Scenario Definition Extraction" sheet** — two scenarios,
  `Intervention - 25% NRV` and `Intervention - 100% NRV`: concentration
  25.64 / 102.56 µg/g (*assumption:* "NRV per average intake" convention as
  for Ethiopia, at 3.9 g/day); coverage = effectiveness = √0.90 ≈ 0.95
  (*assumption:* GF's Nigeria-salt FA compliance cells are blank on the
  current tabs, so the GAIN compliance-targets tab's new-compliance 90% is
  the proxy, encoded per the 2035 equal-split convention adopted 2026-09-09
  — same as Ethiopia salt. Alternative pending GF confirmation: Alem's
  projections on the workbook's "Notes for Discussion" tab recommend Nigeria
  salt compliance 100% for both 2030 and 2035, which would encode as
  1.0 × 1.0).
- [x] Verified by a dry run of the `prep_extracted` machinery redirected to a
  scratch directory: all 12 data needs parse, U5 amounts rescale to the sheet
  totals, and every expected CSV materializes with the intended values. Repo
  result CSVs are untouched until step 5 runs for real.

## 2. Decide the scenario set (research)

- [x] **Decided: two dose scenarios**, `intervention_25_nrv` and
  `intervention_100_nrv`, matching GF's grid and the extraction rows.
  `custom_intervention_scenarios` in `0050_config/config.yaml` is now keyed
  by (location, vehicle) (`config_utils.get_intervention_scenarios`), so
  `nigeria: {salt: [...]}` leaves nigeria's rice and bouillon on the default
  `intervention` scenario. Because a rule's outputs can't depend on the
  `{vehicle}` wildcard, nigeria/salt effective coverage has its own rule,
  `calculate_effective_coverage_nigeria_salt`. Both comparisons (vs baseline)
  are listed in `0050_config/location_vehicle_scenario_comparisons.csv`,
  which the spreadsheet and plots rules now declare as an input.

## 3. Anemia pathway — decision parked, deliberately

Current decision: **nigeria/salt does not change anemia.** It is not listed in
`folate_anemia_vehicles`, so the pipeline produces NTD results only for this
combo. `config_utils.get_combo_pathways` reports `has_anemia_model=False`,
and the dalys/cases notebooks substitute zero-valued anemia inputs, the same
mechanism ethiopia/salt uses for its absent simulation inputs (see T5 below).

- [ ] Revisit later if the team wants folate-deficiency anemia for Nigeria
  (the ethiopia/salt precedent). Flipping it on requires, in order:
  1. Add `nigeria: [salt]` under `folate_anemia_vehicles` in
     `0050_config/config.yaml`.
  2. Generalize `non_pregnant_anemia_ethiopia_folate` in
     `0400_non_pregnant_anemia_model/Snakefile` (currently hardcoded to
     ethiopia) and review `non_pregnant_anemia_folate.ipynb`'s
     folate-deficiency-anemia inputs for Nigeria.
  3. Rerun from 0400 down; the dalys/cases zeros are replaced automatically.

## 4. Flip the switch (engineering — one line)

- [x] Add the row `nigeria,folate,salt` to
  `0050_config/location_fortificant_vehicles.csv`. This is the single point
  the whole pipeline reads combos from; do it **after** step 1, because the
  moment the row exists snakemake demands the step-1 files.

## 5. Run

- [x] ~~`snakemake --cores 4`~~ **Corrected (T1 below):** a plain run *does*
  schedule every artifact build and simulation. Once `prep_extracted` runs,
  Snakemake treats all of its outputs as updated, including the iron
  coverage/consumption CSVs the sims read, even though their contents don't
  change. Instead:
  1. Run data prep on its own:
     `snakemake --cores 4 --config skip_data_prep=true --until prep_extracted
     calculate_effective_coverage_nigeria calculate_effective_coverage_nigeria_salt
     calculate_effective_coverage_india calculate_effective_coverage_ethiopia`
  2. `git diff --stat 0100_data_prep/results`: existing CSVs must be
     unchanged; only new `.../salt/.../nigeria.csv` files appear (16 of them).
  3. Run the rest without the timestamp trigger:
     `snakemake --cores 4 --rerun-triggers params input software-env code`.
     Expected: `neural_tube_defects_model` for every combo (its notebook was
     edited, T2), 0400 for the iron combos and ethiopia/salt (same reason),
     `dalys_by_scenario` + `cases_by_scenario` for every combo (params
     changed, T5), spreadsheet, plots. No artifacts, no simulations.

## 6. V&V (research + engineering)

- [ ] `prep_extracted`'s `check_totals` passes on the new rows.
- [ ] Coverage sanity (the V&V strategy's P9/P10 analog): baseline effective
  coverage ≈ 0; intervention effective coverage by quintile matches the
  extraction targets after the quintile calculation.
- [ ] NTD burden sanity: `0500 .../nigeria/salt/ntd_cases_by_scenario.csv`
  baseline vs GBD's Nigeria NTD births estimate, and the intervention delta
  vs the folate-responsive fraction assumed in `model.ipynb`.
- [ ] Commit the new result CSVs. The regression harness's deterministic
  layer (`tests/test_deterministic_results.py`) enumerates *tracked* result
  CSVs, so committing them is what makes them a guarded baseline; the next
  freshness-aware run then verifies they reproduce.
- [ ] Review the new rows in `results_spreadsheet.xlsx` before they go to the
  partner.

## Test-run log: what it actually took (branch `ndbs/test-nigeria-salt-folate`)

This branch is a trial run, not for merging. It records every change needed
to get nigeria/folate/salt through the pipeline, so the work can be
re-implemented on main in smaller pieces. Each item names the problem, the
fix, and where it lives.
The branch starts from [`3b52d06`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/3b52d06b6f49fda4e2e77882ce25fd6ecbbb7354), which merges `abie/nigeria-salt-folate`
into the full pipeline run on main. The combo row itself (step 4) is
[`856d298`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/856d298b28f3288656cd19126c2c77eadb485291).

**T1. Data-prep reruns pull in the simulations.**
*Problem:* editing `Data Extraction Sheet.xlsx` makes `prep_vehicle` and
`prep_extracted` newer than their outputs. Adding a combo also leaves some
of their outputs missing. Either way Snakemake reruns them, then reschedules
everything that reads any of their outputs: artifacts, both sims, 0400, 5000.
It can't know the regenerated iron CSVs will be byte-identical. Step 5's
original "no simulations" expectation was wrong for this reason.
*Workaround used:* run 0100 alone, diff its outputs, then run the rest with
`--rerun-triggers` excluding `mtime` (step 5).
*For main:* structural. Either split `prep_extracted` so the iron-sim inputs
don't depend on the whole workbook, or make the sim inputs depend on content
(e.g. a checksum-stamped marker) rather than on timestamps.
*Commits:* none (a workaround, not a code change). The run it describes is
[`afc9a14`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/afc9a146debbac8005bb0f9ba9ee6e4931b85038), which re-executed the existing combos' notebooks and changed
no result CSVs (only executed notebooks and the spreadsheet), confirming
the iron inputs were unchanged. [`041c7f6`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/041c7f6bc24d825a4f3bb0b4ba4bbf6b5ce35d11) adds the new nigeria/salt
outputs.

**T2. Intervention scenarios are configured per (location, vehicle).**
*Problem:* `custom_intervention_scenarios` was keyed by location only.
Nigeria/salt needs `intervention_25_nrv` and `intervention_100_nrv`, but
listing `nigeria` there would have given rice and bouillon those scenarios
too. Without it, `prep_extracted` looked for an `intervention` scenario that
the workbook doesn't have and failed its `assert len(sheet) > 0`.
*Fix:*
- `config.yaml` is now nested `location → vehicle → [scenarios]`.
- New helper `config_utils.get_intervention_scenarios(location, vehicle)`,
  which also validates the block (rejects the old layout and typo'd pairs).
- Every caller now uses the helper: the 0100, 0400 and 0500 Snakefiles; the
  `model.ipynb`, `non_pregnant_anemia.ipynb` and
  `non_pregnant_anemia_folate.ipynb` notebooks; and the coverage notebook,
  which had its own hardcoded per-location list.
- A rule's outputs can't depend on the `{vehicle}` wildcard, so nigeria/salt
  coverage got its own rule, `calculate_effective_coverage_nigeria_salt`.
  The nigeria rule is limited to its default-scenario vehicles.
- Tests in `tests/test_config_utils.py`.

*Commits:* [`1633b21`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/1633b2130fd207f7399b85c308bf6bc804ada991) (config, helper, callers, coverage rule),
[`a89edab`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/a89edab7e67dcfa53c89a2eed01f04af86876693) (tests; `CONFIG_DIR` made a module constant so tests can
use a scratch config).

**T3. Scenario comparisons.**
*Fix:* added the two nigeria/salt comparisons to
`location_vehicle_scenario_comparisons.csv` (the file also lacked a trailing
newline). Declared the CSV as an input to `results_spreadsheet` and
`results_plots`, which loop over it but didn't list it.
*Commits:* [`4a983e4`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/4a983e472a3d7676114c5c4294be663ee2b06f8f).

**T4. U5 salt consumption rows didn't match `prep_extracted`.**
See the resolved "U5 disaggregation vintage" caveat below. Ten U5 quintile
rows were deleted from the workbook, and the U5 SD row's Sex was set to
`All (assumed same)`. The SD rows' note should also be corrected: the ~0.31
ratio divides an Addis Ababa survey SD (2.2) by Ethiopia's national mean
(7.1). The Addis survey's own mean is 7.5, which gives ~0.29.
*Commits:* [`12db424`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/12db424d6a66a974cd620fb6f66ae9874c6e33ec) (workbook rows and the caveat). That commit also
corrects the SD note on the U5 row (row 109). The same note was then applied
to the WRA SD row (row 99) in a follow-up commit.

**T5. Result notebooks branched on "does the file exist?".**
*Problem:* the Snakefile decides which result pathways a combo has (iron
sims, 0400 anemia, 0500 NTD) and declares inputs to match. But
`dalys_by_scenario.ipynb` and `cases_by_scenario.ipynb` re-decided with
`if pathlib.Path(path).is_file()`, falling back to india/rice's files as an
all-zero template. Nothing declared those fallbacks. Nigeria/salt's
`cases_by_scenario` started before `0400/.../rice/india/anemia_cases.parquet`
existed and crashed with `FileNotFoundError`. The design had two further
hazards:
- a file missing by mistake (bug, half-finished run) became zeros silently;
- the dalys NTD fallback read a stale `0500/.../india/rice/intervention/`
  file left over from an older layout. The first iron-only combo (e.g.
  nigeria/iron/wheat on `albrja/mic-7549`) would have hit it.

*Fix:*
- `config_utils.get_combo_pathways(location, vehicle)` returns
  `has_simulations`, `has_anemia_model` and `has_ntd_model`. It is the one
  source of truth.
- The 5000 Snakefile declares either the combo's own files or the india/rice
  template for each pathway, and passes the three flags to papermill.
- The notebooks branch on the flags, so an expected file that is missing now
  raises instead of becoming zeros.
- The dalys NTD fallback now points at the current path.
- The Snakefile asserts that the template combo has every pathway.
- Checked with dry runs for nigeria/salt, ethiopia/salt, india/rice and a
  hypothetical nigeria/iron/wheat.

*For main:* consider building the zero frames directly (a helper in
`lsff_utils.results`) instead of reading india/rice's files, so no combo
depends on another's outputs. Delete the stale
`0500_neural_tube_defects_model/results/india/rice/intervention/` files,
which nothing reads now.
*Commits:* [`d4fbb85`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/d4fbb8524cf030d9eeddf031e2e231bb6fa6b4cd) (flags, declared templates, notebooks, tests,
and this log). The nigeria/salt 5000 outputs in [`041c7f6`](https://github.com/ihmeuw/vivarium_gates_lsff_2026/commit/041c7f6bc24d825a4f3bb0b4ba4bbf6b5ce35d11) were
produced before this change, after rerunning past the race. Regenerate
them under the flags; the values should be identical.

## Caveats that ride along

- **Stillbirth definition:** the NTD model uses the 28-week
  stillbirth-to-live-birth ratio, chosen to match the sims' `data_keys.SBR`.
  For Nigeria that is ~1/3 *lower* than GBD 2021's unqualified ratio (see the
  note in `0500_neural_tube_defects_model/model.ipynb`) — it scales the NTD
  stillbirth/YLL accounting. Needs a research decision before partner-facing
  numbers ship.
- **Sequencing with pending engine changes:** the two-pass LBWSG PAF
  correction (held for engineering review) moves iron-combo levels 3–6%, so
  if it lands near the same time, plan one results-spreadsheet regeneration
  that includes both changes rather than shipping numbers twice. (The
  maternal-disorders PAF fix this caveat originally named landed in the
  1.1.x series.)
- **U5 disaggregation vintage (resolved 2026-09-25):** the salt extraction
  originally carried U5 quintile rows copied from the WRA pattern (noted as
  "rescaled by check_totals(fix=True)", but never actually rescaled: mean
  ~3.9 g/day vs the 2.6 g/day U5 total), plus a single Total/Total U5 SD
  row. Since PR #27, `interpolate_extrapolate_consumption_amount` in
  prep_extracted derives Nigeria U5 quintiles itself from the WRA gradient
  (means directly, SDs in variance space) and expects U5 rows at the
  national and by-sex level only, so the old rows failed
  `check_totals_reasonable`. The 10 U5 salt quintile rows were deleted and
  the U5 SD row (0.81) was set to Sex `All (assumed same)`. The salt rows
  now match the rice/bouillon layout and prep_extracted runs end to end,
  leaving all existing CSVs unchanged. Open choice: this gives girls and
  boys the same U5 SD. Applying the borrowed CV (~0.31) to each sex's mean
  would give ≈0.78 (F) / ≈0.84 (M), like the sex-specific SDs rice and
  bouillon carry.
- The combos CSV previously lacked a trailing newline, which silently corrupts
  a naive `echo >>` append (fixed alongside this checklist — but check your
  editor didn't strip it again).
