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
from vivarium.engine.framework.event import Event
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
        # LBWSGRisk._single_axis_ppf is not empty-index safe: empty Series.apply
        # keeps the string dtype, so it subtracts two empty string arrays.
        if index.empty:
            return pd.DataFrame(columns=AXES, dtype=float, index=index)
        if self.new_births is None:
            return super()._get_birth_exposure_source(index)
        return self.new_births.loc[index, AXES]


class LBWSGPAFCalculationRiskEffect(LBWSGRiskEffect):
    """Risk effect component for calculating PAFs for LBWSG.

    Notes
    -----
    This simulation is what produces the LBWSG PAF, so the artifact it runs against
    deliberately does not contain that key. The base class would otherwise try to load
    it, so the calibration constant comes from configuration instead
    (``lbwsg_paf_calibration.enn_paf_path``), and the PAF simulation runs twice
    (see ``data/run_lbwsg_paf_two_pass.py``):

    - **Pass 1** (``enn_paf_path`` empty): the calibration constant is zero, so the
      cohort dies at ``rate x RR`` with no ``(1 - PAF)`` deflation -- roughly
      ``E[RR]`` (about 7x) too much mortality. The early neonatal PAF it observes is
      still exact, because that observation happens on the first time step, before
      anyone has died. The late neonatal PAF it observes is garbage: the inflated
      early neonatal mortality over-depletes the high-RR categories, so the survivor
      weights are far too skewed toward the healthy categories.
    - **Pass 2** (``enn_paf_path`` set): the per-sex early neonatal PAF from pass 1
      deflates mortality to the level the main simulation will actually apply, so the
      late neonatal observation sees the true early-neonatal-survivor frame. Both age
      groups' PAFs are taken from this pass (its early neonatal value reproduces pass
      1 exactly, since mortality still hasn't acted when it is observed).

    The calibration file carries one PAF per sex, applied at every age: only mortality
    that precedes an observation can matter, and the last observation happens before
    any late neonatal death is drawn, so the value applied beyond early neonatal ages
    never affects output.

    The hook is ``get_calibration_constant_data``; the PAF was previously read through
    ``get_population_attributable_fraction_source``, which no longer exists.
    """

    @property
    def configuration_defaults(self) -> Dict[str, Any]:
        config = super().configuration_defaults
        config["lbwsg_paf_calibration"] = {"enn_paf_path": ""}
        return config

    def get_calibration_constant_data(self, builder: Builder) -> LookupTableData:
        path = builder.configuration.lbwsg_paf_calibration.enn_paf_path
        if not path:
            return 0.0
        paf = pd.read_parquet(path)
        expected = {"sex", "age_start", "age_end", "year_start", "year_end", "value"}
        if set(paf.columns) != expected:
            raise ValueError(
                f"Calibration PAF file '{path}' has columns {sorted(paf.columns)}; "
                f"expected exactly {sorted(expected)}. It should be the file "
                "run_lbwsg_paf_two_pass.py writes between its two passes."
            )
        return paf


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
    """Observe the LBWSG PAF of one birth cohort as it ages through the neonatal period.

    The simulation this runs in is a single cohort, initialized at birth and stepped
    once per neonatal age group, so the age group being observed is a property of the
    time step rather than of the simulant:

    - Early neonatal is the first time step. Nobody has died yet, so the exposure
      distribution is GBD's birth prevalence exactly.
    - Late neonatal is the second time step. The cohort has lived through early
      neonatal mortality, so the exposure distribution is birth prevalence depleted by
      the survival this simulation itself produced, per LBWSG category.

    ``results_updater`` keeps each age group's PAF from the time step the cohort spent
    in it. Neither the exposure nor the PAF is ever pooled over age or sex: the
    aggregator refuses to run on a stratum holding both sexes.
    """

    CONFIGURATION_DEFAULTS = {
        "stratification": {
            "lbwsg_paf": {
                "exclude": [],
                "include": [],
            }
        }
    }

    EARLY_NEONATAL = "early_neonatal"
    LATE_NEONATAL = "late_neonatal"

    def __init__(self, target: str):
        super().__init__()
        self.target = TargetString(target)

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder) -> None:
        self.birth_exposure = builder.data.load(data_keys.LBWSG.BIRTH_EXPOSURE)
        self.risk_effect = builder.components.get_component(
            f"risk_effect.low_birth_weight_and_short_gestation_on_{self.target}"
        )
        self.config = builder.configuration.stratification.lbwsg_paf
        self.pop_size = builder.configuration.population.population_size
        self.step_number = 1

        builder.results.register_stratified_observation(
            name=f"calculated_lbwsg_paf_on_{self.target}",
            pop_filter="is_alive == True",
            aggregator=self.calculate_paf,
            results_updater=self.results_updater,
            # Everything the aggregator reads, so that it reads it off the frame the
            # results system hands over rather than looking it up by index in the
            # state table. Sex is assigned by index parity here, so any index the
            # aggregator does not own resolves to a mix of sexes.
            requires_attributes=[
                "is_alive",
                "sex",
                "lbwsg_category",
                self.risk_effect.relative_risk_name,
            ],
            additional_stratifications=self.config.include,
            excluded_stratifications=self.config.exclude,
            # Before the population ages and before mortality, so the first step sees
            # the cohort at birth and the second sees the early neonatal survivors.
            when="time_step__prepare",
        )

    ########################
    # Event-driven methods #
    ########################

    def on_time_step_cleanup(self, event: Event) -> None:
        """Increment step number at the end of each time step."""
        self.step_number += 1

    ##################
    # Helper methods #
    ##################

    def results_updater(self, old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        if self.step_number == 1:  # early neonatal time step
            return new
        # Use the PAF from the first time step for early neonatal and from the second
        # for late neonatal -- the steps in which the cohort occupied each age group.
        return pd.concat(
            [
                old.query(f"age_group == '{self.EARLY_NEONATAL}'"),
                new.query(f"age_group == '{self.LATE_NEONATAL}'"),
            ],
        )

    def calculate_paf(self, x: pd.DataFrame) -> float:
        if x.empty:
            # A stratum with no simulants in it -- on any given time step the cohort
            # occupies one age group, so every other age group is handed over empty.
            # Zero is what the results system fills unobserved strata with anyway, and
            # results_updater keeps only the age group each step is for, so this value
            # is never read.
            return 0.0

        relative_risk = x[self.risk_effect.relative_risk_name].rename("relative_risk")
        lbwsg_category = x["lbwsg_category"]
        sexes = x["sex"].unique()
        if len(sexes) != 1:
            raise ValueError(
                f"Stratified data contains {sorted(sexes)}, but this observer "
                "(LBWSGPAFObserver) needs sex-stratified data. Check that 'sex' is "
                "among the simulation's stratifications."
            )
        sex = sexes[0]

        lbwsg_prevalence = self.birth_exposure.rename(
            {"parameter": "lbwsg_category", "value": "prevalence"}, axis=1
        )
        lbwsg_prevalence = lbwsg_prevalence.loc[lbwsg_prevalence["sex"] == sex]

        # Weight birth prevalence by the fraction of the category that is still alive.
        # That fraction is 1 on the first time step, because nobody has died yet, which
        # is what we want: early neonatal PAFs are calculated on the birth cohort.
        weights = calculate_mortality_weights(self, sex)
        lbwsg_prevalence = lbwsg_prevalence.merge(weights)
        lbwsg_prevalence["prevalence"] = (
            lbwsg_prevalence["prevalence"] * lbwsg_prevalence["proportion_alive"]
        )
        lbwsg_prevalence = lbwsg_prevalence.drop(columns=["proportion_alive"])

        mean_rrs = (
            pd.concat([lbwsg_category, relative_risk], axis=1)
            .groupby("lbwsg_category", as_index=False)
            .mean()
        )
        mean_rrs = mean_rrs.merge(lbwsg_prevalence, on="lbwsg_category")

        mean_rr = np.average(mean_rrs["relative_risk"], weights=mean_rrs["prevalence"])
        paf = (mean_rr - 1) / mean_rr

        return paf


#####################
# Utility functions #
#####################


def calculate_mortality_weights(component: Component, sex: str) -> pd.DataFrame:
    """Calculate the fraction of each LBWSG category still alive, for one sex.

    The whole cohort is read, not just the simulants under observation, so the
    denominator is everyone born into the category.
    """
    full_index = pd.Index(range(component.pop_size))
    pop_data = component.population_view.get(
        full_index, ["lbwsg_category", "is_alive", "sex"], include_untracked=True
    )
    pop_data = pop_data.loc[pop_data["sex"] == sex]
    weights = (
        pop_data.groupby(["lbwsg_category", "sex"])["is_alive"]
        .agg(proportion_alive=lambda x: x.mean())
        .reset_index()
    )
    return weights
