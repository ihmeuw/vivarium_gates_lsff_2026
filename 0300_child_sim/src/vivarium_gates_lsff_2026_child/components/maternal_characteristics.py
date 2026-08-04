"""
Component for maternal supplementation and risk effects
"""

from typing import Callable, List, Optional, Union

import numpy as np
import pandas as pd
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.lookup import LookupTable
from vivarium.engine.framework.population import SimulantData
from vivarium.engine.framework.time import get_time_stamp
from vivarium.engine.framework.values import Pipeline
from vivarium.public_health.risks import RiskEffect

from vivarium_gates_lsff_2026_child.constants import data_keys, data_values
from vivarium_gates_lsff_2026_child.utilities import get_lookup_columns


class MaternalIronConsumptionFromFortification(Component):
    def __init__(self):
        super().__init__()

    # NOTE: Building the frame without dtypes registers these as 'object', which a
    # later batch's real values then cannot be coerced onto. See PopulationLineList.
    COLUMN_DTYPES = {
        "baseline_2021_maternal_iron_consumption_from_fortification_mcg": float,
        "maternal_iron_consumption_from_fortification_mcg": float,
    }

    @property
    def columns_created(self) -> List[str]:
        return list(self.COLUMN_DTYPES)

    #################
    # Setup methods #
    #################

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.start_time = get_time_stamp(builder.configuration.time.start)

        vehicle = builder.data.load(data_keys.IRON_FORTIFICATION.VEHICLE)

        self.birth_weight_effect_size_per_mg_intake = (
            builder.data.load(data_keys.IRON_FORTIFICATION.BIRTH_WEIGHT_EFFECT_SIZE)
            .set_index("vehicle_name")
            .value.loc[vehicle]
        )

        builder.value.register_value_modifier(
            "birth_weight.birth_exposure",
            self.update_birth_weight,
            required_resources=[
                "baseline_2021_maternal_iron_consumption_from_fortification_mcg",
                "maternal_iron_consumption_from_fortification_mcg",
            ],
        )

        builder.population.register_initializer(
            initializer=self.on_initialize_simulants,
            columns=self.columns_created,
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        """
        Initialize simulants from line list data. Population configuration
        contains a key "new_births" which is the line list data.
        """
        new_simulants = pd.DataFrame(
            {col: pd.Series(dtype=dtype) for col, dtype in self.COLUMN_DTYPES.items()},
            index=pop_data.index,
        )

        if pop_data.creation_time >= self.start_time:
            new_births = pop_data.user_data["new_births"]
            new_births.index = pop_data.index

            new_simulants["maternal_iron_consumption_from_fortification_mcg"] = new_births[
                "iron_consumption_from_fortification_mcg"
            ].copy()
            new_simulants[
                "baseline_2021_maternal_iron_consumption_from_fortification_mcg"
            ] = new_births["baseline_2021_iron_consumption_from_fortification_mcg"].copy()

        self.population_view.initialize(new_simulants)

    def update_birth_weight(self, index, exposure):
        pop = self.population_view.get(index, self.columns_created)

        # Delete the baseline effects of fortification baked into the GBD 2021 birthweight distribution
        exposure -= pop.baseline_2021_maternal_iron_consumption_from_fortification_mcg * (
            self.birth_weight_effect_size_per_mg_intake / 1_000
        )  # convert mg to mcg
        exposure += pop.maternal_iron_consumption_from_fortification_mcg * (
            self.birth_weight_effect_size_per_mg_intake / 1_000
        )

        return exposure


class WealthQuintile(Component):
    def __init__(self):
        super().__init__()

    # NOTE: An untyped frame registers this as 'object'; coercing that to int later
    # fails outright, since the placeholder nulls have no integer representation.
    COLUMN_DTYPES = {"wealth_quintile": int}

    @property
    def columns_created(self) -> List[str]:
        return list(self.COLUMN_DTYPES)

    #################
    # Setup methods #
    #################

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.start_time = get_time_stamp(builder.configuration.time.start)
        self.birth_weight_disparities_multiplier = self.build_lookup_table(
            builder,
            "birth_weight_wealth_disparities",
            data_source=builder.data.load(data_keys.LBWSG.BIRTH_WEIGHT_WEALTH_DISPARITIES),
            value_columns="value",
        )

        builder.value.register_value_modifier(
            "birth_weight.birth_exposure",
            self.update_birth_weight,
            required_resources=[
                "wealth_quintile",
            ],
        )

        builder.population.register_initializer(
            initializer=self.on_initialize_simulants,
            columns=self.columns_created,
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        """
        Initialize simulants from line list data. Population configuration
        contains a key "new_births" which is the line list data.
        """
        new_simulants = pd.DataFrame(
            {col: pd.Series(dtype=dtype) for col, dtype in self.COLUMN_DTYPES.items()},
            index=pop_data.index,
        )

        if pop_data.creation_time >= self.start_time:
            new_births = pop_data.user_data["new_births"]
            new_births.index = pop_data.index

            new_simulants["wealth_quintile"] = (
                new_births["wealth_quintile"].astype(int).copy()
            )

        self.population_view.initialize(new_simulants)

    def update_birth_weight(self, index, exposure):
        mean_exposure = exposure.mean()

        multipliers = self.birth_weight_disparities_multiplier(index)
        multipliers /= multipliers.mean()
        scaled = exposure * multipliers
        scale_down_factor = mean_exposure / scaled.mean()
        return scaled * scale_down_factor


# class AdditiveRiskEffect(RiskEffect):
#     def __init__(self, risk: str, target: str):
#         super().__init__(risk, target)
#         self.effect_pipeline_name = f"{self.risk.name}_on_{self.target.name}.effect"

#     #################
#     # Setup methods #
#     #################

#     # noinspection PyAttributeOutsideInit
#     def setup(self, builder: Builder) -> None:
#         super().setup(builder)
#         self.effect = self.get_effect_pipeline(builder)
#         self.excess_shift = self.get_excess_shift(builder)

#     def build_all_lookup_tables(self, builder: Builder) -> None:
#         # NOTE: I have overwritten this method since PAF and RR lookup tables do not
#         # get used in this class. This is to prevent us from having to configure a scalar for all
#         # AdditiveRiskEffect instances in this model
#         self.lookup_tables["relative_risk"] = self.build_lookup_table(builder, 1)
#         self.lookup_tables["population_attributable_fraction"] = self.build_lookup_table(
#             builder, 0
#         )
#         self.lookup_tables["excess_shift"] = self.get_excess_shift_lookup_table(builder)
#         self.lookup_tables["risk_specific_shift"] = self.get_risk_specific_shift_lookup_table(
#             builder
#         )

#     def get_effect_pipeline(self, builder: Builder) -> Pipeline:
#         return builder.value.register_value_producer(
#             self.effect_pipeline_name,
#             source=self.get_effect,
#             requires_values=[self.exposure_pipeline_name],
#         )

#     def get_excess_shift_lookup_table(self, builder: Builder) -> LookupTable:
#         excess_shift_data = builder.data.load(
#             f"{self.risk}.excess_shift",
#             affected_entity=self.target.name,
#             affected_measure=self.target.measure,
#         )
#         excess_shift_data, value_cols = self.process_categorical_data(
#             builder, excess_shift_data
#         )
#         return self.build_lookup_table(builder, excess_shift_data, value_cols)

#     def get_target_modifier(
#         self, builder: Builder
#     ) -> Callable[[pd.Index, pd.Series], pd.Series]:
#         def adjust_target(index: pd.Index, target: pd.Series) -> pd.Series:
#             affected_rates = target + self.effect(index)
#             return affected_rates

#         return adjust_target

#     def get_risk_specific_shift_lookup_table(self, builder: Builder) -> LookupTable:
#         risk_specific_shift_data = builder.data.load(
#             f"{self.risk}.risk_specific_shift",
#             affected_entity=self.target.name,
#             affected_measure=self.target.measure,
#         )
#         return self.build_lookup_table(builder, risk_specific_shift_data, ["value"])

#     def register_paf_modifier(self, builder: Builder) -> None:
#         pass

#     def get_excess_shift(self, builder: Builder) -> Union[LookupTable, Pipeline]:
#         return self.lookup_tables["excess_shift"]

#     ##################################
#     # Pipeline sources and modifiers #
#     ##################################

#     def get_effect(self, index: pd.Index) -> pd.Series:
#         index_columns = ["index", self.risk.name]
#         excess_shift = self.excess_shift(index)
#         exposure = self.exposure(index).reset_index()
#         exposure.columns = index_columns
#         exposure = exposure.set_index(index_columns)

#         relative_risk = excess_shift.stack().reset_index()
#         relative_risk.columns = index_columns + ["value"]
#         relative_risk = relative_risk.set_index(index_columns)

#         raw_effect = relative_risk.loc[exposure.index, "value"].droplevel(self.risk.name)

#         risk_specific_shift = self.lookup_tables["risk_specific_shift"](index)
#         effect = raw_effect - risk_specific_shift
#         return effect
