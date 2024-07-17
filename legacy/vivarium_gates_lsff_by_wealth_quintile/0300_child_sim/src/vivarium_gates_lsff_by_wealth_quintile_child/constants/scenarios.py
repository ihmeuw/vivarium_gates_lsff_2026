from typing import NamedTuple

from vivarium_gates_lsff_by_wealth_quintile_child.constants.data_values import WASTING

#############
# Scenarios #
#############


class InterventionScenario:
    def __init__(
        self,
        name: str,
    ):
        self.name = name


class __InterventionScenarios(NamedTuple):
    BASELINE: InterventionScenario = InterventionScenario("baseline")

    def __getitem__(self, item) -> InterventionScenario:
        for scenario in self:
            if scenario.name == item:
                return scenario
        raise KeyError(item)


INTERVENTION_SCENARIOS = __InterventionScenarios()
