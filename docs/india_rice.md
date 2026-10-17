# India rice fortification

India rice is modelled differently from every other arm. Its consumption, and who receives
government rice, come from household survey microdata (HCES 2023–24), not from the
extraction tables. Rice is fortified mainly through government schemes: the Public
Distribution System (PDS, rice handed out with ration cards), school meals (PM POSHAN) and
anganwadi meals (ICDS). Below, "government rice" means rice from any of these, and "PDS" means
the PDS alone (as in the HCES item codes). Rice bought on the open market is mostly unfortified
today.

This note explains how the baseline and intervention are built. Everything below applies to
every sex and age group: HCES gives values for each sex, age group (0–5, 5–15, 15–30, 30–50,
50+) and wealth quintile, and data prep writes coverage for all of them. Worked numbers are for
women aged 15–50 (an equal-weight average over their quintile and age strata) as of the October
2026 build; other groups are similar (see below).

## Who uses which groups

| Model | Groups |
|---|---|
| Pregnancy sim (`0200`) | Women 10–54, using the HCES values for their age group |
| Child sim (`0300`) | None directly: children's outcomes come through their mothers' iron intake |
| Non-pregnant anemia (`0400`) | All sexes and ages (far more people than the pregnancy sim) |
| NTD model (`0500`) | Women 15–50 |

| Group | Any government rice | Fortifiability | Effective baseline | Effective intervention |
|---|---|---|---|---|
| Under 5 (F/M) | 0.67 | 0.52 | 0.18 | 0.38 |
| 5–15 (F/M) | 0.75–0.76 | 0.57 | 0.24 | 0.48 |
| Women 15–50 | 0.70 | 0.53 | 0.22 | 0.44 |
| Adults 15+ (all) | 0.68–0.71 | 0.52–0.53 | 0.21–0.22 | 0.44 |
| All groups | 0.70 | 0.53 | 0.215 | 0.436 |

