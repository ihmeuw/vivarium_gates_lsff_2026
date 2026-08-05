# TODO: DHS refresh

The DHS surveys behind every wealth-quintile disparity in this study are 1–3 rounds
behind, and newer extracts are already on the same drive. Nothing in the GBD-2023
migration touched them, because DHS is not GBD.

| survey | in use | also available on `/snfs1/DATA/DHS_PROG_DHS/` |
|---|---|---|
| India DHS | **2015–2016** | 2019_2021, **2023_2024** |
| Nigeria DHS | **2018** | **2023_2024** |
| Ethiopia DHS | **2016** | **2024_2025** |

This matters more than its size suggests: DHS produces *all* of
`wealth_quintile_probabilities`, `hemoglobin/{mean,sd}_disparities`,
`birth_weight_disparities` and `maternal_disorders_incidence_disparities` — the
stratification the study exists to report.

**Do this on its own branch, separate from the GBD-2023 work.** Mixing a survey refresh
with a round change would make neither attributable.

Blast radius, counted rather than estimated — of 165 tracked result CSVs:

- **14 direct DHS outputs** (the four families listed above, across locations)
- **up to 24 stage-5000 CSVs**, reached via the artifacts and both microsims
- `0400` outputs move too, but they are parquet and gitignored

So expect **up to ~38 tracked CSVs to change**, not the whole tree.
`0100_data_prep/coverage_calculation/` and the `0500` NTD model do **not** read any DHS
output — checked — so the folate pathway is untouched except where stage 5000 combines the
two streams.

---

## Tier 0 — Decide the vintage before touching any value

- [ ] **Choose a round per country.** India 2023_2024 and Nigeria 2023_2024 align well;
      Ethiopia's 2024_2025 is newer still. Mixed rounds are already the status quo
      (2015/2018/2016), but this is the moment to decide deliberately rather than inherit.
- [ ] **Pull the DHS recode manuals** for the chosen files. Every current file is `DHS7`;
      standard recode variables are stable across rounds, **country-specific `s*`
      variables are not**.
