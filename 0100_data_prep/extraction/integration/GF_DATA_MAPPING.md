# How GF background data maps onto the extraction tables

This is the reference for the GF part of phase 1 of `build_extraction.py`, the defaults.
For 2035 targets (fortifiability, intervention coverage and effectiveness) GF's value comes
first; for measurements GF fills the rows the literature extraction leaves unset, and a `gf`
decision uses GF's value where the literature has one too. This document covers the translation between GF's terms
and ours, which extraction rows the model actually reads, and the questions that are still
open. For how to run the scripts, see `README.md`.

## Terminology

| GF term (Definitions tab) | Our data need | Conversion |
|---|---|---|
| Coverage (Cov): % using the vehicle | `Vehicle consumption by WRA -- any` | None. Quintiles come from the country's stratified tab, the Total from the cover sheet. |
| g/cap | `Vehicle consumption by WRA -- amount` (mean) | Our mean is over **all** women, including non-consumers; the sim treats it as a zero-inflated normal. The GF default uses it as published, i.e. per capita. Exceptions are decisions: Nigeria rice is multiplied by coverage, treating g/cap as among consumers (decision D006, JG 8/31). |
| Consolidation (2035) | `Vehicle "fortifiability"` | None; the 2035 value is used. Fortifiability is used only for the intervention target. |
| Compliance (2035) | `Intervention coverage % of fortifiable` and `Intervention effective % of fortified` | Each = √compliance, rounded to 2 d.p. This is the equal split agreed with KB on 9/9. |
| Current consolidation × compliance | `Vehicle fortification at baseline -- any` × `Baseline effective % of fortified` | any = consolidation × √compliance; effectiveness = √compliance. Applied only when GF gives both numbers. |
| Effective coverage | output of `coverage_calculation/` | A cross-check, not an input. Our quintile values, weighted by each quintile's share of women aged 15–49, match GF's national figures to within about 0.01. |

Quintile labels: Poorest/Lowest → Lowest, Second/2nd → Second, Third/3rd → Middle,
Fourth/4th → Fourth, Wealthiest → Highest.

