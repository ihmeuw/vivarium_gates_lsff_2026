# Issue B (rewritten) — pre-existing bug, not a migration regression

**Title:** `maternal_disorders.ylds divided by the draw count (250x) whenever artifacts are built with --mean`

**Labels:** `bug`, `data`, `affects-published-results`

---

## Summary

`cause.maternal_disorders.ylds` is written into the artifact **250x smaller than it should be**, because its loader mixes two draw conventions and a `.fillna(0)` absorbs the resulting mismatch instead of letting it raise.

This is **not** caused by GBD 2023 and **not** introduced by #3. The pre-migration loader has an identical structure, so every artifact ever built with `--mean` is affected — including the one behind the April-2025 published results. The Snakefile always passes `--mean`.

Impact is real but bounded: **under 0.2% of total DALYs.** Details below.

## Mechanism

`loader.get_data` collapses 250 draw columns to a single mean when `mean_draw=True`:

```python
data["mean_draw"] = data.filter(like="draw_").mean(axis=1)
data = data.drop(columns=data.filter(like="draw_").columns)
data = data.rename(columns={"mean_draw": "draw_0"})
```

So anything fetched through `get_data` comes back with **one** draw column, while `extra_gbd.*` and `load_raw_incidence_data` return **250**. `load_maternal_disorders_ylds` combines both:

```python
csmr      = get_data(data_keys.MATERNAL_DISORDERS.CSMR, location, mean_draw)  # 1 column
incidence = load_raw_incidence_data(...)                                      # 250 columns
ylds = (all_md_ylds - anemia_ylds) / (incidence - csmr)
return ylds.fillna(0)
```

1. `incidence - csmr` aligns on column *names*. Only `draw_0` matches; the other 249 become NaN.
2. `.fillna(0)` converts those 249 NaN into **zeros** rather than letting the mismatch surface.
3. Back in `get_data`, `mean(axis=1)` averages one real value against 249 zeros — dividing by exactly 250.

## Evidence

- The loader returns 250 draw columns with **exactly one non-zero draw per row** (18 of 50 rows; the rest are legitimately all-zero, being outside childbearing ages).
- Direct loader call: median non-zero `0.0130539`. Stored in the artifact: `5.22154e-05`. Ratio **250.0** to five significant figures, against exactly 250 draws.
- Independent cross-check: computing `(md_ylds - anemia_ylds) / (incidence - csmr)` from raw GBD gives ~0.0123 for release 9 and ~0.0075 for release 16 — both consistent with the *un-divided* value, not the stored one.
- Building the artifact twice reproduces `5.22e-05` exactly, so this is deterministic rather than a cache artifact.

**Scope is exactly one loader.** A source scan of every consumer of the module-local `get_data()` shows all the others fetch every term through it, so their draws stay consistent. Only `load_maternal_disorders_ylds` mixes.

**Why an existing GBD-2023 artifact appears unaffected:** the copy at `/mnt/team/.../artifacts/legacy/maternal/nigeria.hdf` holds `0.01306`, the correct value, because it was built **without** `--mean` — so it stores `draw_0` and never hits the collapse. That also explains the milder differences in other keys between it and a `--mean` build (e.g. `hemoglobin.standard_deviation` 23.7 vs 18.0): single draw versus mean of draws.

## Impact: measured

`maternal_disorders` is 2.32% of published baseline DALYs for india/rice, but that stream is almost entirely **deaths**:

| loc/vehicle | YLD | YLL | DALYs | YLD share |
|---|---|---|---|---|
| india/rice | 558 | 2,213,530 | 2,214,088 | **0.03%** |
| nigeria/rice | 252 | 1,986,612 | 1,986,864 | **0.01%** |
| nigeria/bouillon | 252 | 1,986,612 | 1,986,864 | **0.01%** |

Multiplying the YLDs by 250 moves published totals by:

| loc/vehicle | total DALYs | added | % of total |
|---|---|---|---|
| india/rice | 93,304,110 | 138,860 | **0.149%** |
| nigeria/rice | 82,597,894 | 62,805 | **0.076%** |
| nigeria/bouillon | 82,597,894 | 62,805 | **0.076%** |

And on DALYs averted, which is what the study reports: **0.000%** (india/rice — that comparison is folate-driven, so the contribution is identical in both arms and cancels), **0.107%** (nigeria/rice), **0.124%** (nigeria/bouillon).

So **no published conclusion is affected.** Worth fixing for correctness, and worth fixing because the same construct could bite a key where the share is not 0.03%.

## Suggested fix

Either is a small change:

1. **Fetch every term through the same convention.** Pass the draws uncollapsed and let `get_data` do the single collapse at the end — i.e. use the raw-draw path for `csmr` too.
2. **Drop the `.fillna(0)`** so the mismatch raises instead of being silently absorbed. This is the safer default: the zero-filling is what converted a loud alignment error into a quiet 250x scaling error.

Option 2 also removes one of the six `.fillna(0)` sites flagged in the companion test.

## Regression tests

On `abie/reproduce-and-regression-harness`, `tests/test_draw_alignment.py`:

- `test_mixing_loaders_are_accounted_for` — reads the loader source, needs no dependencies, runs anywhere. Records the one known offender so a *new* mixing loader fails immediately. Verified to fire.
- `test_draws_are_consistently_collapsed` — calls the loader against real GBD and looks for the one-non-zero-draw signature. Currently `xfail(strict=True)`, so it stays out of the way while this is open and **fails loudly once fixed**, prompting removal from `KNOWN_MIXING_LOADERS`.
