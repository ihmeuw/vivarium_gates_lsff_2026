from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import scipy.stats
from vivarium import Component
from vivarium.framework.engine import Builder
from vivarium.framework.population import SimulantData
from vivarium_public_health.utilities import get_lookup_columns

from vivarium_gates_lsff_by_wealth_quintile.constants import (
    data_keys,
    data_values,
    models,
)


class VehicleConsumption(Component):
    @property
    def columns_created(self) -> List[str]:
        return ["vehicle_consumption_grams"]

    @property
    def columns_required(self) -> List[str]:
        return ["tracked", "wealth_quintile"]
    
    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {"requires_streams": [self.name], "requires_columns": self.columns_required}
    
    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.randomness = builder.randomness.get_stream(self.name)

        index_columns = ["sex", "age_start", "age_end", "wealth_quintile"]
        any_consumed = builder.data.load(data_keys.VEHICLE_CONSUMPTION.ANY_CONSUMED).set_index(index_columns)["value"].rename("any_consumed")
        any_consumed = self.build_lookup_table(
            builder,
            any_consumed.reset_index(),
            value_columns=["any_consumed"],
        )
        self.any_consumed = builder.value.register_value_producer(
            "vehicle_consumption.any_consumed",
            source=any_consumed,
            requires_columns=get_lookup_columns([any_consumed]),
        )

        mean = (
            builder.data.load(data_keys.VEHICLE_CONSUMPTION.MEAN)
            .set_index(index_columns)["value"]
            .rename("mean")
        )
        stddev = (
            builder.data.load(data_keys.VEHICLE_CONSUMPTION.STANDARD_DEVIATION)
            .set_index(index_columns)["value"]
            .rename("stddev")
        )
        distribution_parameters = self.build_lookup_table(
            builder,
            pd.concat([mean, stddev], axis=1).reset_index(),
            value_columns=["mean", "stddev"],
        )

        self.distribution_parameters = builder.value.register_value_producer(
            "vehicle_consumption.exposure_parameters",
            source=distribution_parameters,
            requires_columns=get_lookup_columns([distribution_parameters]),
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            {"vehicle_consumption_grams": None},
            index=pop_data.index,
        )
        any_consumed_prob = self.any_consumed(pop_data.index)
        any_consumed = self.randomness.filter_for_probability(
            pop_data.index,
            probability=any_consumed_prob,
            additional_key="any_vehicle_consumed",
        )
        pop_update.loc[~pop_update.index.isin(any_consumed), "vehicle_consumption_grams"] = 0
        distribution_parameters = self.distribution_parameters(any_consumed)
        pop_update.loc[any_consumed, "vehicle_consumption_grams"] = self.randomness.sample_from_distribution(any_consumed, scipy.stats.norm(
            # Scaling up to account for the 0s introduced by ~any_consumed
            distribution_parameters["mean"] / any_consumed_prob.mean(),
            distribution_parameters.stddev / any_consumed_prob.mean(),
        )).clip(lower=0)

        self.population_view.update(pop_update)


class IronFortification(Component):
    CONFIGURATION_DEFAULTS = {
        "intervention": {
            "scenario": "baseline",
        }
    }

    @property
    def columns_created(self) -> List[str]:
        return ["baseline_iron_fortification", "iron_fortification", "baseline_iron_consumption_from_fortification_mcg", "iron_consumption_from_fortification_mcg"]

    @property
    def columns_required(self) -> List[str]:
        return ["tracked", "vehicle_consumption_grams", "wealth_quintile"]

    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {"requires_streams": [self.name], "requires_columns": self.columns_required}

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.randomness = builder.randomness.get_stream(self.name)

        index_columns = ["sex", "age_start", "age_end", "wealth_quintile"]
        baseline_coverage = builder.data.load(data_keys.IRON_FORTIFICATION.BASELINE_COVERAGE).set_index(index_columns)["value"].rename("baseline_coverage")
        baseline_coverage = self.build_lookup_table(
            builder,
            baseline_coverage.reset_index(),
            value_columns=["baseline_coverage"],
        )
        self.baseline_coverage = builder.value.register_value_producer(
            "iron_fortification.baseline_coverage",
            source=baseline_coverage,
            requires_columns=get_lookup_columns([baseline_coverage]),
        )
        self.hemoglobin_effect_size_per_mcg_intake = builder.data.load(data_keys.IRON_FORTIFICATION.HEMOGLOBIN_EFFECT_SIZE).value[
            0
        ]

        self.scenario = builder.configuration.intervention.scenario
        self.fortification_mcg_per_gram = data_values.IRON_FORTIFICATION_CONCENTRATION

        builder.value.register_value_modifier(
            "hemoglobin.exposure",
            self.update_hemoglobin_exposure,
            requires_columns=["vehicle_consumption_grams"],
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            index=pop_data.index,
        )

        pop_update["baseline_iron_fortification"] = False
        baseline_iron_fortified = self.randomness.filter_for_probability(
            pop_data.index,
            probability=self.baseline_coverage(pop_data.index),
            additional_key="baseline_iron_fortified"
        )
        pop_update.loc[baseline_iron_fortified, "baseline_iron_fortification"] = True

        vehicle_consumption = self.population_view.subview(["vehicle_consumption_grams"]).get(pop_data.index)["vehicle_consumption_grams"]

        pop_update["baseline_iron_consumption_from_fortification_mcg"] = self._calculate_iron_consumption(vehicle_consumption, pop_update.baseline_iron_fortification)

        coverage_among_baseline_uncovered = data_values.INTERVENTION_SCENARIO_COVERAGE_AMONG_BASELINE_UNCOVERED[self.scenario]

        pop_update["iron_fortification"] = pop_update["baseline_iron_fortification"]
        baseline_uncovered = pop_data.index[~pop_update.baseline_iron_fortification]

        additional_iron_fortified = self.randomness.filter_for_probability(
            baseline_uncovered,
            probability=coverage_among_baseline_uncovered,
            additional_key="iron_fortified",
        )
        pop_update.loc[additional_iron_fortified, "iron_fortification"] = True

        pop_update["iron_consumption_from_fortification_mcg"] = self._calculate_iron_consumption(vehicle_consumption, pop_update.iron_fortification)

        self.population_view.update(pop_update)


    def update_hemoglobin_exposure(self, index, exposure):
        pop = self.population_view.get(index)

        # Delete the baseline effects of fortification
        exposure -= (
            pop.baseline_iron_consumption_from_fortification_mcg * self.hemoglobin_effect_size_per_mcg_intake
        )
        exposure += (
            pop.iron_consumption_from_fortification_mcg * self.hemoglobin_effect_size_per_mcg_intake
        )

        return exposure

    def _calculate_iron_consumption(self, vehicle_consumption, iron_fortification):
        return iron_fortification.astype(int) * vehicle_consumption * self.fortification_mcg_per_gram
