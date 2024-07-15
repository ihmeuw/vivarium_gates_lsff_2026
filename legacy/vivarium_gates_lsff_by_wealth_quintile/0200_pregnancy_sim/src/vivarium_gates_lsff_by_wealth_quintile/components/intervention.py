from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import scipy.stats
from vivarium import Component
from vivarium.framework.engine import Builder
from vivarium.framework.event import Event
from vivarium.framework.population import SimulantData
from vivarium.framework.randomness import RESIDUAL_CHOICE
from vivarium.framework.time import get_time_stamp

from vivarium_gates_lsff_by_wealth_quintile.constants import (
    data_keys,
    data_values,
    models,
)


class IronFortification(Component):
    CONFIGURATION_DEFAULTS = {
        "intervention": {
            "scenario": "baseline",
        }
    }

    @property
    def columns_created(self) -> List[str]:
        return ["intervention"]

    @property
    def columns_required(self) -> List[str]:
        return ["tracked"]

    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {"requires_streams": [self.name], "requires_columns": self.columns_required}

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.clock = builder.time.clock()
        self.start_date = get_time_stamp(builder.configuration.time.start)
        self.randomness = builder.randomness.get_stream(self.name)

        self.scenario = builder.configuration.intervention.scenario
        self.coverage = builder.data.load(data_keys.IRON_FORTIFICATION.COVERAGE).value[0]
        self.stillbirth_rr = builder.data.load(
            data_keys.IRON_FORTIFICATION.STILLBIRTH_RR
        ).value[0]
        self.effect_size = builder.data.load(data_keys.IRON_FORTIFICATION.EFFECT_SIZE).value[
            0
        ]

        builder.value.register_value_modifier(
            "hemoglobin.exposure",
            self.update_exposure,
            requires_columns=self.columns_created,
        )

        builder.value.register_value_modifier(
            "birth_outcome_probabilities",
            self.adjust_stillbirth_probability,
            requires_columns=self.columns_created,
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            {"intervention": None},
            index=pop_data.index,
        )
        baseline_fortification = self.randomness.choice(
            pop_data.index,
            choices=[models.IRON_FORTIFICATION, models.NO_TREATMENT],
            p=[self.coverage, RESIDUAL_CHOICE],
            additional_key="baseline_fortification",
        )
        coverage = data_values.INTERVENTION_SCENARIO_COVERAGE.loc[self.scenario]
        pop_update["intervention"] = coverage["fortification"]

        unsampled_fortification = pop_update["intervention"] == "maybe"
        pop_update.loc[unsampled_fortification, "intervention"] = baseline_fortification.loc[
            unsampled_fortification
        ]

        self.population_view.update(pop_update)

    def update_exposure(self, index, exposure):
        pop = self.population_view.get(index)
        exposure.loc[pop["intervention"] == models.NO_TREATMENT] -= (
            self.coverage * self.effect_size
        )
        exposure.loc[pop["intervention"] != models.NO_TREATMENT] += (
            1 - self.coverage
        ) * self.effect_size

        return exposure

    def adjust_stillbirth_probability(self, index, birth_outcome_probabilities):
        pop = self.population_view.subview(["intervention"]).get(index)

        on_treatment = pop["intervention"] == models.IRON_FORTIFICATION
        # Add spare probability onto live births first
        birth_outcome_probabilities.loc[
            on_treatment, models.LIVE_BIRTH_OUTCOME
        ] += birth_outcome_probabilities.loc[on_treatment, models.STILLBIRTH_OUTCOME] * (
            1 - self.stillbirth_rr
        )
        # Then re-scale stillbirth probability
        birth_outcome_probabilities.loc[
            on_treatment, models.STILLBIRTH_OUTCOME
        ] *= self.stillbirth_rr
        # This preserves normalization by construction

        return birth_outcome_probabilities
