from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import scipy.stats
from vivarium import Component
from vivarium.framework.engine import Builder
from vivarium.framework.population import SimulantData
from vivarium.framework.randomness import RESIDUAL_CHOICE
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
        return ["tracked", "wealth_quintile", "sex", "age"]

    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {
            "requires_streams": [self.name],
            "requires_columns": self.columns_required,
        }

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.randomness = builder.randomness.get_stream(self.name)

        vehicle = builder.data.load(data_keys.VEHICLE.NAME)

        def drop_vehicle(df):
            if "vehicle_name" not in df.columns:
                return df
            assert vehicle in df.vehicle_name.values
            return df[df.vehicle_name == vehicle].drop(columns=["vehicle_name"])

        index_columns = ["wealth_quintile", "sex", "age_start", "age_end"]
        any_consumed = (
            drop_vehicle(builder.data.load(data_keys.VEHICLE_CONSUMPTION.ANY_CONSUMED))
            .set_index(index_columns)["value"]
            .rename("any_consumed")
        )
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
            drop_vehicle(builder.data.load(data_keys.VEHICLE_CONSUMPTION.MEAN))
            .set_index(index_columns)["value"]
            .rename("mean")
        )
        stddev = (
            drop_vehicle(
                builder.data.load(data_keys.VEHICLE_CONSUMPTION.STANDARD_DEVIATION)
            )
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
        pop_update.loc[
            ~pop_update.index.isin(any_consumed), "vehicle_consumption_grams"
        ] = 0
        # Consider the original distribution, described by mean and stddev, to be
        # not normal but a mixture of a normal distribution and a point mass at 0.
        # This is a mixture of Gaussians (M), for the degenerate case where one has mean = 0, variance = 0.
        distribution_parameters = self.distribution_parameters(any_consumed)
        # Mean of the mixture is just p_A * mean(A), so mean(A) = mean(M) / p_A
        nonzero_component_mean = (
            distribution_parameters["mean"] / any_consumed_prob.loc[any_consumed]
        )
        # Here is a formula for the variance of a Gaussian mixture: https://stats.stackexchange.com/a/16609 (see first comment)
        # Setting mean and variance of B to zero, we solve for A, and get:
        # var(A) = (var(M) / p_A) - mean(A)^2 * (1 - p_A)
        nonzero_component_variance = (
            (distribution_parameters.stddev**2) / any_consumed_prob.loc[any_consumed]
        ) - (nonzero_component_mean**2) * (1 - any_consumed_prob.loc[any_consumed])
        # NOTE: By clipping here, we are overshooting our target of how many people don't consume
        # any at all! It doesn't mess with the mean very much though.
        # We could improve this by using a non-negative distribution instead of normal.
        pop_update.loc[any_consumed, "vehicle_consumption_grams"] = (
            self.randomness.sample_from_distribution(
                any_consumed,
                scipy.stats.norm(
                    nonzero_component_mean,
                    np.sqrt(nonzero_component_variance),
                ),
            ).clip(lower=0)
        )

        self.population_view.update(pop_update)


class IronFortification(Component):
    CONFIGURATION_DEFAULTS = {
        "intervention": {
            "scenario": "baseline",
        }
    }

    @property
    def columns_created(self) -> List[str]:
        return [
            "baseline_iron_fortification",
            "iron_fortification",
            "baseline_iron_consumption_from_fortification_mcg",
            "iron_consumption_from_fortification_mcg",
        ]

    @property
    def columns_required(self) -> List[str]:
        return ["tracked", "vehicle_consumption_grams", "wealth_quintile", "sex", "age"]

    @property
    def initialization_requirements(self) -> Dict[str, List[str]]:
        return {
            "requires_streams": [self.name],
            "requires_columns": self.columns_required,
        }

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.randomness = builder.randomness.get_stream(self.name)

        vehicle = builder.data.load(data_keys.VEHICLE.NAME)

        def drop_vehicle(df):
            if "vehicle_name" not in df.columns:
                return df
            assert vehicle in df.vehicle_name.values
            return df[df.vehicle_name == vehicle].drop(columns=["vehicle_name"])

        self.baseline_any_coverage = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.IRON_FORTIFICATION.BASELINE_ANY_COVERAGE)
            ),
            value_columns=["value"],
        )

        self.baseline_full_coverage = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.IRON_FORTIFICATION.BASELINE_FULL_COVERAGE)
            ),
            value_columns=["value"],
        )

        mean = drop_vehicle(
            builder.data.load(
                data_keys.IRON_FORTIFICATION.BASELINE_PARTIAL_COVERAGE_AMOUNT_MEAN
            )
        )
        mean = mean.set_index([c for c in mean.columns if c != "value"])[
            "value"
        ].rename("mean")
        stddev = drop_vehicle(
            builder.data.load(
                data_keys.IRON_FORTIFICATION.BASELINE_PARTIAL_COVERAGE_AMOUNT_SD
            )
        )
        stddev = stddev.set_index([c for c in stddev.columns if c != "value"])[
            "value"
        ].rename("stddev")
        self.distribution_parameters = self.build_lookup_table(
            builder,
            pd.concat([mean, stddev], axis=1).reset_index(),
            value_columns=["mean", "stddev"],
        )

        self.intervention_coverage = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.IRON_FORTIFICATION.INTERVENTION_COVERAGE)
            ).assign(sex="Female"),
            value_columns=["value"],
        )

        self.scenario = builder.configuration.intervention.scenario

        self.baseline_effectiveness = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.IRON_FORTIFICATION.BASELINE_EFFECTIVENESS)
            ).assign(sex="Female"),
            value_columns=["value"],
        )

        if self.scenario == "intervention":
            effectiveness_key = data_keys.IRON_FORTIFICATION.INTERVENTION_EFFECTIVENESS
        else:
            effectiveness_key = data_keys.IRON_FORTIFICATION.BASELINE_EFFECTIVENESS

        self.effectiveness = self.build_lookup_table(
            builder,
            drop_vehicle(builder.data.load(effectiveness_key)).assign(sex="Female"),
            value_columns=["value"],
        )

        self.hemoglobin_effect_size_above_intake_threshold = (
            builder.data.load(data_keys.IRON_FORTIFICATION.HEMOGLOBIN_EFFECT_SIZE)
            .set_index("vehicle_name")
            .value.loc[vehicle]
        )

        self.baseline_fortification_mcg_per_gram = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.IRON_FORTIFICATION.BASELINE_CONCENTRATION)
            ).assign(sex="Female"),
            value_columns=["value"],
        )

        self.intervention_fortification_mcg_per_gram = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(
                    data_keys.IRON_FORTIFICATION.INTERVENTION_CONCENTRATION
                )
            ).assign(sex="Female"),
            value_columns=["value"],
        )

        self.fortifiability = self.build_lookup_table(
            builder,
            drop_vehicle(
                builder.data.load(data_keys.VEHICLE_CONSUMPTION.FORTIFIABILITY)
            ),
            value_columns=["value"],
        )

        builder.value.register_value_modifier(
            "hemoglobin.exposure",
            self.update_hemoglobin_exposure,
            requires_columns=["vehicle_consumption_grams"],
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            index=pop_data.index,
        )

        baseline_full_prob = self.baseline_full_coverage(pop_data.index)
        baseline_any_prob = (
            self.baseline_any_coverage(pop_data.index) - baseline_full_prob
        )

        baseline_fortification = self.randomness.choice(
            pop_data.index,
            choices=[
                1.0,
                -1.0,  # Sentinel for partial
                0.0,
            ],
            p=pd.concat(
                [
                    baseline_full_prob,
                    baseline_any_prob,
                    pd.Series(RESIDUAL_CHOICE, index=pop_data.index),
                ],
                axis=1,
            ),
            additional_key="baseline_fortification_status",
        )
        partial = pop_data.index[baseline_fortification == -1]
        # NOTE: We need these even for the non-partial, for calculating additional
        # coverage
        distribution_parameters = self.distribution_parameters(pop_data.index)
        if len(partial) > 0:
            baseline_fortification.loc[partial] = (
                self.randomness.sample_from_distribution(
                    partial,
                    scipy.stats.norm(
                        distribution_parameters.loc[partial]["mean"],
                        distribution_parameters.loc[partial].stddev,
                    ),
                ).clip(0, 1)
            )

        assert (baseline_fortification >= 0).all()

        pop_update["baseline_iron_fortification"] = baseline_fortification
        if self.scenario == "zero":
            pop_update["iron_fortification"] = 0
        elif self.scenario == "baseline":
            pop_update["iron_fortification"] = pop_update[
                "baseline_iron_fortification"
            ].copy()
        elif self.scenario == "intervention":
            pop_update["iron_fortification"] = pop_update[
                "baseline_iron_fortification"
            ].copy()

            # NOTE: There are multiple ways you could imagine this working with respect to
            # individual heterogeneity. The choice I have made here is that the intervention
            # would "max out" fortification for a subset of *simulants*.
            # I think this makes more sense in the Nigeria case.
            # In the India case it is less clear.
            current_coverage = (
                baseline_full_prob + baseline_any_prob * distribution_parameters["mean"]
            )

            target_coverage = self.intervention_coverage(
                pop_data.index
            ) * self.fortifiability(pop_data.index)
            additional_coverage = target_coverage - current_coverage
            assert (
                (additional_coverage >= 0) | np.isclose(additional_coverage, 0)
            ).all()
            additional_coverage = additional_coverage.clip(lower=0)

            intervention_covered = self.randomness.filter_for_probability(
                pop_data.index,
                # I am not sure I can clearly explain what this division represents.
                # However, I have checked that it results in coverages that match the target,
                # both overall and by quintile.
                probability=additional_coverage / (1 - current_coverage),
                additional_key="newly_covered",
            )

            pop_update.loc[intervention_covered, "iron_fortification"] = 1.0
        else:
            raise ValueError("Unknown scenario")

        # Not all coverage is effective
        ineffective_baseline = self.randomness.filter_for_probability(
            pop_data.index,
            probability=1 - self.baseline_effectiveness(pop_data.index),
            # NOTE: Same key as next
            additional_key="ineffective",
        )
        ineffective = self.randomness.filter_for_probability(
            pop_data.index,
            probability=1 - self.effectiveness(pop_data.index),
            additional_key="ineffective",
        )
        # NOTE: We assume ineffective means totally ineffective
        pop_update.loc[ineffective_baseline, "baseline_iron_fortification"] = 0.0
        pop_update.loc[ineffective, "iron_fortification"] = 0.0

        vehicle_consumption = self.population_view.subview(
            ["vehicle_consumption_grams"]
        ).get(pop_data.index)["vehicle_consumption_grams"]

        baseline_concentration_mcg_per_gram = self.baseline_fortification_mcg_per_gram(
            pop_data.index
        )

        pop_update["baseline_iron_consumption_from_fortification_mcg"] = (
            self._calculate_iron_consumption(
                vehicle_consumption,
                pop_update.baseline_iron_fortification,
                baseline_concentration_mcg_per_gram,
            )
        )

        if self.scenario == "zero":
            concentration_mcg_per_gram = 0
        elif self.scenario == "baseline":
            concentration_mcg_per_gram = baseline_concentration_mcg_per_gram
        elif self.scenario == "intervention":
            concentration_mcg_per_gram = self.intervention_fortification_mcg_per_gram(
                pop_data.index
            )

        pop_update["iron_consumption_from_fortification_mcg"] = (
            self._calculate_iron_consumption(
                vehicle_consumption,
                pop_update.iron_fortification,
                concentration_mcg_per_gram,
            )
        )

        self.population_view.update(pop_update)

    def update_hemoglobin_exposure(self, index, exposure):
        pop = self.population_view.get(index)

        baseline_benefit = pop.baseline_iron_consumption_from_fortification_mcg > 0

        # Delete the baseline effects of fortification
        exposure -= (
            baseline_benefit * self.hemoglobin_effect_size_above_intake_threshold
        )

        benefit = pop.iron_consumption_from_fortification_mcg > 0
        exposure += benefit * self.hemoglobin_effect_size_above_intake_threshold

        return exposure.clip(lower=0)

    def _calculate_iron_consumption(
        self, vehicle_consumption, fortification, concentration_mcg_per_gram
    ):
        return fortification * vehicle_consumption * concentration_mcg_per_gram