- [ ] **Decide whether Ethiopia gets a maternal-mortality notebook.** Only India and
      Nigeria have one, so only they produce `maternal_disorders_incidence_disparities`.
      This asymmetry is deliberate today (see CLAUDE.md, "Location coverage is asymmetric
      on purpose") — a refresh is the natural point to revisit it, not to quietly fix it.
- [ ] **Update the hardcoded filenames.** Directories *and* the
      `Y2018M12D06`-style extraction stamps are hardcoded per location in:
      - `0100_data_prep/dhs/common.ipynb`
      - `0100_data_prep/dhs/maternal_mortality_india.ipynb`
      - `0100_data_prep/dhs/maternal_mortality_nigeria.ipynb`

      (`0100_data_prep/hces/01_extract_hces.ipynb` also holds hardcoded paths, but HCES
      2022–2023 is current — leave it alone.)

## Tier 1 — The stratifier itself, which re-bases everything below

- [ ] **Wealth quintile composition** — `v190` (women) / `hv270` (household), weighted by
      `v005`/`hv005` → `results/wealth_quintile_probabilities/{location}.csv`
      → consumed by `0200`, `0400`

**Refresh this first and stop to look at it.** Quintiles are a *within-survey relative*
measure, so a new round re-defines the wealth distribution rather than merely updating it.
Every disparity below is conditioned on it, so a shift here re-bases all of them.

The `poorest…richest` → 1–5 recode lives in `lsff_utils.data_processing`, so a label
change fails loudly rather than silently — that part is safe.

## Tier 2 — Hemoglobin exposure disparities

- [ ] **Hemoglobin mean by quintile** — `ha56` → `results/hemoglobin/mean_disparities/{location}.csv`
- [ ] **Hemoglobin SD by quintile** — `ha56` → `results/hemoglobin/sd_disparities/{location}.csv`

Both consumed by the `0200` artifact and `0400`. Both stratified by pregnancy status
(`v213`), emitted for Female 15–125 plus a `not_pregnant` subset.

- [ ] Confirm DHS-8 **altitude/smoking adjustment** conventions. The code deliberately
      uses `ha56` (altitude-adjusted), not `ha53` (raw).
- [ ] Note `hc53`/`hc56`/`hc57` (child hemoglobin) are read but only adults feed the
      output. Leave as-is unless the child model changes.
- [ ] **Re-run layer 3 of the harness after this step.** These disparities are reindexed
      onto GBD age groups by `reindex_series_onto_df_by_age_groups`, which silently drops
      rows if a GBD bin straddles a DHS bin edge. `test_gbd_assumptions.py` guards exactly
      this — and run it in **both** `.venv_modern` and `.venv`.
- [ ] Expect `risk_factor.hemoglobin.pregnant_proportion_below_70_gL` to move. It will move
      *legitimately* this time — see CLAUDE.md, "The severe-anemia finding was a code bug",
      for why an earlier large move there was ours and not the data's.

## Tier 3 — Birth outcomes

- [ ] **Mean birth weight by quintile** — `m19` → `results/birth_weight_disparities/{location}.csv`
      → consumed by the `0300` child artifact

- [ ] **Decide the `m18` question.** `m18` (`size_of_child`, the subjective proxy) is read
      but unused. `m19` is card-or-recall reported, with heavy missingness and heaping at
      round numbers, and **its coverage differs by wealth quintile** — which biases
      precisely the disparity being estimated. Either use `m18` to impute or record why
      not. The current `.replace()` for missing codes is at `common.ipynb` line ~356.

## Tier 4 — Maternal disorders

- [ ] **Maternal-disorder incidence disparity** — sibling-survival `mm1`–`mm16` (Nigeria)
      → `results/maternal_disorders_incidence_disparities/{india,nigeria}.csv`
      → consumed by the `0200` artifact

**Refresh this and re-check the clip saturation together — they are not independent.** This
disparity is multiplied into incidence *immediately before* `.clip(upper=1)` at
`0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/data/loader.py:429`, where 27 of
45 Nigeria rows currently sit at exactly 1.0. Wider disparities push more cells into the
clip; narrower ones relieve it. See `docs/gbd_2023_migration/issue_a_maternal_disorder_saturation.md`.

- [ ] The two `maternal_mortality_*.ipynb` files are per-country copies with
      `if location == "india" else …` branches. India filenames appear inside the Nigeria
      notebook for that reason — **it does not read India data**. Verified; don't "fix" it.

## Tier 5 — Computed but not exported

- [ ] **Pregnancy duration by quintile** — `s220a` (India), `b20` (others). Computed at
      `common.ipynb` line ~376 and **never written to CSV**, so it is exploratory only.

Low priority *because it is not exported*, but it is the highest-risk variable in the
refresh: `s220a` is India-specific and country-specific variables get renumbered between
rounds. Check it before anyone wires it into an output.

---

## Verification sequence

- [ ] Rebuild maternal and child artifacts.
- [ ] `LSFF_ARTIFACT=<new> LSFF_REFERENCE_ARTIFACT=<pre-refresh> pytest tests/test_artifact_sanity.py`
      — the ratio and saturation checks are the right tool here, and localise a problem to
      one key in seconds rather than after two microsims.
- [ ] `pytest tests/test_gbd_assumptions.py` in both environments (age-bin nesting).
- [ ] `pytest tests/test_simulation_plausibility.py --runslow` — needs no baseline, so it
      still works when the reference is legitimately out of date.
- [ ] Full pipeline. **Expect layer 1 (`test_deterministic_results.py`) to fail broadly and
      legitimately** — the DHS-derived CSVs are the deterministic half of the pipeline.
      That is the one situation where regenerating baselines is the right call, but only
      after the diffs have been reviewed value by value.
- [ ] Decide separately whether to regenerate `tests/reference/sim_proportions.csv`. It is
      the only surviving record of published behaviour, and the April-2025 parquet exists
      nowhere.

## Two cautions specific to this refresh

1. **`dhs/common.ipynb` and both maternal-mortality notebooks `to_csv` without `mkdir`.**
   They only work because the tracked output directories already exist. Do not clean the
   tree before running them.
2. **A failed Snakemake run deletes committed baseline CSVs.** Commit or stash before any
   pipeline run, and restore with `git checkout -- '*/results/'`.

## Not in scope here, but adjacent

These are non-GBD inputs that a DHS refresh will *not* fix, listed so they are not
forgotten (full inventory in the conversation that produced this file):

- Anemia disability weights are frozen at GBD 2021 — `auxiliary_data/` has no 2023
  equivalent, so `0400` computes YLDs with 2021 weights against 2023 prevalence.
- `s_dist_deaths_by_wealth` in `0500` is **all 1s for every location** — no wealth gradient
  in NTD deaths, in a wealth-stratification study. The code calls it a guess.
- Iron effect sizes (rice 3.25, salt 4.4, bouillon 4.2 g/L; 1.67 g birthweight per mcg/day)
  come from the hand-maintained extraction sheet.
- NTD log-odds coefficients are Crider 2014 and Daly 1995.
- `/share/mnch/anemia/code/reference/model/anemia_thresholds.csv` was last modified
  2022-03-10, lives in another team's directory, and is duplicated as hardcoded thresholds
  in `0200/constants/data_values.py` — the two can drift apart silently.
- `PROBABILITY_MODERATE_MATERNAL_HEMORRHAGE` and
  `RR_MATERNAL_HEMORRHAGE_ATTRIBUTABLE_TO_HEMOGLOBIN` are each **defined twice** in
  `0200/constants/data_values.py` (lines 25/99 and 73/101). Values agree today, so it is
  latent: edit one and the later definition silently wins.
