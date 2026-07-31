"""Layer 4: transitions that must actually fire.

Unlike the other layers this needs **no baseline**, which is the point. Layers 1
and 2 compare against a reference run, so they cannot help on a branch whose
output is legitimately expected to differ -- exactly the situation during a
migration. These checks assert from first principles that a quantity cannot be
zero, so they work anywhere, including on the migration branch.

Motivated by a real failure: maternal hemorrhage incidence coming out zero on
albrja/mic-7325/framework-updates-pt1. There is a silent zero built into
``ParturitionSelectionTransition.compute_transition_proportion``
(``components/disease.py``):

    transition_proportion = pd.Series(0.0, index=index)
    sub_pop = self.population_view.get(
        index, query="(alive == 'alive') & (pregnancy == 'parturition')"
    ).index
    transition_proportion.loc[sub_pop] = self.lookup_tables["proportion"](sub_pop)

If that filter matches nobody the function returns all zeros and raises nothing.
One way for it to match nobody: the class obtains ``pregnancy`` by declaring
``columns_required``, which the pinned engine reads at ``component.py:771`` but
which does not exist anywhere in vivarium-engine 5.5.3 -- so declaring it there is
a silent no-op and the column never reaches the population view.

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
        "  For the maternal disease transitions, check that `pregnancy` is in "
        "ParturitionSelectionTransition's population view -- compute_transition_proportion "
        "returns an all-zero series when its parturition filter matches nobody, silently. "
        "`columns_required` is not read by vivarium-engine 5.5.3."
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
