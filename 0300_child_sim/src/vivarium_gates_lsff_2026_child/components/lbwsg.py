"""
====================================
Low Birth Weight and Short Gestation
====================================

This is a module to subclass the LBWSG component in Vivrium Public Health to use its functionality but to do so on
simulants who are initialized from line list data.

"""

import itertools
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.lookup import LookupTable, LookupTableData
from vivarium.engine.framework.population import PopulationView, SimulantData
from vivarium.engine.framework.time import get_time_stamp
from vivarium.engine.framework.values import Pipeline
from vivarium.public_health.causal_factor.utilities import get_exposure_post_processor
from vivarium.public_health.risks.implementations.low_birth_weight_and_short_gestation import (
    AXES,
    BIRTH_WEIGHT,
    LBWSGRisk,
    LBWSGRiskEffect,
)
from vivarium.public_health.utilities import TargetString

from vivarium_gates_lsff_2026_child.constants import data_keys


class LBWSGLineList(LBWSGRisk):
    """
    Component to initialize low birthweight and short gestation data for simulants based on existing line list data.
    """

    LOW_BIRTH_WEIGHT_LIMIT = 2500  # grams

    @property
    def columns_created(self) -> List[str]:
        # NOTE: The exposure and propensity columns are registered by LBWSGRisk's own
        # initializers; these are the two extra columns this subclass adds.
        return [
            self.raw_gestational_age_exposure_column_name,
            self.birth_weight_status_column_name,
        ]

    def __init__(self):
        super().__init__()
        self.raw_gestational_age_exposure_column_name = "raw_gestational_age_exposure"
        self.birth_weight_status_column_name = "birth_weight_status"
        self.new_births = None

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder):
        super().setup(builder)
        self.start_time = get_time_stamp(builder.configuration.time.start)

        # Runs after LBWSGRisk.initialize_exposure, which is what populates the
        # exposure columns this initializer derives its values from.
        builder.population.register_initializer(
            initializer=self.initialize_line_list_columns,
            columns=self.columns_created,
            required_resources=[self.get_exposure_name(axis) for axis in AXES],
        )

    ########################
    # Event-driven methods #
    ########################

    # noinspection PyAttributeOutsideInit
    def initialize_exposure(self, pop_data: SimulantData) -> None:
        """Stash the line list records, then let the base class populate exposures.

        The base implementation reads the birth exposure pipeline, whose source this
        class overrides to return the line list values -- so the records have to be
        available before that call.
        """
        new_births = pop_data.user_data.get("new_births")
        if new_births is not None:
            new_births = new_births.copy()
            new_births.index = pop_data.index
        self.new_births = new_births
        super().initialize_exposure(pop_data)

    def initialize_line_list_columns(self, pop_data: SimulantData) -> None:
        """Add the raw gestational age and the derived birth weight status."""
        raw_gestational_age = pd.Series(
            np.nan, index=pop_data.index, name=self.raw_gestational_age_exposure_column_name
        )
        birth_weight_status = pd.Series(
            "", index=pop_data.index, name=self.birth_weight_status_column_name
        )

        if self.new_births is not None:
            raw_gestational_age = pd.Series(
                self.new_births["gestational_age"].to_numpy(),
                index=pop_data.index,
                name=self.raw_gestational_age_exposure_column_name,
            )
            birth_weight = self.population_view.get(
                pop_data.index, self.get_exposure_name(BIRTH_WEIGHT)
            )
            birth_weight_status = pd.Series(
                np.where(
                    birth_weight <= self.LOW_BIRTH_WEIGHT_LIMIT,
                    "low_birth_weight",
                    "adequate_birth_weight",
                ),
                index=pop_data.index,
                name=self.birth_weight_status_column_name,
            )

        self.population_view.initialize(
            pd.concat([raw_gestational_age, birth_weight_status], axis=1)
        )

    ##################################
    # Pipeline sources and modifiers #
    ##################################

    def _get_birth_exposure_source(self, index: pd.Index) -> pd.DataFrame:
        """Take birth exposures from the line list instead of sampling them.

        Falls back to the base implementation when there are no line list records,
        which is the case for the (empty) initial population.
        """
        if self.new_births is None:
            return super()._get_birth_exposure_source(index)
        return self.new_births.loc[index, AXES]


class LBWSGPAFCalculationRiskEffect(LBWSGRiskEffect):
    """Risk effect component for calculating PAFs for LBWSG.

    Notes
    -----
    This simulation is what produces the LBWSG PAF, so the artifact it runs against
    deliberately does not contain that key. The base class would otherwise try to load
    it, so the calibration constant is supplied as zero here instead.

    The hook is ``get_calibration_constant_data``; the PAF was previously read through
    ``get_population_attributable_fraction_source``, which no longer exists.
    """

    def get_calibration_constant_data(self, builder: Builder) -> LookupTableData:
        return 0.0


