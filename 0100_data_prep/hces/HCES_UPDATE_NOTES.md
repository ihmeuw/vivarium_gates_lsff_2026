# HCES notebook — 2026 update notes

Prepared on branch `ndbs-claude-hces` ahead of the HCES vintage update. These are
**suggestions, not a finished change** — see "Status and caveats" at the bottom before
merging any of it.

The changes all target one theme: when `01_extract_hces.ipynb` is pointed at a new HCES
round, its most likely failure modes are **silent**. Nothing raises; you get a dataframe
that looks fine and is wrong. Everything below is about converting those into loud
failures, plus one genuine bug fix found along the way.

---

## What changed

### 1. Survey vintage is configured in one place

`SURVEY_VINTAGE` and `FILE_STAMP` now drive a `hces_path(level)` helper, and all six level
reads go through it. Previously the round appeared in the directory string *and* in six
separate filenames (`IND_HCES_2022_2023_LVL_0*_Y2024M07D25.TXT`), so a vintage swap meant
seven coordinated edits with no guard against missing one — and a partial edit would load
some levels from the new round and some from the old. The merges are `on="common_id"` with
`how="outer"`, so a mixed-vintage load would not necessarily fail loudly; it would produce
a half-matched frame.

The config cell is written to be papermill-overridable if we ever want to run more than one
vintage from the Snakefile.

### 2. Fixed-width layouts are checked before reading (`checked_fwf_path`)

Every level is parsed with a hardcoded `widths=[...]` list. **If NSSO changed any field
width, or inserted or removed a field, `pd.read_fwf` does not error.** It shifts every
subsequent column and returns values that still look like plausible numbers. Given that
these columns feed the wealth PCA and the rice consumption tabulations, that failure could
propagate a long way before anyone noticed.

`checked_fwf_path(level, widths)` compares `sum(widths)` against the actual record length in
the first 200 lines and raises with both numbers if they disagree. This is cheap and catches
the common case. It is **not** a substitute for diffing the layout document — a change that
preserves total record width (e.g. one field grows by 1 and its neighbour shrinks by 1)
will slip through. Please still check the 2023-24 layout document field by field.

To make this possible the inline `widths=[...]` lists were hoisted into named variables
(`level_1_widths`, `level_3_widths`, …) directly above each read. That is the bulk of the
diff and is a pure move, no value changes.

### 3. Code→label maps are checked (`checked_map`)

The twelve `.map({...})` calls became `checked_map(series, mapping, name)`. Plain `.map()`
turns any unrecognised code into `NaN`; those `NaN`s are then swallowed downstream by
`.dropna(how="any")` before the wealth PCA. So a revised NSSO code list would quietly
degrade the wealth index — fewer households in the fit, no error, no visible symptom.
`checked_map` raises instead, naming the column and listing the unrecognised codes.

Set `STRICT_CODE_MAPS = False` in the helpers cell to downgrade this to warnings while
investigating.

### 4. Bug fix — employer meals were double-counted

In the `meals` sum, `meals_from_employer_last_30_days` appeared **twice**:

```python
household_members["meals"] = (
    household_members.meals_at_home_last_30_days.fillna(0)
    + household_members.meals_from_employer_last_30_days.fillna(0)     # <-- 1st
    + household_members.meals_from_school_balwadi_last_30_days.fillna(0)
    + household_members.meals_from_employer_last_30_days.fillna(0)     # <-- 2nd
    + household_members.meals_paid_last_30_days.fillna(0)
    + household_members.meals_others_last_30_days.fillna(0)
)
```

This looks like a copy-paste slip rather than intent. It inflates `meals`, which flows into
`non_government_meals_away_from_home`, then `rice`, then `proportion_government` and
`proportion_fortifiable` — i.e. into the saved India consumption and fortifiability outputs.

**This is the one change that alters results.** Re-running will shift the India numbers
slightly even on the unchanged 2022-23 data. If that matters for reproducing the published
2025 estimates, consider landing this fix on its own commit so the effect is attributable.

---

## Flagged but deliberately NOT changed

Both are judgment calls that belong to whoever owns the analysis. Comments were added
inline at each site; no behaviour changed.

**The 95th-percentile clip on `rice_per_meal_kg`.** The comment above it refers to the
handful of households reporting rice consumption with zero at-home meals, but the clip is
applied to the entire column — truncating the top 5% of *everyone's* rice-per-meal. Since
the SD of consumption feeds the pregnancy microsimulation, this shapes the tail of the
exposure distribution. Options: clip only the `impossible_rice_consumption` rows, or keep
the global clip as a deliberate, documented choice.

**`GOVERNMENT_BASELINE_COVERAGE = 0.8`.** Justified in-code by an IMPDS dashboard reading of
~70% in 2024. In **February 2026 the Government of India temporarily discontinued rice
fortification** under PMGKAY and allied schemes, following an IIT Kharagpur study on
micronutrient degradation in stored fortified rice; states may supply fortified or
non-fortified rice at their discretion for KMS 2025-26. This constant is where "the
programme is running" is encoded, so it is the natural place to revisit once the India
baseline scenario is re-agreed with stakeholders. That is a scenario-definition question,
not a data-prep one.

---

## Status and caveats

- **Untested against real data.** These edits were written without access to `/snfs1`, so
  the notebook has not been executed end to end. Treat the diff as a reviewed suggestion.
- **Verified in isolation.** `checked_map` and `checked_fwf_path` were exercised against
  synthetic fixtures: correct mapping, NaN tolerance, raising on unmapped codes, the
  strict/warn toggle, matching and mismatching record widths.
- **If `checked_map` raises on the current 2022-23 data**, that is itself a finding worth
  looking at rather than a reason to revert. Flip `STRICT_CODE_MAPS = False` to keep moving
  while you investigate which codes are unrecognised.
- Touched cells were formatted with `black` to match the surrounding style.

## Related: survey landscape as of Sept 2026

Context that motivated this pass. Full detail, with source-confidence labels, is in
`0100_data_prep/DATA_SOURCE_SCAN_2026-09.md`.

- **India** — HCES 2023-24 (Aug 2023–Jul 2024, ~262k households) is released; unit-level data
  on microdata.gov.in (catalog 237). NFHS-6 fieldwork ran May 2023–Dec 2024; fact sheets
  released May/Aug 2026, but unit-level recode availability via the DHS Program is unconfirmed.
- **Nigeria** — NFCMS 2021 remains the newest nutrition survey and its **microdata does not
  appear to be publicly obtainable**; the route is a formal request to IITA / FMoH / Intake.
  (An earlier version of this file said the microdata was catalogued on GHDx and downloadable
  from there — that was wrong, and is withdrawn.) More promising: **NLSS 2023** (NBS microdata
  catalog 168) is an LSMS-type survey whose food module captures 7-day *quantities* for ~99
  items, which would let the wealth-index approach in this notebook transfer to Nigeria —
  contingent on bouillon appearing in the item list, which is unconfirmed. A *voluntary*
  multiple-micronutrient bouillon standard was adopted Sept 2024, which complicates the current
  assumption of zero effective baseline coverage.
- **Ethiopia** — the salt + folic acid scenario is now an actual national programme rather than
  hypothetical. Two 2025 Tesfaye papers bear on the serum→RBC folate step. The FNS baseline
  final report still appears unpublished, but the BMJ Open 2023 protocol paper confirms the
  survey was fielded Jul 2021–Dec 2023 and is the same survey as the FNS baseline — so EPHI is
  the place to ask, and the data does exist.
