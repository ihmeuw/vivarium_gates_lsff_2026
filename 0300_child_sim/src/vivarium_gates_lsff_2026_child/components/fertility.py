"""
================
Fertility Models
================

Fertility module to create simulants from existing data

"""

import os
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
from vivarium.artifact import Artifact
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.event import Event
from vivarium.public_health import utilities

from vivarium_gates_lsff_2026_child.constants import data_keys

PREGNANCY_DURATION = pd.Timedelta(days=9 * utilities.DAYS_PER_MONTH)


class FertilityLineList(Component):
    """
    This class will determine what simulants need to be added to the state table based on their birth data from existing
    line list data.  Simulants will be registered to the state table on the time steps in which their birth takes place.
    """

    #################
    # Setup methods #
    #################

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder):
        self.clock = builder.time.clock()
        self.simulant_creator = builder.population.get_simulant_creator()

        # Requirements for input data
        self.birth_records = self._get_birth_records(builder)

    @staticmethod
    def _get_birth_records(builder: Builder) -> pd.DataFrame:
        """
        Method to load existing fertility data to use as birth records.
        """
        scenario = builder.configuration.intervention.maternal_scenario
        draw = builder.configuration.input_data.input_draw_number
        seed = builder.configuration.randomness.random_seed

        # HACK: cannot filter by more than one thing in the config!
        # If we don't do this, the entire fertility line-list gets
        # loaded into memory
        artifact_copy = Artifact(
            builder.data._manager.artifact._path,
            builder.data._manager.artifact._filter_terms
            + [
                # NOTE: "input_draw" becomes "value" when loading
                f"input_draw == {draw}",
                f"scenario == '{scenario}'",
                f"random_seed == {seed}",
            ],
        )
        birth_records = artifact_copy.load(
            data_keys.POPULATION.FERTILITY_DATA,
        ).reset_index()
        birth_records["birth_date"] = pd.to_datetime(birth_records["birth_date"])
        return birth_records

    def on_time_step(self, event: Event) -> None:
        """Adds new simulants every time step determined by a simulant's birth date in the line list data.
        Parameters
        ----------
        event
            The event that triggered the function call.
        """
        birth_records = self.birth_records
        born_previous_step_mask = (birth_records["birth_date"] < self.clock()) & (
            birth_records["birth_date"] > self.clock() - event.step_size
        )
        born_previous_step = birth_records[born_previous_step_mask].copy()
        # everyone is currently born on the first time step so this is always empty after the first time step
        if born_previous_step.empty:
            return
        # Stillbirths get an exit time immediately. Their 'is_alive' and
        # 'cause_of_death' are set by ChildMortality, which owns those columns.
        born_previous_step.loc[:, "exit_time"] = np.datetime64("NaT")
        is_stillbirth = born_previous_step["pregnancy_outcome"] == "stillbirth"
        born_previous_step.loc[is_stillbirth, "exit_time"] = self.clock()

        simulants_to_add = len(born_previous_step)

        if simulants_to_add > 0:
            self.simulant_creator(
                simulants_to_add,
                population_configuration={
                    "age_start": 0,
                    "age_end": 0,
                    "sim_state": "time_step",
                    "new_births": born_previous_step,
                },
            )

    # NOTE: The former on_time_step_cleanup that stamped 'cause_of_death' as
    # "stillborn" is gone. A component may only write its own private columns now,
    # and 'cause_of_death' belongs to the mortality component -- ChildMortality
    # sets it during initialization instead.
