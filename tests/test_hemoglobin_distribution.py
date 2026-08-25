"""Unit tests for the hemoglobin ensemble distribution.

Why this file exists
--------------------
``lsff_utils.hemoglobin_distribution`` is the highest-risk module in the repo and
until now had no test at all. It is shared by both ``0400`` notebooks *and* by
``0200``'s ``loader.get_hemoglobin_below_70``, and it is where the retracted
severe-anemia finding came from: a ``1 - cdf`` workaround for
https://github.com/ihmeuw/risk_distributions/issues/62 stayed in place after the
upstream bug was fixed, so it re-inverted an already-correct CDF. Because the
mirrored-Gumbel component carries 60% of the ensemble weight, the "CDF" was wrong
by up to 0.6 and *decreased* with x. ``pregnant_proportion_below_70_gL`` came out
at 0.582 and was written up as a GBD-2023 data effect before anyone noticed it was
ours.

None of the five regression layers could have caught that. What did catch it was
``test_pdfs_cdfs_consistency`` inside ``0400/non_pregnant_anemia.ipynb`` -- an
assertion that only runs during a papermill execution needing GBD access, even
though the quantity it checks is a pure function of a mean and a standard
deviation. These tests bring that check into the suite, where it costs
milliseconds and needs no cluster, no GBD and no artifact.

Ground truth throughout is the **numerically integrated PDF**. That is what
settled the question originally (mean absolute error 0.4815 with the inversion,
0.0000 without), and it is the only reference here that cannot itself be wrong in
the same direction as the code under test.

Calling convention
------------------
The module requires ``len(parameters) == len(x)``: each row of (mean, sd) is
evaluated at the corresponding element of ``x``, rather than every mean being
evaluated at every x. To evaluate one distribution over a grid you therefore tile
the parameters to the grid's length, which is what ``cdf_at``/``pdf_at`` below do.
See ``test_mismatched_parameter_and_x_lengths_are_loud`` for why that matters.
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.integrate

# The module imports ``vivarium.risk_distributions``, which exists only in the
# modern suite: .venv has the old standalone ``risk_distributions`` and .test_venv
# has neither. Skipping rather than erroring keeps the harness's "runs in every
# environment, skipping what it cannot do" property. Run this file in .venv_modern.
_distribution = pytest.importorskip(
    "lsff_utils.hemoglobin_distribution",
    reason="needs vivarium.risk_distributions (present only in .venv_modern)",
)

GAMMA_DISTRIBUTION_WEIGHT = _distribution.GAMMA_DISTRIBUTION_WEIGHT
MIRROR_GUMBEL_DISTRIBUTION_WEIGHT = _distribution.MIRROR_GUMBEL_DISTRIBUTION_WEIGHT
XMAX = _distribution.XMAX
hemoglobin_cdf_from_mean_sd = _distribution.hemoglobin_cdf_from_mean_sd
hemoglobin_pdf_from_mean_sd = _distribution.hemoglobin_pdf_from_mean_sd
hemoglobin_sampler_from_mean_sd = _distribution.hemoglobin_sampler_from_mean_sd

# Mean/sd pairs spanning the hemoglobin range the study actually models, from
# severely anemic populations up to non-anemic adult males. The top of the range
# loses ~0.3% of its mass off the XMAX=220 truncation, which is why the moment
# tolerances below are relative rather than exact.
DISTRIBUTIONS = [(90.0, 10.0), (110.0, 15.0), (130.0, 20.0), (150.0, 25.0)]

# Hemoglobin values to evaluate at. 70 and 120 are real anemia thresholds (severe,
# and the non-pregnant adult female cutoff), so they are the points where a wrong
# CDF does the most damage.
TEST_POINTS = np.array([50.0, 70.0, 90.0, 110.0, 120.0, 130.0, 150.0, 170.0])

# Integration grid for the ground-truth PDF. 22001 points over [0, 220] puts the
# trapezoid error at 3e-6..1.5e-4 across DISTRIBUTIONS (measured), comfortably
# below CONSISTENCY_TOLERANCE.
GRID = np.linspace(0.0, float(XMAX), 22001)

# Generous next to the measured 1.5e-4 worst case, and still ~500x smaller than
# the 0.4815 error the inverted CDF produced. A tolerance that only just passes
# would be a tolerance that gets loosened the next time something drifts.
CONSISTENCY_TOLERANCE = 1e-3


# numpy renamed trapz -> trapezoid in 2.0. This module has to run under both:
# .venv_modern is on numpy 1.26.4, and the pinned pipeline env may move.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz

# Importing ``vivarium.testing_utils`` sets ``numpy.seterr(all="raise")``, so the
# far tail of these densities -- where ``exp`` legitimately underflows to zero,
# measured as low as 2.8e-22 -- raises FloatingPointError inside the test process
# but not in the notebooks. Underflow to zero is the correct answer for a density
# 10 standard deviations out, so it is suppressed here rather than avoided by
# shrinking the integration range. ``0400/non_pregnant_anemia.ipynb`` wraps its own
# consistency check the same way. Only ``under`` is suppressed: overflow, div-zero
# and invalid still raise, because none of those has a benign reading here.
_IGNORE_UNDERFLOW = np.errstate(under="ignore")


def cdf_at(mean: float, sd: float, x) -> np.ndarray:
    """The analytic ensemble CDF of one distribution, evaluated at every x."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    with _IGNORE_UNDERFLOW:
        cdf = hemoglobin_cdf_from_mean_sd(np.full(x.size, mean), np.full(x.size, sd))
        return np.asarray(cdf(x), dtype=float).ravel()


