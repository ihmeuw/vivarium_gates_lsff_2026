"""Layer 4: transitions that must actually fire.

Unlike the other layers this needs **no baseline**, which is the point. Layers 1
and 2 compare against a reference run, so they cannot help on a branch whose
output is legitimately expected to differ -- exactly the situation during a
migration. These checks assert from first principles that a quantity cannot be
zero, so they work anywhere, including on the migration branch.

Motivated by a real failure: maternal hemorrhage incidence coming out zero on
albrja/mic-7325/framework-updates-pt1.

There are two silent zeros on that path, either of which turns a data or wiring
problem into a plausible-looking result rather than an error.

The first is in the data loader, and is the more likely culprit.
``load_pregnant_maternal_hemorrhage_incidence`` ends with::

    return result.reindex(...).fillna(0)

so any index misalignment -- different age bins, a changed disparity join, an
extra index level -- silently becomes zeros. That is a live risk on the migration
branch, which carries commits explicitly working around "2021 vs 2023 data
misalignment" and one that loosened a ``np.allclose`` assertion in
``_distribute_by_disparities_multiplicative`` to mask NaNs. Masked NaNs feeding a
``fillna(0)`` is exactly how you get a silent zero.

The second is in the component: ``compute_transition_proportion`` seeds an
all-zero series and only fills rows matching ``pregnancy == 'parturition'``, so a
filter matching nobody also returns zeros without raising.

Check the artifact key before the component -- it is cheaper and more likely.

For reference, the values this produced on the verified GBD-2021 run: hemorrhage
8.4% of parturitions in India/rice and 11.6% in Nigeria; maternal disorders much
higher. The bands below are deliberately wide sanity bounds, not validation
targets -- their job is to catch zero, near-zero and runaway, not to pin
epidemiology that legitimately shifts between GBD rounds.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.baseline import REPO_ROOT
from tests.reference_proportions import SIMULATED, sim_output_path

# Transitions that must fire in every scenario, with the denominator to express
# them against. An explicit allowlist rather than "every transition", because
# some are legitimately zero -- see EXPECTED_ZERO_TRANSITIONS.
MUST_FIRE = (
    # (measure, sub_entity, per_parturition_low, per_parturition_high)
    ("pregnancy", "pregnant_to_parturition", None, None),
    ("pregnancy", "parturition_to_postpartum", None, None),
    ("maternal_disorders", "susceptible_to_maternal_disorders_to_maternal_disorders", 0.001, 5.0),
    ("maternal_hemorrhage", "susceptible_to_maternal_hemorrhage_to_maternal_hemorrhage", 0.001, 0.5),
)

# postpartum_to_not_pregnant is zero by design: UntrackNotPregnant untracks
# simulants on time-step cleanup as soon as they reach not_pregnant, and the
# observers filter on `tracked == True`, so the transition is never recorded.
# Listed so nobody "fixes" it by adding it to MUST_FIRE.
EXPECTED_ZERO_TRANSITIONS = (("pregnancy", "postpartum_to_not_pregnant"),)

CASES = [
    (location, vehicle, measure, sub_entity, low, high)
    for location, vehicle in SIMULATED
    for measure, sub_entity, low, high in MUST_FIRE
]


def load_transitions(location: str, vehicle: str, measure: str) -> pd.DataFrame | None:
    path = sim_output_path(location, vehicle, f"transition_count_{measure}")
    return pd.read_parquet(path) if path.exists() else None


def parturitions_by_scenario(location: str, vehicle: str) -> pd.Series:
    """Live births plus stillbirths. Partial-term pregnancies never reach
    parturition, so they are not opportunities for these transitions."""
    outcomes = pd.read_parquet(sim_output_path(location, vehicle, "pregnancy_outcome_count"))
    reaching = outcomes[outcomes["sub_entity"].astype(str).isin(["live_birth", "stillbirth"])]
    return reaching.groupby("scenario", observed=True)["value"].sum()


@pytest.mark.parametrize(
    "location,vehicle,measure,sub_entity,low,high",
    CASES,
    ids=lambda part: str(part),
)
def test_transition_fires_in_every_scenario(
    location: str, vehicle: str, measure: str, sub_entity: str, low: float | None, high: float | None
) -> None:
    transitions = load_transitions(location, vehicle, measure)
    if transitions is None:
        pytest.skip(f"no {measure} output for {location}/{vehicle} -- run the 0200 sims")

    matching = transitions[transitions["sub_entity"].astype(str) == sub_entity]
    assert not matching.empty, (
        f"{location}/{vehicle}: no rows for transition {sub_entity!r} in "
        f"transition_count_{measure}. Present: "
        f"{sorted(transitions['sub_entity'].astype(str).unique())}"
    )

    per_scenario = matching.groupby("scenario", observed=True)["value"].sum()
    zeroed = per_scenario[per_scenario <= 0]
    assert zeroed.empty, (
        f"{location}/{vehicle}: {sub_entity} never fires in "
        f"{list(zeroed.index)} (counts {zeroed.to_dict()}).\n"
        "  Check the artifact input first: for the maternal disease transitions, load\n"
        "  `cause.<cause>.incident_probability` and see whether it is zero. Its loader\n"
        "  (data/loader.py::load_pregnant_maternal_hemorrhage_incidence) ends with\n"
        "  `.reindex(...).fillna(0)`, so any index misalignment becomes zeros rather\n"
        "  than an error. On the verified GBD-2021 run that key has mean 0.011,\n"
        "  max 0.110, 45/250 rows non-zero.\n"
        "  If the input is fine, then look at the component: compute_transition_proportion\n"
        "  seeds an all-zero series and only fills rows matching\n"
        "  `pregnancy == 'parturition'`, so a filter that matches nobody is also silent."
    )

    if low is None:
        return

    denominator = parturitions_by_scenario(location, vehicle)
    rates = (per_scenario / denominator).dropna()
    implausible = rates[(rates < low) | (rates > high)]
    assert implausible.empty, (
        f"{location}/{vehicle}: {sub_entity} per parturition outside the sanity band "
        f"[{low:.1%}, {high:.1%}]: "
        f"{ {scenario: f'{rate:.3%}' for scenario, rate in implausible.items()} }\n"
        "  This band is a smoke test, not a validation target. If GBD legitimately "
        "moved the rate, widen it here."
    )


@pytest.mark.parametrize("measure,sub_entity", EXPECTED_ZERO_TRANSITIONS)
def test_expected_zero_transitions_are_still_zero(measure: str, sub_entity: str) -> None:
    """If one of these starts firing, an assumption changed and the note in
    EXPECTED_ZERO_TRANSITIONS needs revisiting."""
    checked = 0
    for location, vehicle in SIMULATED:
        transitions = load_transitions(location, vehicle, measure)
        if transitions is None:
            continue
        checked += 1
        total = transitions[
            transitions["sub_entity"].astype(str) == sub_entity
        ]["value"].sum()
        assert total == 0, (
            f"{location}/{vehicle}: {sub_entity} now fires ({total:,.0f}), but it is "
            "recorded as zero-by-design because UntrackNotPregnant untracks simulants "
            "before the observer sees them. Re-examine that reasoning."
        )
    if not checked:
        pytest.skip("no simulation output on disk")
