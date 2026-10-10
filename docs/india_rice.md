# India rice fortification

India rice is modelled differently from every other arm. Its consumption, and who receives
government rice, come from household survey microdata (HCES 2023–24), not from the
extraction tables. Rice is fortified mainly through the Public Distribution System (PDS):
government rice handed out with ration cards, which is fortified centrally. Rice bought on the
open market is mostly unfortified today.

This note explains how the baseline and intervention are built. Numbers are for women aged
15–50 (an equal-weight average over the HCES quintile and age strata) as of the October 2026
build.

## Data sources

| Quantity | Source |
|---|---|
| Rice consumption (share eating rice, g/day mean and SD) | HCES, `0100_data_prep/hces/01_extract_hces.ipynb` |
| Shares of women eating *any* / *only* PDS rice | HCES → `hces/india_share_eating_{any,only}_government_rice.csv` |
| PDS share of each woman's rice, among those eating some (mean, SD) | HCES → `results/{fortificant}/rice/baseline_fortification/partial_coverage_amount/` |
| PDS share of rice volume; purchased share of non-PDS rice | HCES → `hces/india_proportion_government_rice.csv`, `hces/india_non_government_rice_proportion_purchased.csv` |
| Share of PDS rice fortified, baseline effectiveness | Extraction tables: √(GF current compliance 0.5) = 0.71 (decisions D030, D029) |
| Industry consolidation (applied to purchased non-PDS rice) | Extraction tables: 0.175 (decision P011) |
| Intervention coverage and effectiveness | Extraction tables: √(GF 2035 compliance 0.85) = 0.92 each |
| Baseline concentrations | Base extraction table, passed through unchanged: iron 42.5 mcg/g, folic acid 0.125 mcg/g (Indian standard values; the literature extraction agrees) |
| Intervention concentrations | Iron 42.5 mcg/g (literature default); folic acid 1.3 mcg/g (base value, kept by D031) |

The HCES notebook reads microdata on `/snfs1`, so it runs only on the cluster. It writes facts
from the survey only; every assumption (share fortified, effectiveness, consolidation) is
applied later in data prep, which runs anywhere. In the build, India rice is in `HCES_ARMS`
(`build_extraction.py`): it takes no literature defaults except for intervention rows, and its
GF baseline values are the √ split described below (see `GF_DATA_MAPPING.md`). Rows that
neither source sets, such as the baseline concentrations, keep their base-table values.

HCES item codes 061 and 101 are PDS rice (free or paid); 102 is other rice, split into
purchased and home-grown. Household rice is shared among members by meals eaten at home, and
school meals are assumed to use PDS rice. The survey has no pregnancy status, so pregnancy is
assumed not to change consumption. Wealth quintiles are built from HCES assets with the DHS
method.

## Baseline: fortification today

HCES puts each woman in one of three groups:

| Group | Share of women | Fortified share of her rice, if covered |
|---|---|---|
| Eats only PDS rice | 0.147 | all of it |
| Eats some PDS rice | 0.550 | her PDS share (mean 0.526) |
| Eats no PDS rice | 0.303 | none |

Two assumptions turn this into baseline fortification, each √(GF current compliance 0.5) = 0.71:

