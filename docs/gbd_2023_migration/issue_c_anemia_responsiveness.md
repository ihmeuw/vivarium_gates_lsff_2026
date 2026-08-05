# Issue C — anemia responsiveness classification in `0400`

**Title:** `0400 treats unclassified anemia sequelae as iron-responsive, giving ~1-4% of anemia a fortification benefit it may not be entitled to`

**Labels:** `data`, `research-decision`, `0400-non-pregnant-anemia`

---

## Summary

`0400_non_pregnant_anemia_model` splits anemia into iron-responsive and non-responsive. The iron-responsive group is built as a **residual**, so any anemia sequela the notebook does not explicitly classify is treated as iron-responsive and receives the fortification hemoglobin shift.

26 anemia sequelae are currently unclassified — genetic and endocrine causes (thalassemia, G6PD deficiency, thyroid-related). Their combined prevalence in Nigeria averages **0.0049** and peaks at **0.0182**, against a modelled total anemia prevalence of **0.472**: so about **1% of all anemia on average, rising to ~3.9%** in the strata where these causes concentrate. If they are in fact non-responsive, which their aetiology suggests, the model is **overstating the benefit of iron fortification** for that share of the anemic population.

This needs a decision from whoever owns the anemia model. It is not a code bug — the code does what it says — it is a question of whether the scoping is intended.

GBD 2023 added three more (below), but those are numerically negligible. **The 26 are the finding.**

---

## Why "unclassified" means "responsive"

Not obvious from reading the notebook top to bottom, and I initially recorded it backwards, so worth being explicit.

The notebook defines two lists:

```
line 333:  iron_responsive_anemia_sequelae     = [ ... 138 entries ... ]
line 473:  non_iron_responsive_anemia_sequelae = [ ...  60 entries ... ]
```

Only the second is ever consumed. Every reference to the first:

```
line 333:  iron_responsive_anemia_sequelae = [      # definition
line 535:  len(iron_responsive_anemia_sequelae)     # display cell
```

That is the whole list of uses. `iron_responsive_anemia_sequelae` is **dead code** — 138 entries of documentation.

The non-responsive list drives the actual split:

```python
# line 584
non_iron_responsive_prevalence = pull_sequelae_prevalence(
    location, non_iron_responsive_anemia_sequelae
)
# line 975 -- denominator is total anemia from the hemoglobin distribution,
# not the sum of the classified sequelae
non_iron_responsive_anemia_proportion = (
    non_iron_responsive_prevalence / gbd_anemia_prevalence
)
# line 990 -- responsive is what is left after removing non-responsive
iron_responsive_distributions = delete_from_mixture_distributions(
    hemoglobin_distributions_by_age_sex_quintile,
    non_iron_responsive_hemoglobin_distributions,
    non_iron_responsive_anemia_prevalence_by_age_sex_quintile,
)
```

and downstream the notebook uses `1 - non_iron_responsive_anemia_prevalence_by_age_sex_quintile` (lines 1054, 1078, 1083, 1120, 1125).

So the responsive group is the complement of the 60-entry list against **total** anemia prevalence. An unclassified sequela is not excluded from the population — it is silently included as responsive and gets the fortification shift.

**Consequence:** omitting a genuinely non-responsive sequela biases the estimated fortification benefit **upward**. The direction matters for how the study reads, which is why this is worth an issue rather than a code comment.

---

## Magnitude

Combined prevalence, Nigeria, GBD 2023, sequelae combined under the notebook's own independence assumption (`result += p * (1 - result)`):

| group | count | mean prevalence | peak prevalence |
|---|---|---|---|
| **GBD-2021 backlog** (genetic/endocrine) | 26 (25 with data) | 0.0049 | **0.0182** |
| GBD-2023 additions (puerperal sepsis) | 3 | 3.2e-07 | 2.7e-06 |

For the denominator I used the notebook's own construction — the ensemble hemoglobin CDF from `lsff_utils.hemoglobin_distribution` evaluated at the `adult_female_np` mild-anemia threshold of 120 g/L, against the hemoglobin mean and SD in the Nigeria maternal artifact. That gives anemia prevalence of **0.441-0.514 across 45 strata, median 0.472**, which is a plausible figure for Nigerian women of reproductive age.

