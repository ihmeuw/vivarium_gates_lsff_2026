from vivarium.public_health.population import BasePopulation as BasePopulation_
from vivarium.public_health.population.base_population import AgeOutSimulants, Disability

from vivarium_gates_lsff_2026_maternal.components.mortality import MaternalMortality


class BasePopulation(BasePopulation_):
    """BasePopulation with MaternalMortality as the sole mortality sub-component."""

    def __init__(self):
        super(BasePopulation_, self).__init__()
        self._sub_components += [AgeOutSimulants(), MaternalMortality(), Disability()]
