# Mapping the GF background data into the extraction workbook

`import_gf_background_data.py` reads `Nutrition PST Background Data.xlsx` (GF, last updated
30 Sep 2026) and writes `Data Extraction Sheet (GF 2026-09-30).xlsx` plus
`gf_import_changelog.csv`. The original workbook is not modified.

## Terminology

| GF term (Definitions tab) | Our data need | Conversion |
|---|---|---|
| Coverage (Cov): % using the vehicle | `Vehicle consumption by WRA -- any` | none; quintiles from the country's stratified tab, Total from the cover sheet |
| g/cap | `Vehicle consumption by WRA -- amount` (mean) | Our mean is over **all** women, including non-consumers (the sim treats it as a zero-inflated normal). Rice and wheat g/cap are NFCMS figures **among consumers**, so the script multiplies them by coverage. Bouillon and Ethiopia salt are used as they are. |
| Consolidation (2035) | `Vehicle "fortifiability"` | none; the 2035 value. Our model uses fortifiability only for the intervention target. |
| Compliance (2035) | `Intervention coverage % of fortifiable` and `Intervention effective % of fortified` | each = √compliance, rounded to 2 d.p. (the equal split agreed with KB on 9/9) |
| Current Consolidation × Compliance | `Vehicle fortification at baseline -- any` × `Baseline effective % of fortified` | any = consolidation × √compliance; effectiveness = √compliance |
| Effective coverage | output of `coverage_calculation/` | It is a cross-check, not an input. The new intervention values reproduce GF's 2035 effective coverage: wheat 0.16–0.30 vs GF 0.238; rice 0.26–0.51 vs 0.413; bouillon 0.82–0.84 vs 0.834; Ethiopia salt 0.788 vs 0.791. |

Quintile labels: Poorest/Lowest → Lowest, Second/2nd → Second, Third/3rd → Middle,
Fourth/4th → Fourth, Wealthiest → Highest.

The script reads only typed-in GF cells. It refuses to read formula cells, because the GF
file's cached formula results may be stale (it was saved with `fullCalcOnLoad`, and for
India wheat the Reach and Coverage Over Time tabs disagree on compliance, 5% vs 50%).

## Which extraction rows the model actually reads

| Data need | Read by | Notes |
|---|---|---|
| WRA any | coverage calc, pregnancy sim, NTD, folate anemia | Not used for India, which takes it from HCES. Total rows are only used for a sanity check. |
| WRA amount mean / SD | pregnancy sim (iron arms); NTD and folate anemia (mean only) | Not used for India (HCES). The Ethiopia salt SD is never read. Total rows are only used for a sanity check. |
| U5 amount | Nigeria only | Feeds the 5–15 age row (as 0.5 × adult + 0.5 × U5), which the pregnancy sim uses for ages 10–15. The 0–5 rows are read by nothing; the child sim reads no consumption data. Ethiopia's U5 rows are never read. |
| U5 any | **nothing** | not listed in `prep_extracted` `data_needs` |
| Fortifiability | coverage calc, pregnancy sim (intervention only) | For India, the value is applied only to purchased non-PDS rice |
| Baseline any / concentration / effectiveness | coverage calc, pregnancy sim, NTD, folate anemia | For India, baseline coverage comes from HCES (`GOVERNMENT_BASELINE_COVERAGE = 0.8`). The "2021" baseline is forced to 0 in the models. |
| Intervention rows | coverage calc, pregnancy sim (`intervention` scenario only), NTD, folate anemia | |
| Vehicle Extraction (Hb, birthweight) | pregnancy sim, non-pregnant anemia model, child sim | The salt row is never read |
| Country Extraction, Universal | **nothing** | |

## Not filled by the GF file (still need data)

- **Nigeria wheat concentrations** (baseline and intervention, iron and folate). They are still
  rice placeholders, so baseline wheat now has 79% coverage but 0 mcg/g.
- **Wheat hemoglobin and birthweight effects**: still rice placeholders.
- **Wheat WRA SDs and U5 amounts**: these are DERIVED from rice, tagged
  `DERIVED (MIC-7549)`. The derivation assumes wheat consumers have the same coefficient of
  variation as rice consumers, and U5 values are scaled by the wheat/rice ratio.
- **India rice fortifiability (0.45 → GF 0.529) and baseline effectiveness**: skipped. GF's
  figures are market-wide, while ours apply to non-PDS purchased rice and to the HCES
  baseline, so they don't map one-to-one. These need a decision.

## Known issue in `prep_extracted.ipynb`

With the real wheat wealth gradient (3 → 22 g/day), `check_totals_reasonable` fails at the
U5 step of the Nigeria interpolation (males are 10.3% off; the tolerance is 10%). The check
compares the U5 sex totals with the **unweighted** mean of the quintiles. The notebook
builds those quintiles to match the total **weighted** by U5 wealth probabilities, so a steep
gradient fails regardless of the U5 inputs. Raising `rtol` to 0.15, or weighting the mean,
fixes it. With either change, the whole of data prep and every coverage calculation ran.