`extract_gf.py` reads only typed-in GF cells. Formula cells are skipped, because the GF
file's cached formula results may be stale (it was saved with `fullCalcOnLoad`). Where the
same current value is typed in two places, the GF defaults use the cover sheet ('Burden x
Vehicle Matrix'). The one place they disagree (India wheat compliance) is listed under
"Questions to raise with GF" below, and `extract_gf.py` prints a warning for it.

India rice is special. Its consumption and baseline coverage come from HCES microdata
(`0100_data_prep/hces`), so only its intervention rows take GF values. Its fortifiability
and baseline effectiveness are left alone: GF's figures are market-wide, while ours apply
to purchased non-PDS rice and to the HCES baseline.

## Which extraction rows the model actually reads

| Data need | Read by | Notes |
|---|---|---|
| WRA any | coverage calc, pregnancy sim, NTD, folate anemia | Not used for India, which takes it from HCES. Total rows are used only in a sanity check. |
| WRA amount mean / SD | pregnancy sim (iron arms); NTD and folate anemia (mean only) | Not used for India (HCES). The Ethiopia salt SD is never read. Total rows are used only in a sanity check. |
| U5 amount | Nigeria only | Feeds the 5–15 age row (as 0.5 × adult + 0.5 × U5), which the pregnancy sim uses for ages 10–15. The 0–5 rows are read by nothing; the child sim reads no consumption data. |
| U5 any | **nothing** | not listed in `prep_extracted` `data_needs` |
| Fortifiability | coverage calc, pregnancy sim (intervention only) | For India, applied only to purchased non-PDS rice |
| Baseline any / concentration / effectiveness | coverage calc, pregnancy sim, NTD, folate anemia | For India, baseline coverage comes from HCES (`GOVERNMENT_BASELINE_COVERAGE = 0.8`), and the "2021" baseline is forced to 0 in the models. |
| Intervention rows | coverage calc, pregnancy sim (`intervention` scenario only), NTD, folate anemia | |
| Vehicle Extraction (Hb, birthweight) | pregnancy sim, non-pregnant anemia model, child sim | The salt row is never read |
| Country Extraction, Universal | **nothing** | |

## How baseline values affect results

The results are intervention minus baseline. Baseline values matter only through **effective
baseline coverage**: the share of people already benefiting.

- **Pregnancy sim (iron):** baseline-scenario hemoglobin equals GBD's, whatever baseline
  values are entered. The sim removes the benefit it assumes is built into the 2021 data and
  then adds the same benefit back for the same simulants. The intervention's gain is the
  share benefiting under the intervention minus the share benefiting at baseline.
  - The hemoglobin effect is all-or-nothing, so baseline concentration matters only as
    zero vs. non-zero.
  - The birthweight effect (child sim) is linear in iron intake, so the concentration value
    itself matters.
- **Non-pregnant anemia model:** uses baseline effective coverage computed **without**
  concentration. (This is from the initial code trace and should be verified.)
- **NTD model:** the folate it treats as already in the baseline is effective coverage ×
  concentration, so it is zero when the concentration is 0.

Because the anemia model ignores concentration, a baseline with non-zero coverage but a zero
concentration is treated as fortified by that model and as unfortified by the others. Keep
baseline coverage and concentration consistent. Nigeria wheat is now consistent: baseline
coverage 0.79 and effectiveness 0.79 (GF; D021, D022), concentration 40 mcg/g iron and
2.6 mcg/g folic acid (D019, D020).

## Automatic rules

Most interpretive choices are decisions in `decisions.csv`. A few are built into the GF
defaults in `build_extraction.py` instead. `STATUS.md` lists, under "Automatic choices made by
the build", every row where one of these stopped a GF number being used. Any of them can be
overridden with a decision.

| Rule | Where | Effect |
|---|---|---|
| If GF's national g/cap is more than 10% from the mean of its own quintiles, keep the base Total. | `gf_consumption_amount` | Avoids failing the totals check in `prep_extracted`. Applies to Nigeria rice (38 vs 60.1). Overriding it: `method:scale_to_gf_total` rescales the quintiles to the national figure (proposed decision P009). |
| For arms in `HCES_ARMS` (India rice), consumption, fortifiability and baseline effectiveness are not taken from GF (nor from the literature). | `default_scope`, `apply_gf_defaults`, `gf_fortifiability`, `gf_baseline` | India rice keeps its HCES-based values. |
| Arms the model doesn't run (not in `0050_config/location_fortificant_vehicles.csv`) take no defaults. | `read_arms`, `default_scope` | They keep their base values; `comparison.csv` shows GF's numbers for them. |
| Effect sizes take no defaults, from the literature or GF. | `default_scope` | They change only through decisions. |
| Baseline coverage and effectiveness are set only when GF gives both current consolidation and compliance; effectiveness is left alone when the resulting coverage is 0. | `gf_baseline` | Arms with "n/a" in GF (Nigeria rice, bouillon) keep the base baseline. |
| Compliance is split equally: coverage = effectiveness = √compliance, rounded to 2 d.p. | `gf_baseline`, `gf_intervention` | All arms. |
| GF compliance is per vehicle, so iron and folate get the same baseline and intervention values. | `gf_baseline`, `gf_intervention` | Wrong if a vehicle is fortified with only one nutrient today; override with a decision for the other fortificant. |
| CI and SE are cleared when a value changes by more than 1%. | `common.Workbook.outputs` | The base uncertainty no longer describes the new value. |
| Literature units: % on a 0–100 scale becomes a fraction, ppm becomes mcg/g, g/dL becomes g/L. | `extract_lit.convert_units` | The g/dL conversion is flagged for checking. |

## Questions to raise with GF

1. **Nigeria rice national g/cap.** The cover sheet gives 38 g/day (sourced to M4N). GF's own
   quintiles (34.1–79.5, mean 60.1) and zones (48.7–73) come from NFCMS and are consistent with
   NFCMS's national 61.2 and with a GHS-Panel 2023/24 estimate of 62.7. Is 38 an update that
   should replace the NFCMS values, or a different measure (e.g. industrially milled rice, or all
   ages)? Currently the NFCMS national mean is used (D028; the literature has both figures).
   Proposed decision P009
   would rescale the quintiles to 38 (× 0.63).
2. **India wheat current compliance.** The cover sheet (R7) says 5%; Coverage Over Time (E20) says
   50%. GF's update log for 28 Sep says current wheat flour compliance was changed from 5% to
   50%, but only Coverage Over Time was changed. We are using 5% (D023, D024), which seems more
   plausible. Which is intended?
3. **Basis of the consumption figures.** Are the g/cap figures (NFCMS usual intake) means over
   all women, or among consumers? An earlier email (JG, 8/31) said among consumers for rice;
   NFCMS's method and the GHS-Panel cross-check point to all women. Nigeria rice is still
   treated as among consumers (D006); wheat as per capita.
4. **What coverage measures.** Nigeria wheat coverage (28%) is home use of wheat flour (NFCMS
   Table 146), and NFCMS notes that most others eat vendor-made bread. Is the 28% meant to be
   the full reach of fortifiable wheat, or should bread eaters count?
5. **Compliance by nutrient.** GF gives one compliance per vehicle. Is Nigerian (and Indian)
   wheat flour currently fortified with folic acid, or only iron?
6. **Nigeria bouillon 2035 compliance** rose from 50% (April workbook) to 85%. This roughly
   doubles the modelled intervention effect, so it is worth confirming.
7. **India rice.** GF's 2035 consolidation (0.53) and current compliance (50%) are market-wide.
   Our model applies consolidation only to purchased rice outside the PDS, and takes baseline
   coverage from HCES, so we haven't used them. (Our handling of India rice is itself under
   review.)
