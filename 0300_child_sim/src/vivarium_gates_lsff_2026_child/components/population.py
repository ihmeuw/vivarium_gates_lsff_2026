"""
==========================
Module for Base Population
==========================

This module contains a component for creating a base population from line list data.

"""

from typing import Dict, List

import numpy as np
import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.population import SimulantData
from vivarium.engine.framework.time import get_time_stamp
from vivarium.public_health.population.base_population import (
    AgeOutSimulants,
    BasePopulation,
    Disability,
)
from vivarium.public_health.population.data_transformations import (
    assign_demographic_proportions,
)

from vivarium_gates_lsff_2026_child.components.mortality import ChildMortality
from vivarium_gates_lsff_2026_child.constants import data_keys


class PopulationLineList(BasePopulation):
    """
    Component to produce and age simulants based on line list data.
    """

    # NOTE: 'is_alive' is deliberately absent -- it is a private column of the mortality
    # sub-component (ChildMortality), which initializes it from the same line list birth
    # records this component reads.
    #
    # The dtypes matter. The initial population is empty (population_size is 0; simulants
    # arrive from the line list on later time steps), and building the frame without
    # dtypes registers every column as 'object'. A later batch's real values then cannot
    # be coerced onto that column -- an object column holding NaN will not cast to
    # datetime64, for instance.
    COLUMN_DTYPES = {
        "age": float,
        "sex": object,
        # "subnational": object,
        "location": object,
        "entrance_time": "datetime64[ns]",
        "exit_time": "datetime64[ns]",
        "maternal_entrance_time": "datetime64[ns]",
        "maternal_age": float,
    }

    @property
    def columns_created(self) -> List[str]:
        return list(self.COLUMN_DTYPES)

    @property
    def time_step_priority(self) -> int:
        return 8

    def __init__(self) -> None:
        # Swap the stock Mortality sub-component for one that can initialize
        # stillbirths as already dead. Mirrors the maternal package's BasePopulation.
        super(BasePopulation, self).__init__()
        self._sub_components += [AgeOutSimulants(), ChildMortality(), Disability()]

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.config = builder.configuration.population
        self.key_columns = builder.configuration.randomness.key_columns
        if self.config.include_sex not in ["Male", "Female", "Both"]:
            raise ValueError(
                "Configuration key 'population.include_sex' must be one "
                "of ['Male', 'Female', 'Both']. "
                f"Provided value: {self.config.include_sex}."
            )

        source_population_structure = self._load_population_structure(builder)
        self.population_data = assign_demographic_proportions(
            source_population_structure,
            include_sex=self.config.include_sex,
        )

        self.randomness = {
            "general_purpose": builder.randomness.get_stream("population_generation"),
            "bin_selection": builder.randomness.get_stream(
                "bin_selection", initializes_crn_attributes=True
            ),
            "age_smoothing": builder.randomness.get_stream(
                "age_smoothing", initializes_crn_attributes=True
            ),
            "age_smoothing_age_bounds": builder.randomness.get_stream(
                "age_smoothing_age_bounds", initializes_crn_attributes=True
            ),
        }
        self.register_simulants = builder.randomness.register_simulants

        self.start_time = get_time_stamp(builder.configuration.time.start)
        self.location = self._get_location(builder)
        # self.subnational = builder.configuration.intervention.subnational

        builder.population.register_initializer(
            initializer=self.initialize_population,
            columns=self.columns_created,
        )

    def initialize_population(self, pop_data: SimulantData) -> None:
        """
        Creates simulants based on their birth date from the line list data.  Their demographic characteristics are also
        determined by the input data.
        """
        new_simulants = pd.DataFrame(
            {col: pd.Series(dtype=dtype) for col, dtype in self.COLUMN_DTYPES.items()},
            index=pop_data.index,
        )

        if pop_data.creation_time >= self.start_time:
            new_births = pop_data.user_data["new_births"]
            new_births.index = pop_data.index

            # Create columns for state table
            new_simulants["age"] = 0.0
            new_simulants["sex"] = new_births["sex"]
            new_simulants["location"] = self.location
            new_simulants["entrance_time"] = pop_data.creation_time
            new_simulants["exit_time"] = new_births["exit_time"]
            new_simulants["maternal_entrance_time"] = new_births["maternal_entrance_time"]
            new_simulants["maternal_age"] = new_births["maternal_age"]

        self.register_simulants(new_simulants[self.key_columns])

        # if pop_data.creation_time >= self.start_time:
        #     if self.subnational == "All":
        #         new_simulants["subnational"] = self._get_subnational_locations(
        #             new_simulants.index
        #         )
        #     else:
        #         new_simulants["subnational"] = self.subnational

        self.population_view.initialize(new_simulants)

    def _get_location(self, builder: Builder) -> Dict[str, str]:
        return builder.data.load("population.location")

    # def _get_subnational_locations(self, pop_index: pd.Index) -> pd.Series:
    #     subnational_percents = pd.read_csv(SUBNATIONAL_PERCENTAGES)
    #     subnational_percents = subnational_percents.loc[
    #         subnational_percents["national_location"] == self.location
    #     ]
    #     location_choices = self.randomness["general_purpose"].choice(
    #         index=pop_index,
    #         choices=subnational_percents["location"],
    #         p=subnational_percents["percent_in_location"],
    #         additional_key="subnational_location_choice",
    #     )
    #     return location_choices


class EvenlyDistributedPopulation(BasePopulation):
    """
    Component for producing and aging simulants which are initialized with ages
    evenly distributed between age start and age end, and evenly split between
    male and female.
    """

    # NOTE: 'is_alive' is created by the Mortality sub-component, not here.
    COLUMNS_CREATED = ["age", "sex", "location", "entrance_time", "exit_time"]

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.location = builder.data.load(data_keys.POPULATION.LOCATION)
        # self.subnational = builder.configuration.intervention.subnational

    def initialize_population(self, pop_data: SimulantData) -> None:
        age_start = pop_data.user_data.get("age_start", self.config.initialization_age_min)
        age_end = pop_data.user_data.get("age_end", self.config.initialization_age_max)

        population = pd.DataFrame(index=pop_data.index)
        population["entrance_time"] = pop_data.creation_time
        population["exit_time"] = pd.NaT
        population["location"] = self.location
        population["age"] = np.linspace(
            age_start, age_end, num=len(population) + 1, endpoint=False
        )[1:]
        population["sex"] = "Female"
        population.loc[population.index % 2 == 1, "sex"] = "Male"
        self.register_simulants(population[list(self.key_columns)])

        # if self.subnational == "All":
        #     self._distribute_subnational_locations(population.index)
        # else:
        #     population["subnational"] = self.subnational

        self.population_view.initialize(population[self.COLUMNS_CREATED])

    # def _distribute_subnational_locations(self, pop_index: pd.Index) -> pd.Series:
    #     subnational_locations = pd.read_csv(SUBNATIONAL_PERCENTAGES)
    #     subnational_locations = subnational_locations.loc[
    #         subnational_locations["national_location"] == self.location
    #     ]["location"].unique()

    #     # Get repeating array of subnationals then fill remaining rows if necessary
    #     filled_subnationals = np.repeat(
    #         subnational_locations, repeats=len(pop_index) / len(subnational_locations)
    #     )
    #     remainder = len(pop_index) - len(filled_subnationals)
    #     if remainder > 0:
    #         extra_fill = subnational_locations[:remainder]
    #         filled_subnationals = np.append(filled_subnationals, extra_fill)

    #     subnational_choices = pd.Series(filled_subnationals, index=pop_index)

    #     return subnational_choices
