# Automated V&V — status tracker

Tracks the research V&V list against what the validation lib can actually check.
Notebooks live in `notebooks/`. Update the status column as things land.

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
| P1 | Baseline coverage levels for fortification | T3 | `VehicleConsumption` / `IronFortification` are plain `Component`s, no observations. `MaternalInterventionObserver` exists in `components/observers.py` but is not in `model_spec.yaml`. No coverage/exposure artifact key |
| P2 | ACMR | DROP | `MaternalMortality.standard_lookup_tables` drops the all-cause rate — only maternal-disorder deaths are modelled. `CauseSpecificMortalityRate("all_causes")` would run and compare a maternal CSMR against a general-population ACMR. Adding background mortality is a model change |
| P3 | Prevalence of anemia by severity | T3 → T2 | Sim side ready (`person_time_anemia`). Blocked on (a) no anemia artifact key at all, (b) the `RiskExposure` level-name asymmetry (see Open questions). A custom measure sidesteps (b), but (a) needs a research decision on the reference |
| P4 | Incidence rate of maternal disorders and maternal hemorrhage | **T2** | Best first custom measure. Sim emits `transition_count_*` + susceptible person-time; artifact has `incident_probability`, which is what `ParturitionSelectionTransition` consumes. Built-in `Incidence` can't: it wants `cause.*.incidence_rate` (absent) and its weights want `cause.*.prevalence` (absent). Only row where wealth stratification is validatable |
| P5a | CSMR of maternal disorders | **runs; not a meaningful check** | `cause.maternal_disorders.cause_specific_mortality_rate`, in `maternal_validation.ipynb`. Runs end to end on `legacy_1.0/maternal/nigeria/2026_08_06_16_51_40` and the report renders after the year-bin fix, but the result is not usable. Three compounding problems: (1) non-integer person-time denominators make the Bayes factor `nan`, so `reject_null` can never be True — the "No significant difference / Conclusive" verdict on observed 0.00424 vs target 0.0309 is vacuous; (2) `verify` inflates the target ~52x via `/ step_size` when observed is already an annual rate; (3) **even with 1 and 2 fixed**, `UntrackNotPregnant` registers `register_tracked_query`, so the sim denominator is pregnancy-exposure person-time while GBD's CSMR denominator is all women — a ~7x gap by construction, not a defect. Making this meaningful needs a pregnancy-denominator reference, or reframing as maternal deaths per pregnancy against `cause.maternal_disorders.mortality_probability` (CSMR ÷ raw incidence, which is what the model actually consumes). That reframing is Tier 2 |
| P5b | CSMR of maternal hemorrhage | DROP | Artifact key exists but the sim never attributes a death to hemorrhage. `mortality_probability` is the all-maternal-disorders case fatality, and `load_pregnant_maternal_hemorrhage_incidence` subtracts `mh_csmr` so the hemorrhage state holds survivors only. Splitting them out changes model results |
| P6 | YLLs and YLDs for maternal disorders and hemorrhage | T2 | `ylls` / `ylds` already emitted in standard form. No YLL/YLD measure class exists |
| P7 | Anemia YLDs | T2 | Same as P6; `DisabilityObserver` subclass already adds anemia as a cause of disability |
| P8 | Hb distribution | T3 | `Hemoglobin` is a plain `Component`, no observer emits exposure, and the artifact has `.mean` / `.standard_deviation` rather than an `.exposure` key. Needs an observer *and* a distribution measure |
| P9 | LBWSG distribution | T3 | Birth weight / GA leave the sim only via the `births` concatenating line list. Artifact has the LBWSG exposure key, but `RiskExposure` needs `person_time_<risk>` and mothers don't accrue person-time in an LBWSG category |
| P10 | Fortification coverage and vehicle consumption rates | T3 | See P1 |
| P11 | Effective coverage ratio | T3 | See P1 |
| P12 | Shift in Hb due to fortification | T3 | See P8 |
| P13 | Effect of Hb on maternal disorders (relative risk) | T3 | `CategoricalRelativeRisk` needs a categorical risk stratification column in the sim output and a resolvable affected-measure artifact key. Hb is continuous with an exponential RR, isn't stratified on, and the affected measure (`incidence_rate`) has no key |
| P14 | Shift in birthweight due to fortification | T3 | See P9 |
| P15 | Change in anemia prevalence by severity | T3 | See P3 |
| P16 | Reduction in DALYs due to fortification | T2 | See P6 |
| — | Prevalence of maternal disorders / hemorrhage | DROP | Both states have `dwell_time = one time step`, so sim "prevalence" is (incident cases × 1 week) ÷ person-time — a step-size artifact, not comparable to GBD prevalence. Adding a `cause.*.prevalence` key would make it run and mean nothing |
| — | `population.structure` | Blocked upstream | `PopulationStructure.rate_aggregation_weights` raises `NotImplementedError` (MIC-6804) and `RatioMeasureDataBundle.__init__` calls it eagerly for artifact sources |

