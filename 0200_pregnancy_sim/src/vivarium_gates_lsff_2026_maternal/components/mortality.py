from typing import Any, Dict, List, Union

import pandas as pd
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.event import Event
from vivarium.engine.framework.lookup import LookupTable
from vivarium.engine.framework.population import PopulationView, SimulantData
from vivarium.engine.framework.randomness import RandomnessStream
from vivarium.engine.framework.values import Pipeline
from vivarium.public_health.population import Mortality

from vivarium_gates_lsff_2026_maternal.constants import data_keys


class MaternalMortality(Mortality):
    ##############
    # Properties #
    ##############

    @property
    def standard_lookup_tables(self) -> List[str]:
        # This component only models maternal-disorder deaths, so it does not
        # use an all-cause mortality rate.
        return ["life_expectancy"]

    @property
    def time_step_priority(self) -> int:
        return 9

    @property
    def configuration_defaults(self) -> Dict[str, Dict[str, Any]]:
        return {
            self.name: {
                "data_sources": {
                    "life_expectancy": "population.theoretical_minimum_risk_life_expectancy",
                },
            },
        }

    #####################
    # Lifecycle methods #
    #####################

    def __init__(self):
        super().__init__()
        self.mortality_probability_pipeline_name = "mortality_probability"

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.random = self.get_randomness_stream(builder)
        self.clock = builder.time.clock()
        self.step_size = builder.time.step_size()
        self.life_expectancy_table = self.build_lookup_table(builder, "life_expectancy")
        self.mortality_probability = self.get_mortality_probability(builder)

        builder.value.register_attribute_modifier("exit_time", self.update_exit_times)

        builder.population.register_initializer(
            initializer=self.on_initialize_simulants,
            columns=[
                "is_alive",
                self.cause_of_death_column_name,
                self.years_of_life_lost_column_name,
            ],
        )

    ###################
    # Setup Methods   #
    ###################

    def get_mortality_probability(self, builder: Builder):
        # NOTE: I did not add this to the configurable lookup tables because
        # it is only used as the source for the pipeline.
        probability_data = builder.data.load(
            data_keys.MATERNAL_DISORDERS.MORTALITY_PROBABILITY
        )
        probability_pipeline_source = self.build_lookup_table(
            builder,
            "mortality_probability",
            data_source=probability_data,
        )
        return builder.value.register_value_producer(
            self.mortality_probability_pipeline_name,
            source=probability_pipeline_source,
        )

    ########################
    # Event-driven methods #
    ########################

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            {
                "is_alive": True,
                self.cause_of_death_column_name: "not_dead",
                self.years_of_life_lost_column_name: 0.0,
            },
            index=pop_data.index,
        )
        self.population_view.initialize(pop_update)

    def on_time_step(self, event: Event) -> None:
        at_risk = self.population_view.get_filtered_index(
            event.index,
            query="(is_alive == True) & (maternal_disorders == 'maternal_disorders')",
        )
        mortality_probability = self.mortality_probability(at_risk)

        deaths = self.random.filter_for_probability(
            at_risk, mortality_probability, additional_key="death"
        )
        if deaths.empty:
            return

        # 'exit_time' is updated by the attribute modifier registered in setup.
        pop_update = pd.DataFrame(
            {
                "is_alive": False,
                self.cause_of_death_column_name: "maternal_disorders",
                self.years_of_life_lost_column_name: self.life_expectancy_table(deaths),
            },
            index=deaths,
        )
        self.population_view.update(list(pop_update.columns), lambda _: pop_update)