def pdf_at(mean: float, sd: float, x) -> np.ndarray:
    """The analytic ensemble PDF of one distribution, evaluated at every x."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    with _IGNORE_UNDERFLOW:
        pdf = hemoglobin_pdf_from_mean_sd(np.full(x.size, mean), np.full(x.size, sd))
        return np.asarray(pdf(x), dtype=float).ravel()


def sample(mean: float, sd: float, distribution_propensity, propensity) -> np.ndarray:
    with _IGNORE_UNDERFLOW:
        sampler = hemoglobin_sampler_from_mean_sd(
            np.full(distribution_propensity.size, mean),
            np.full(distribution_propensity.size, sd),
        )
        return np.asarray(sampler(distribution_propensity, propensity), dtype=float)


def integrated_pdf(mean: float, sd: float) -> np.ndarray:
    """Cumulative trapezoid integral of the PDF over GRID -- the ground truth."""
    density = pdf_at(mean, sd, GRID)
    increments = (density[1:] + density[:-1]) / 2 * np.diff(GRID)
    return np.concatenate([[0.0], np.cumsum(increments)])


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_cdf_matches_numerically_integrated_pdf(mean: float, sd: float) -> None:
    """The check that would have caught the inverted MirroredGumbel CDF.

    A PDF and a CDF derived from the same parameters are two routes to the same
    quantity, so disagreement between them localises the fault to one of the two
    without needing any external reference.
    """
    analytic = cdf_at(mean, sd, TEST_POINTS)
    numeric = np.interp(TEST_POINTS, GRID, integrated_pdf(mean, sd))
    error = np.abs(analytic - numeric)

    worst = int(np.argmax(error))
    assert error.max() < CONSISTENCY_TOLERANCE, (
        f"mean={mean} sd={sd}: analytic CDF disagrees with the integrated PDF by "
        f"{error.max():.4f} at hemoglobin={TEST_POINTS[worst]:.0f} "
        f"(analytic={analytic[worst]:.4f}, integrated={numeric[worst]:.4f}).\n"
        "  Suspect the ensemble weights or a component's CDF. If the discrepancy is\n"
        f"  close to {MIRROR_GUMBEL_DISTRIBUTION_WEIGHT} or "
        f"{GAMMA_DISTRIBUTION_WEIGHT}, a component is INVERTED rather than\n"
        "  mis-parameterised -- an error pinned at a component's mixture weight is the\n"
        "  signature of a `1 - cdf` applied to an already-correct CDF. That is exactly\n"
        "  the risk_distributions#62 workaround that produced the retracted 0.582\n"
        "  severe-anemia finding; see the comment in hemoglobin_cdf_from_mean_sd."
    )


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_cdf_is_not_inverted(mean: float, sd: float) -> None:
    """A named regression for risk_distributions#62, stated as direction.

    The consistency test above subsumes this numerically, but this one fails with
    a message that says *inverted* rather than *inconsistent*, and it holds even
    if the PDF is ever broken in the same direction as the CDF.

    Concretely: as shipped with the stale workaround, ``cdf(70)`` for mean 110 /
    sd 15 returned 0.5896 -- i.e. 59% of that population classed as severely
    anemic -- against a true 0.0114.
    """
    values = cdf_at(mean, sd, TEST_POINTS)

    assert np.all(np.diff(values) >= 0), (
        f"mean={mean} sd={sd}: CDF is not non-decreasing across "
        f"{TEST_POINTS.tolist()}: {np.round(values, 4).tolist()}.\n"
        "  A CDF that decreases with x has a reversed component. Do not reinstate the\n"
        "  `1 - cdf` workaround against the modern vivarium.risk_distributions -- it is\n"
        "  needed only for the OLD library (<= 2.0.16, in .venv)."
    )
    # Far below the mean, the cumulative probability must be small. Under the
    # inversion this lands near the 0.6 mirrored-Gumbel weight instead.
    below = float(cdf_at(mean, sd, [mean - 2.5 * sd])[0])
    assert below < 0.1, (
        f"mean={mean} sd={sd}: CDF at 2.5 standard deviations below the mean is "
        f"{below:.4f}, which is far too much mass in the left tail. Under the "
        f"reversed-CDF bug this sits near {MIRROR_GUMBEL_DISTRIBUTION_WEIGHT}."
    )


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_cdf_is_a_probability_over_the_whole_support(mean: float, sd: float) -> None:
    """Bounded in [0, 1], monotone on a fine grid, and spanning ~0 to ~1."""
    values = cdf_at(mean, sd, GRID)

    assert np.isfinite(values).all(), f"mean={mean} sd={sd}: CDF has non-finite values"
    assert values.min() >= 0.0 and values.max() <= 1.0, (
        f"mean={mean} sd={sd}: CDF escapes [0, 1] "
        f"(min={values.min():.6f}, max={values.max():.6f})"
    )
    # -1e-12 rather than 0 because floating-point summation of the two weighted
    # components can jitter in the last bit; a real reversal is O(0.1), not O(1e-16).
    assert np.all(
        np.diff(values) >= -1e-12
    ), f"mean={mean} sd={sd}: CDF decreases somewhere on [0, {XMAX}]"
    assert values[0] < 1e-3, f"mean={mean} sd={sd}: CDF(0)={values[0]:.6f}, expected ~0"
    assert values[-1] > 0.99, (
        f"mean={mean} sd={sd}: CDF({XMAX})={values[-1]:.6f}, expected ~1. Mass is "
        f"escaping past the XMAX={XMAX} truncation."
    )


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_pdf_is_a_density(mean: float, sd: float) -> None:
    """Non-negative everywhere, and integrating to 1 over the support."""
    density = pdf_at(mean, sd, GRID)

    assert np.isfinite(density).all(), f"mean={mean} sd={sd}: PDF has non-finite values"
    assert (
        density.min() >= 0.0
    ), f"mean={mean} sd={sd}: PDF goes negative (min={density.min():.3e})"
    total = float(integrated_pdf(mean, sd)[-1])
    assert total == pytest.approx(1.0, abs=0.01), (
        f"mean={mean} sd={sd}: PDF integrates to {total:.6f} over [0, {XMAX}], not 1. "
        "Either the ensemble weights no longer sum to 1 or the truncation is losing mass."
    )


def test_ensemble_weights_sum_to_one() -> None:
    """Stated separately because it is the cheapest possible explanation for a
    failure in either of the two tests above."""
    assert GAMMA_DISTRIBUTION_WEIGHT + MIRROR_GUMBEL_DISTRIBUTION_WEIGHT == pytest.approx(1.0)


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_distribution_recovers_the_requested_mean_and_sd(mean: float, sd: float) -> None:
    """Both components are parameterised to the requested moments, so the mixture
    carries them too. A mis-parameterisation that happened to stay monotone and
    normalised would still show up here.

    Tolerances are relative and loose because the XMAX truncation genuinely costs
    the widest distribution ~0.3% of its mass, pulling its numerical mean down.
    """
    density = pdf_at(mean, sd, GRID)
    first = float(_trapezoid(GRID * density, GRID))
    second = float(_trapezoid(GRID**2 * density, GRID))
    numerical_sd = float(np.sqrt(second - first**2))

    assert first == pytest.approx(
        mean, rel=0.01
    ), f"requested mean {mean}, numerically integrated mean {first:.4f}"
    assert numerical_sd == pytest.approx(
        sd, rel=0.05
    ), f"requested sd {sd}, numerically integrated sd {numerical_sd:.4f}"


def test_pdf_accepts_a_python_float() -> None:
    """Pins the ``np.atleast_1d`` coercion in ``hemoglobin_pdf_from_mean_sd``.

    ``scipy.integrate.quad`` calls its integrand with a Python float, which has no
    ``.copy()``, and ``risk_distributions`` also rejects 0-d arrays. Without the
    coercion a cold pregnancy-artifact build dies with
    ``AttributeError: 'float' object has no attribute 'copy'`` at loader.py:678 --
    which is why that artifact had never been buildable from scratch.
    """
    with _IGNORE_UNDERFLOW:
        pdf = hemoglobin_pdf_from_mean_sd(110.0, 15.0)
        value = np.asarray(pdf(70.0), dtype=float).ravel()
    assert (
        value.size == 1 and np.isfinite(value[0]) and value[0] > 0.0
    ), f"pdf(70.0) on a Python float returned {value!r}"


def test_pdf_integrates_to_one_through_scipy_quad() -> None:
    """The real ``quad`` call path, end to end.

    Exercises the scalar-float integrand *and* normalisation together, which is how
    ``loader.py`` actually consumes this module.
    """
    with _IGNORE_UNDERFLOW:
        pdf = hemoglobin_pdf_from_mean_sd(110.0, 15.0)
        total, _ = scipy.integrate.quad(pdf, 0, XMAX)
    assert total == pytest.approx(
        1.0, abs=0.01
    ), f"scipy.integrate.quad over the PDF gives {total:.6f}, not 1"


@pytest.mark.parametrize("mean,sd", DISTRIBUTIONS)
def test_sampler_agrees_with_the_cdf(mean: float, sd: float) -> None:
    """Third route to the same distribution: sample, then read the CDF back.

    Checked away from the median on purpose. The reversed-CDF bug is very nearly
    symmetric *at* the median, so a median-only check would have passed straight
    through it; at p=0.1 the inverted CDF returns ~0.58 instead of 0.1.
    """
    count = 20_000
    generator = np.random.default_rng(20260805)
    samples = sample(mean, sd, generator.uniform(size=count), generator.uniform(size=count))

    assert np.isfinite(
        samples
    ).all(), f"mean={mean} sd={sd}: sampler produced non-finite draws"
    assert samples.min() > 0.0, (
        f"mean={mean} sd={sd}: sampler produced a non-positive hemoglobin value "
        f"(min={samples.min():.2f})"
    )

    probabilities = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
    quantiles = np.quantile(samples, probabilities)
    recovered = cdf_at(mean, sd, quantiles)
    # 0.02 absolute is ~5x the Monte Carlo standard error of a quantile at
    # n=20,000, so this is about the sampler and the CDF disagreeing, not noise.
    assert np.allclose(recovered, probabilities, atol=0.02), (
        f"mean={mean} sd={sd}: CDF evaluated at the sampler's own empirical "
        f"quantiles returns {np.round(recovered, 4).tolist()} where it should return "
        f"{probabilities.tolist()}. The sampler and the CDF disagree, so one of the "
        "two components is parameterised or inverted differently between them."
    )


def test_sampler_routes_propensities_to_the_two_components() -> None:
    """``distribution_propensity`` below the gamma weight must select the gamma
    part and above it the mirrored-Gumbel part. If the branch ever inverts, the
    ensemble silently becomes 60/40 instead of 40/60 -- which no aggregate moment
    check would notice, because both components share the same mean and sd.
    """
    count = 20_000
    generator = np.random.default_rng(20260805)
    propensity = generator.uniform(size=count)

    gamma = sample(110.0, 15.0, np.zeros(count), propensity)
    mirrored = sample(
        110.0, 15.0, np.full(count, GAMMA_DISTRIBUTION_WEIGHT + 0.1), propensity
    )

    assert np.isfinite(gamma).all() and np.isfinite(mirrored).all()
    # The two components are deliberately different shapes at the same moments:
    # gamma is right-skewed, the mirrored Gumbel left-skewed. So their medians must
    # straddle the common mean in opposite directions.
    assert np.median(gamma) < 110.0 < np.median(mirrored), (
        f"gamma median {np.median(gamma):.2f} and mirrored-Gumbel median "
        f"{np.median(mirrored):.2f} do not straddle the common mean of 110 in the "
        "expected directions (gamma right-skewed so median below the mean, mirrored "
        "Gumbel left-skewed so median above). The propensity branch in "
        "hemoglobin_sampler_from_mean_sd may be routing to the wrong component."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Records a real asymmetry rather than asserting a verdict: the mirrored-Gumbel "
        "component cannot exceed its mirror point of XMAX, but the gamma component is "
        "not bounded by it, so the ensemble's upper support is XMAX for 60% of the "
        "weight and unbounded for the other 40%. Measured at mean 150 / sd 25 the "
        "sampler reaches 239 g/L. Whether that matters is the anemia model owner's "
        "call -- the sim's own hemoglobin means sit near 100-130, where it does not "
        "arise. xfail(strict) so a deliberate fix fails loudly and prompts removing "
        "this marker."
    ),
)
def test_sampler_stays_within_the_ensemble_truncation() -> None:
    """The sampler and the density disagree about where the support ends.

    ``cdf(XMAX)`` is 0.9976 at mean 150 / sd 25, i.e. the density itself puts 0.24%
    of its mass above the truncation, and the sampler duly emits it. Recorded here
    so the next person to find a 239 g/L hemoglobin value finds this instead of
    re-deriving it.
    """
    count = 20_000
    generator = np.random.default_rng(20260805)

    samples = sample(
        150.0, 25.0, generator.uniform(size=count), generator.uniform(size=count)
    )

    above = samples[samples > XMAX]
    assert above.size == 0, (
        f"{above.size} of {count} samples exceed XMAX={XMAX} "
        f"(max {samples.max():.1f} g/L). The gamma part's ppf is not clipped to the "
        "computability bounds set in _hemoglobin_distribution_parts_from_mean_sd."
    )


@pytest.mark.parametrize("evaluate", [cdf_at, pdf_at])
def test_mismatched_parameter_and_x_lengths_are_loud(evaluate) -> None:
    """Documents and pins the module's calling convention.

    Every parameter/x length mismatch must raise. This is the safe half of the
    broadcasting behaviour; the unsafe half is the next test.
    """
    with pytest.raises(ValueError):
        parameters = np.full(9, 110.0)
        function = (
            hemoglobin_cdf_from_mean_sd if evaluate is cdf_at else hemoglobin_pdf_from_mean_sd
        )(parameters, np.full(9, 15.0))
        function(np.linspace(60.0, 180.0, 3))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Open upstream bug: MirroredGumbel in vivarium.risk_distributions 3.1.8 no "
        "longer broadcasts a length-1 parameter row over an N-element x, and returns "
        "NaN for every element but the first instead of raising. xfail(strict) rather "
        "than a hard failure so the suite stays green while it is tracked -- it will "
        "fail loudly once the library is fixed or a guard is added to the module, "
        "prompting removal of this marker."
    ),
)
def test_single_parameter_row_does_not_silently_broadcast_to_nan() -> None:
    """The one length mismatch that is *silent* rather than loud.

    Measured: ``hemoglobin_cdf_from_mean_sd(110.0, 15.0)`` evaluated at nine
    hemoglobin points returns one real number and eight NaNs. Every other mismatch
    raises ValueError (see the previous test), so this is the single hole.

    No current call site triggers it -- ``loader.py:888`` passes matched-length
    ``.values`` arrays and is backed by ``assert result[draw].notnull().all()`` --
    but that is a property of today's call sites, not of the module. A caller
    holding one stratum's mean and sd and wanting the CDF at several anemia
    thresholds is the natural way to hit it, and it fails quietly.
    """
    points = np.linspace(50.0, 200.0, 9)
    cdf = hemoglobin_cdf_from_mean_sd(110.0, 15.0)

    values = np.asarray(cdf(points), dtype=float).ravel()
    missing = int(np.isnan(values).sum())
    assert missing == 0, (
        f"{missing} of {points.size} CDF values are NaN when a single (mean, sd) row "
        "is evaluated over multiple hemoglobin values. Either the library broadcasts "
        "again, or hemoglobin_distribution should tile the parameters itself, or it "
        "should raise like every other length mismatch does."
    )