So the backlog is roughly **1% of all anemia on average and up to ~3.9%** where it peaks; the GBD-2023 additions are about one part per million. Four orders of magnitude apart.

Caveat on the denominator: those hemoglobin parameters are the maternal artifact's, i.e. reproductive-age women, used as a proxy because `0400`'s own denominator is built the same way. Good enough to separate "1%" from "negligible", not a substitute for running the notebook.

The 26, from `KNOWN_UNCOVERED_ANEMIA_SEQUELAE`:

- beta thalassemia major (mild/moderate/severe anemia)
- hemoglobin E beta thalassemia (mild/moderate/severe)
- hemoglobin H disease (mild/moderate/severe)
- G6PD deficiency (mild/moderate/severe)
- hyper- and hypothyroidism (mild/moderate/severe each)
- other endocrine/metabolic/blood/immune disorders (mild/moderate/severe)
- other hemoglobinopathies and hemolytic anemias, plus its four heart-failure sequelae

These are structural haemoglobin and endocrine disorders. Iron supplementation does not correct them, and in thalassemia and G6PD contexts iron loading is a recognised clinical concern rather than a benefit. That argues for the non-responsive bucket, but the call is the model owner's.

---

## The GBD 2023 additions

GBD 2023 added `puerperal_sepsis_with_{mild,moderate,severe}_anemia`. Verified genuinely new: GBD 2021 exposes 2088 sequelae with none of them, GBD 2023 exposes 2106 with all three.

Numerically negligible, and for a good reason — puerperal sepsis is a postpartum condition and `0400` models the **non-pregnant** population, so the overlap is nearly empty. Anemia accompanying sepsis is plausibly inflammatory rather than iron-deficiency, which would put it in the non-responsive bucket.

Worth classifying deliberately. Not worth a rerun on its own.

Recorded in `UNCLASSIFIED_GBD_2023_ANEMIA_SEQUELAE`, kept separate from the 26 so the two do not get conflated — one is a round-change consequence, the other inherited scope.

---

## How this surfaced, and a gap it exposed

`tests/test_gbd_assumptions.py::test_anemia_sequela_lists_cover_gbd` caught the three additions. It was written precisely for this case: a *removed* sequela raises `AttributeError` and is loud, an *added* one is silent.

It had been **skipping** in `.venv_modern` — the fixture did `importorskip("gbd_mapping")` and the modern suite renamed that module to `vivarium.gbd_mapping`, so the check was dark in the one environment now used for everything. Fixed to try both names; it then failed immediately on the three new sequelae. Worth knowing if other checks in the repo guard on old-namespace imports.

One limit of the check, recorded in its docstring: it compares against sequelae named **anywhere** in the notebook, so adding one to the dead 138-entry list silences it without changing the model. A green run means "classified", not "classified correctly".

---

## Suggested next steps

1. **Decide the 26.** If non-responsive, add them to `non_iron_responsive_anemia_sequelae` and rerun `0400`. Expect the anemia benefit to fall by something on the order of the ~1% average share, more in the strata where it peaks — but the effect on final DALYs is mediated by the distribution shift, so measure it rather than predicting from the prevalence share.
2. **Decide the 3** GBD-2023 additions the same way; no rerun needed for magnitude alone.
3. **Delete or wire up `iron_responsive_anemia_sequelae`.** 138 entries that look load-bearing and are not is a trap — it is what made me record the bias direction backwards. Either drop it, or compute the responsive prevalence from it and assert the two partitions sum to total anemia prevalence, which would make any future gap loud instead of silent.
4. Remove entries from `KNOWN_UNCOVERED_ANEMIA_SEQUELAE` / `UNCLASSIFIED_GBD_2023_ANEMIA_SEQUELAE` as they are classified; the test asserts in both directions and will prompt for the cleanup.

## Reproducing

```bash
source .venv_modern/bin/activate
pytest tests/test_gbd_assumptions.py::test_anemia_sequela_lists_cover_gbd
```

Run it in `.venv` too — the rounds disagree about which sequelae exist, so each environment exercises a different input contract.

Prevalence figures above come from the notebook's own `pull_sequelae_prevalence` logic against `vivarium_inputs.get_measure(..., "prevalence", "Nigeria")`, summed over each group with the independence assumption.