8. **India rice consolidation path.** Current consolidation is 0.50, 2031 is 0.48 and 2035 is
   0.53, so it falls before it rises. Is the 2031 value intended? (Proposed decisions P010 and
   P011 would align India rice with GF's current compliance and 2035 consolidation.)
9. **Minor transcription differences** spotted in the literature extraction: Nigeria wheat
   coverage 28.0 vs NFCMS 28.2; salt 99.2 vs 99.3; rice poorest-quintile g/cap 34.1 vs NFCMS
   34.2.

## Latent issue in `prep_extracted.ipynb`

`check_totals_reasonable` compares the U5 sex totals with the **unweighted** mean of the
quintile values built by the Nigeria interpolation. Those values are scaled to match a total
**weighted** by U5 wealth probabilities. A steep enough WRA wealth gradient therefore fails
the 10% tolerance, whatever the U5 inputs are.
- Wheat treated as among consumers (3 → 22 g/day) failed the check.
- Treated as per capita (16 → 62 g/day), it passes.

If it trips again, weight that mean (or loosen `rtol`).

## Open questions and planned improvements

1. **What basis is NFCMS consumption on?** It is most likely population-wide. NFCMS's
   NCI usual-intake method produces intake for everyone, and the GHS-Panel cross-check
   matches for rice. To be confirmed with GF (question 3 above).
   - **Wheat:** treated as per capita. SDs use the NFCMS CV (decisions D007, D008), because NFCMS
     usual-intake SDs are incompatible with our zero-inflated model. See
     `CONSUMPTION_DISTRIBUTION.md`.
   - **Rice:** deliberately kept as among consumers (D006), for comparability with earlier
     results. Switching means rejecting D006 and activating P007 and P008. P008 currently
     reports as invalid because the literature workbook has two candidate national rice means
     (NFCMS 61.2, M4N 38); marking one `Use in model` = yes fixes that.
   - **A redesign** of the consumption model (a non-negative intake distribution, with GF
     coverage unchanged) is described in `CONSUMPTION_DISTRIBUTION.md`, section 5.
2. **Store published numbers and convert in code.** Label each amount row's basis in the
   tables (e.g. "mean among consumers" vs "mean, all women") and let `prep_extracted` do
   the conversion, for SDs as well as means.
3. **Put baseline and intervention coverage on the same basis.**
   - Baseline "any" coverage is a share of *consumers*, with consolidation already folded in.
   - Intervention coverage is a share of *fortifiable* product, multiplied by
     fortifiability in code.
   - Plan: store current fortifiability too, and compute baseline coverage from it the same
     way.
4. **Nigeria wheat baseline** is set (D019–D022): GF coverage and effectiveness (0.79 each),
   concentrations at the national standard (40 mcg/g iron, 2.6 mcg/g folic acid). This treats
   wheat flour as already fortified with both today, which reduces the modelled intervention
   effect. The literature alternatives (NFCMS 12.6% coverage, 73% compliance, 53.9 mcg/g) were
   rejected (P001–P004); question 5 above affects the folate part.
5. **Arms not in the model yet** (Nigeria salt, India wheat, India salt, Ethiopia wheat) keep
   their base values while their data are reviewed or extracted; `comparison.csv` still shows
   GF's numbers for them. India wheat already has baseline decisions (D023, D024). To add one,
   restore it in `0050_config/location_fortificant_vehicles.csv`,
   `location_vehicle_scenario_comparisons.csv` and (for Nigeria salt) the commented-out
   scenarios in `config.yaml`. The next build fills it in from the literature and GF and runs
   the checks on it; expect to need decisions (e.g. Ethiopia wheat's DUMMY SDs fail the
   consumer-variance check against GF's means).
6. **India rice** handling is under review: fortifiability (0.45, applied to purchased non-PDS
   rice), baseline effectiveness (0.8) and the HCES-based baseline coverage
   (`GOVERNMENT_BASELINE_COVERAGE = 0.8`). Proposed decisions P010 (baseline effectiveness 0.625,
   matching GF's 50% compliance) and P011 (industry consolidation 0.175, matching GF's 2035
   consolidation) record one way to align it with GF. A cleaner long-term fix is to move the
   0.8 out of the HCES notebook into the extraction tables; that needs one HCES rerun on the
   cluster.
7. **Literature row IDs** are hashes of each row's content, so editing key fields in the
   literature workbook (e.g. fixing a scenario label) changes the ID and breaks decisions that
   use it. The build stops and suggests replacements. `extract_lit.py` already reads an `ID`
   column; adding one to the workbook would prevent this.
8. **Coverage Totals: literature vs GF.** GF's national coverage rounds NFCMS (rice 0.54 vs
   0.536, wheat 0.28 vs 0.282). D025 and D026 keep GF's figures so the values match the
   PR #53 run; rejecting them switches to the literature's (small changes to the rice
   national mean and the wheat Total and U5 SDs). D027 keeps the rice U5 means at NFCMS ×
   0.536; if the rice basis changes (P007), revisit it too.
9. **Decisions that only restate GF targets.** Since GF comes first for 2035 targets,
   D011–D018 (GF fortifiability and intervention coverage/effectiveness for Nigeria rice,
   bouillon and wheat) no longer change anything. They are kept for their rationale and
   could be retired.
