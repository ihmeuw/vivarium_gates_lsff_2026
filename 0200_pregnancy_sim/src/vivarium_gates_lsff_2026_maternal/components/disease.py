import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.state_machine import State, Transition
from vivarium.engine.framework.values import Pipeline, list_combiner, union_post_processor
from vivarium.public_health.disease import DiseaseState, SusceptibleState
from vivarium.public_health.disease.transition import ProportionTransition

from vivarium_gates_lsff_2026_maternal.constants import models


class ParturitionSelectionState(SusceptibleState):
    def add_transition(
        self,
        output: State,
        source_data_type: str = "proportion",
        **kwargs,
    ) -> Transition:
        transition = ParturitionSelectionTransition(self, output, **kwargs)
        self.transition_set.append(transition)
        return transition


class ParturitionSelectionTransition(ProportionTransition):
    def __init__(self, input_state: State, output_state: State, **kwargs) -> None:
        cause = output_state.state_id
        proportion = lambda builder: builder.data.load(f"cause.{cause}.incident_probability")
        super().__init__(input_state, output_state, proportion=proportion, **kwargs)

    ##############
    # Properties #
    ##############

    #####################
    # Lifecycle methods #
    #####################

    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        pipeline_name = f"{self.output_state.state_id}.transition_proportion"
        self.proportion_pipeline = builder.value.register_value_producer(
            pipeline_name,
            source=self.compute_transition_proportion,
            required_resources=["age", "sex", "is_alive", "pregnancy"],
        )

    ###################
    # Pipeline methods#
    ###################

    def compute_transition_proportion(self, index) -> pd.Series:
        transition_proportion = pd.Series(0.0, index=index)
        sub_pop = self.population_view.get_filtered_index(
            index, query="(is_alive == True) & (pregnancy == 'parturition')"
        )

        transition_proportion.loc[sub_pop] = self.proportion_table(sub_pop)
        return transition_proportion

    ####################
    # Helper methods   #
    ####################

    def _probability(self, index) -> pd.Series:
        return self.proportion_pipeline(index)


class ParturitionExclusionState(DiseaseState):
    ##############
    # Properties #
    ##############

    # #####################
    # # Lifecycle methods #
    # #####################

    def register_disability_weight_pipeline(self, builder: Builder) -> None:
        builder.value.register_attribute_producer(
            f"{self.state_id}.disability_weight",
            source=self.compute_disability_weight,
            required_resources=[
                self.disability_weight_table,
                "is_alive",
                self.model,
                "pregnancy",
            ],
        )

    ##################################
    # Pipeline sources and modifiers #
    ##################################

    def compute_disability_weight(self, index: pd.Index) -> pd.Series:
        disability_weight = pd.Series(0, index=index)
        raw_disability_weight = pd.Series(0, index=index)
        with_condition = self.with_condition(index)
        raw_disability_weight.loc[with_condition] = self.base_disability_weight(
            with_condition
        )

        dw_map = {
            models.NOT_PREGNANT_STATE_NAME: raw_disability_weight,
            models.PREGNANT_STATE_NAME: raw_disability_weight,
            ## Pause YLD accumulation during the parturition state
            models.PARTURITION_STATE_NAME: pd.Series(0, index=index),
            models.POSTPARTUM_STATE_NAME: raw_disability_weight,
        }

        pop = self.population_view.get(index, ["is_alive", "pregnancy"])
        alive = pop["is_alive"]
        for state, dw in dw_map.items():
            in_state = alive & (pop["pregnancy"] == state)
            disability_weight[in_state] = dw.loc[in_state]

        return disability_weight