- **Coverage (share of PDS rice fortified).** A random 71% of PDS eaters receive fortified PDS
  rice; the rest receive none ("maximum heterogeneity": people are missed entirely, not 29% of
  each person's rice). `prep_extracted.ipynb` multiplies the HCES any/only shares by 0.71 to
  write `baseline_fortification/any_coverage` and `full_coverage`.
- **Effectiveness.** The sim then sets fortification to zero for a random 29% of everyone
  (ineffective means totally ineffective).

Fortification therefore lands only on PDS rice: a covered, effective woman in the "some PDS
rice" group has her PDS share fortified and her other rice unfortified. In the pregnancy sim,
her iron intake = fortified share × rice consumption × concentration.

The 0.71 replaces `GOVERNMENT_BASELINE_COVERAGE = 0.8`, formerly hard-coded in the HCES
notebook (with baseline effectiveness also 0.8). GF's compliance of 50% applies to government
rice (literature extraction). The government reports all PDS rice fortified since March 2024,
so the 0.71 is better read as part of compliance than as roll-out.

### Effective coverage

The coverage notebook (`calculate_effective_coverage_by_quintile_and_scenario.ipynb`), whose
output the NTD and folate anemia models read, computes:

- fortified share of rice = full + (any − full) × partial mean = 0.71 × (0.147 + 0.550 × 0.526)
  = 0.71 × 0.439. The 0.439 is close to the PDS share of rice volume (0.45), a check that
  coverage lands on PDS rice.
- effective baseline coverage = share eating rice × fortified share × effectiveness
  = 0.986 × 0.71 × 0.439 × 0.71 ≈ **0.218**.

This is a share of rice, which suits folate and birthweight (where the amount matters). The
hemoglobin effect is all-or-nothing, so for hemoglobin what matters is the share of women with
*any* effective fortified rice: 0.697 × 0.71 × 0.71 ≈ **0.35**. Both are right for their models;
"effective coverage" is not a single number for India.

### Fortification built into the input data

The PDS roll-out happened after the reference years of the input data, so for India the
"2021" fortification status in the pregnancy sim (GBD 2021 hemoglobin) and the 2019–20
coverage in the folate models are set to 0. Nothing is subtracted from the input data, and the
`zero` scenario equals the GBD or survey values. See `docs/scenarios.md`.

## Intervention: the 2035 scale-up

### Fortifiability

Fortifiability is the share of a woman's rice that *could* be fortified by 2035. It is computed
per stratum in `prep_extracted.ipynb`:

fortifiability = PDS share + (1 − PDS share) × purchased share of non-PDS rice × **industry
consolidation**

PDS rice is all fortifiable; open-market rice is fortifiable in proportion to industry
consolidation; home-grown rice never is. Fortifiability averages 0.529 (by wealth quintile,
poorest to richest: 0.56, 0.58, 0.56, 0.53, 0.41).

**Industry consolidation = 0.175 (P011)**, chosen so national fortifiability matches GF's 2035
consolidation (0.529). The previous value, 0.45, was labelled "industry consolidation" but was
probably market-wide (about the PDS share), so applying it to open-market rice counted the PDS
twice (national 0.65). GF's own scenario is mostly better compliance on PDS rice (0.50 → 0.85)
plus a small rise in consolidation (0.50 → 0.529).

| Industry consolidation | National fortifiability | Intervention effective coverage | Women with any effective fortified rice |
|---|---|---|---|
| 0.45 (previous) | 0.652 | 0.544 | 0.642 |
| **0.175 (P011, GF's 2035 level)** | **0.529** | **0.441** | **0.565** |
| 0.065 (GF's increase only) | 0.479 | 0.400 | 0.535 |
| 0 (PDS only) | 0.450 | 0.376 | 0.517 |

GF's 0.529 is itself a reach-weighted blend of two channels in GF's source data, "Rice w/
PDS" (0.63 in 2035) and "Rice w/o PDS" (0.35); if the latter is open-market consolidation, it
would map directly onto our industry consolidation (about 0.35, national fortifiability about
0.61). See GF question 7 in `GF_DATA_MAPPING.md`.

GF's 2035 effective coverage is 0.444. P011 attributes the gap between our PDS share (0.45) and
GF's current consolidation (0.50) to industry; if that gap is a measurement difference, 0.065
(matching only GF's increase) is the alternative. Open-market rice is bought mostly by richer
households, so a larger industry consolidation flattens the wealth gradient.

### How the intervention is applied

- **Target** (rice share) = intervention coverage × fortifiability = 0.92 × 0.529.
- **Pregnancy sim** (`components/intervention.py`): women covered at baseline keep their
  baseline fortified share. Others are newly covered at random within each stratum, with
  probability (target − current) / (1 − current), and get **all** their rice fortified, PDS
  and non-PDS. Intervention effectiveness (0.92) then replaces baseline effectiveness for
  everyone, and covered women get the intervention concentrations.
- **Coverage notebook:** intervention effective coverage = share eating rice × target ×
  effectiveness ≈ **0.441**. It checks that the target is at least current coverage.

Because newly covered women are drawn at random, the intervention does not target open-market
or PDS rice specifically; fortifiability only sets how many women are covered. The code itself
notes this "max out" choice is less clear-cut for India than for Nigeria.

## Comparisons

Both India comparisons are against `zero` (`0050_config/location_vehicle_scenario_comparisons.csv`):

- **Current PDS fortification vs none** (`zero` vs `baseline`);
- **Scaled-up PDS and industry fortification with increased folate vs none** (`zero` vs
  `intervention`).

Because they are against `zero`, the intervention level itself (not its gain over baseline) is
the effect size.

## Open questions

- GF questions 7 and 8 (`GF_DATA_MAPPING.md`): is GF's current consolidation of 0.50 the PDS
  share, and is compliance meant for government rice only? Why does consolidation dip to 0.48
  in 2031?
- The HCES any/only PDS files were derived from the previous outputs (÷ 0.8, exact). The next
  HCES run on the cluster should reproduce them up to floating-point error.
- Iron concentration uses the top of the national standard (28–42.5 mg/kg). This doesn't affect
  hemoglobin (all-or-nothing) but scales the birthweight effect.

## Decisions

D029 (baseline effectiveness), D030 (share of PDS rice fortified), P011 (industry
consolidation), D031 (single intervention scenario, folic acid 1.3 mcg/g); P010 is rejected.
See `0100_data_prep/extraction/integration/STATUS.md`.