class LBWSGPAFCalculationExposure(LBWSGRisk):
    # NOTE: The exposure columns are registered by LBWSGRisk's own initializer; these
    # are the extra columns this subclass adds, and they must be created before
    # LBWSGRisk.initialize_exposure runs because the birth exposure source reads them.
    COLUMNS_CREATED = ["lbwsg_category", "age_bin"]

    def setup(self, builder: Builder) -> None:
        self.lbwsg_categories = builder.data.load(data_keys.LBWSG.CATEGORIES)
        self.age_bins = builder.data.load(data_keys.POPULATION.AGE_BINS)
        builder.population.register_initializer(
            initializer=self.initialize_category_assignments,
            columns=self.COLUMNS_CREATED,
            required_resources=["age", "sex"],
        )
        # Registered after the initializer above so that LBWSGRisk's exposure
        # initializer, which depends on those columns, is ordered behind it.
        super().setup(builder)

    ########################
    # Event-driven methods #
    ########################

    def initialize_category_assignments(self, pop_data: SimulantData) -> None:
        """Deterministically spread simulants across every LBWSG category."""
        pop = self.population_view.get(pop_data.index, ["age", "sex"])
        pop["age_bin"] = pd.cut(pop["age"], self.age_bins["age_start"])
        pop = pop.sort_values(["sex", "age"])

        lbwsg_categories = self.lbwsg_categories.keys()
        num_repeats, remainder = divmod(len(pop), 2 * len(lbwsg_categories))
        if remainder != 0:
            raise ValueError(
                "Population size should be multiple of double the number of LBWSG categories."
                f"Population size is {len(pop)}, but should be a multiple of "
                f"{2*len(lbwsg_categories)}."
            )

        assigned_categories = list(lbwsg_categories) * (2 * num_repeats)
        pop["lbwsg_category"] = assigned_categories
        self.population_view.initialize(pop[self.COLUMNS_CREATED])

    ##################################
    # Pipeline sources and modifiers #
    ##################################

    def _get_birth_exposure_source(self, index: pd.Index) -> pd.DataFrame:
        """Spread exposures evenly over each category's birth weight / GA interval.

        Notes
        -----
        The base class expects a single DataFrame carrying every axis, so both axes
        are filled in one pass here (the previous per-axis hook no longer exists).
        """
        pop = self.population_view.get(index, ["age_bin", "sex", "lbwsg_category"])
        lbwsg_categories = self.lbwsg_categories.keys()
        num_simulants_in_category = int(
            len(pop)
            / (len(lbwsg_categories) * pop["sex"].nunique() * pop["age_bin"].nunique())
        )
        num_points_in_interval = int(math.sqrt(num_simulants_in_category))

        exposure_values = pd.DataFrame(index=pop.index, columns=AXES, dtype=float)

        for age_bin, sex, cat in itertools.product(
            pop["age_bin"].unique(), pop["sex"].unique(), lbwsg_categories
        ):
            description = self.lbwsg_categories[cat]

            birthweight_endpoints = [
                float(val)
                for val in description.split(", [")[1].split(")")[0].split("]")[0].split(", ")
            ]
            birthweight_interval_values = np.linspace(
                birthweight_endpoints[0],
                birthweight_endpoints[1],
                num=num_points_in_interval + 2,
            )[1:-1]

            gestational_age_endpoints = [
                float(val)
                for val in description.split("- [")[1].split(")")[0].split("+")[0].split(", ")
            ]
            gestational_age_interval_values = np.linspace(
                gestational_age_endpoints[0],
                gestational_age_endpoints[1],
                num=num_points_in_interval + 2,
            )[1:-1]

            birthweight_points, gestational_age_points = np.meshgrid(
                birthweight_interval_values, gestational_age_interval_values
            )
            lbwsg_exposures = pd.DataFrame(
                {
                    "birth_weight": birthweight_points.flatten(),
                    "gestational_age": gestational_age_points.flatten(),
                }
            )

            subset_index = pop[
                (pop["lbwsg_category"] == cat)
                & (pop["age_bin"] == age_bin)
                & (pop["sex"] == sex)
            ].index
            exposure_values.loc[subset_index, AXES] = lbwsg_exposures[AXES].values

        return exposure_values


class LBWSGPAFObserver(Component):
    CONFIGURATION_DEFAULTS = {
        "stratification": {
            "lbwsg_paf": {
                "exclude": [],
                "include": [],
            }
        }
    }

    def __init__(self, target: str):
        super().__init__()
        self.target = TargetString(target)

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.lbwsg_exposure = builder.data.load(data_keys.LBWSG.EXPOSURE)
        self.risk_effect = builder.components.get_component(
            f"risk_effect.low_birth_weight_and_short_gestation_on_{self.target}"
        )
        self.config = builder.configuration.stratification.lbwsg_paf

        builder.results.register_adding_observation(
            name=f"calculated_lbwsg_paf_on_{self.target}",
            pop_filter="is_alive == True",
            aggregator=self.calculate_paf,
            requires_attributes=["is_alive"],
            additional_stratifications=self.config.include,
            excluded_stratifications=self.config.exclude,
            when="time_step__prepare",
        )

    def calculate_paf(self, x: pd.DataFrame) -> float:
        relative_risk = self.risk_effect.target_modifier(x.index, pd.Series(1, index=x.index))
        relative_risk.name = "relative_risk"
        lbwsg_category = self.population_view.get(x.index, "lbwsg_category")
        lbwsg_prevalence = self.lbwsg_exposure.rename(
            {"parameter": "lbwsg_category", "value": "prevalence"}, axis=1
        )
        lbwsg_prevalence = lbwsg_prevalence.groupby("lbwsg_category", as_index=False)[
            "prevalence"
        ].sum()

        mean_rrs = (
            pd.concat([lbwsg_category, relative_risk], axis=1)
            .groupby("lbwsg_category", as_index=False)
            .mean()
        )
        mean_rrs = mean_rrs.merge(lbwsg_prevalence, on="lbwsg_category")

        mean_rr = np.average(mean_rrs["relative_risk"], weights=mean_rrs["prevalence"])
        paf = (mean_rr - 1) / mean_rr

        return paf
