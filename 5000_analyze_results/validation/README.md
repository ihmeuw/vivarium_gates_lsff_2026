# Automated V&V — status tracker

Tracks the research V&V list against what the validation lib can actually check.
Notebooks live in `notebooks/` (this tracker's automated V&V), with the hand-written
checks in `child_model/` and `pregnancy_model_NO/`. Update the status column as things
land.

**What every notebook here reads.** The archived iteration named by
`lsff_utils.paths.MODEL_NUMBER` — resolved through `paths.archive_root`, so no path or
run timestamp is pasted into a notebook and none has to be updated after a rerun. Set
`location` / `vehicle` in the first cell for the arm you want, and `model_number` to read
a previous iteration; see "Reading an archived iteration" in the root `README.rst`. This
means a notebook checks what `archive_last_run.sh` published, so **archive before
validating** — a run still only in the working tree is not what these read.

**Commit executions with their cell outputs.** These notebooks carry version-free
filenames and are rerun in place each iteration (`77aafea`), so the run-over-run diff is
the git history. Which run an execution used was pinned by the literal path in its first
cell; now that no path is written down, the pin is that cell's printed output —

```
model1.1.1 bouillon/nigeria
  results:  /mnt/team/.../results/model1.1.1/child/bouillon/nigeria/2026_08_28_20_20_09
  artifact: /mnt/team/.../artifacts/model1.1.1/child/bouillon/nigeria.hdf
```

— together with `MODEL_NUMBER` at that commit. Strip the outputs and the record of what
was validated goes with them. `LSFF_model0_phase2_version_mat_dis_anemia.ipynb` is the
exception to all of this: a frozen record of the model-0 comparison, pointed at the
legacy `vivarium_gates_lsff_by_wealth_quintile` archive, and not rerun.

**Status key**

| | Meaning |
| --- | --- |
| **OK** | Working comparison, in the notebook now |
| **T1** | Tier 1 — results plumbing only, no change to model behavior |
| **T2** | Tier 2 — needs a custom `RatioMeasure` |
| **T3** | Tier 3 — needs research input (reference data or a model decision) |
| **DROP** | Not worth doing; reason given |

**Two facts that apply to many rows, so they are not repeated below**

1. **Sim-vs-sim is not supported.** `FuzzyComparison.verify` requires `test_source == "sim"`
   and `ref_source in ("artifact", "gbd")`. Every "intervention scenario check / comparison
   with baseline" item is therefore out of scope for this tool, independent of whether the
   sim emits the quantity. Those rows are marked T2/T3 for the *baseline* half only.
2. **Wealth-quintile stratification is only validatable against a wealth-stratified key.**
   `verify` stratifies on the intersection of test and reference index names. `wealth_quintile`
   is on every sim output but on none of the artifact keys backing an OOTB measure, so it is
   silently marginalized away. The only key that carries disparities and could support it is
   `cause.*.incident_probability` (maternal, row P4).

## Pregnancy sim

| # | Research V&V item | Status | Detail |
| --- | --- | --- | --- |
| P1 | Baseline coverage levels for fortification | T3 | **Reason corrected 2026-09-16 — it is not a missing key.** `iron_fortification.baseline_any_coverage` / `.baseline_full_coverage` / `.intervention_coverage` all exist in `constants/data_keys.py`, and `IronFortification` draws coverage straight from them. The blocker is that the effectiveness knockout is applied *in place* (`intervention.py:405`, `pop_update.loc[ineffective, "iron_fortification"] = 0.0`), so the column that reaches the state table holds coverage x effectiveness — with `baseline_effectiveness` = 0.8 in Nigeria, counting it against a coverage key would report a 20% shortfall and call it a defect. `IronFortificationObserver` (added 2026-09-16) therefore emits `effective_iron_fortification_count`, named for what the column actually holds. Unblocking this needs `IronFortification` to keep the pre-knockout value as its own column — a component change, ticketed separately |
| P2 | ACMR | DROP | `MaternalMortality.standard_lookup_tables` drops the all-cause rate — only maternal-disorder deaths are modelled. `CauseSpecificMortalityRate("all_causes")` would run and compare a maternal CSMR against a general-population ACMR. Adding background mortality is a model change |
| P3 | Prevalence of anemia by severity | **T2, unblocked for the severe level** | **Correction 2026-09-16: "no anemia artifact key at all" was wrong.** `risk_factor.hemoglobin.pregnant_proportion_below_70_gL` exists, and 70 g/L is exactly the severe-anemia threshold for pregnant women 15+. So severe anemia has a reference: numerator `person_time_anemia` with `sub_entity = severe` (or `hemoglobin_below_70_count`, added 2026-09-16), denominator `person_time_population` (added 2026-09-16). Needs only a custom `RatioMeasure`. Caveat: ages 10–15 use a threshold of 80, not 70 (`data_values._hemoglobin_threshold_data`), so stratify by age group. Mild/moderate remain blocked on a reference, and (b) the `RiskExposure` level-name asymmetry still applies to the `.exposure` route |
| P4 | Incidence rate of maternal disorders and maternal hemorrhage | **T2 — needs no sim change at all** | Best first custom measure. Sim emits `transition_count_*` + susceptible person-time; artifact has `incident_probability`, which is what `ParturitionSelectionTransition` consumes. Built-in `Incidence` can't: it wants `cause.*.incidence_rate` (absent) and its weights want `cause.*.prevalence` (absent). Only row where wealth stratification is validatable. **Confirmed 2026-09-16:** the state/transition names in `constants/models.py` already match what the library's `TransitionCounts` / `StatePersonTime` formatters construct — `susceptible_to_maternal_disorders_to_maternal_disorders` and `susceptible_to_maternal_disorders`. The custom class only has to point at `.incident_probability` and supply `rate_aggregation_weights` that do not need `cause.*.prevalence`. Purely 5000-package work |
| P5a | CSMR of maternal disorders | **runs; not a meaningful check** | `cause.maternal_disorders.cause_specific_mortality_rate`, in `maternal_validation.ipynb`. Runs end to end on `legacy_1.0/maternal/nigeria/2026_08_06_16_51_40` and the report renders after the year-bin fix, but the result is not usable. Three compounding problems: (1) non-integer person-time denominators make the Bayes factor `nan`, so `reject_null` can never be True — the "No significant difference / Conclusive" verdict on observed 0.00424 vs target 0.0309 is vacuous; (2) `verify` inflates the target ~52x via `/ step_size` when observed is already an annual rate; (3) **even with 1 and 2 fixed**, `UntrackNotPregnant` registers `register_tracked_query`, so the sim denominator is pregnancy-exposure person-time while GBD's CSMR denominator is all women — a ~7x gap by construction, not a defect. Making this meaningful needs a pregnancy-denominator reference, or reframing as maternal deaths per pregnancy against `cause.maternal_disorders.mortality_probability` (CSMR ÷ raw incidence, which is what the model actually consumes). That reframing is Tier 2 |
| P5b | CSMR of maternal hemorrhage | DROP | Artifact key exists but the sim never attributes a death to hemorrhage. `mortality_probability` is the all-maternal-disorders case fatality, and `load_pregnant_maternal_hemorrhage_incidence` subtracts `mh_csmr` so the hemorrhage state holds survivors only. Splitting them out changes model results |
| P6 | YLLs and YLDs for maternal disorders and hemorrhage | **T2, unblocked** | `ylls` / `ylds` already emitted in standard form; `cause.maternal_disorders.ylds` exists as an artifact key, and `person_time_population` (added 2026-09-16) is the denominator. Needs only a YLD measure class |
| P7 | Anemia YLDs | T2 | Same as P6; `DisabilityObserver` subclass already adds anemia as a cause of disability. No `cause.anemia.ylds` artifact key, so the reference is still open |
| P8 | Hb distribution | **T2** | Sim side landed 2026-09-16: `HemoglobinObserver` emits `hemoglobin_exposure_sum` and `raw_hemoglobin_exposure_sum`, so mean Hb is available over `person_time_population`. The artifact has `.mean` / `.standard_deviation` rather than `.exposure`, so a *mean* comparison is a custom measure and a full distribution comparison still needs the standard deviation out of the sim |
| P9 | LBWSG distribution | T3 | Birth weight / GA leave the sim only via the `births` concatenating line list. Artifact has the LBWSG exposure key, but `RiskExposure` needs `person_time_<risk>` and mothers don't accrue person-time in an LBWSG category |
| P10 | Fortification coverage and vehicle consumption rates | **consumption T2, coverage blocked** | `IronFortificationObserver` (2026-09-16) emits `any_vehicle_consumption_count` and `vehicle_consumption_grams_sum`, against the existing `vehicle_consumption.any_consumed` / `.mean` keys. Smoke-tested on Nigeria/rice: sim 1477/3000 = 0.492 vs artifact mean 0.528 (artifact mean is unweighted across strata, sim is population-weighted). Coverage half: see P1 |
| P11 | Effective coverage ratio | T3 | See P1 — the sim column already *is* effective coverage; what is missing is raw coverage to divide it by |
| P12 | Shift in Hb due to fortification | **T2** | Unblocked 2026-09-16: the shift is `hemoglobin_exposure_sum - raw_hemoglobin_exposure_sum`. Verified nonzero and correctly signed on Nigeria/rice — identical under `baseline` (where that arm has no fortification) and +21,212 g/L total under `intervention` |
| P13 | Effect of Hb on maternal disorders (relative risk) | T3 | `CategoricalRelativeRisk` needs a categorical risk stratification column in the sim output and a resolvable affected-measure artifact key. Hb is continuous with an exponential RR, isn't stratified on, and the affected measure (`incidence_rate`) has no key |
| P14 | Shift in birthweight due to fortification | T3 | See P9 |
| P15 | Change in anemia prevalence by severity | T3 | See P3 |
| P16 | Reduction in DALYs due to fortification | T2 | See P6 |
| — | **Stillbirth-to-live-birth ratio** (not on the research V&V list) | **T2, unblocked** | Found 2026-09-16. `covariate.stillbirth_28_weeks_to_live_birth_ratio.estimate` is on the artifact, and `pregnancy_outcome_count` already carries both `stillbirth` and `live_birth` as sub-entities — numerator and denominator in one existing dataset, no sim change. Cheap second custom measure after P4 |
| — | Prevalence of maternal disorders / hemorrhage | DROP | Both states have `dwell_time = one time step`, so sim "prevalence" is (incident cases × 1 week) ÷ person-time — a step-size artifact, not comparable to GBD prevalence. Adding a `cause.*.prevalence` key would make it run and mean nothing |
| — | `population.structure` | Blocked upstream | `PopulationStructure.rate_aggregation_weights` raises `NotImplementedError` (MIC-6804) and `RatioMeasureDataBundle.__init__` calls it eagerly for artifact sources |

## Child sim

| # | Research V&V item | Status | Detail |
| --- | --- | --- | --- |
| C1 | ACMR | **code done 2026-08-19, needs a child psimulate rerun** | Enabled in `child_validation.ipynb`. Three changes landed: (a) `PersonTimeObserver` → `PublicHealthObserver` emitting `person_time_population`, so the loader derives `person_time_total`; (b) age-group labels renamed to the GBD inclusive convention so `AgeSchema` parses them and the library rebins the sim onto the artifact's 6 under-5 GBD bins — no `stratifications` juggling needed, `generate_results()` works; (c) `stillborn` excluded via `stratification.excluded_categories.cause_of_death`. Unlike P5a the denominators genuinely correspond (child untracking is at age 5, not a cohort filter), and it is not a tautology: `LBWSGRiskEffect` shifts `cause.affected_unmodeled.cause_specific_mortality_rate`, so this checks the PAF correction nets back to the population mean. **Caveat:** per-age-bin rows are distorted — rebinning allocates by bin *width*, and 3.8% of the 0–5-month bucket lands in the first week, where under-5 deaths actually concentrate. Totals are conserved, so the age-aggregated comparison is the sound one. Verdict still meaningless until the two upstream bugs land |
| C2 | YLLs and YLDs | T2 | `ylls` / `ylds` already standard. No measure class |
| C3 | Birthweight and gestational age distributions | T3, prerequisite done | `BirthObserver` → `PublicHealthObserver` landed 2026-09-16, so `live_births`, `birth_weight_sum`, `gestational_age_sum` and `low_weight_births` now load. Verified against the schema and sane on Nigeria/rice: mean birth weight 3302 g, mean GA 38.1 weeks, LBW fraction 0.124. Still no OOTB measure — two sums are not a *distribution*, which needs binned birth weight counts or LBWSG-category person time the child sim does not accrue |
| C4 | Baseline maternal iron consumption | T3, prerequisite done | `BirthObserver` (2026-09-16) emits `maternal_iron_consumption_sum` and `baseline_2021_maternal_iron_consumption_sum`, summed over each birth cohort so `live_births` is their denominator. Still blocked on the reference: the child artifact has only `risk.iron_fortification.effect_size` / `.vehicle`. The natural check is cross-sim against the maternal sim's own fortification observer. `CategoricalInterventionObserver` is not usable here — it needs a `CausalFactor` component registered as `intervention.<name>` with an `.exposure` pipeline and `get_categories()`, and it emits *categorical person time*, not a continuous intake sum |
| C5 | Fortification coverage and consumption rates | T3 | See C4 |
| C6 | Shift in birthweight due to fortification | T3 | See C3 |
| C7 | Verify GA distribution is unchanged | T3 | See C3 |
| C8 | Reduction in deaths and YLLs due to fortification | T2 | See C2 |
| — | CSMR by cause | DROP | Artifact has per-cause CSMRs for the unmodeled causes, but `ChildMortality` attributes all of those deaths to `other_causes`, which has no artifact key. Only the all-cause roll-up is comparable |

## Changes made

| Date | Change | Where |
| --- | --- | --- |
| 2026-08-18 | Added `validation/` with `notebooks/maternal_validation.ipynb` and `notebooks/child_validation.ipynb` | this dir |
| 2026-08-18 | Added `[validation]` extra, pulled in by `[data]`, so the artifact env gets `vivarium-validation` + jupyter | `pyproject.toml` |
| 2026-08-18 | Maternal `population.structure` year bin now uses a new `GBD_EXTRACT_YEAR = 2023` constant instead of a hardcoded 2021/2022, so it joins against the GBD-sourced keys | `0200_pregnancy_sim/.../constants/metadata.py`, `.../data/loader.py` |
| 2026-08-19 | Child `PersonTimeObserver` → `PublicHealthObserver`, dataset renamed `person_time` → `person_time_population` | `0300_child_sim/.../components/observers.py` |
| 2026-08-19 | Child age-group labels → GBD inclusive convention (`0_to_5_months`, `6_to_9_months`, `10_to_17_months`, `18_to_59_months`). Labels only; `age_start`/`age_end` unchanged | `0300_child_sim/.../components/observers.py` |
| 2026-08-19 | Excluded `stillborn` from the `cause_of_death` stratification | `0300_child_sim/.../model_specifications/model_spec.yaml` |
| 2026-08-19 | Updated for the dataset rename (breaking change from the observer edit) | `5000_analyze_results/0100_rescale_results/child_results.ipynb` |
| 2026-08-19 | Enabled the child ACMR comparison | `notebooks/child_validation.ipynb` |
| 2026-09-02 | Added `paths.archive_root` / `paths.artifact_path`, and repointed every V&V notebook at the archived iteration `MODEL_NUMBER` names instead of a pasted-in path and run timestamp | `src/lsff_utils/paths.py`, all notebooks here except `pregnancy_model_NO/LSFF_model0_phase2_version_mat_dis_anemia.ipynb`, which reads the legacy `vivarium_gates_lsff_by_wealth_quintile` archive on purpose |
| 2026-09-16 | Child `BirthObserver` → `PublicHealthObserver`. Dataset names unchanged; the four gain the standard schema columns and now load | `0300_child_sim/.../components/observers.py` |
| 2026-09-16 | Child `BirthObserver` also emits `maternal_iron_consumption_sum` / `baseline_2021_maternal_iron_consumption_sum`, denominated by `live_births` (C4/C5 prerequisite) | `0300_child_sim/.../components/observers.py` |
| 2026-09-16 | New maternal `PersonTimeObserver`, emitting `person_time_population`. Makes the rate denominator explicit instead of leaving `person_time_total` to be elected from whichever `person_time_*` dataset happens to sum highest. Verified equal to all four others (1117.4511 on a 3k/20-step run) | `0200_pregnancy_sim/.../components/{observers,__init__}.py`, `model_spec.yaml` |
| 2026-09-16 | New maternal `HemoglobinObserver` (P8/P12, and a second route to severe anemia for P3) | `0200_pregnancy_sim/.../components/{observers,__init__}.py`, `model_spec.yaml` |
| 2026-09-16 | New maternal `IronFortificationObserver` (P10 consumption; coverage blocked, see P1) | `0200_pregnancy_sim/.../components/{observers,__init__}.py`, `model_spec.yaml` |
| 2026-09-16 | Fixed `PregnancyOutcomeObserver` stamping `entity = "pregnancy_countcome"` on every row of `pregnancy_outcome_count` | `0200_pregnancy_sim/.../components/observers.py` |

## Planned changes

| Change | Status | Notes |
| --- | --- | --- |
| Test `maternal_validation.ipynb` on the cluster | done 2026-08-18 | Runs; report renders after the maternal artifact rebuild. Result not usable — see row P5a |
| Fix the maternal `population.structure` year bin | done, artifact rebuilt 2026-08-18 | Confirmed by the report rendering, which means weights and data joined |
| Child observer + age-label + `stillborn` changes | code done 2026-08-19, **needs a child psimulate rerun** | Existing child outputs have no `person_time_*` dataset, so nothing works until the sim is rerun. Rerun also regenerates `person_time_population` for `child_results.ipynb` |
| Observer refactor (MIC-7425) | code done 2026-09-16, **needs a full pipeline rerun** | Both sims. Every new dataset below is absent from existing output until then. Smoke-tested via `InteractiveContext` on Nigeria/rice and checked against the loader's pandera schema: 10/10 child and 20/21 maternal datasets load, the exception being `births`, which is the line list and is never requested |
| Child `BirthObserver` → `PublicHealthObserver` | **done 2026-09-16, needs the rerun** | Makes `live_births` / `birth_weight_sum` / `gestational_age_sum` / `low_weight_births` loadable. No OOTB measure consumes them, so this is a prerequisite for Tier 2 (rows C3, C6, C7), not a check on its own |
| Fix the two upstream bugs | Jira ticket filed 2026-08-19 | Fuzzy checker (non-integer `n` → `nan` → silent pass) and `vivarium-validation` `comparison.py:356` (`/ step_size`). Until these land, no rate verdict from this framework means anything — here or in the MACE V&V, which runs the same code |
| First custom measure: P4 (maternal/hemorrhage incidence) | not started, **unblocked** | Tier 2, and confirmed 2026-09-16 to need no sim change — see P4 |
| Expose pre-effectiveness fortification coverage on `IronFortification` | ticket to file | Unblocks P1/P11. A component change, deliberately excluded from the 2026-09-16 observer refactor |

## Observers that deliberately keep the framework `Observer`

Recorded 2026-09-16 so this is not re-litigated. Neither can use `PublicHealthObserver`: it
wraps only *adding* observations, and its `format_results` would force the four-column measure
schema onto data that is not a measure. `MicrodataObserver` was considered as a base for both
and rejected.

- **Maternal `BirthObserver`** — a concatenating line list whose `births` dataset is read back
  in by the child sim (`0300_child_sim/.../data/loader.py:320`, via
  `paths.FERTILITY_DATA_NAME`), so its columns are an inter-simulation contract.
  `MicrodataObserver` meets none of it: it names the dataset after itself
  (`microdata_observer.<label>`), has no formatter hook for the
  `entrance_time`→`maternal_entrance_time` renames, stamps `event_time` rather than the
  constant `birth_date` that `FertilityLineList` windows against, and adds `event_time` to the
  column set — which `load_fertility_data` turns into an artifact index level. The V&V loader
  never asks for `births` (it loads only datasets a measure names, plus `person_time_*`), so
  this costs nothing.
- **`LBWSGPAFObserver`** — a `register_stratified_observation` whose output is an *artifact
  input* (`load_lbwsg_paf` → `data_keys.LBWSG.PAF`), not a V&V dataset. Volume is not the
  obstacle (61,364 simulants x 2 timesteps ≈ 123k rows). The blocker is that
  `calculate_mortality_weights` (`components/lbwsg.py:409`) reads the whole cohort with
  `include_untracked=True`, and `MicrodataObserver.register_observations` never passes that
  flag, so it takes the default `False` and there is no config knob for it.

## Open questions

| Question | Why it matters | How to settle it |
| --- | --- | --- |
| Does `RiskExposure` actually collapse the risk categories? Sim keeps the level named `parameter` (`RiskStatePersonTime.format_dataset`); the artifact path renames it to the risk-factor name (`get_measure_data_from_sim_inputs`). `verify` intersects index names, so neither survives. The lib's own `get_measure_index_names` says `exposure` is keyed by `parameter`, so the rename looks like a bug. Lib tests only cover `add_comparison` and `get_frame` for this measure, never `verify` | Gates P3 / P15 | Code read only, not observed. Build a context, add any `risk_factor.*.exposure` comparison, print `test_bundle.index_names` and `reference_bundle.index_names` |
| Should the child sim use GBD age bins? | Gates age-specific (vs crude) child ACMR, row C1 | Research decision. The sim's 10-month and 18-month cut points are not GBD boundaries and its 0–6 month bin swallows GBD's three neonatal/infant bins, so the schemas don't nest either way. The lib rebins by width-proportional allocation, which is crude for mortality since neonatal deaths concentrate in the first days. Rebinning conserves totals, so the age-*aggregated* check is unaffected |
| Child age-group labels are inconsistent | Makes the age failure silent rather than loud | `0_to_6_months` / `6_to_10_months` / `10_to_18_months` are written exclusive-end, `18_to_59_months` inclusive-end. `AgeGroup.from_string` reads `X_to_Y` as ending at `Y + 1`, so the first three parse to the wrong ranges, overlap, and `AgeSchema._validate` raises — which `format_dataframe_from_age_bin_df` swallows. `0_to_5_months` / `6_to_9_months` / `10_to_17_months` / `18_to_59_months` describe the same bins correctly. Label-only change |

## Upstream issues worth filing

- **Non-integer denominators make every proportion test silently un-failable (found 2026-08-19).**
  `FuzzyChecker.test_proportion` passes `observed_denominator` straight to
  `scipy.stats.binom(p=..., n=...)` (point target) or `betabinom(a, b, n=...)` (interval
  target). Vivarium person-time is person-*years* — `len(x) * to_years(step_size)` — so `n` is
  a float, scipy's `_argcheck` rejects it, and `pmf` returns `nan`. `_calculate_bayes_factor`
  then computes `nan / nan`, which does not raise, so the
  `except (ZeroDivisionError, FloatingPointError): return inf` fallback never fires. Every
  downstream comparison against `nan` is `False`: `reject_null = nan > 100` is False, and
  `_determine_confidence` starts at `"Conclusive"` and only ever downgrades, so its three
  `nan` comparisons leave it there. Result: a 7x discrepancy renders as
  **"No significant difference / Conclusive"**. The `assert observed_numerator <=
  observed_denominator` does not catch it, and `_determine_confidence` type-hints
  `observed_denominator: int` while receiving a float. Any rate measure whose denominator is
  person-time is affected — i.e. all of them.
- **`verify` scales the target by `1 / step_size`, which looks like the wrong direction.**
  `FuzzyComparison.verify` does `target = ref_datasets["data"] / step_size`. For a binomial
  framing over person-timesteps you would want `n = person_years / step_size` and
  `p = annual_rate * step_size`; the code instead leaves `n` in person-years and multiplies the
  target by `1 / step_size` (~52x for a 7-day step). Observed 0.00424 against target 0.0309
  is consistent with the artifact CSMR being ~5.9e-4 and inflated 52x. Needs confirmation from
  whoever owns the fuzzy checker's intended units before we conclude the sim is off.
- **Error message reports index names when the assertion is on index values.**
  `calculations.weighted_average` raises `"Data and weights must have the same index levels.
  Data index: [...], Weights index: [...]"` printing only `.names`, which are usually
  identical — the failing check is `data.index.equals(weights.index)`. Cost us a wrong
  hypothesis before the real cause showed up. Should print the diverging values.
- `RiskExposure` level-name asymmetry (see Open questions), if confirmed.
- `PopulationStructure.rate_aggregation_weights` — MIC-6804.
- Custom reference data is unusable: `upload_custom_data` exists, but
  `RatioMeasureDataBundle._get_formatted_datasets` raises `NotImplementedError` for
  `DataSource.CUSTOM` and `verify` requires `artifact`/`gbd`. Any reference must land in the
  artifact.
