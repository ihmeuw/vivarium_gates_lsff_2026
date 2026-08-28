# Checklist: adding Nigeria / salt / folic acid to the results

The partner's top-priority triple. This document is the ordered, complete list
of what it takes; each step names who does it and how to know it's done. The
same sequence works for any future folate-only (location, vehicle) pair — only
the data sources change.

**Shape of the addition:** folic acid never enters the Vivarium simulations
(those model iron → hemoglobin only), so this triple touches only the
deterministic stages: data prep (0100), the NTD model (0500), and results
processing (5000). No new artifacts, no cluster runs, no changes to the
pregnancy or child sim packages.

## 0. Already in place (engineering — done on `snakemake-monorepo-port`)

NOTE for readers on `main`: the two items below live on the
`snakemake-monorepo-port` branch and have not been merged yet. The extraction
data (step 1) is branch-independent and already entered.

- [x] Per-(location, vehicle) fortificant gating in
  `5000_analyze_results/Snakefile`. Previously the dalys/cases input functions
  gated on the *location's* fortificants, which would have demanded pregnancy
  and child simulation results for nigeria/salt (nigeria has iron via rice and
  bouillon). Verified DAG-identical for all existing combos, and verified with
  a trial `nigeria,folate,salt` row that the new combo schedules only
  `prep_extracted`, `calculate_effective_coverage_nigeria`,
  `neural_tube_defects_model`, `dalys_by_scenario`, `cases_by_scenario`, and
  the spreadsheet/plots — no simulations, no anemia model.
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
  for Ethiopia, at 3.9 g/day); reach 0.9 × effectiveness 1.0 (*assumption:*
  GF's Nigeria-salt FA compliance cells are literally "XX"; the GAIN
  compliance-targets tab's 90% for Nigeria salt used as proxy).
- [x] Verified by a dry run of the `prep_extracted` machinery redirected to a
  scratch directory: all 12 data needs parse, U5 amounts rescale to the sheet
  totals, and every expected CSV materializes with the intended values. Repo
  result CSVs are untouched until step 5 runs for real.

## 2. Decide the scenario set (research)

- [ ] Default is a single `intervention` scenario, which needs no config
  change. **GF's grid asks for two dose scenarios** (25% and 100% NRV, like
  Ethiopia's), and the extraction rows are entered under those names — so
  this knob decision is now live: `custom_intervention_scenarios` in
  `0050_config/config.yaml` is **location-level**, and listing nigeria there
  would apply the custom scenarios to nigeria's iron vehicles too. Giving
  that knob a vehicle dimension is a small engineering change that must land
  before step 4.

## 3. Anemia pathway — decision parked, deliberately

Current decision: **nigeria/salt does not change anemia.** It is not listed in
`folate_anemia_vehicles`, so the pipeline produces NTD results only for this
combo; the dalys/cases notebooks substitute zero-valued anemia inputs (the
same mechanism ethiopia uses for its absent simulation inputs).

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

- [ ] Add the row `nigeria,folate,salt` to
  `0050_config/location_fortificant_vehicles.csv`. This is the single point
  the whole pipeline reads combos from; do it **after** step 1, because the
  moment the row exists snakemake demands the step-1 files.

## 5. Run

- [ ] `snakemake --cores 4` (artifact env prerequisites as usual). Expected to
  run: `prep_extracted`, `calculate_effective_coverage_nigeria`
  (folate/salt), `neural_tube_defects_model` (nigeria/salt),
  `dalys_by_scenario` + `cases_by_scenario` (nigeria/salt), spreadsheet,
  plots. Expected NOT to run: any simulation, any artifact build, any 0400
  job. If the DAG schedules more than that for this change, stop and look.

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

## Caveats that ride along

- **Stillbirth definition:** the NTD model uses the 28-week
  stillbirth-to-live-birth ratio, chosen to match the sims' `data_keys.SBR`.
  For Nigeria that is ~1/3 *lower* than GBD 2021's unqualified ratio (see the
  note in `0500_neural_tube_defects_model/model.ipynb`) — it scales the NTD
  stillbirth/YLL accounting. Needs a research decision before partner-facing
  numbers ship.
- **Sequencing with the maternal-disorders PAF fix:** the pending PAF fix
  changes iron-combo DALYs ~20%, so plan one results-spreadsheet regeneration
  that includes both changes rather than shipping numbers twice.
- The combos CSV previously lacked a trailing newline, which silently corrupts
  a naive `echo >>` append (fixed alongside this checklist — but check your
  editor didn't strip it again).
