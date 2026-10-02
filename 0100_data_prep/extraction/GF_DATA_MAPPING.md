# Mapping the GF background data into the extraction workbook

`import_gf_background_data.py` reads `Nutrition PST Background Data.xlsx` (GF, last updated
30 Sep 2026) and writes `Data Extraction Sheet (GF 2026-09-30).xlsx` plus
`gf_import_changelog.csv`. The original workbook is not modified.

## Terminology

| GF term (Definitions tab) | Our data need | Conversion |
|---|---|---|
| Coverage (Cov): % using the vehicle | `Vehicle consumption by WRA -- any` | none; quintiles from the country's stratified tab, Total from the cover sheet |
| g/cap | `Vehicle consumption by WRA -- amount` (mean) | Our mean is over **all** women, including non-consumers (the sim treats it as a zero-inflated normal). Nigeria rice is treated as **among consumers** and multiplied by coverage, as before (JG 8/31). Nigeria wheat, bouillon and Ethiopia salt are treated as **per capita** and used as they are. Set per arm by `gcap_basis` in `ARMS`. |
| Consolidation (2035) | `Vehicle "fortifiability"` | none; the 2035 value. Our model uses fortifiability only for the intervention target. |
| Compliance (2035) | `Intervention coverage % of fortifiable` and `Intervention effective % of fortified` | each = √compliance, rounded to 2 d.p. (the equal split agreed with KB on 9/9) |
| Current Consolidation × Compliance | `Vehicle fortification at baseline -- any` × `Baseline effective % of fortified` | any = consolidation × √compliance; effectiveness = √compliance |
| Effective coverage | output of `coverage_calculation/` | It is a cross-check, not an input. Our quintile values, weighted by each quintile's share of women aged 15–49, match GF's national effective coverage to within about 0.01. Nigeria wheat: 0.179 vs GF 0.176 (baseline) and 0.243 vs 0.238 (2035). 2035 for the others: Nigeria rice 0.402 vs 0.413, bouillon 0.831 vs 0.834, Ethiopia salt 0.788 vs 0.791. |

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

## Latent issue in `prep_extracted.ipynb`

`check_totals_reasonable` compares the U5 sex totals with the **unweighted** mean of the
quintile values that the Nigeria interpolation builds. Those values are scaled to match the
total **weighted** by U5 wealth probabilities, so a steep enough WRA wealth gradient fails the
10% tolerance no matter what the U5 inputs are. Wheat treated as among consumers
(3 → 22 g/day) failed it. Treated as per capita (16 → 62 g/day), it passes, and all of data
prep and every coverage calculation runs on the unmodified notebooks. If it trips again, the
fix is to weight that mean (or loosen `rtol`).

## Open questions and planned improvements

These are deferred on purpose: for now we only want the pipeline running on the new data.

1. **What basis is NFCMS consumption on?** This is still open.
   - **Rice: among consumers.** We kept this to match earlier work. It rests only on the
     existing workbook note ("based on email from Jonathan Gorstein 8/31 we have assumed
     the number reported is among consumers").
   - **Wheat: per capita.** We chose this because a closer review of NFCMS (Juhi) suggests
     its figures are over the whole population. Wheat consumers then average 84–177 g/day
     by quintile.
   - **Inconsistency:** the two vehicles come from parallel NFCMS tables, so this should be
     resolved with JG/GF. If rice is also per capita, its means are about 2–3x larger, and its
     IQR-based SDs need re-reading.
2. **Store published numbers, convert in code.** The model only needs P(any consumption) and
   the consumers' distribution, and the sim recovers the consumer mean as mean ÷ `any`. So
   storing population means just makes a round trip, and our sources don't agree on a basis.
   Plan: label each amount row's basis in the workbook (e.g. "mean among consumers" vs
   "mean, all women") and let `prep_extracted` convert. The same applies to SDs.
3. **Put baseline and intervention coverage on the same basis.**
   - Baseline "any" coverage is a share of *consumers*, with consolidation already folded
     in. Intervention coverage is a share of *fortifiable* product, and is multiplied by
     fortifiability in code.
   - Plan: store current fortifiability too, and compute baseline coverage from consolidation
     × compliance in code, the same way as the intervention.
4. **Arms beyond `ARMS`.** The main branch added India wheat, India salt, Ethiopia wheat and
   Nigeria salt. They are left out of `ARMS` on purpose while their data are being extracted
   from other sources. Their placeholder rows appear in the change log as "still
   placeholder".
5. **Extract everything from GF into a tidy table.** A separate step could write every GF
   value (country × vehicle × stratum × metric × year) to a long CSV, with no judgment calls
   in it. The workbook update would then read from that CSV.
