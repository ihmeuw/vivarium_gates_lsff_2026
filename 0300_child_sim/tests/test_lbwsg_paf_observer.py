"""Guards the exposure frame ``LBWSGPAFObserver`` weights its PAFs by.

The PAF is a weighted average of relative risks over the LBWSG exposure
distribution, so the weights are the whole calculation. Three things about them
are easy to get wrong and none of them raises:

- the distribution has to be birth prevalence, not the neonatal exposure key,
  which GBD has already depleted by mortality;
- it has to be the prevalence of the stratum's own sex, not of both pooled;
- late neonatal weights have to be birth prevalence depleted by the early
  neonatal survival this simulation produced.
"""

import numpy as np
import pandas as pd
import pytest

from vivarium_gates_lsff_2026_child.components.lbwsg import (
    LBWSGPAFObserver,
    calculate_mortality_weights,
)

TARGET = "cause.affected_unmodeled.cause_specific_mortality_rate"
RELATIVE_RISKS = {"cat1": 3.0, "cat2": 1.0}
BIRTH_PREVALENCE = {
    ("Female", "cat1"): 0.2,
    ("Female", "cat2"): 0.8,
    ("Male", "cat1"): 0.5,
    ("Male", "cat2"): 0.5,
}


class FakePopulationView:
    """The slice of ``PopulationView`` the observer uses."""

    def __init__(self, population: pd.DataFrame):
        self.population = population

    def get(self, index, attributes, **kwargs):
        subset = self.population.loc[index]
        if isinstance(attributes, str):
            return subset[attributes]
        return subset[list(attributes)]


class IndexIgnoringView(FakePopulationView):
    """A view that returns the whole population whatever index it is given.

    Stands in for the state-table lookup going wrong: the aggregator must not
    depend on it for anything about the stratum it was handed.
    """

    def get(self, index, attributes, **kwargs):
        return super().get(self.population.index, attributes, **kwargs)


class FakeRiskEffect:
    relative_risk_name = "lbwsg_relative_risk"


def make_population(dead: dict[tuple[str, str], int] | None = None) -> pd.DataFrame:
    """Four simulants per (sex, category), with ``dead`` of them not alive."""
    dead = dead or {}
    rows = []
    for sex in ("Female", "Male"):
        for category in RELATIVE_RISKS:
            for i in range(4):
                rows.append(
                    {
                        "sex": sex,
                        "lbwsg_category": category,
                        "is_alive": i >= dead.get((sex, category), 0),
                        FakeRiskEffect.relative_risk_name: RELATIVE_RISKS[category],
                    }
                )
    return pd.DataFrame(rows)


def make_birth_exposure() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "location": "Nigeria",
                "sex": sex,
                "year_start": 2021,
                "year_end": 2022,
                "parameter": category,
                "value": value,
            }
            for (sex, category), value in BIRTH_PREVALENCE.items()
        ]
    )


def make_observer(population: pd.DataFrame) -> LBWSGPAFObserver:
    observer = LBWSGPAFObserver(TARGET)
    observer._population_view = FakePopulationView(population)
    observer.birth_exposure = make_birth_exposure()
    observer.risk_effect = FakeRiskEffect()
    observer.pop_size = len(population)
    observer.step_number = 1
    return observer


def paf_from(weights: dict[str, float]) -> float:
    mean_rr = np.average(
        [RELATIVE_RISKS[category] for category in weights],
        weights=list(weights.values()),
    )
    return (mean_rr - 1) / mean_rr


def test_mortality_weights_are_the_living_fraction_of_the_birth_cohort():
    """The denominator is everyone born into the category, not just the survivors."""
    population = make_population(dead={("Female", "cat1"): 2, ("Male", "cat2"): 1})
    observer = make_observer(population)

    weights = calculate_mortality_weights(observer, "Female")

    assert list(weights["sex"].unique()) == ["Female"]
    proportion_alive = weights.set_index("lbwsg_category")["proportion_alive"]
    assert proportion_alive["cat1"] == 0.5
    assert proportion_alive["cat2"] == 1.0


def test_paf_uses_the_stratum_sex_birth_prevalence():
    """Each sex gets its own exposure distribution, and never the pooled one."""
    population = make_population()
    observer = make_observer(population)

    pafs = {
        sex: observer.calculate_paf(population[population["sex"] == sex])
        for sex in ("Female", "Male")
    }

    assert pafs["Female"] == pytest.approx(paf_from({"cat1": 0.2, "cat2": 0.8}))
    assert pafs["Male"] == pytest.approx(paf_from({"cat1": 0.5, "cat2": 0.5}))
    pooled = paf_from({"cat1": 0.7, "cat2": 1.3})
    assert pooled != pytest.approx(pafs["Female"])
    assert pooled != pytest.approx(pafs["Male"])


def test_paf_weights_are_birth_prevalence_depleted_by_simulated_mortality():
    """The survivors of a high risk category count for less in the next age group."""
    population = make_population(dead={("Female", "cat1"): 2})
    observer = make_observer(population)
    living_females = population[(population["sex"] == "Female") & population["is_alive"]]

    paf = observer.calculate_paf(living_females)

    assert paf == pytest.approx(paf_from({"cat1": 0.2 * 0.5, "cat2": 0.8}))


def test_paf_refuses_to_pool_sexes():
    population = make_population()
    observer = make_observer(population)

    with pytest.raises(ValueError, match=r"\['Female', 'Male'\]"):
        observer.calculate_paf(population)


def test_paf_of_an_empty_stratum_is_zero():
    """The aggregator is handed every stratification combination, including empty ones.

    The cohort occupies one age group per time step, so the other age groups arrive
    with no rows. Weighting a PAF over nothing raises, and the sex guard reads an
    empty stratum as a pooled one, so the empty case has to be answered first.
    """
    population = make_population()
    observer = make_observer(population)

    assert observer.calculate_paf(population.iloc[:0]) == 0.0


def test_paf_reads_the_stratum_it_is_handed():
    """Sex, category and relative risk come from the stratum, not an index lookup.

    Looking them up in the state table by ``x.index`` made the PAF depend on the
    index the results system happened to hand over, and this population assigns
    sex by index parity -- so a wrong index silently mixes the sexes. Only the
    mortality weights read the wider population, and those read the whole cohort
    by design.
    """
    population = make_population()
    observer = make_observer(population)
    observer._population_view = IndexIgnoringView(population)

    paf = observer.calculate_paf(population[population["sex"] == "Female"])

    assert paf == pytest.approx(paf_from({"cat1": 0.2, "cat2": 0.8}))


def test_results_updater_keeps_each_age_group_from_its_own_time_step():
    """Early neonatal comes from the first step and late neonatal from the second."""
    observer = make_observer(make_population())
    first_step = _results({"early_neonatal": 0.3, "late_neonatal": 0.0})
    second_step = _results({"early_neonatal": 0.0, "late_neonatal": 0.2})

    early = observer.results_updater(pd.DataFrame(), first_step)
    observer.on_time_step_cleanup(event=None)
    late = observer.results_updater(early, second_step)

    assert early.equals(first_step)
    assert late["value"].to_dict() == {
        ("early_neonatal", "Female"): 0.3,
        ("late_neonatal", "Female"): 0.2,
    }


def _results(values: dict[str, float]) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(age_group, "Female") for age_group in values], names=["age_group", "sex"]
    )
    return pd.DataFrame({"value": list(values.values())}, index=index)
