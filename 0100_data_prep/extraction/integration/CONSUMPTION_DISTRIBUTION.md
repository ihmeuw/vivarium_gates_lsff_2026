# Vehicle consumption: survey data vs. the model's distribution

This note covers three things:

1. A mismatch between how the Nigeria survey data (NFCMS) report vehicle consumption and
   how our models represent it.
2. The interim fix now used for Nigeria wheat: consumption SDs from the survey's coefficient
   of variation (section 4).
3. A proposed redesign of the consumption model, written so it can be handed to software
   engineers (section 5).

Status (2 Oct 2026):
- The interim fix is used for Nigeria wheat (decisions D007 and D008 in `decisions.csv`).
- Nigeria rice is unchanged on purpose, so that its results stay comparable with earlier runs.
- The redesign is not implemented.

## 1. How the model represents consumption today

For each arm, the extraction sheet gives, by wealth quintile (and age/sex for children):

| quantity | file in `0100_data_prep/results/<vehicle>/vehicle_consumption/` | meaning in the model |
|---|---|---|
| `any` = *p* | `any/` | probability a woman consumes the vehicle at all |
| mean *m* | `amount/mean/` | mean g/day over **all** women, non-consumers counted as 0 |
| SD *s* | `amount/sd/` | SD over **all** women, non-consumers counted as 0 |

The pregnancy sim (`0200_pregnancy_sim/.../components/intervention.py`,
`VehicleConsumption.on_initialize_simulants`) treats intake as a **zero-inflated normal**:

- with probability 1 − *p*: intake = 0;
- with probability *p*: intake ~ Normal(μ, σ²), clipped at 0.

It recovers the consumers' parameters from the inputs:

    μ  = m / p
    σ² = s² / p − μ² (1 − p)

Other places use the same assumption:

