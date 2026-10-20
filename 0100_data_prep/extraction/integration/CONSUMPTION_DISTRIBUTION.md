# Vehicle consumption: survey data vs. the model's distribution

## Current model

For each arm and stratum, data prep writes the probability *p* that a woman eats the vehicle (`any/`) and the mean *m* and SD *s* of intake over all women, non-consumers counted as 0 (`amount/mean/`, `amount/sd/`, under `0100_data_prep/results/<vehicle>/vehicle_consumption/`). The pregnancy sim (`0200_pregnancy_sim/.../components/intervention.py`, `VehicleConsumption.on_initialize_simulants`) treats intake as a zero-inflated normal: 0 with probability 1 − *p*, otherwise Normal(μ, σ²) clipped at 0, with

    μ  = m / p
    σ² = s² / p − μ² (1 − p)

The NTD model (`0500_neural_tube_defects_model/model.ipynb`, cells 46–51) also uses *m*/*p*. The hemoglobin effect is all-or-nothing (any fortified iron intake > 0 gets the full effect in `update_hemoglobin_exposure`), so hemoglobin depends on effective coverage (*p* × share fortified × effectiveness), not on amount. Birthweight is linear in maternal iron intake, so it depends on the mean. NTD risk is nonlinear in folate intake among consumers.

## What the survey reports

NFCMS (Nigeria, 2021) reports NCI-method usual intake (Tooze 2010): a long-run daily average for every person, so occasional eaters get small positive values and there is no point mass at 0. The usual-intake tables (e.g. Tables 147, 172) are population-wide; NFCMS labels consumer-only statistics "among consumers" and these tables carry no such label. GHS-Panel 2023/24 microdata give rice intake of 62.7 g/day, against 61.2 in NFCMS.

Our *p* is GF's coverage, the share who eat the vehicle, fortified or not, and the first factor in GF's effective coverage (coverage × consolidation × compliance). It comes from a separate survey question: for wheat, households using wheat flour at home, 28% (Table 146); for rice, an INTAKE tabulation, 53.6%. Usual intake is positive for almost everyone, and women who don't use flour at home still eat vendor-made bread, so coverage and the intake distribution measure different things. The model has to say how they relate.

## The problem

A zero-inflated distribution with mean *m* has a minimum standard
deviation (SD), reached when every consumer eats exactly *m*/*p*:

    SD over all women ≥ m √((1 − p) / p)

The NFCMS SDs (IQR/1.35) fall well below it for low-coverage vehicles:

| Nigeria, poorest quintile | *m* | *p* | minimum SD | NFCMS SD |
|---|---|---|---|---|
| wheat | 16.1 | 0.191 | 33.1 | 13.3 |
| rice (if read as per capita) | 34.2 | 0.336 | 48.1 | 24.8 |

Using these directly gives a negative consumer variance and NaN draws; the build checks for this and stops. Separately, clipping at 0 with a consumer CV around 0.8 puts about 10% of consumers at zero intake, and because the hemoglobin effect is all-or-nothing they lose the benefit, cutting effective coverage by up to about 10%.

## Interim fix: survey coefficient of variation (CV) applied to consumers

