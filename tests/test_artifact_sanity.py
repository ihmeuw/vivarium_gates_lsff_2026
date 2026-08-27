"""Layer 5: compare two artifacts, before any simulation runs.

The cheapest place to catch a data problem is the artifact. A bad key here shows
up in the final results only after two microsimulations and an aggregation stage
have smeared it across thousands of numbers and mixed it with Monte Carlo noise.
Comparing artifacts localises the problem to a single key in seconds.

This layer was written after diffing a GBD-2023 artifact against the verified
GBD-2021 one, which surfaced things a pipeline run would have shown only as "the
DALYs moved":

  - ``risk_factor.hemoglobin.pregnant_proportion_below_70_gL`` went up 38x, to
    0.582 -- 58% of pregnant women in the worst stratum classed as severely
    anemic -- and ``hemoglobin_on_maternal_hemorrhage.paf`` 14.9x with it. (The
    hemoglobin SD is *not* the driver, though an earlier read of this said so: a
    ``--mean`` rebuild moves it only 1.18x. Comparing a ``--mean`` build against a
    non-``--mean`` one is what created that false lead.)
  - ``cause.maternal_disorders.ylds`` differing ~250x, which turned out not to be
    a GBD revision at all but a pre-existing draw-alignment bug on the ``--mean``
    path. Guarded separately by ``test_draw_alignment.py``.
  - That same key carries 8 ``inf`` values in *both* vintages, from dividing by a
    zero maternal-disorders incidence at ages 60+. ``.fillna(0)`` does not catch
    ``inf``. Harmless while the sim runs ages 10-54, but latent.
  - ``cause.maternal_disorders.incident_probability`` pinned at exactly 1.0 for
    60% of its non-zero rows, by a ``.clip(upper=1)`` that was inert under GBD
    2021. The ratio check is structurally blind to this -- a value clipped at 1.0
    cannot move far, so it registered only 1.63x -- which is why the saturation
    check below exists.

Of the 35 keys comparable between two ``--mean`` builds, the 30 not listed above
moved within 0.42x-1.94x, an ordinary GBD-revision range. That contrast is what
makes the ratio check useful: the outliers are not at the edge of a broad
distribution, they are far outside it.

Framing matters here. The degeneracy checks are written as *regressions against a
reference artifact* rather than against an allowlist of keys permitted to be zero,
because whether zero is correct is context-dependent -- Nigeria has no baseline
rice fortification programme (legitimately 0.0) but does have bouillon (~0.52).
"No key newly became all-zero" is both sharper and needs no maintenance.

The saturation check is the exception: it needs no reference, because a clip bound
is an absolute statement about the data rather than a comparison.

Usage::

    LSFF_ARTIFACT=/path/to/new.hdf \
    LSFF_REFERENCE_ARTIFACT=/path/to/known-good.hdf \
        pytest tests/test_artifact_sanity.py

With only LSFF_ARTIFACT set, the single-artifact checks still run and the
comparison checks skip.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ordinary GBD-revision movement between rounds was 0.42x-1.94x across the
# unflagged keys in the 2021-vs-2023 comparison. 3x is comfortably outside that, so
# an exceedance means "a human should look", not necessarily "this is wrong".
RATIO_THRESHOLD = 3.0

# Keys whose values are per-draw columns rather than a single 'value'; compared on
# the first numeric column, which is enough to detect degeneracy and scale shifts.
FIRST_NUMERIC_COLUMN = 0

# A key bounded in [0, 1] is a probability or proportion, and this is the bound a
# loader clips to. `load_pregnant_maternal_disorders_incidence_probability` ends
# with `.clip(upper=1)`.
PROBABILITY_BOUND = 1.0

# How much of a probability key may sit exactly at its bound before it reads as
# clipped rather than computed. Empirical basis: across three verified GBD-2021
# artifacts (rice/nigeria, rice/india, bouillon/nigeria), *no* probability-valued
# key had even a single value at exactly 1.0 -- floating-point arithmetic does not
# land on the bound by accident. So any exceedance is outside observed good
# behaviour. The allowance is not zero only to leave room for a key that is 1.0 by
# definition in a stratum or two (a full-coverage proportion, say); the defect this
# was written for sits at 60%, so the gap is wide.
SATURATION_FRACTION_THRESHOLD = 0.05


def _load_artifact(env_var: str):
    path = os.environ.get(env_var)
    if not path:
        pytest.skip(f"set {env_var}=/path/to/artifact.hdf")
    if not Path(path).exists():
        pytest.skip(f"{env_var} does not exist: {path}")
    artifact_module = pytest.importorskip(
        "vivarium.artifact", reason="needs an environment with the artifact library"
    )
    return artifact_module.Artifact(path)


@pytest.fixture(scope="module")
def artifact():
    return _load_artifact("LSFF_ARTIFACT")


@pytest.fixture(scope="module")
def reference_artifact():
    return _load_artifact("LSFF_REFERENCE_ARTIFACT")


def numeric_series(data) -> pd.Series | None:
    if not hasattr(data, "select_dtypes"):
        return None
    numeric = data.select_dtypes("number")
    if numeric.empty:
        return None
    return numeric.iloc[:, FIRST_NUMERIC_COLUMN]


def summarise(series: pd.Series) -> dict:
    finite = series[np.isfinite(series)]
    non_zero = finite[finite != 0]
    return {
        "rows": len(series),
        "non_finite": int((~np.isfinite(series)).sum()),
        "non_zero": int((finite != 0).sum()),
        "median_non_zero": float(non_zero.median()) if len(non_zero) else float("nan"),
    }


def artifact_keys(artifact) -> list[str]:
    return sorted(str(key) for key in artifact.keys)


def pytest_generate_tests(metafunc):
    """Parametrize over the keys of whichever artifact is under test.

    Done here rather than with a fixture so each key is its own test case and a
    failure names the key directly.
    """
    if "key" not in metafunc.fixturenames:
        return
    path = os.environ.get("LSFF_ARTIFACT")
    keys: list[str] = []
    if path and Path(path).exists():
        try:
            from vivarium.artifact import Artifact

            keys = artifact_keys(Artifact(path))
        except Exception:  # pragma: no cover - environment without the library
            keys = []
    metafunc.parametrize(
        "key", keys or [pytest.param("(no artifact)", marks=pytest.mark.skip)]
    )


def test_key_has_no_non_finite_values(artifact, reference_artifact, key: str) -> None:
    """No key may gain inf or NaN relative to the reference.

    `.fillna(0)` in the loaders catches NaN but not inf, so a division by a zero
    denominator survives into the artifact and then into a lookup table.
    """
    series = numeric_series(artifact.load(key))
    if series is None:
        pytest.skip(f"{key} has no numeric column")
    current = summarise(series)["non_finite"]
    if not current:
        return

    reference_keys = set(artifact_keys(reference_artifact))
    baseline = 0
    if key in reference_keys:
        reference_series = numeric_series(reference_artifact.load(key))
        if reference_series is not None:
            baseline = summarise(reference_series)["non_finite"]

    assert current <= baseline, (
        f"{key} has {current} non-finite value(s), up from {baseline} in the "
        f"reference. `.fillna(0)` does not catch inf, so a divide-by-zero upstream "
        f"reaches the artifact intact."
    )


def test_key_did_not_newly_become_all_zero(artifact, reference_artifact, key: str) -> None:
    """A key that used to carry values must not silently go flat.

    This is the fillna(0) failure mode: an index misalignment upstream becomes
    zeros with no error. Comparing against a reference avoids having to decide in
    the abstract whether zero is legitimate -- for some keys it is.
    """
    series = numeric_series(artifact.load(key))
    if series is None:
        pytest.skip(f"{key} has no numeric column")
    if summarise(series)["non_zero"]:
        return

    reference_keys = set(artifact_keys(reference_artifact))
    if key not in reference_keys:
        pytest.skip(f"{key} is not in the reference artifact")
    reference_series = numeric_series(reference_artifact.load(key))
    if reference_series is None:
        pytest.skip(f"{key} has no numeric column in the reference")

    assert not summarise(reference_series)["non_zero"], (
        f"{key} is entirely zero but carries values in the reference artifact. "
        "That is the signature of an upstream index misalignment converted to "
        "zeros by `.fillna(0)`."
    )


def test_probability_key_is_not_saturated_at_its_bound(artifact, key: str) -> None:
    """A probability must not sit pinned at 1.0 for much of its range.

    The loaders convert rates to probabilities and then `.clip(upper=1)`. While the
    underlying rate stays in range the clip does nothing; once it does not, the clip
    silently converts "this value is impossible" into "this value is certainty".
    Every woman in an affected stratum then deterministically gets the condition,
    and nothing about the artifact looks wrong.

    Deliberately needs no reference artifact. The other checks ask "did this move?",
    which cannot see this failure: a value clipped at 1.0 has nowhere to move to, so
    the key that motivated this test registered a mere 1.63x on the ratio check
    while over half its live rows were pinned at the bound.
    """
    series = numeric_series(artifact.load(key))
    if series is None:
        pytest.skip(f"{key} has no numeric column")

    finite = series[np.isfinite(series)]
    if finite.empty or finite.min() < 0.0 or finite.max() > PROBABILITY_BOUND:
        pytest.skip(f"{key} is not bounded in [0, 1], so it is not a probability")

    non_zero = finite[finite != 0]
    if non_zero.empty:
        pytest.skip(f"{key} is entirely zero")  # the all-zero check owns this case

    at_bound = int((non_zero == PROBABILITY_BOUND).sum())
    fraction = at_bound / len(non_zero)
    assert fraction <= SATURATION_FRACTION_THRESHOLD, (
        f"{key} is exactly {PROBABILITY_BOUND} for {at_bound} of {len(non_zero)} "
        f"non-zero values ({fraction:.0%}), over the "
        f"{SATURATION_FRACTION_THRESHOLD:.0%} allowance.\n"
        "  A computed probability does not land on its bound by accident: this is the "
        "signature of a `.clip(upper=1)` absorbing an out-of-range input. Every "
        "simulant in an affected stratum then gets the condition with certainty.\n"
        "  Fix the quantity being clipped rather than the clip. If the value really "
        "is 1.0 by definition here, record the key and say why."
    )


def test_key_magnitude_is_comparable_to_reference(
    artifact, reference_artifact, key: str
) -> None:
    """Flag keys whose scale moved far more than a GBD revision plausibly would.

    Not a correctness assertion -- a genuine revision can exceed the threshold, in
    which case widen it or record the key. It is a review trigger, and it is how
    the hemoglobin SD and maternal-disorders YLD problems were found.
    """
    if key not in set(artifact_keys(reference_artifact)):
        pytest.skip(f"{key} is not in the reference artifact")

    series = numeric_series(artifact.load(key))
    reference_series = numeric_series(reference_artifact.load(key))
    if series is None or reference_series is None:
        pytest.skip(f"{key} has no numeric column in both artifacts")

    current = summarise(series)["median_non_zero"]
    baseline = summarise(reference_series)["median_non_zero"]
    if not np.isfinite(current) or not np.isfinite(baseline) or baseline == 0:
        pytest.skip(f"{key} has no comparable non-zero median")

    ratio = current / baseline
    fold = max(ratio, 1 / ratio)
    assert fold <= RATIO_THRESHOLD, (
        f"{key} moved {ratio:.3g}x (median of non-zero values: {baseline:.6g} -> "
        f"{current:.6g}), beyond the {RATIO_THRESHOLD}x review threshold.\n"
        "  Ordinary GBD-round movement in this artifact was 0.42x-1.94x, so this is "
        "worth a look before it reaches a production run. If the revision is real, "
        "widen RATIO_THRESHOLD or record the key here."
    )


# --- PAF/RR internal consistency (V&V strategy check P5) -------------------------
#
# The stored hemoglobin-on-maternal-disorders PAF must equal the risk-deletion
# integral implied by the artifact's own hemoglobin distribution and RR:
#
#     weighted_burden = E[ RR ** (max(TMREL - hgb, 0) / RR_SCALAR) ]
#     PAF = (weighted_burden - 1) / weighted_burden
#
# with the exponent on the hemoglobin DEFICIT, because that is how the simulation
# applies the RR to individuals (Hemoglobin.adjust_maternal_disorder_probability
# exponentiates (tmrel - hemoglobin).clip(lower=0)). If the two disagree, risk
# deletion does not cancel the per-simulant RRs and every population
# maternal-disorders rate the sim produces is scaled by ~E[RR**deficit].
#
# This is the check that would have caught the inverted max(x - tmrel, 0) in
# _hemoglobin_paf, which produced stored PAFs of ~0.01 where ~0.3 is correct
# (found via LSFF_model0 V&V, 2026-08-26). A ratio or saturation check cannot see
# it: the wrong values are small, positive, and unsaturated.
#
# Constants mirror the maternal package (constants/data_values.py); they are
# duplicated here so the test does not need the simulation package importable.
PAF_TMREL_G_PER_L = 120.0
PAF_RR_SCALAR_G_PER_L_PER_G_PER_DL = 10.0
PAF_CONSISTENCY_ROW_CAP = 40


def test_hemoglobin_maternal_disorders_paf_consistent_with_rr(artifact) -> None:
    integrate = pytest.importorskip("scipy.integrate")
    hemoglobin_distribution = pytest.importorskip("lsff_utils.hemoglobin_distribution")

    keys = {
        "paf": "risk_factor.hemoglobin_on_maternal_disorder.paf",
        "mean": "risk_factor.hemoglobin.mean",
        "sd": "risk_factor.hemoglobin.standard_deviation",
        "rr": "risk_factor.hemoglobin_on_maternal_disorder.relative_risk",
    }
    missing = [key for key in keys.values() if key not in artifact.keys]
    if missing:
        pytest.skip(f"artifact lacks {missing}")

    def first_draw(key: str, name: str) -> pd.DataFrame:
        frame = artifact.load(key)
        draw_column = frame.filter(like="draw").columns[0]
        return frame[[draw_column]].rename(columns={draw_column: name}).reset_index()

    paf = first_draw(keys["paf"], "paf")
    mean = first_draw(keys["mean"], "mean")
    sd = first_draw(keys["sd"], "sd")
    # The RR is a biological constant carried at whatever GBD year it was pulled
    # for, which need not match the demography year on the other keys; the PAF
    # generator drops the RR's year levels before its lookup, and so does this.
    rr = first_draw(keys["rr"], "rr").drop(
        columns=["year_start", "year_end"], errors="ignore"
    )

    merged = paf.merge(mean, on=[c for c in paf.columns if c in mean.columns and c != "paf"])
    merged = merged.merge(sd, on=[c for c in merged.columns if c in sd.columns and c not in ("paf", "mean")])
    merged = merged.merge(rr, on=[c for c in merged.columns if c in rr.columns and c not in ("paf", "mean", "sd")])
    merged = merged[merged["mean"] > 0]
    # The generator computes the PAF for the window the simulation enrolls
    # (_among_wra: ages 10-55) and stores 0.0 elsewhere. The floor was 15 until
    # 2026-08-27, which left 10-14 with RR applied but nothing deleted -- the
    # residual 10_to_14 spike in maternal V&V. Artifacts built before the
    # widening fail here on their zero-valued 10-14 rows, correctly: rebuild them.
    merged = merged[
        (merged["age_start"] >= 10) & (merged["age_end"] <= 55)
    ]
    if merged.empty:
        pytest.skip("no rows with a positive hemoglobin mean to check")

    # Deterministic thinning: enough rows to cover ages and quintiles without
    # paying for an integral per demographic cell.
    step = max(1, len(merged) // PAF_CONSISTENCY_ROW_CAP)
    rows = merged.iloc[::step]

    def expected_paf(mean: float, sd: float, rr: float) -> float:
        pdf = hemoglobin_distribution.hemoglobin_pdf_from_mean_sd(mean, sd)
        with np.errstate(under="ignore"):
            weighted_burden = integrate.quad(
                lambda x: pdf(x)
                * rr
                ** (
                    max(PAF_TMREL_G_PER_L - x, 0)
                    / PAF_RR_SCALAR_G_PER_L_PER_G_PER_DL
                ),
                0,
                hemoglobin_distribution.XMAX,
                epsabs=0.0001,
            )[0]
        return (weighted_burden - 1) / weighted_burden

    expected = rows.apply(lambda r: expected_paf(r["mean"], r["sd"], r["rr"]), axis=1)
    # Loose on purpose: distribution and integration wiggle is percent-level, the
    # defect this exists for is thirty-fold.
    mismatched = ~np.isclose(rows["paf"], expected, atol=0.02, rtol=0.10)
    detail = rows.assign(expected=expected)[mismatched][
        [c for c in rows.columns if c not in ("mean", "sd", "rr")] + ["expected"]
    ]
    assert not mismatched.any(), (
        f"stored PAF disagrees with the deficit-direction RR integral for "
        f"{int(mismatched.sum())} of {len(rows)} sampled rows. If the stored values are "
        f"~0.01 and the expected ~0.3, the artifact was built with the inverted "
        f"max(x - tmrel, 0) exponent in loader._hemoglobin_paf and every "
        f"maternal-disorders rate downstream is inflated by ~E[RR**deficit].\n"
        f"{detail.head(10).to_string(index=False)}"
    )


# --- LBWSG interpolator/RR internal consistency ----------------------------------
#
# The stored relative-risk interpolator is a kx=1/ky=1 spline whose grid contains
# every category midpoint, so an aligned build reproduces log(stored RR) exactly at
# each category's own (gestational age, birth weight) midpoint. The defect this
# guards: loader.load_lbwsg_interpolated_rr feeds scipy griddata positionally, and
# the midpoint Series (categories-dict order) and log-RR rows (lexicographic order)
# used to disagree on ordering -- pairing each category's midpoint with a different
# category's RR. That scrambles the whole RR surface (mean ~2.9x, max ~66x at its
# own knots) while leaving every marginal-distribution check green, because the
# same set of RR values is present -- just at the wrong coordinates. Only an
# evaluate-at-the-knots check can see it.
LBWSG_KEYS = {
    "rr": "risk_factor.low_birth_weight_and_short_gestation.relative_risk",
    "interp": "risk_factor.low_birth_weight_and_short_gestation.relative_risk_interpolator",
    "categories": "risk_factor.low_birth_weight_and_short_gestation.categories",
}
# Aligned knots are exact to float precision; the scramble produces mean ~1.0 in
# log space. Anything in between means a new construction bug worth a human look.
LBWSG_KNOT_TOLERANCE_LOG_SPACE = 0.05


def test_lbwsg_interpolator_matches_relative_risk_at_category_midpoints(artifact) -> None:
    import pickle
    import re

    missing = [key for key in LBWSG_KEYS.values() if key not in artifact.keys]
    if missing:
        pytest.skip(f"artifact lacks {missing}")

    categories = artifact.load(LBWSG_KEYS["categories"])
    rr = artifact.load(LBWSG_KEYS["rr"]).reset_index()
    interp = artifact.load(LBWSG_KEYS["interp"]).reset_index()

    draw_column = [c for c in rr.columns if c.startswith("draw")][0]

    def midpoints(description: str):
        intervals = re.findall(r"\[([\d.]+), ([\d.]+)\)", description)
        if len(intervals) != 2:
            return None
        (ga_lo, ga_hi), (bw_lo, bw_hi) = intervals
        return (
            (float(ga_lo) + float(ga_hi)) / 2,
            (float(bw_lo) + float(bw_hi)) / 2,
        )

    checked, failures = 0, []
    for _, interp_row in interp.iterrows():
        spline = pickle.loads(bytes.fromhex(interp_row[draw_column]))
        stratum = rr[
            (rr.sex == interp_row.sex) & (rr.age_start == interp_row.age_start)
        ]
        for _, rr_row in stratum.iterrows():
            point = midpoints(categories.get(rr_row.parameter, ""))
            if point is None or rr_row[draw_column] <= 0:
                continue
            gestational_age, birth_weight = point
            error = abs(
                float(spline(gestational_age, birth_weight, grid=False))
                - np.log(rr_row[draw_column])
            )
            checked += 1
            if error > LBWSG_KNOT_TOLERANCE_LOG_SPACE:
                failures.append(
                    (interp_row.sex, interp_row.age_start, rr_row.parameter, round(error, 3))
                )
    assert checked > 0, "no evaluable (interpolator, RR, category) triples found"
    assert not failures, (
        f"the stored LBWSG RR interpolator disagrees with the stored RR at "
        f"{len(failures)} of {checked} category midpoints (|log error| > "
        f"{LBWSG_KNOT_TOLERANCE_LOG_SPACE}). If mean errors are ~1 in log space, the "
        f"artifact was built with the pre-fix positional midpoint/RR pairing in "
        f"load_lbwsg_interpolated_rr and must be rebuilt (and the LBWSG PAF "
        f"simulation rerun).\nWorst: {sorted(failures, key=lambda f: -f[3])[:8]}"
    )
