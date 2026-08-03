"""
=========
Mortality
=========

Mortality for the child model. Extends the public health :class:`Mortality`
component so that simulants arriving from the maternal line list as stillbirths
can be initialized already dead.

"""

import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.population import SimulantData
from vivarium.public_health.population import Mortality


class ChildMortality(Mortality):
    """Mortality that seeds ``is_alive`` and ``cause_of_death`` from birth records.

    The stock :class:`Mortality` initializes every new simulant as alive. Children
    entering this model come from the maternal simulation's birth records, some of
    which are stillbirths and must start dead with a cause of death of 'stillborn'.

    Notes
    -----
    This lives on the mortality component rather than on ``FertilityLineList``
    because ``is_alive`` and ``cause_of_death`` are private columns of the mortality
    component, and the population system only permits a component to write its own
    private columns.
    """

    STILLBIRTH_OUTCOME = "stillbirth"
    STILLBIRTH_CAUSE_OF_DEATH = "stillborn"

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.start_time = builder.time.clock()()

    def initialize_mortality(self, pop_data: SimulantData) -> None:
        """Initialize mortality columns, starting stillbirths dead."""
        is_alive = pd.Series(True, index=pop_data.index)
        cause_of_death = pd.Series("not_dead", index=pop_data.index)

        new_births = pop_data.user_data.get("new_births")
        if new_births is not None and not new_births.empty:
            outcomes = pd.Series(
                new_births["pregnancy_outcome"].to_numpy(), index=pop_data.index
            )
            stillborn = outcomes == self.STILLBIRTH_OUTCOME
            is_alive.loc[stillborn] = False
            cause_of_death.loc[stillborn] = self.STILLBIRTH_CAUSE_OF_DEATH

        self.population_view.initialize(
            pd.DataFrame(
                {
                    "is_alive": is_alive,
                    self.cause_of_death_column_name: cause_of_death,
                    self.years_of_life_lost_column_name: 0.0,
                },
                index=pop_data.index,
            )
        )