(Equal-weight averages over each group's wealth quintiles.)

## Data sources

| Quantity | Source |
|---|---|
| Rice consumption (share eating rice, g/day mean and SD) | HCES, `0100_data_prep/hces/01_extract_hces.ipynb` |
| Shares of people eating *any* / *only* government rice | HCES → `hces/india_share_eating_{any,only}_government_rice.csv` |
| Government share of each person's rice, among those eating some (mean, SD) | HCES → `results/{fortificant}/rice/baseline_fortification/partial_coverage_amount/` |
| Government share of rice volume; purchased share of non-government rice | HCES → `hces/india_proportion_government_rice.csv`, `hces/india_non_government_rice_proportion_purchased.csv` |
| Share of government rice fortified, baseline effectiveness | Extraction tables: √(GF current compliance 0.5) = 0.71 (decisions D030, D029) |
| Industry consolidation (applied to purchased non-government rice) | Extraction tables: 0.175 (decision P011) |
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
purchased and home-grown. Household rice is shared among members by meals eaten at home. A
person's government rice is the PDS rice in their meals at home, all rice in school and
anganwadi meals, and the household's PDS share of other meals away from home. School meals are
why 5–15-year-olds have a higher government share than adults. The survey has no pregnancy status, so pregnancy is
assumed not to change consumption. Wealth quintiles are built from HCES assets with the DHS
method.

## Baseline: fortification today

HCES puts each person in one of three groups (shares shown for women 15–50):

| Group | Share of women 15–50 | Fortified share of their rice, if covered |
|---|---|---|
| Eats only government rice | 0.147 | all of it |
| Eats some government rice | 0.550 | their government share (mean 0.526) |
| Eats no government rice | 0.303 | none |

In the pregnancy simulation, two assumptions turn this into baseline fortification, each √(GF current compliance 0.5) = 0.71:

- **Coverage (share of government rice fortified).** A random 71% of government-rice eaters
  receive fortified government rice; the rest receive none ("maximum heterogeneity": people are missed entirely, not 29% of
  each person's rice). `prep_extracted.ipynb` multiplies the HCES any/only shares by 0.71 to
  write `baseline_fortification/any_coverage` and `full_coverage`.
- **Effectiveness.** The sim then sets fortification to zero for a
  random 29% of everyone (independently of whether they were covered;
  only people who are covered will be affected). This is also
  maximum heterogeneity: a person’s fortified rice is either all
  effective or all ineffective, not 71% effective for everyone.

Fortification therefore lands only on government rice: a covered, effective person in the "some
government rice" group has their government share fortified and their other rice unfortified. In the pregnancy
sim, a woman's iron intake = fortified share × rice consumption × concentration.

The 0.71 replaces `GOVERNMENT_BASELINE_COVERAGE = 0.8`, formerly hard-coded in the HCES
notebook (with baseline effectiveness also 0.8). GF's compliance of 50% applies to government
rice (literature extraction). The government reports rice in all its schemes fortified since
March 2024, so the 0.71 is better read as part of compliance than as roll-out.

### Effective coverage

The coverage notebook (`calculate_effective_coverage_by_quintile_and_scenario.ipynb`), whose
output the NTD and non-pregnant anemia models read, computes for each group (women 15–50
shown):

- fortified share of rice = full + (any − full) × partial mean = 0.71 × (0.147 + 0.550 × 0.526)
  = 0.71 × 0.439. The 0.439 is close to the government share of rice volume (0.45), a check
  that coverage lands on government rice.
- effective baseline coverage = share eating rice × fortified share × effectiveness
  = 0.986 × 0.71 × 0.439 × 0.71 ≈ **0.218**.

This is a share of rice, which suits folate and birthweight (where the amount matters). The
hemoglobin effect is all-or-nothing, so for hemoglobin in the pregnancy sim what matters is the
share of women with *any* effective fortified rice: 0.697 × 0.71 × 0.71 ≈ **0.35**. Both are right for their models;
"effective coverage" is not a single number for India.

### Fortification built into the input data

The government rice fortification roll-out happened after the reference years of the input data, so for India the
"2021" fortification status in the pregnancy sim (GBD 2021 hemoglobin) and the 2019–20
coverage in the folate models are set to 0. Nothing is subtracted from the input data, and the
`zero` scenario equals the GBD or survey values. See `docs/scenarios.md`.

## Intervention: the 2035 scale-up

### Fortifiability

Fortifiability is the share of a person's rice that *could* be fortified by 2035. It is computed
per stratum in `prep_extracted.ipynb`:

fortifiability = government share + (1 − government share) × purchased share of non-government
rice × **industry consolidation**

Government rice is all fortifiable; open-market rice is fortifiable in proportion to industry
consolidation; home-grown rice never is. Fortifiability averages 0.529 for women 15–50 (by
wealth quintile, poorest to richest: 0.56, 0.58, 0.56, 0.53, 0.41) and 0.534 over all groups.

**Industry consolidation = 0.175 (P011)**, chosen so fortifiability for women 15–50 matches
GF's 2035 consolidation (0.529). GF's figure is market-wide; over all groups ours is 0.534, so
the calibration holds to within about 1%. The previous value, 0.45, was labelled "industry consolidation" but was
probably market-wide (about the government share), so applying it to open-market rice counted
government rice twice (national 0.65). GF's own scenario is mostly better compliance on
government rice (0.50 → 0.85)
plus a small rise in consolidation (0.50 → 0.529).

| Industry consolidation (women 15–50) | Fortifiability | Intervention effective coverage | Women with any effective fortified rice |
|---|---|---|---|
| 0.45 (previous) | 0.652 | 0.544 | 0.642 |
| **0.175 (P011, GF's 2035 level)** | **0.529** | **0.441** | **0.565** |
| 0.065 (GF's increase only) | 0.479 | 0.400 | 0.535 |
| 0 (government rice only) | 0.450 | 0.376 | 0.517 |

GF's 0.529 is itself a reach-weighted blend of two channels in GF's source data, "Rice w/
PDS" (0.63 in 2035) and "Rice w/o PDS" (0.35); if the latter is open-market consolidation, it
would map directly onto our industry consolidation (about 0.35, national fortifiability about
0.61). GF's labels say PDS; whether they mean the PDS or all government rice is part of GF
question 7 in `GF_DATA_MAPPING.md`.

GF's 2035 effective coverage is 0.444. P011 attributes the gap between our government share (0.45) and
GF's current consolidation (0.50) to industry; if that gap is a measurement difference, 0.065
(matching only GF's increase) is the alternative. Open-market rice is bought mostly by richer
households, so a larger industry consolidation flattens the wealth gradient.

### How the intervention is applied

- **Target** (rice share) = intervention coverage × fortifiability = 0.92 × 0.529.
- **Pregnancy sim** (`components/intervention.py`): women covered at baseline keep their
  baseline fortified share. Others are newly covered at random within each stratum, with
  probability (target − current) / (1 − current), and get **all** their rice fortified, government
  and non-government. Intervention effectiveness (0.92) then replaces baseline effectiveness for
  everyone, and covered women get the intervention concentrations.
- **Coverage notebook:** intervention effective coverage = share eating rice × target ×
  effectiveness ≈ **0.441**. It checks that the target is at least current coverage.

In the pregnancy sim, newly covered women are drawn at random, so the intervention does not
target open-market or government rice specifically; fortifiability only sets how many women are
covered. The code itself notes this "max out" choice is less clear-cut for India than for
Nigeria.

## Comparisons

India has three comparisons (`0050_config/location_vehicle_scenario_comparisons.csv`):

- **Current PDS fortification vs none** (`zero` vs `baseline`);
- **Scaled-up PDS and industry fortification with increased folate vs none** (`zero` vs
  `intervention`);
- **Scale-up beyond current PDS fortification** (`baseline` vs `intervention`).

(The labels say "PDS" but cover all government rice.)

The first two match the 2024 targets (vs none), where the intervention level itself is the
effect size; GF's updated baseline values barely affect the second. The third is the gain over
today's program and is where the baseline values matter.

## Open questions

- GF questions 7 and 8 (`GF_DATA_MAPPING.md`): is GF's current consolidation of 0.50 the
  government (or PDS) share, and is compliance meant for government rice only? Why does
  consolidation dip to 0.48 in 2031?
- Iron concentration uses the top of the national standard (28–42.5 mg/kg). This doesn't affect
  hemoglobin (all-or-nothing) but scales the birthweight effect.

## Decisions

D029 (baseline effectiveness), D030 (share of government rice fortified), P011 (industry
consolidation), D031 (single intervention scenario, folic acid 1.3 mcg/g); P010 is rejected.
See `0100_data_prep/extraction/integration/STATUS.md`.