Keep *p* and the published mean *m*, give consumers the survey CV = *s*/*m*, and write the implied SD over all women to the extraction tables:

    μ = m / p
    σ = CV × μ
    SD over all women = sqrt( p σ² + p (1 − p) μ² )

This is decisions D007 and D008 (Nigeria wheat) and P008 and D032 (Nigeria rice) in `decisions.csv` (`source = method:consumer_cv`, amount SD rows, WRA and U5). `method_consumer_cv()` in `build_extraction.py` reads the NFCMS mean and SD from `lit_long.csv`: the literature row an active `lit:` decision chose for the row, if any, otherwise by the literature extraction's `Use in model` pick when there are several candidates, and takes *p* from the build's current coverage values. U5 rows use national WRA coverage, since children get the women's coverage.

It keeps the published mean (birthweight) and GF's coverage (effective coverage, hemoglobin), and consumer variance is always positive. It gives up the NFCMS SD over all women (45–101 for wheat vs. 13–33), assumes the usual-intake CV carries over to consumers, and still clips 3–12% of wheat consumers.

Nigeria wheat, women 15+:

| quintile | *p* | mean | consumer mean | consumer CV | SD, all women (previous, rice-derived) | clipped |
|---|---|---|---|---|---|---|
| Lowest | 0.191 | 16.1 | 84.3 | 0.82 | 44.9 (48.3) | 11% |
| Second | 0.253 | 23.4 | 92.5 | 0.81 | 55.1 (48.8) | 11% |
| Middle | 0.305 | 38.2 | 125.2 | 0.72 | 76.2 (63.8) | 8% |
| Fourth | 0.333 | 49.3 | 148.0 | 0.64 | 88.4 (72.2) | 6% |
| Highest | 0.353 | 62.4 | 176.8 | 0.53 | 101.1 (86.6) | 3% |

Nigeria rice used the older among-consumers treatment (D006: g/cap × coverage, NFCMS SDs as published) until 9 Oct 2026, which understated consumers' intake by 1/*p* (1.5× in the richest quintile to 3.0× in the poorest). It is now per capita with the same CV rule (P008, D032).

Nigeria rice, women 15+:

| quintile | *p* | mean | consumer mean | consumer CV | SD, all women (NFCMS) | clipped (before) |
|---|---|---|---|---|---|---|
| Lowest | 0.336 | 34.2 | 101.8 | 0.73 | 64.4 (24.8) | 8% (15%) |
| Second | 0.448 | 52.4 | 117.0 | 0.64 | 76.6 (33.3) | 6% (5%) |
| Middle | 0.546 | 60.7 | 111.2 | 0.58 | 72.9 (35.0) | 4% (1%) |
| Fourth | 0.633 | 73.7 | 116.4 | 0.51 | 73.5 (37.8) | 3% (0%) |
| Highest | 0.676 | 79.5 | 117.6 | 0.49 | 72.7 (39.0) | 2% (0%) |

## Proposed redesign: gamma intake for covered women

GF coverage, consolidation, compliance and effective coverage are unchanged, as are the coverage notebook, the anemia models and `IronFortification`'s coverage logic. Only covered women's intake changes, to a gamma computed in data prep, with a per-arm option stating what women outside coverage eat:

- `all_intake_in_covered`: they eat none, as now. Covered women's intake is gamma with mean *m*/*p* and the survey CV (the interim rule without clipping).
- `covered_are_upper_tail`: the survey distribution describes everyone and covered women are its top *p*; the rest eat forms the coverage question doesn't count, such as bought bread. Fit a gamma *F* to *m* and *s* over everyone; covered women draw *U* ~ Uniform(1 − *p*, 1), intake = *F*⁻¹(*U*). For Nigeria wheat, poorest quintile, covered women eat about 38 g/day (vs. 84), and the covered group eats about 45% of all wheat.

Both give the same effective coverage, so hemoglobin is nearly the same; birthweight and NTD differ. Which is right depends on what each coverage figure measures, e.g. whether wheat's 28% includes bread.

The redesign removes the clipping loss, uses the survey mean and SD (or CV) without an infeasible constraint, makes the assumption about women outside coverage an explicit setting, and computes consumer parameters once in data prep instead of as `mean / any` in both the sim and the NTD model.

### Changes by component

| Where | Change |
|---|---|
| `build_extraction.py` / extraction tables | Store survey numbers as published with a basis label (e.g. "usual intake mean (all women)"). Add the per-arm option. |
| `prep_extracted.ipynb` | Write gamma shape and scale per stratum to `vehicle_consumption/amount/consumer_shape/` and `consumer_scale/`. The Nigeria U5 interpolation (on means and variances) carries over; its "within-group variance > 0" check is dropped. |
| `intervention.py`, `VehicleConsumption` | Keep the Bernoulli(*p*) "covered" draw. Covered simulants draw from the gamma, or for `covered_are_upper_tail` take its quantile at *U* = 1 − *p* + *p* × uniform. Remove the mixture inversion and clip. Use framework randomness streams so scenarios share draws. |
| `IronFortification` | Coverage logic unchanged. Optional `minimum_effective_iron_mcg_per_day` (default 0) in `update_hemoglobin_exposure`. |
| NTD model (`0500`, cells 46–51, 66–68) | Read consumer mean from data prep instead of `mean / any`; ideally integrate risk over the consumer distribution. |
| Coverage notebook, anemia models (`0400`), child sim | No change. |

### Tests

- Draws match target consumer mean and SD per stratum, with no negatives.
- Sim effective coverage equals coverage × fortified share × effectiveness and matches GF.
- Under `covered_are_upper_tail`, covered women's mean matches the analytic upper-tail mean.
- Regression: `all_intake_in_covered` matches the current model on bouillon (*p* ≈ 0.98); differences on wheat and rice are explained by removing the clipping.
- A per-arm `consumption_model = zero_inflated_normal | gamma` switch runs old and new side by side.
