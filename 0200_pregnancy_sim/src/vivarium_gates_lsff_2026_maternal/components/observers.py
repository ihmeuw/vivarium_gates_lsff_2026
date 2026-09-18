from datetime import datetime
from functools import partial
from typing import Any, Dict

import pandas as pd
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.results import Observer
from vivarium.engine.framework.time import get_time_stamp
from vivarium.public_health.disease import DiseaseState
from vivarium.public_health.results import COLUMNS
from vivarium.public_health.results import DisabilityObserver as DisabilityObserver_
from vivarium.public_health.results import (
    DiseaseObserver,
    MortalityObserver,
    PublicHealthObserver,
)
from vivarium.public_health.results import ResultsStratifier as ResultsStratifier_
from vivarium.public_health.results import SimpleCause
from vivarium.public_health.utilities import to_years

from lsff_utils import data_processing
from vivarium_gates_lsff_2026_maternal.constants import data_values, models


class ResultsStratifier(ResultsStratifier_):
    def register_stratifications(self, builder: Builder) -> None:
        super().register_stratifications(builder)

        builder.results.register_stratification(
            "anemia_status_at_birth",
            list(data_values.ANEMIA_STATUS_AT_BIRTH_CATEGORIES),
            requires_attributes=["anemia_status_at_birth"],
        )

        builder.results.register_stratification(
            "anemia_levels",
            list(data_values.ANEMIA_DISABILITY_WEIGHTS),
            requires_attributes=["anemia_levels"],
        )

        # builder.results.register_stratification(
        #     "maternal_bmi_anemia_category",
        #     models.BMI_ANEMIA_CATEGORIES,
        #     requires_attributes=["maternal_bmi_anemia_category"],
        # )

        # builder.results.register_stratification(
        #     "intervention",
        #     models.FORTIFICATION_CATEGORIES,
        #     requires_attributes=["intervention"],
        # )

        builder.results.register_stratification(
            "pregnancy_outcome",
            list(models.PREGNANCY_OUTCOMES),
            requires_attributes=["pregnancy_outcome"],
        )

        builder.results.register_stratification(
            "wealth_quintile",
            list(data_processing.WEALTH_QUINTILES),
            requires_attributes=["wealth_quintile"],
        )


class PregnancyObserver(DiseaseObserver):
    def __init__(self):
        super().__init__("pregnancy")


class MaternalMortalityObserver(MortalityObserver):
    def set_causes_of_death(self, builder: Builder) -> None:
        super().set_causes_of_death(builder)
        self.causes_of_death += [
            SimpleCause(
                models.MATERNAL_DISORDERS_MODEL_NAME,
                models.MATERNAL_DISORDERS_MODEL_NAME,
                "cause",
            )
        ]


