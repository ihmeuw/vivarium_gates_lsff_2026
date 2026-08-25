"""Layer 2: microsimulation outputs must stay statistically consistent.

Simulation output cannot be compared exactly -- it varies with the random seed --
so an exact check would either fail constantly or need an arbitrary tolerance.
Instead we use ``FuzzyChecker`` from ``vivarium-testing-utils``, which runs a
Bayesian hypothesis test between a "no bug" and a "bug" beta-binomial
distribution and only fails when the evidence for a bug is decisive.

The target for each group is the 95% Jeffreys credible interval implied by the
*reference* counts. So the question each test asks is: "given how much data the
reference run had, is this new observation plausibly the same proportion?" That
is scale-free with respect to seed count, which matters because the reference was
taken at 10 seeds and a production run uses 200.

FuzzyChecker also warns when a test could never be conclusive at the current
sample size. Those warnings are useful output, not noise -- they tell you where
you need more seeds to detect a regression at all.

Marked ``slow`` because it needs simulation output on disk. Run with:

    pytest tests/test_stochastic_results.py --runslow
"""

from __future__ import annotations

import pandas as pd
import pytest
import scipy.stats

from tests.reference_proportions import (
    GROUP_BY,
    compute_proportions,
    load_reference,
)

CREDIBLE_MASS = 0.95
IDENTITY = ["location", "vehicle", "measure", *GROUP_BY, "sub_entity"]

_reference = load_reference()
_CASES: list[tuple] = (
    [] if _reference is None else [tuple(row) for row in _reference[IDENTITY].itertuples(index=False)]
)


def jeffreys_interval(numerator: int, denominator: int) -> tuple[float, float]:
    """95% credible interval for a proportion under a Jeffreys prior.

    Beta(k + 1/2, n - k + 1/2) is the posterior for a binomial proportion under
    the non-informative Jeffreys prior, and stays well behaved when k is 0 or n.
    """
    tail = (1 - CREDIBLE_MASS) / 2
    posterior = scipy.stats.beta(numerator + 0.5, denominator - numerator + 0.5)
    return float(posterior.ppf(tail)), float(posterior.ppf(1 - tail))


@pytest.fixture(scope="module")
def current_proportions() -> pd.DataFrame | None:
    """Proportions recomputed from whatever simulation output is on disk now."""
    if _reference is None:
        return None
    frames = [
        frame
        for location, vehicle, measure in (
            _reference[["location", "vehicle", "measure"]].drop_duplicates().itertuples(index=False)
        )
        if (frame := compute_proportions(location, vehicle, measure)) is not None
    ]
    return pd.concat(frames, ignore_index=True) if frames else None


def test_reference_exists() -> None:
    assert _reference is not None, (
        "tests/reference/sim_proportions.csv is missing. Generate it from a trusted "
        "run with `python -m tests.reference_proportions`."
    )


@pytest.mark.slow
@pytest.mark.parametrize("case", _CASES, ids=lambda c: "/".join(str(part) for part in c))
def test_simulated_proportion_consistent_with_reference(
    case: tuple, current_proportions: pd.DataFrame | None, fuzzy_checker
) -> None:
    if current_proportions is None:
        pytest.skip("no simulation output on disk -- run the 0200 simulations first")

    selector = dict(zip(IDENTITY, case))
    reference_row = _lookup(_reference, selector)
    current_row = _lookup(current_proportions, selector)
    if current_row is None:
        pytest.fail(
            f"group present in the reference but absent from current output: {selector}. "
            "A renamed sub_entity or a dropped stratification would look like this."
        )
    if current_row["denominator"] == 0:
        pytest.skip(f"empty denominator in current output for {selector}")

    fuzzy_checker.fuzzy_assert_proportion(
        observed_numerator=int(current_row["numerator"]),
        observed_denominator=int(current_row["denominator"]),
        target_proportion=jeffreys_interval(
            int(reference_row["numerator"]), int(reference_row["denominator"])
        ),
        name=f"{selector['measure']}:{selector['sub_entity']}",
        name_additional=(
            f"{selector['location']}/{selector['vehicle']}/{selector['scenario']}"
            f"/q{selector['wealth_quintile']}"
        ),
    )


def _lookup(frame: pd.DataFrame, selector: dict) -> pd.Series | None:
    mask = pd.Series(True, index=frame.index)
    for column, value in selector.items():
        mask &= frame[column].astype(str) == str(value)
    matched = frame[mask]
    if matched.empty:
        return None
    assert len(matched) == 1, f"ambiguous selector {selector} matched {len(matched)} rows"
    return matched.iloc[0]