- The NTD model (`0500_neural_tube_defects_model/model.ipynb`, cells 46–51) uses the
  consumer mean *m*/*p*.
- The coverage notebook and the anemia models multiply effective coverage by *p*.

How each outcome depends on these quantities:

- **Hemoglobin (pregnancy sim):** all-or-nothing. Anyone with fortified iron intake > 0 gets
  the full effect (`update_hemoglobin_exposure`). Hemoglobin results therefore depend on
  **effective coverage** (*p* × share fortified × effectiveness), not on the amount eaten.
- **Birthweight (child sim):** linear in maternal iron intake, so it depends on mean intake.
- **NTD:** a non-linear function of folate intake among consumers.

## 2. What the survey reports

NFCMS (Nigeria, 2021) reports **usual intake** estimated with the NCI method (Tooze 2010).
The NCI method combines each person's probability of eating a food on a given day with
their usual amount when they do. The result is a long-run daily average **for every person
in the (sub)population**. Occasional eaters get small positive values rather than zeros, so
the distribution has **no point mass at 0**. NFCMS labels consumer-only statistics
explicitly as "among consumers". The usual-intake tables (e.g. Tables 147, 172) have no
such label.

Juhi cross-checked this against the GHS-Panel 2023/24 microdata. Population-wide rice intake
there is 62.7 g/day, against 61.2 in NFCMS. That supports reading the NFCMS means as
population-wide. GF's column label, "g/cap", says the same.

Separately, our *p* is GF's **coverage**: the share of the population that eats the vehicle,
fortified or not. It is the first factor in GF's effective coverage
(coverage × consolidation × compliance). Each coverage figure comes from a specific survey
question, separate from the intake tables:
- wheat: share of households using wheat flour at home, 28% (NFCMS Table 146);
- rice: an INTAKE tabulation, 53.6%.

NCI usual intake is positive for almost everyone, so coverage can't be "the share with non-zero
usual intake". NFCMS itself notes that women who don't use flour at home still eat vendor-made
bread. So coverage and the intake distribution measure the vehicle in different ways, and the
model has to say how they relate.

## 3. The problem

A zero-inflated distribution with a mean of *m* has a minimum possible SD:

    SD over all women ≥ m √((1 − p) / p)      (this is when every consumer eats exactly m/p)

NFCMS's SDs (Juhi derived them as IQR/1.35) are well below that floor for the low-coverage
vehicles:

| Nigeria, poorest quintile | *m* | *p* | minimum possible SD | NFCMS SD |
|---|---|---|---|---|
| wheat | 16.1 | 0.191 | 33.1 | 13.3 |
| rice (if read as per capita) | 34.2 | 0.336 | 48.1 | 24.8 |

Putting NFCMS's mean and SD into the model as they are would give a **negative consumer
variance**, and the sim would draw NaN. The build checks for this and stops.

The cause is that the two numbers describe different things. NFCMS's mean and SD describe a
distribution over everyone, with no zeros. Our *p* says that 1 − *p* of women eat none.

A second, smaller artifact: the consumer normal is clipped at 0. With a consumer CV around
0.8, about 10% of consumers are drawn at ≤ 0. Because the hemoglobin effect is
all-or-nothing, they lose the benefit, so effective coverage is cut by up to about 10%. The
code comment in `intervention.py` already notes that a non-negative distribution would fix
this.

## 4. Interim fix (Nigeria wheat): survey CV applied to consumers

**Rule:** keep *p* and the published mean *m*. Give consumers the published **coefficient of
variation** CV = *s*_NFCMS / *m*_NFCMS, and write to the extraction sheet the SD over all
women that this implies:

    μ = m / p
    σ = CV × μ
    SD over all women = sqrt( p σ² + p (1 − p) μ² )

**Implementation:**

- In `decisions.csv`, D007 and D008 apply `source = method:consumer_cv` to the Nigeria wheat
  amount SD rows (WRA and U5).
- `build_extraction.py` → `method_consumer_cv()` reads the matching NFCMS mean and SD rows
  from Juhi's extraction (`lit_long.csv`).
  - It uses Juhi's `Use in model` pick when there are several.
  - It takes *p* from the output workbook. Under-5 rows use national WRA coverage, because
    the pipeline gives children the women's coverage.
- In `changelog.csv`, these rows have step "decision" and source "literature CV applied to
  consumers". Their `reference` gives the literature row IDs.

**What it preserves:**
- the published mean, and with it birthweight (linear in the mean);
- GF's coverage *p*, and with it effective coverage, which drives hemoglobin;
- the vehicle's own distribution shape (CV), rather than borrowing rice's;
- positive consumer variance, always, by construction.

**What it gives up:**
- The SD over all women no longer matches NFCMS. For wheat it is 45–101 vs NFCMS's 13–33.
- It assumes the spread of usual intake carries over to consumers.
- The clipping artifact remains: 3–12% of wheat consumers are clipped, by quintile.

**Result (Nigeria wheat, women 15+):**

| quintile | *p* | mean | consumer mean | consumer CV | SD over all women (was rice-derived) | consumers clipped to 0 |
|---|---|---|---|---|---|---|
| Lowest | 0.191 | 16.1 | 84.3 | 0.82 | 44.9 (48.3) | 11% |
| Second | 0.253 | 23.4 | 92.5 | 0.81 | 55.1 (48.8) | 11% |
| Middle | 0.305 | 38.2 | 125.2 | 0.72 | 76.2 (63.8) | 8% |
| Fourth | 0.333 | 49.3 | 148.0 | 0.64 | 88.4 (72.2) | 6% |
| Highest | 0.353 | 62.4 | 176.8 | 0.53 | 101.1 (86.6) | 3% |

All of data prep and every coverage calculation ran on the unmodified notebooks with these
values.

**Nigeria rice** keeps its old treatment, so results stay comparable with earlier runs: g/cap
multiplied by coverage (decision D006), and the original NFCMS SDs. Under the population-wide
reading this understates mean rice intake by a factor of about 1/0.536 ≈ 1.9. To switch it
later: reject D006, activate P007 (per capita) and P008 (consumer CV SDs), rebuild, and
compare.

## 5. Proposed redesign: a non-negative intake distribution, with GF coverage unchanged

### What stays the same

GF's coverage stays exactly what it is now: the share of women who eat the vehicle, fortified
or not. Consolidation (fortifiability) and compliance (fortification coverage × effectiveness)
also stay as now. Effective coverage = coverage × fortified share × effectiveness, the same
formula and the same numbers as GF's. The coverage notebook, the anemia models and
`IronFortification`'s coverage logic don't change.

### What changes

Only **how much covered women eat** changes. Today their intake is a normal distribution
clipped at 0, backed out of a mean and SD over all women. The redesign draws it from a
non-negative distribution (gamma), with parameters computed once in data prep. It also makes
explicit one assumption that today is implicit: **what women outside coverage eat.**

There are two coherent ways to tie the survey's intake distribution to GF's coverage, set as
a per-arm option:

1. **`all_intake_in_covered`: women outside coverage eat none of the vehicle.** This is today's
   assumption.
   - Covered women's intake: gamma with mean *m*/*p* and the survey's CV (the interim rule,
     without the clipping).
   - Uses the survey mean exactly. The survey SD is used only through its CV.
   - Every gram of the vehicle is in the covered group, so all of it can be fortified.
