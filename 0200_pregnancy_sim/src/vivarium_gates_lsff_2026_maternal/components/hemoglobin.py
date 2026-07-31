from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import scipy.stats
from vivarium.engine import Component
from vivarium.engine.framework.engine import Builder
from vivarium.engine.framework.event import Event
from vivarium.engine.framework.population import SimulantData
from vivarium.engine.framework.randomness import RESIDUAL_CHOICE
from vivarium_gates_lsff_2026_maternal.constants import data_keys, data_values, models
from vivarium_gates_lsff_2026_maternal.constants.data_values import (
    ANEMIA_DISABILITY_WEIGHTS,
    ANEMIA_THRESHOLD_DATA,
    HEMOGLOBIN_SCALE_FACTOR_MODERATE_HEMORRHAGE,
    HEMOGLOBIN_SCALE_FACTOR_SEVERE_HEMORRHAGE,
    RR_SCALAR,
    SEVERE_ANEMIA_AMONG_PREGNANT_WOMEN_THRESHOLD,
    TMREL_HEMOGLOBIN_ON_MATERNAL_DISORDERS,
)
from vivarium_gates_lsff_2026_maternal.utilities import get_lookup_columns

from lsff_utils import hemoglobin_distribution


class Hemoglobin(Component):
    """
    class for hemoglobin utilities and calculations that in turn will
    be used to find anemia status for simulants.
    """

    @property
    def configuration_defaults(self) -> Dict[str, Dict[str, Any]]:
        return {
            self.name: {
                "data_sources": {
                    "hemorrhage_relative_risk": data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN,
                    "hemorrhage_population_attributable_fraction": data_keys.MATERNAL_HEMORRHAGE.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN,
                    "maternal_disorders_relative_risk": data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN,
                    "maternal_disorders_population_attributable_fraction": data_keys.MATERNAL_DISORDERS.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN,
                }
            }
        }

    @property
    def columns_created(self) -> List[str]:
        return [
            "hemoglobin_distribution_propensity",
            "hemoglobin_percentile",
            "hemoglobin_scale_factor",
        ]

    # TODO MIC-4366: We include tracked here as a bandaid, given new RMS essentially requires
    # pipelines used in observation to return untracked simulants. Consider changing this!
    @property
    def columns_required(self) -> List[str]:
        return ["tracked", "alive", "maternal_hemorrhage"]

    # noinspection PyAttributeOutsideInit
    def setup(self, builder: Builder):
        self.randomness = builder.randomness.get_stream(self.name)

        index_columns = [
            "sex",
            "age_start",
            "age_end",
            "year_start",
            "year_end",
            "wealth_quintile",
        ]

        # load data
        mean = (
            builder.data.load(data_keys.HEMOGLOBIN.MEAN)
            .set_index(index_columns)["value"]
            .rename("mean")
        )
        stddev = (
            builder.data.load(data_keys.HEMOGLOBIN.STANDARD_DEVIATION)
            .set_index(index_columns)["value"]
            .rename("stddev")
        )
        # NOTE: I did not add this to the configurable lookup tables because
        # it is only used as the source for the pipeline.
        distribution_parameters = self.build_lookup_table(
            builder,
            "distribution_parameters",
            data_source=pd.concat([mean, stddev], axis=1).reset_index(),
            value_columns=["mean", "stddev"],
        )

        # Build configurable lookup tables
        self.maternal_disorders_relative_risk_table = self.build_lookup_table(
            builder, "maternal_disorders_relative_risk"
        )
        self.maternal_disorders_population_attributable_fraction_table = (
            self.build_lookup_table(
                builder, "maternal_disorders_population_attributable_fraction"
            )
        )
        self.hemorrhage_relative_risk_table = self.build_lookup_table(
            builder, "hemorrhage_relative_risk"
        )
        self.hemorrhage_population_attributable_fraction_table = self.build_lookup_table(
            builder, "hemorrhage_population_attributable_fraction"
        )

        self.moderate_hemorrhage_probability = builder.data.load(
            data_keys.MATERNAL_HEMORRHAGE.MODERATE_HEMORRHAGE_PROBABILITY
        ).value.values[0]

        self.distribution_parameters = builder.value.register_value_producer(
            "hemoglobin.exposure_parameters",
            source=distribution_parameters,
            required_resources=get_lookup_columns([distribution_parameters]),
        )

        # Fix resource dependency cycle
        self.raw_hemoglobin = builder.value.register_value_producer(
            "raw_hemoglobin.exposure",
            source=self.hemoglobin_source,
            required_resources=["hemoglobin.exposure_parameters"],
        )

        self.hemoglobin = builder.value.register_value_producer(
            "hemoglobin.exposure",
            source=self.raw_hemoglobin,
        )

        builder.value.register_value_modifier(
            "maternal_disorders.transition_proportion",
            self.adjust_maternal_disorder_proportion,
            required_resources=["hemoglobin.exposure"]
            + get_lookup_columns(
                [
                    self.maternal_disorders_population_attributable_fraction_table,
                    self.maternal_disorders_relative_risk_table,
                ]
            ),
        )
        builder.value.register_value_modifier(
            "maternal_hemorrhage.transition_proportion",
            self.adjust_maternal_hemorrhage_proportion,
            required_resources=["hemoglobin.exposure"]
            + get_lookup_columns(
                [
                    self.hemorrhage_population_attributable_fraction_table,
                    self.hemorrhage_relative_risk_table,
                ]
            ),
        )

        builder.value.register_value_modifier(
            "hemoglobin.exposure",
            self.adjust_hemoglobin_exposure,
            required_resources=["maternal_hemorrhage"],
        )

        builder.population.register_initializer(
            self.on_initialize_simulants,
            columns=self.columns_created,
            required_resources=[self.randomness],
        )

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        pop_update = pd.DataFrame(
            {
                "hemoglobin_distribution_propensity": self.randomness.get_draw(
                    pop_data.index, additional_key="hemoglobin_distribution_propensity"
                ),
                "hemoglobin_percentile": self.randomness.get_draw(
                    pop_data.index, additional_key="hemoglobin_percentile"
                ),
                "hemoglobin_scale_factor": self.randomness.choice(
                    pop_data.index,
                    choices=[
                        HEMOGLOBIN_SCALE_FACTOR_MODERATE_HEMORRHAGE,
                        HEMOGLOBIN_SCALE_FACTOR_SEVERE_HEMORRHAGE,
                    ],
                    p=[self.moderate_hemorrhage_probability, RESIDUAL_CHOICE],
                    additional_key="hemorrhage_scale_factors",
                ),
            },
            index=pop_data.index,
        )
        self.population_view.update(list(pop_update.columns), lambda _: pop_update)

    def hemoglobin_source(self, idx: pd.Index) -> pd.Series:
        if len(idx) == 0:
            return pd.Series(index=idx, dtype=float)
        pop = self.population_view.get(idx)
        distribution_parameters = self.distribution_parameters(pop.index)
        sampler = hemoglobin_distribution.hemoglobin_sampler_from_mean_sd(
            distribution_parameters["mean"],
            distribution_parameters["stddev"],
        )
        result = pd.Series(
            sampler(
                pop["hemoglobin_distribution_propensity"],
                pop["hemoglobin_percentile"],
            ),
            index=idx,
        )
        assert result.notnull().all()
        return result

    def adjust_maternal_disorder_proportion(
        self, index: pd.Index, maternal_disorder_probability: pd.DataFrame
    ) -> pd.Series:
        hemoglobin_level = self.hemoglobin(index)
        rr = self.maternal_disorders_relative_risk_table(index)
        ## annoyingly formatted
        paf = self.maternal_disorders_population_attributable_fraction_table(index)
        tmrel = TMREL_HEMOGLOBIN_ON_MATERNAL_DISORDERS
        per_simulant_exposure = (tmrel - hemoglobin_level).clip(lower=0) / RR_SCALAR
        per_simulant_rr = rr**per_simulant_exposure
        maternal_disorder_probability *= (1 - paf) * per_simulant_rr
        return maternal_disorder_probability.clip(upper=1)

    def adjust_maternal_hemorrhage_proportion(self, index, maternal_hemorrhage_probability):
        paf = self.hemorrhage_population_attributable_fraction_table(index)
        rr = self.hemorrhage_relative_risk_table(index)
        hemoglobin = self.hemoglobin(index)
        maternal_hemorrhage_probability *= 1 - paf
        # Dichotomous risk based on severe anemia
        maternal_hemorrhage_probability.loc[
            hemoglobin <= SEVERE_ANEMIA_AMONG_PREGNANT_WOMEN_THRESHOLD
        ] *= rr
        return maternal_hemorrhage_probability.clip(upper=1)

    def adjust_hemoglobin_exposure(
        self, index: pd.Index, hemoglobin_exposure: pd.DataFrame
    ) -> pd.DataFrame:
        pop = self.population_view.get(index)
        # We need to persist this value for both current and recovered maternal hemorrhage
        # We don't need to undo after postpartum, as simulants become untracked
        maternal_hemorrhage_mask = (pop["alive"] == "alive") & (
            pop["maternal_hemorrhage"] != "susceptible_to_maternal_hemorrhage"
        )
        hemoglobin_exposure.loc[maternal_hemorrhage_mask] *= pop.loc[
            maternal_hemorrhage_mask, "hemoglobin_scale_factor"
        ]
        return hemoglobin_exposure


