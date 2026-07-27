from typing import List

import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.public_health.disease import DiseaseModel, DiseaseState, RecoveredState
from vivarium.public_health.disease.transition import ProportionTransition
from vivarium.public_health.utilities import to_years
from vivarium_gates_lsff_2026_maternal.components.disease import ParturitionSelectionState
from vivarium_gates_lsff_2026_maternal.constants import data_keys, models
from vivarium_gates_lsff_2026_maternal.constants.metadata import ARTIFACT_INDEX_COLUMNS


def MaternalDisorders():
    cause = models.MATERNAL_DISORDERS_STATE_NAME
    susceptible = ParturitionSelectionState(cause, allow_self_transition=True)
    with_condition = DiseaseState(
        cause,
        allow_self_transition=True,
        get_data_functions={
            "prevalence": lambda *_: 0.0,
            "disability_weight": get_maternal_disorders_disability_weight,
            "excess_mortality_rate": lambda *_: 0.0,
            "dwell_time": lambda builder, cause: builder.time.step_size()(),
        },
    )
    recovered = RecoveredState(cause, allow_self_transition=True)
    susceptible.transition_set.append(
        ParturitionSelectionTransition(
            susceptible,
            with_condition,
            get_data_functions={
                "proportion": lambda builder, cause: builder.data.load(
                    f"cause.{cause}.incident_probability"
                )
            },
        )
    )
    with_condition.add_dwell_time_transition(recovered)

    return DiseaseModel(
        cause,
        states=[susceptible, with_condition, recovered],
        get_data_functions={"cause_specific_mortality_rate": lambda *_: 0.0},
    )


def MaternalHemorrhage():
    cause = models.MATERNAL_HEMORRHAGE_STATE_NAME
    susceptible = ParturitionSelectionState(cause, allow_self_transition=True)
    with_condition = DiseaseState(
        cause,
        allow_self_transition=True,
        get_data_functions={
            "prevalence": lambda *_: 0.0,
            "disability_weight": lambda *_: 0.0,
            "excess_mortality_rate": lambda *_: 0.0,
            "dwell_time": lambda builder, cause: builder.time.step_size()(),
        },
    )
    recovered = RecoveredState(cause, allow_self_transition=True)
    susceptible.transition_set.append(
        ParturitionSelectionTransition(
            susceptible,
            with_condition,
            get_data_functions={
                "proportion": lambda builder, cause: builder.data.load(
                    f"cause.{cause}.incident_probability"
                )
            },
        )
    )
    with_condition.add_dwell_time_transition(recovered)

    return DiseaseModel(
        cause,
        states=[susceptible, with_condition, recovered],
        get_data_functions={"cause_specific_mortality_rate": lambda *_: 0.0},
    )


class ParturitionSelectionTransition(ProportionTransition):
    ##############
    # Properties #
    ##############

    @property
    def columns_required(self) -> List[str]:
        return ["alive", "pregnancy"]

    #####################
    # Lifecycle methods #
    #####################

    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        pipeline_name = f"{self.output_state.state_id}.transition_proportion"
        self.proportion_pipeline = builder.value.register_value_producer(
            pipeline_name,
            source=self.compute_transition_proportion,
            requires_attributes=["age", "sex", "wealth_quintile", "alive"],
        )

    ###################
    # Pipeline methods#
    ###################

    def compute_transition_proportion(self, index) -> pd.Series:
        transition_proportion = pd.Series(0.0, index=index)
        sub_pop = self.population_view.get(
            index, query="(alive == 'alive') & (pregnancy == 'parturition')"
        ).index

        transition_proportion.loc[sub_pop] = self.lookup_tables["proportion"](sub_pop)
        return transition_proportion

    ####################
    # Helper methods   #
    ####################

    def _probability(self, index) -> pd.Series:
        return self.proportion_pipeline(index)


def get_maternal_disorders_disability_weight(builder: Builder, cause: str):
    ylds = builder.data.load(data_keys.MATERNAL_DISORDERS.YLDS).set_index(
        ARTIFACT_INDEX_COLUMNS
    )
    timestep = builder.time.step_size()
    return ylds.div(to_years(timestep())).reset_index()