2. **`covered_are_upper_tail`: the survey distribution describes everyone, and covered women
   are its top *p*.** Women outside coverage eat the vehicle in forms the coverage question
   doesn't count, such as bought bread when coverage means home flour use.
   - Fit gamma(*m*, *s*) to the survey's mean and SD over everyone, both used exactly.
   - Covered women draw from its upper tail: *U* ~ Uniform(1 − *p*, 1), intake = *F*⁻¹(*U*).
   - Only covered women's intake can be fortified, consistent with GF's effective-coverage
     logic.
   - Nigeria wheat, poorest quintile: covered women eat about 38 g/day (vs. 84 under
     `all_intake_in_covered`). The covered group accounts for about 45% of all wheat eaten.

The two options give the **same effective coverage**, so hemoglobin results are nearly the
same. They differ in the amount of fortified vehicle eaten, so birthweight and NTD results
differ. Which one is right depends on what each coverage figure measures. That's a question for
GF, separate from this redesign: for example, does wheat's 28% mean home flour use only, or all
wheat products? If GF revises a coverage figure, it goes in unchanged under either option.

### Why it's better

- **It removes the clipping artifact.** No covered woman is drawn at zero intake, so
  effective coverage is exactly coverage × fortified share × effectiveness, as GF intends.
- **It uses the survey's numbers coherently.** `covered_are_upper_tail` uses the mean and SD as
  published. `all_intake_in_covered` uses the mean and CV, with no impossible constraint and
  no negative variance to guard against.
- **The assumption about women outside coverage becomes explicit and testable.** It moves
  birthweight and NTD results, and today it's hidden inside the mixture inversion.
- **Consumer parameters are computed in one place** (data prep), instead of being re-derived
  in the sim (`mean / any`) and in the NTD model (`mean / any`) separately.

### Changes by component

| Where | Change |
|---|---|
| Extraction sheet / `build_extraction.py` | Store the survey numbers as published, with a basis label (e.g. Data point name "usual intake mean (all women)", "usual intake SD (all women)"). Add the per-arm option. Coverage rows are unchanged. |
| `prep_extracted.ipynb` | Compute consumer intake parameters (gamma shape and scale) per stratum, for the chosen option. Write them to `vehicle_consumption/amount/consumer_shape/` and `consumer_scale/` (or mean/SD among consumers). The Nigeria U5 interpolation already works on means and variances, so it carries over. Its "within-group variance > 0" check becomes unnecessary. |
| `0200_pregnancy_sim/.../intervention.py`, `VehicleConsumption` | Keep the Bernoulli(*p*) draw for "covered". For covered simulants, draw grams from the gamma, or, for `covered_are_upper_tail`, set *U* = 1 − *p* + *p* × uniform and take the gamma quantile at *U*. Remove the mixture inversion and the clip. Use the framework's randomness streams so scenarios share draws. |
| `IronFortification` | No change to coverage logic. Optionally add a `minimum_effective_iron_mcg_per_day` parameter (default 0) to `update_hemoglobin_exposure`, so the "any intake gives the full effect" assumption is explicit. |
| Coverage notebook, anemia models (`0400`) | No change. |
| NTD model (`0500`, cells 46–51, 66–68) | Read the consumers' mean intake from data prep instead of computing `mean / any`. Ideally, integrate NTD risk over the consumers' intake distribution rather than using its mean, because the risk is non-linear. |
| Child sim | No change. It takes maternal iron intake from the pregnancy sim's output. |

### Tests

- Draws match the target consumer mean and SD per stratum, within sampling tolerance, and
  there are no negative draws.
- Effective coverage from the sim equals coverage × fortified share × effectiveness (no
  clipping loss), and matches GF's figures.
- Under `covered_are_upper_tail`, the mean intake of covered women matches the analytic
  upper-tail mean.
- **Regression check:** with `all_intake_in_covered`, results match the current model on a
  high-coverage arm (bouillon, *p* ≈ 0.98). Differences on wheat and rice should be
  explainable by removing the clipping.
- **Rollout:** a per-arm switch (`consumption_model = zero_inflated_normal | gamma`), so the
  old and new models can run side by side.

### Questions to settle before implementing

1. **For each vehicle, what does GF's coverage figure measure?** For Nigeria wheat, is it home
   flour use only, or does it include bread and other products? This decides which option
   applies.
2. **Should a minimum effective dose replace "any intake"** for the hemoglobin effect?
