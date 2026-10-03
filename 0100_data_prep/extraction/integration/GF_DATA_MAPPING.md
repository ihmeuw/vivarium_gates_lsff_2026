# How GF background data maps onto the extraction sheet

This is the reference for phase 1 of `build_extraction.py`, the GF defaults. It covers the
translation between GF's terms and ours, which extraction-sheet rows the model actually
reads, and the questions that are still open. For how to run the scripts, see `README.md`.

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
file's cached formula results may be stale (it was saved with `fullCalcOnLoad`). The GF
file also disagrees with itself in one place: India wheat compliance is 5% on the cover
sheet and 50% on Coverage Over Time. `extract_gf.py` prints a warning for it.

India rice is special. Its consumption and baseline coverage come from HCES microdata
(`0100_data_prep/hces`), so only its intervention rows take GF values. Its fortifiability
and baseline effectiveness are left alone: GF's figures are market-wide, while ours apply
to purchased non-PDS rice and to the HCES baseline.

## Which extraction-sheet rows the model actually reads

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

**Inconsistency to resolve:** Nigeria wheat now has 79% baseline coverage (GF-derived) but a
placeholder baseline concentration of 0.
- The pregnancy sim and NTD model therefore treat it as unfortified today.
- The non-pregnant anemia model treats it as 62% effectively fortified.

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
   matches for rice (Juhi, Oct 2026). Confirmation from JG/GF has been requested.
   - **Wheat:** treated as per capita. SDs use the NFCMS CV (decisions D007, D008), because NFCMS
     usual-intake SDs are incompatible with our zero-inflated model. See
     `CONSUMPTION_DISTRIBUTION.md`.
   - **Rice:** deliberately kept as among consumers (D006), for comparability with earlier
     results. Switching means rejecting D006 and activating P007 and P008.
   - **A redesign** of the consumption model (a non-negative intake distribution, with GF
     coverage unchanged) is described in `CONSUMPTION_DISTRIBUTION.md`, section 5.
2. **Store published numbers and convert in code.** Label each amount row's basis in the
   sheet (e.g. "mean among consumers" vs "mean, all women") and let `prep_extracted` do
   the conversion, for SDs as well as means.
3. **Put baseline and intervention coverage on the same basis.**
   - Baseline "any" coverage is a share of *consumers*, with consolidation already folded in.
   - Intervention coverage is a share of *fortifiable* product, multiplied by
     fortifiability in code.
   - Plan: store current fortifiability too, and compute baseline coverage from it the same
     way.
4. **Nigeria wheat baseline.** Decide coverage (12.6% NFCMS vs 79% GF-derived), compliance
   (73% NFCMS vs 63% M4N) and concentration (53.9 mcg/g) together, as a set. These are
   proposals P002–P004 in `decisions.csv`.
   - With P003 alone, the hemoglobin gain falls by about three quarters.
   - The birthweight gain would be about zero, because the measured baseline
     concentration is above the 40 mcg/g intervention standard.
   - Folate baseline coverage should probably be 0 (P001).
5. **Arms not taking GF values yet** (India wheat, India salt, Ethiopia wheat, Nigeria salt)
   have `apply_gf = no` in `arms.csv` while Juhi extracts their data. `comparison.xlsx`
   still shows GF's numbers for them.
