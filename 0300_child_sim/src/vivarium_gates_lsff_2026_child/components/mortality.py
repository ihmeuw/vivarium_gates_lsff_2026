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
from vivarium.engine.framework.randomness.stream import RandomnessStream
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

    @property
    def name(self) -> str:
        """Keep the base class's configuration key.

        A component's configuration is looked up by its name, and ``Mortality``
        hardcodes ``"mortality"`` in its ``configuration_defaults``.
        """
        return "mortality"

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.start_time = builder.time.clock()()

    def get_randomness_stream(self, builder: Builder) -> RandomnessStream:
        """Request the mortality stream with the pre-monorepo rate conversion.

        TEMPORARY -- delete once the vivarium randomness bug is fixed upstream.

        :meth:`Mortality.on_time_step` draws deaths with ``filter_for_rate``, which converts
        the mortality hazard to a per-step probability. Vivarium changed that conversion's
        default from exponential (``1 - exp(-rate)``) to linear
        (``rate * time_scaling_factor``); since ``1 - exp(-r) < r``, linear raises every
        per-step death probability. This override restores the old behaviour so the new code
        can be compared against the 2026_08_13 run on equal terms.

        It reaches through ``builder.randomness._manager`` because there is currently no
        supported way to select the conversion: ``RandomnessInterface.get_stream`` drops the
        ``rate_conversion_type`` parameter when delegating, and
        ``configuration.randomness.rate_conversion_type`` is read by ``RandomnessManager``
        into ``self._rate_conversion_type`` and then never used. The manager's own method
        does accept the parameter and performs the normal stream registration, so this is
        the closest available call to the intended one.
        """
        return builder.randomness._manager.get_randomness_stream(
            self._randomness_stream_name,
            rate_conversion_type="exponential",
        )

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
