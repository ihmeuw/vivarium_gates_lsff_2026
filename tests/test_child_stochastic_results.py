"""Layer 2, extended to ``0300_child_sim``.

Why this file exists
--------------------
The fuzzy layer covered exactly one observer -- ``pregnancy_outcome_count`` from the
pregnancy sim -- out of the 20 the two simulations emit between them. The child sim
had none, despite producing every child DALY, death and low-birth-weight case the
study reports.

The child observers do not fit the composition model in
``test_stochastic_results.py``: ``live_births``, ``low_weight_births`` and ``deaths``
are separate files with no ``sub_entity`` to take a share within. So these are
expressed as **ratios between two count observers**, which is if anything a cleaner
binomial: each live birth either is or is not low weight, and either does or does not
die. ``reference_proportions.compute_child_proportions`` asserts numerator <=
denominator, so a ratio that stops being a proportion fails loudly rather than being
fed to the checker.

The reference
-------------
``tests/reference/child_sim_proportions.csv``, snapshotted from
``.child_results_gbd2021_reference`` -- the only surviving GBD-2021 child output, and
only for **two of the three** combinations, because the child rule's ``rm -rf``
overwrote rice/nigeria before anyone preserved it. rice/nigeria therefore has no
reference rows and no checks here; that is a known gap, not an oversight.

Deliberately a separate file from ``sim_proportions.csv``, which is the only record
of published *pregnancy*-sim behaviour and must not be rewritten while the GBD-2023
findings are open. Regenerate this one with::

    python -m tests.reference_proportions --child

Expect these to FAIL against current output, for the same reason the pregnancy
checks do: the reference is GBD 2021 and the simulations now run GBD 2023. That is
the layer working. Marked ``slow`` so the default suite stays green and the
comparison is opt-in::

    pytest tests/test_child_stochastic_results.py --runslow
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.reference_proportions import (
    CHILD_RATIO_MEASURES,
    GROUP_BY,
    compute_child_proportions,
    load_child_reference,
    ratio_measure_name,
)
from tests.test_stochastic_results import jeffreys_interval

IDENTITY = ["location", "vehicle", "measure", *GROUP_BY, "sub_entity"]

_reference = load_child_reference()
_CASES: list[tuple] = (
    []
    if _reference is None
    else [tuple(row) for row in _reference[IDENTITY].itertuples(index=False)]
)


@pytest.fixture(scope="module")
def current_child_proportions() -> pd.DataFrame | None:
    """Ratios recomputed from whatever child output is on disk now."""
    if _reference is None:
        return None
    wanted = _reference[["location", "vehicle"]].drop_duplicates()
    frames = [
        frame
        for location, vehicle in wanted.itertuples(index=False)
        for numerator, denominator in CHILD_RATIO_MEASURES
        if (frame := compute_child_proportions(location, vehicle, numerator, denominator))
        is not None
    ]
    return pd.concat(frames, ignore_index=True) if frames else None


def test_child_reference_exists() -> None:
    assert _reference is not None, (
        "tests/reference/child_sim_proportions.csv is missing. Generate it from the "
        "preserved GBD-2021 child output with "
        "`python -m tests.reference_proportions --child`."
    )


def test_child_reference_covers_every_ratio_measure() -> None:
    """A measure silently absent from the reference would check nothing while the
    suite stayed green -- the same vacuity trap layer 1 has."""
    if _reference is None:
        pytest.skip("no child reference on disk")

    expected = {
        ratio_measure_name(numerator, denominator)
        for numerator, denominator in CHILD_RATIO_MEASURES
    }
    missing = expected - set(_reference["measure"])
    assert not missing, (
        f"CHILD_RATIO_MEASURES declares {sorted(missing)} but the reference has no rows "
        "for it. Regenerate with `python -m tests.reference_proportions --child`."
    )


def test_child_reference_proportions_are_within_the_unit_interval() -> None:
    """Cheap guard on the reference itself, which every comparison is judged against."""
    if _reference is None:
        pytest.skip("no child reference on disk")

    proportion = _reference["numerator"] / _reference["denominator"]
    assert proportion.between(0, 1).all(), (
        "the committed child reference contains a proportion outside [0, 1]:\n"
        f"{_reference[~proportion.between(0, 1)].to_string()}"
    )
    assert (_reference["denominator"] > 0).all(), "a reference row has a zero denominator"


@pytest.mark.slow
@pytest.mark.parametrize("case", _CASES, ids=lambda c: "/".join(str(part) for part in c))
def test_child_proportion_consistent_with_reference(
    case: tuple, current_child_proportions: pd.DataFrame | None, fuzzy_checker
) -> None:
    if current_child_proportions is None:
        pytest.skip("no child simulation output on disk -- run the 0300 simulations first")

    selector = dict(zip(IDENTITY, case))
    reference_row = _lookup(_reference, selector)
    current_row = _lookup(current_child_proportions, selector)
    if current_row is None:
        pytest.fail(
            f"group present in the child reference but absent from current output: "
            f"{selector}. A renamed observer, a dropped stratification, or a scenario "
            "that stopped being simulated would look like this."
        )
    if current_row["denominator"] == 0:
        pytest.skip(f"empty denominator in current output for {selector}")

    fuzzy_checker.fuzzy_assert_proportion(
        observed_numerator=int(current_row["numerator"]),
        observed_denominator=int(current_row["denominator"]),
        target_proportion=jeffreys_interval(
            int(reference_row["numerator"]), int(reference_row["denominator"])
        ),
        name=f"{selector['measure']}",
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