class AnemiaObserver(PublicHealthObserver):
    @property
    def configuration_defaults(self) -> Dict[str, Any]:
        return {
            "stratification": {
                self.get_configuration_name(): {
                    "exclude": [],
                    "include": ["anemia_levels"],
                },
            },
        }

    def register_observations(self, builder: Builder) -> None:
        self.register_adding_observation(
            builder=builder,
            name="person_time_anemia",
            pop_filter="is_alive == True",
            when="time_step__prepare",
            requires_attributes=["is_alive", "anemia_levels"],
            additional_stratifications=builder.configuration.stratification.anemia.include,
            excluded_stratifications=builder.configuration.stratification.anemia.exclude,
            aggregator=partial(aggregate_state_person_time, builder.time.step_size()()),
        )

    def format(self, measure: str, results: pd.DataFrame) -> pd.DataFrame:
        results = results.reset_index()
        results.rename(columns={"anemia_levels": COLUMNS.SUB_ENTITY}, inplace=True)
        return results

    def get_measure_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("person_time", index=results.index)

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("impairment", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("anemia", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        # This column was created in the 'format' method
        return results[COLUMNS.SUB_ENTITY]


class MaternalInterventionObserver(PublicHealthObserver):
    @property
    def configuration_defaults(self) -> Dict[str, Any]:
        return {
            "stratification": {
                self.get_configuration_name(): {
                    "exclude": [],
                    "include": ["intervention"],
                },
            },
        }

    def register_observations(self, builder: Builder) -> None:
        # 2 weeks between administration and effect
        intervention_date = get_time_stamp(builder.configuration.time.start) + pd.Timedelta(
            days=data_values.DURATIONS.INTERVENTION_DELAY_DAYS - 2 * 7
        )
        self.register_adding_observation(
            builder=builder,
            name="intervention_count",
            pop_filter=(
                "is_alive == True and "
                f'event_time > "{intervention_date}" and '
                f'event_time <= "{intervention_date + builder.time.step_size()()}"'
            ),
            requires_attributes=["is_alive", "intervention", "event_time"],
            additional_stratifications=builder.configuration.stratification.maternal_intervention.include,
            excluded_stratifications=builder.configuration.stratification.maternal_intervention.exclude,
        )

    def format(self, measure: str, results: pd.DataFrame) -> pd.DataFrame:
        results = results.reset_index()
        results.rename(columns={"intervention": "sub_entity"}, inplace=True)
        return results

    def get_measure_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series(measure, index=results.index)

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("intervention", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("maternal_intervention", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        # This column was created in the 'format' method
        return results[COLUMNS.SUB_ENTITY]


class PregnancyOutcomeObserver(PublicHealthObserver):
    @property
    def configuration_defaults(self) -> Dict[str, Any]:
        return {
            "stratification": {
                self.get_configuration_name(): {
                    "exclude": [],
                    "include": ["pregnancy_outcome"],
                },
            },
        }

    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.clock = builder.time.clock()
        self.start_date = get_time_stamp(builder.configuration.time.start)

    def register_observations(self, builder: Builder) -> None:

        self.register_adding_observation(
            builder=builder,
            name="pregnancy_outcome_count",
            pop_filter="",
            requires_attributes=["pregnancy_outcome"],
            additional_stratifications=builder.configuration.stratification.pregnancy_outcome.include,
            excluded_stratifications=builder.configuration.stratification.pregnancy_outcome.exclude,
            aggregator=self.count_pregnancy_outcomes_at_initialization,
        )

    def format(self, measure: str, results: pd.DataFrame) -> pd.DataFrame:
        results = results.reset_index()
        results.rename(columns={"pregnancy_outcome": COLUMNS.SUB_ENTITY}, inplace=True)
        return results

    def get_measure_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series(measure, index=results.index)

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("custom_fertility", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("pregnancy_outcome", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        # This column was created in the 'format' method
        return results[COLUMNS.SUB_ENTITY]

    ###############
    # Aggregators #
    ###############

    def count_pregnancy_outcomes_at_initialization(self, x: pd.DataFrame) -> float:
        if self.clock() == self.start_date:
            return len(x)
        else:
            return 0


class DisabilityObserver(DisabilityObserver_):
    def set_causes_of_disability(self, builder: Builder) -> None:
        super().set_causes_of_disability(builder)
        self.causes_of_disability += [SimpleCause("anemia", "anemia", "cause")]


class PersonTimeObserver(PublicHealthObserver):
    """Total population person time, emitted in the standard four-column results format."""

    def register_observations(self, builder: Builder) -> None:
        self.register_adding_observation(
            builder=builder,
            name="person_time_population",
            pop_filter="is_alive == True",
            when="time_step__prepare",
            additional_stratifications=self.configuration.include,
            excluded_stratifications=self.configuration.exclude,
            aggregator=partial(aggregate_state_person_time, builder.time.step_size()()),
        )

    def get_measure_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("person_time", index=results.index)

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("population", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("population", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        # No sub-breakdown: this is whole-population person time.
        return pd.Series("population", index=results.index)


class HemoglobinObserver(PublicHealthObserver):
    """Hemoglobin exposure, before and after fortification, plus the severe-anemia count."""

    SEVERE_ANEMIA_THRESHOLD = 70  # g/L, pregnant, age 15+

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.hemoglobin_name = "hemoglobin.exposure"
        self.raw_hemoglobin_name = "raw_hemoglobin.exposure"

    # noinspection PyAttributeOutsideInit
    def register_observations(self, builder: Builder) -> None:
        observations = (
            # (observation name, sub_entity, pipeline, aggregator)
            ("hemoglobin_exposure_sum", "exposure", self.hemoglobin_name, self.sum_exposure),
            (
                "raw_hemoglobin_exposure_sum",
                "raw_exposure",
                self.raw_hemoglobin_name,
                self.sum_exposure,
            ),
            (
                "hemoglobin_below_70_count",
                "below_70",
                self.hemoglobin_name,
                self.count_below_threshold,
            ),
        )
        self.sub_entities = {name: sub_entity for name, sub_entity, _, _ in observations}
        for name, _, pipeline, aggregator in observations:
            self.register_adding_observation(
                builder=builder,
                name=name,
                pop_filter="is_alive == True",
                when="time_step__prepare",
                requires_attributes=[pipeline],
                additional_stratifications=self.configuration.include,
                excluded_stratifications=self.configuration.exclude,
                aggregator=partial(aggregator, pipeline),
            )

    ###############
    # Aggregators #
    ###############

    def sum_exposure(self, pipeline: str, x: pd.DataFrame) -> float:
        return x[pipeline].sum()

    def count_below_threshold(self, pipeline: str, x: pd.DataFrame) -> float:
        return float((x[pipeline] < self.SEVERE_ANEMIA_THRESHOLD).sum())

    ##############################
    # Results formatting methods #
    ##############################

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("risk_factor", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("hemoglobin", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series(self.sub_entities[measure], index=results.index)


class IronFortificationObserver(PublicHealthObserver):
    """Vehicle consumption and iron fortification, summed over the pregnancy cohort."""

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        super().setup(builder)
        self.clock = builder.time.clock()
        self.start_date = get_time_stamp(builder.configuration.time.start)

    # noinspection PyAttributeOutsideInit
    def register_observations(self, builder: Builder) -> None:
        observations = (
            # (observation name, sub_entity, column, aggregator)
            (
                "any_vehicle_consumption_count",
                "any_vehicle_consumption",
                "vehicle_consumption_grams",
                self.count_positive_at_initialization,
            ),
            (
                "vehicle_consumption_grams_sum",
                "vehicle_consumption_grams",
                "vehicle_consumption_grams",
                self.sum_at_initialization,
            ),
            (
                "effective_iron_fortification_count",
                "effective_iron_fortification",
                "iron_fortification",
                self.count_positive_at_initialization,
            ),
            (
                "iron_consumption_from_fortification_mcg_sum",
                "iron_consumption_from_fortification_mcg",
                "iron_consumption_from_fortification_mcg",
                self.sum_at_initialization,
            ),
            (
                "baseline_2021_iron_consumption_from_fortification_mcg_sum",
                "baseline_2021_iron_consumption_from_fortification_mcg",
                "baseline_2021_iron_consumption_from_fortification_mcg",
                self.sum_at_initialization,
            ),
        )
        self.sub_entities = {name: sub_entity for name, sub_entity, _, _ in observations}
        for name, _, column, aggregator in observations:
            self.register_adding_observation(
                builder=builder,
                name=name,
                requires_attributes=[column],
                additional_stratifications=self.configuration.include,
                excluded_stratifications=self.configuration.exclude,
                aggregator=partial(aggregator, column),
            )

    ###############
    # Aggregators #
    ###############

    def sum_at_initialization(self, column: str, x: pd.DataFrame) -> float:
        if self.clock() != self.start_date:
            return 0.0
        return x[column].sum()

    def count_positive_at_initialization(self, column: str, x: pd.DataFrame) -> float:
        if self.clock() != self.start_date:
            return 0.0
        return float((x[column] > 0).sum())

    ##############################
    # Results formatting methods #
    ##############################

    def get_entity_type_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("intervention", index=results.index)

    def get_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series("iron_fortification", index=results.index)

    def get_sub_entity_column(self, measure: str, results: pd.DataFrame) -> pd.Series:
        return pd.Series(self.sub_entities[measure], index=results.index)


def aggregate_state_person_time(step_size, df: pd.DataFrame) -> float:
    return len(df) * to_years(step_size)


class BirthObserver(Observer):

    COL_MAPPING = {
        "entrance_time": "maternal_entrance_time",
        "age": "maternal_age",
        "sex_of_child": "sex",
        "birth_weight": "birth_weight",
        "gestational_age": "gestational_age",
        "pregnancy_outcome": "pregnancy_outcome",
        "baseline_2021_iron_consumption_from_fortification_mcg": "baseline_2021_iron_consumption_from_fortification_mcg",
        "iron_consumption_from_fortification_mcg": "iron_consumption_from_fortification_mcg",
        "wealth_quintile": "wealth_quintile",
    }

    def register_observations(self, builder: Builder) -> None:
        builder.results.register_concatenating_observation(
            name="births",
            pop_filter=(
                "("
                f"pregnancy_outcome == '{models.LIVE_BIRTH_OUTCOME}' "
                f"or pregnancy_outcome == '{models.STILLBIRTH_OUTCOME}'"
                ") "
                f"and previous_pregnancy == '{models.PREGNANT_STATE_NAME}' "
                f"and pregnancy == '{models.PARTURITION_STATE_NAME}'"
            ),
            requires_attributes=list(self.COL_MAPPING),
            results_formatter=self.format,
        )

    def format(self, measure: str, results: pd.DataFrame) -> pd.DataFrame:
        new_births = results[list(self.COL_MAPPING)].rename(columns=self.COL_MAPPING)
        new_births["birth_date"] = datetime(2024, 12, 30).strftime("%Y-%m-%d T%H:%M.%f")
        # new_births["joint_bmi_anemia_category"] = new_births["joint_bmi_anemia_category"].map(
        #     {
        #         "low_bmi_anemic": "cat1",
        #         "normal_bmi_anemic": "cat2",
        #         "low_bmi_non_anemic": "cat3",
        #         "normal_bmi_non_anemic": "cat4",
        #     }
        # )

        return new_births
