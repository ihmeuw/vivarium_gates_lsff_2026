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