class Anemia(Component):
    @property
    def columns_created(self):
        return ["anemia_status_at_birth"]

    # TODO MIC-4366: We include tracked here as a bandaid, given new RMS essentially requires
    # pipelines used in observation to return untracked simulants. Consider changing this!
    @property
    def columns_required(self) -> List[str]:
        return ["alive", "pregnancy", "tracked"]

    @property
    def time_step_priority(self) -> int:
        return 4

    def setup(self, builder: Builder):
        self.hemoglobin = builder.value.get_value("hemoglobin.exposure")

        self.anemia_thresholds_table = self.build_lookup_table(
            builder,
            "anemia_thresholds",
            data_source=ANEMIA_THRESHOLD_DATA,
            value_columns=["severe", "moderate", "mild"],
        )

        self.anemia_levels = builder.value.register_value_producer(
            "anemia_levels",
            source=self.anemia_source,
            required_resources=["hemoglobin.exposure"]
            + get_lookup_columns([self.anemia_thresholds_table]),
        )

        self.disability_weight = builder.value.register_value_producer(
            "anemia.disability_weight",
            source=self.compute_disability_weight,
            required_resources=["alive", "pregnancy"],
        )

        builder.value.register_value_modifier(
            "disability_weight",
            self.disability_weight,
        )

    def anemia_source(self, index: pd.Index) -> pd.Series:
        hemoglobin_level = self.hemoglobin(index)
        thresholds = self.anemia_thresholds_table(index)

        choice_index = (hemoglobin_level.values[np.newaxis].T < thresholds).sum(axis=1)

        return pd.Series(
            np.array(["not_anemic", "mild", "moderate", "severe"])[choice_index],
            index=index,
            name="anemia_levels",
        )

    def compute_disability_weight(self, index: pd.Index):
        anemia_levels = self.anemia_levels(index)
        raw_anemia_disability_weight = anemia_levels.map(ANEMIA_DISABILITY_WEIGHTS)
        dw_map = {
            models.NOT_PREGNANT_STATE_NAME: raw_anemia_disability_weight,
            models.PREGNANT_STATE_NAME: raw_anemia_disability_weight,
            ## Pause YLD accumulation during the parturition state
            models.PARTURITION_STATE_NAME: pd.Series(0, index=index),
            models.POSTPARTUM_STATE_NAME: raw_anemia_disability_weight,
        }

        pop = self.population_view.get(index)
        alive = pop["alive"] == "alive"
        disability_weight = pd.Series(np.nan, index=index)
        for state, dw in dw_map.items():
            in_state = alive & (pop["pregnancy"] == state)
            disability_weight[in_state] = dw.loc[in_state]

        return disability_weight

    def on_initialize_simulants(self, pop_data: SimulantData) -> None:
        self.population_view.update(
            "anemia_status_at_birth",
            lambda _: pd.Series(
                "invalid", index=pop_data.index, name="anemia_status_at_birth"
            ),
        )

    def on_time_step(self, event: Event):
        pop_update = self.population_view.get(
            event.index, query=("alive == 'alive' & pregnancy == 'parturition'")
        )
        self.population_view.update(
            "anemia_status_at_birth",
            lambda _: self.anemia_levels(pop_update.index).rename("anemia_status_at_birth"),
        )