## Child sim

| # | Research V&V item | Status | Detail |
| --- | --- | --- | --- |
| C1 | ACMR | **code done 2026-08-19, needs a child psimulate rerun** | Enabled in `child_validation.ipynb`. Three changes landed: (a) `PersonTimeObserver` → `PublicHealthObserver` emitting `person_time_population`, so the loader derives `person_time_total`; (b) age-group labels renamed to the GBD inclusive convention so `AgeSchema` parses them and the library rebins the sim onto the artifact's 6 under-5 GBD bins — no `stratifications` juggling needed, `generate_results()` works; (c) `stillborn` excluded via `stratification.excluded_categories.cause_of_death`. Unlike P5a the denominators genuinely correspond (child untracking is at age 5, not a cohort filter), and it is not a tautology: `LBWSGRiskEffect` shifts `cause.affected_unmodeled.cause_specific_mortality_rate`, so this checks the PAF correction nets back to the population mean. **Caveat:** per-age-bin rows are distorted — rebinning allocates by bin *width*, and 3.8% of the 0–5-month bucket lands in the first week, where under-5 deaths actually concentrate. Totals are conserved, so the age-aggregated comparison is the sound one. Verdict still meaningless until the two upstream bugs land |
| C2 | YLLs and YLDs | T2 | `ylls` / `ylds` already standard. No measure class |
| C3 | Birthweight and gestational age distributions | T3 | `BirthObserver` emits `live_births`, `birth_weight_sum`, `gestational_age_sum`, `low_weight_births` as bare adding observations — unloadable. Converting it to `PublicHealthObserver` (T1) makes them loadable but no OOTB measure consumes them |
| C4 | Baseline maternal iron consumption | T3 | `MaternalIronConsumptionFromFortification` is a plain `Component`, no observations. Artifact has only `risk.iron_fortification.effect_size` / `.vehicle` |
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

## Planned changes

| Change | Status | Notes |
| --- | --- | --- |
| Test `maternal_validation.ipynb` on the cluster | done 2026-08-18 | Runs; report renders after the maternal artifact rebuild. Result not usable — see row P5a |
| Fix the maternal `population.structure` year bin | done, artifact rebuilt 2026-08-18 | Confirmed by the report rendering, which means weights and data joined |
| Child observer + age-label + `stillborn` changes | code done 2026-08-19, **needs a child psimulate rerun** | Existing child outputs have no `person_time_*` dataset, so nothing works until the sim is rerun. Rerun also regenerates `person_time_population` for `child_results.ipynb` |
| Child `BirthObserver` → `PublicHealthObserver` | not started | Makes `live_births` / `birth_weight_sum` / `gestational_age_sum` / `low_weight_births` loadable. No OOTB measure consumes them, so this is a prerequisite for Tier 2 (rows C3, C6, C7), not a check on its own |
| Fix the two upstream bugs | Jira ticket filed 2026-08-19 | Fuzzy checker (non-integer `n` → `nan` → silent pass) and `vivarium-validation` `comparison.py:356` (`/ step_size`). Until these land, no rate verdict from this framework means anything — here or in the MACE V&V, which runs the same code |
| First custom measure: P4 (maternal/hemorrhage incidence) | not started | Tier 2 |

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
- `vivarium-validation` imports `matplotlib`, `seaborn` and `IPython` at module load
  (`interface.py`, `visualization/plot_utils.py`) but declares none of them. Worked around
  here by pulling `[interactive]` into the `[validation]` extra.
- `RiskExposure` level-name asymmetry (see Open questions), if confirmed.
- `PopulationStructure.rate_aggregation_weights` — MIC-6804.
- Custom reference data is unusable: `upload_custom_data` exists, but
  `RatioMeasureDataBundle._get_formatted_datasets` raises `NotImplementedError` for
  `DataSource.CUSTOM` and `verify` requires `artifact`/`gbd`. Any reference must land in the
  artifact.
