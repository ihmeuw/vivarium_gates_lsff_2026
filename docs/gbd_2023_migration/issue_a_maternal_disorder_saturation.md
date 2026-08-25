# Issue A (rewritten, with retraction) — for the GBD 2023 migration

**Title:** `GBD 2023: maternal-disorder probability saturates at its clip bound in Nigeria (RETRACTS the earlier severe-anemia report)`

**Labels:** `data`, `gbd-2023`, `blocker-before-production-run`

---

## Retraction first

**An earlier version of this issue reported that `risk_factor.hemoglobin.pregnant_proportion_below_70_gL` jumped 38x to 0.582 under GBD 2023, and called it a genuine round effect. That was wrong. It was our own bug.**

The cause was the `1 - cdf` MirroredGumbel workaround in `lsff_utils.hemoglobin_distribution`, still applied against a library that had fixed the upstream bug it was written for ([risk_distributions#62](https://github.com/ihmeuw/risk_distributions/issues/62)). The workaround re-inverted an already-correct CDF, and since the mirrored-Gumbel component carries 60% of the ensemble weight the result was wrong by up to 0.6 and *decreased* with x.

The smoking gun: as shipped, `cdf(70)` = **0.5896** — which is the 0.582 the artifact was reporting.

Fixed, artifacts rebuilt, and measured against the verified GBD-2021 reference:

| key | combo | GBD 2021 | GBD 2023 | ratio |
|---|---|---|---|---|
| `hemoglobin.pregnant_proportion_below_70_gL` | nigeria | 0.01534 | 0.02333 | **1.52x** |
| | india | 0.01802 | 0.02671 | **1.48x** |
| `hemoglobin_on_maternal_hemorrhage.paf` | nigeria | 0.04309 | 0.06741 | **1.56x** |
| | india | 0.04814 | 0.07186 | **1.49x** |

So severe anemia is up about **1.5x**, an ordinary GBD revision. **The dependent claims are void too**: the PAF is 1.56x rather than 14.9x, and the reported collapse of simulated hemorrhage incidence to 0.21x was downstream of the same bug.

### Why the earlier reasoning failed

I argued it was a data effect because the value **reproduced in two independently built GBD-2023 artifacts**. Both were built with the modern library, so both carried the inverted CDF. **Reproducibility across builds distinguishes nothing when the builds share a code path** — it rules out a one-off build accident and nothing more.

Two related lessons, since they cost real time:

- **Re-test upstream-bug workarounds individually on a library upgrade.** #62 became actively harmful; its sibling #61 (the `computability_min`/`max` override) is still required — `Gamma.get_parameters` returns bounds of [69.4, 162.2] for mean 110 / sd 15, and without the override 4 of 9 hemoglobin test points come back NaN. A blanket "don't touch these" was wrong in both directions.
- **The `0400` notebook's own `test_pdfs_cdfs_consistency` found this**, not any of the five regression-harness layers. It was failing by a mean of 0.5866 against a 0.005 tolerance, with a maximum of exactly **0.600000** — the mirrored-Gumbel weight. A discrepancy pinned at a component's weight says that component is inverted, not mis-tuned. Worth reading self-checks when they fire rather than widening the tolerance.

---

## Finding 1 (stands): maternal-disorder probability saturates at exactly 1.0

`cause.maternal_disorders.incident_probability` is pinned at its clip bound for most of Nigeria's childbearing-age rows. Independent of the CDF bug — re-verified against the rebuilt artifacts.

| combo | GBD 2021 median | GBD 2023 median | values exactly 1.0 (of 45 non-zero) |
|---|---|---|---|
| nigeria/rice, nigeria/bouillon | 0.614 | **1.000** | **27** (0 under GBD 2021) |
| india/rice | 0.606 | 0.549 | **3** (0 under GBD 2021) |

The cause is the last line of `load_pregnant_maternal_disorders_incidence_probability` (`0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/data/loader.py:429`):

```python
result = _distribute_by_disparities_multiplicative(
    maternal_disorders_incidence.dropna(how="all"), disparities, location
).clip(upper=1)
```

That guard was **inert under GBD 2021** — nothing reached 1.0, max 0.841 — and is now load-bearing. `maternal_disorders.raw_incidence_rate` rose only 1.59x in Nigeria (0.0649 → 0.1030), so the clip is the amplifier, not the revision.

**Simulation consequence:** every pregnant woman in a saturated age x quintile cell deterministically gets a maternal disorder. Nigeria reports maternal disorders in **91.8%** of parturitions against 76.5% under GBD 2021.

**Pipeline consequence, and this is the sharpest evidence:** `maternal_disorders_incident_cases_by_scenario` moves **1.84x for Nigeria but 0.578x for India** — opposite directions. India's underlying incidence actually *fell* (`raw_incidence_rate` 0.850x), so its cases fell; Nigeria's rose modestly and then the clip amplified it. A single round revision producing opposite-signed changes in two countries is the signature of a threshold effect rather than a data trend.

**A probability pinned at its clip bound is exactly the failure mode the clip was meant to hide.** Whatever the fix to the numerator, the clip should warn or raise rather than silently saturate, so the next round does not do this again quietly. Note India at 3/45 is already over the line — this is not a Nigeria-only problem, just a Nigeria-mostly one.

---

## Finding 2 (stands): the revisions diverge sharply by country

Also independent of the CDF bug, and worth flagging because it defeats any single-country sanity check.

| key | nigeria | india |
|---|---|---|
| `maternal_abortion_and_miscarriage.raw_incidence_rate` | **4.51x** (0.0164 → 0.0740) | **0.43x** (0.00501 → 0.00215) |
| `ectopic_pregnancy.raw_incidence_rate` | 0.42x | 0.33x |
| `maternal_disorders.raw_incidence_rate` | 1.59x | 0.85x |
| `0100_data_prep` pregnancy incidence | — | **0.77x** (Ethiopia: **1.18x**) |

Nigeria's abortion/miscarriage incidence more than quadrupled while India's more than halved. In Nigeria this is a primary driver of model output — the partial-term share of parturitions goes 18.4% → 46.2%, crowding live births down 78.9% → 52.7% and shrinking the birth line list by a third. That line list is the **entire input population of `0300_child_sim`**.

I originally logged the abortion/miscarriage move as "no amplifying downstream, not obviously wrong." That was also wrong, and running the simulation is what showed it.

---

## Pipeline-level impact: the headline survives

Full pipeline under GBD 2023, all stages, 10 seeds:

| combination | comparison | GBD 2021 averted | GBD 2023 averted | ratio |
|---|---|---|---|---|
| india/rice | baseline → intervention | 476,326 | 476,531 | 1.000 |
| nigeria/rice | baseline → intervention | 280,678 | 270,990 | 0.965 |
| nigeria/bouillon | baseline → intervention | 1,978,043 | 1,700,343 | 0.860 |
| ethiopia/salt | baseline → 100% NRV | 528,422 | 541,116 | 1.024 |

**128 of 165 tracked CSVs are byte-identical.** The levels moved far more than the differences — total DALYs 0.93–0.97x, Ethiopia's prevalent anemia 1.24x — which is why averted DALYs barely budge: it is a within-run difference, so common shifts cancel.

Two caveats on reading these:

- **The round and the estimation year are not separable.** `vivarium_inputs.get_measure` with no `years` argument returns the round's terminal year — verified, `[2021]` from the old library and `[2023]` from the modern one. GBD 2023 does not estimate hemoglobin me_ids 10487/10488 for 2021 *at all*, so holding the year fixed is impossible.
- **10 seeds, not 200.** The reproduction measured Monte Carlo noise at median 0.001–1.2% with per-cell maxima near 11%, so the 3.5% and 14% aggregate moves are real but per-quintile detail is not trustworthy.

---

## Separate open decision: the stillbirth definition

GBD 2023 split `stillbirth_to_live_birth_ratio` into 20-week and 28-week variants and dropped the unqualified one. The migration uses **28 weeks** (`data_keys.SBR`), and I matched it in `0500` and `pregnancy_results.ipynb` so the stages share a definition. **This is not the continuity-preserving choice.** For Nigeria:

| covariate | value | vs GBD 2021 unqualified (0.0387) |
|---|---|---|
| GBD 2023, 20 weeks | 0.0436 | 1.13x |
| GBD 2023, 28 weeks | 0.0265 | **0.68x** |

So the current choice cuts the stillbirth ratio by about a third relative to what the published results used. It affects neonatal deaths and needs a research decision, not a default.

---

## Reproducing

```bash
LSFF_ARTIFACT=<new>.hdf LSFF_REFERENCE_ARTIFACT=<gbd2021>.hdf \
    pytest tests/test_artifact_sanity.py
```

Against the rebuilt GBD-2023 artifacts this now flags exactly two keys each — and notably **not** the hemoglobin keys, which is the retraction confirmed by the harness:

- nigeria/rice: `maternal_abortion_and_miscarriage.raw_incidence_rate`, `maternal_disorders.incident_probability`
- india/rice: `ectopic_pregnancy.raw_incidence_rate`, `maternal_disorders.incident_probability`

Finding 1 is caught by a check added for it, `test_probability_key_is_not_saturated_at_its_bound`: no key bounded in [0, 1] may sit at exactly 1.0 for more than 5% of its non-zero values. It needs no reference artifact, because a clip bound is an absolute statement about the data. The ratio checks are structurally blind to saturation — a value clipped at 1.0 has nowhere to move, so `incident_probability` registers only 1.63x. The 5% allowance is empirical: across three verified GBD-2021 artifacts, no probability-valued key had a single value at exactly 1.0.

Copy any artifact under `/mnt/team/` before opening it — `Artifact` can write and that path is shared.

---

## Confirmed fine — recorded so nobody re-chases

- **Maternal hemorrhage is fixed.** `incident_probability` is non-zero with 45 non-zero rows in every build, and hemorrhage transitions fire in all three scenarios. The `broadcast_onto` fix in `02158e1` works.
- **Severe anemia and the hemorrhage PAF are ordinary revisions** (~1.5x). See the retraction.
- **The hemoglobin SD is not a problem.** An even earlier read blamed it; that was an artifact built without `--mean` (single draw, 23.74). A `--mean` rebuild gives 18.05 against 15.25 — 1.18x.
- **Data-prep-derived keys are numerically identical** across vintages, as they should be — no GBD coupling — which is what makes the comparison isolate GBD effects cleanly.
- Five `iron_fortification.baseline_*` keys are all-zero in **both** vintages; Nigeria has no existing rice fortification programme (bouillon is ~0.52).
- **Pregnancy incidence in the simulation is unchanged** — parturitions per seed match to 0.05%.
- `maternal_disorders.ylds` differing ~250x between a `--mean` and a non-`--mean` build is a pre-existing draw-alignment bug, filed separately as #&lt;ISSUE-B&gt;. The anemia-responsiveness scoping question is #&lt;ISSUE-C&gt;.

**Beware comparing artifacts built with and without `--mean`.** A no-`--mean` build stores `draw_0`; a `--mean` build stores the mean across draws. That produced one of the false leads above.
