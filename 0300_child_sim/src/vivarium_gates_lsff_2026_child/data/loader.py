"""Loads, standardizes and validates input data for the simulation.

Abstract the extract and transform pieces of the artifact ETL.
The intent here is to provide a uniform interface around this portion
of artifact creation. The value of this interface shows up when more
complicated data needs are part of the project. See the BEP project
for an example.

`BEP <https://github.com/ihmeuw/vivarium_gates_bep/blob/master/src/vivarium_gates_bep/data/loader.py>`_

.. admonition::

   No logging is done here. Logging is done in vivarium inputs itself and forwarded.
"""

import pickle
from pathlib import Path
from typing import Dict, List, Tuple, Union

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats
from scipy.interpolate import RectBivariateSpline, griddata
from vivarium.artifact import EntityKey
from vivarium.engine.framework.randomness import get_hash
from vivarium.gbd_mapping import Cause, RiskFactor, sequelae
from vivarium.public_health.utilities import TargetString
from vivarium_gbd_access import constants as gbd_constants
from vivarium_gbd_access import gbd
from vivarium_inputs import extract
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import interface
from vivarium_inputs import utilities as vi_utils
from vivarium_inputs import utility_data
from vivarium_inputs.globals import DEMOGRAPHIC_COLUMNS, DRAW_COLUMNS
from vivarium_inputs.mapping_extension import AlternativeRiskFactor

from vivarium_gates_lsff_2026_child.constants import data_keys, data_values, metadata, paths
from vivarium_gates_lsff_2026_child.constants.metadata import ARTIFACT_INDEX_COLUMNS
from vivarium_gates_lsff_2026_child.data import utilities
from vivarium_gates_lsff_2026_child.utilities import (
    get_lognorm_from_quantiles,
    get_random_variable_draws,
)

NATIONAL_LEVEL_DATA_KEYS = [
    data_keys.POPULATION.LOCATION,
    data_keys.POPULATION.STRUCTURE,
    data_keys.POPULATION.AGE_BINS,
    data_keys.POPULATION.DEMOGRAPHY,
    data_keys.POPULATION.TMRLE,
    data_keys.POPULATION.FERTILITY_DATA,
    # NOTE: Diarrhea is necessary for calculating LBWSG PAFs!
    data_keys.DIARRHEA.DURATION,
    data_keys.DIARRHEA.REMISSION_RATE,
    data_keys.DIARRHEA.RESTRICTIONS,
    # data_keys.MEASLES.RESTRICTIONS,
    # data_keys.LRI.DURATION,
    # data_keys.LRI.REMISSION_RATE,
    # data_keys.LRI.RESTRICTIONS,
    # data_keys.MALARIA.DURATION,
    # data_keys.MALARIA.REMISSION_RATE,
    # data_keys.MALARIA.RESTRICTIONS,
    # data_keys.WASTING.DISTRIBUTION,
    # data_keys.WASTING.ALT_DISTRIBUTION,
    # data_keys.WASTING.CATEGORIES,
    # data_keys.WASTING.RELATIVE_RISK,
    # data_keys.STUNTING.DISTRIBUTION,
    # data_keys.STUNTING.ALT_DISTRIBUTION,
    # data_keys.STUNTING.CATEGORIES,
    # data_keys.STUNTING.RELATIVE_RISK,
    # data_keys.UNDERWEIGHT.RELATIVE_RISK,
    # data_keys.UNDERWEIGHT.DISTRIBUTION,
    # data_keys.UNDERWEIGHT.CATEGORIES,
    # data_keys.PEM.RESTRICTIONS,
    # data_keys.MODERATE_PEM.RESTRICTIONS,
    # data_keys.SEVERE_PEM.RESTRICTIONS,
    data_keys.LBWSG.DISTRIBUTION,
    data_keys.LBWSG.CATEGORIES,
    data_keys.LBWSG.EXPOSURE,
    data_keys.LBWSG.RELATIVE_RISK,
    data_keys.LBWSG.RELATIVE_RISK_INTERPOLATOR,
    data_keys.LBWSG.PAF,
    data_keys.AFFECTED_UNMODELED_CAUSES.URI_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.OTITIS_MEDIA_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.MENINGITIS_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.ENCEPHALITIS_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_PRETERM_BIRTH_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_ENCEPHALOPATHY_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_SEPSIS_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_JAUNDICE_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.OTHER_NEONATAL_DISORDERS_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.SIDS_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.LRI_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.DIARRHEAL_DISEASES_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.MEASLES_CSMR,
    data_keys.AFFECTED_UNMODELED_CAUSES.MALARIA_CSMR,
    # data_keys.IFA_SUPPLEMENTATION.DISTRIBUTION,
    # data_keys.IFA_SUPPLEMENTATION.CATEGORIES,
    # data_keys.IFA_SUPPLEMENTATION.EXPOSURE,
    # data_keys.IFA_SUPPLEMENTATION.EXCESS_SHIFT,
    # data_keys.IFA_SUPPLEMENTATION.RISK_SPECIFIC_SHIFT,
    data_keys.IRON_FORTIFICATION.BIRTH_WEIGHT_EFFECT_SIZE,
]


def get_data(
    lookup_key: str,
    location: Union[str, List[int]],
    mean_draw: bool,
    fertility_data_path: str = None,
    vehicle: str = None,
    fetch_subnationals: bool = False,
) -> pd.DataFrame:
    """Retrieves data from an appropriate source.

    Parameters
    ----------
    lookup_key
        The key that will eventually get put in the artifact with
        the requested data.
    location
        The location to get data for.

    Returns
    -------
        The requested data.

    """
    if lookup_key == data_keys.POPULATION.FERTILITY_DATA:
        return load_fertility_data(fertility_data_path)
    elif lookup_key == data_keys.IRON_FORTIFICATION.VEHICLE:
        return vehicle

    mapping = {
        data_keys.POPULATION.LOCATION: load_population_location,
        data_keys.POPULATION.STRUCTURE: load_population_structure,
        data_keys.POPULATION.AGE_BINS: load_age_bins,
        data_keys.POPULATION.DEMOGRAPHY: load_demographic_dimensions,
        data_keys.POPULATION.TMRLE: load_theoretical_minimum_risk_life_expectancy,
        data_keys.POPULATION.ACMR: load_standard_data,
        data_keys.POPULATION.CRUDE_BIRTH_RATE: load_standard_data,
        data_keys.DIARRHEA.DURATION: load_duration,
        data_keys.DIARRHEA.PREVALENCE: load_prevalence_from_incidence_and_duration,
        data_keys.DIARRHEA.INCIDENCE_RATE: load_standard_data,
        data_keys.DIARRHEA.REMISSION_RATE: load_neonatal_deleted_remission_from_duration,
        data_keys.DIARRHEA.DISABILITY_WEIGHT: load_standard_data,
        data_keys.DIARRHEA.EMR: load_emr_from_csmr_and_prevalence,
        data_keys.DIARRHEA.CSMR: load_neonatal_deleted_csmr,
        data_keys.DIARRHEA.RESTRICTIONS: load_metadata,
        data_keys.DIARRHEA.BIRTH_PREVALENCE: load_post_neonatal_birth_prevalence,
        # data_keys.MEASLES.PREVALENCE: load_standard_data,
        # data_keys.MEASLES.INCIDENCE_RATE: load_standard_data,
        # data_keys.MEASLES.DISABILITY_WEIGHT: load_standard_data,
        # data_keys.MEASLES.EMR: load_standard_data,
        # data_keys.MEASLES.CSMR: load_standard_data,
        # data_keys.MEASLES.RESTRICTIONS: load_metadata,
        # data_keys.LRI.DURATION: load_duration,
        # data_keys.LRI.INCIDENCE_RATE: load_standard_data,
        # data_keys.LRI.PREVALENCE: load_prevalence_from_incidence_and_duration,
        # data_keys.LRI.REMISSION_RATE: load_neonatal_deleted_remission_from_duration,
        # data_keys.LRI.DISABILITY_WEIGHT: load_standard_data,
        # data_keys.LRI.EMR: load_emr_from_csmr_and_prevalence,
        # data_keys.LRI.CSMR: load_neonatal_deleted_csmr,
        # data_keys.LRI.RESTRICTIONS: load_metadata,
        # data_keys.MALARIA.DURATION: load_duration,
        # data_keys.MALARIA.PREVALENCE: load_prevalence_from_incidence_and_duration,
        # data_keys.MALARIA.INCIDENCE_RATE: load_standard_data,
        # data_keys.MALARIA.REMISSION_RATE: load_neonatal_deleted_malaria_remission_from_duration,
        # data_keys.MALARIA.DISABILITY_WEIGHT: load_standard_data,
        # data_keys.MALARIA.EMR: load_emr_from_csmr_and_prevalence,
        # data_keys.MALARIA.CSMR: load_neonatal_deleted_csmr,
        # data_keys.MALARIA.RESTRICTIONS: load_metadata,
        # data_keys.MALARIA.BIRTH_PREVALENCE: load_post_neonatal_birth_prevalence,
        # data_keys.WASTING.DISTRIBUTION: load_metadata,
        # data_keys.WASTING.ALT_DISTRIBUTION: load_metadata,
        # data_keys.WASTING.CATEGORIES: load_metadata,
        # data_keys.WASTING.EXPOSURE: load_gbd_2021_exposure,
        # data_keys.WASTING.RELATIVE_RISK: load_gbd_2021_rr,
        # data_keys.WASTING.PAF: load_categorical_paf,
        # data_keys.WASTING.TRANSITION_RATES: load_wasting_transition_rates,
        # data_keys.WASTING.BIRTH_PREVALENCE: load_wasting_birth_prevalence,
        # data_keys.STUNTING.DISTRIBUTION: load_metadata,
        # data_keys.STUNTING.ALT_DISTRIBUTION: load_metadata,
        # data_keys.STUNTING.CATEGORIES: load_metadata,
        # data_keys.STUNTING.EXPOSURE: load_standard_data,
        # data_keys.STUNTING.RELATIVE_RISK: load_gbd_2021_rr,
        # data_keys.STUNTING.PAF: load_categorical_paf,
        # data_keys.UNDERWEIGHT.DISTRIBUTION: load_metadata,
        # data_keys.UNDERWEIGHT.EXPOSURE: load_underweight_exposure,
        # data_keys.UNDERWEIGHT.CATEGORIES: load_metadata,
        # data_keys.UNDERWEIGHT.RELATIVE_RISK: load_gbd_2021_rr,
        # data_keys.CHILD_GROWTH_FAILURE.PAF: load_cgf_paf,
        # data_keys.PEM.EMR: load_pem_emr,
        # data_keys.PEM.CSMR: load_pem_csmr,
        # data_keys.PEM.RESTRICTIONS: load_pem_restrictions,
        # data_keys.MODERATE_PEM.DISABILITY_WEIGHT: load_pem_disability_weight,
        # data_keys.MODERATE_PEM.EMR: load_pem_emr,
        # data_keys.MODERATE_PEM.CSMR: load_pem_csmr,
        # data_keys.MODERATE_PEM.RESTRICTIONS: load_pem_restrictions,
        # data_keys.SEVERE_PEM.DISABILITY_WEIGHT: load_pem_disability_weight,
        # data_keys.SEVERE_PEM.EMR: load_pem_emr,
        # data_keys.SEVERE_PEM.CSMR: load_pem_csmr,
        # data_keys.SEVERE_PEM.RESTRICTIONS: load_pem_restrictions,
        data_keys.LBWSG.DISTRIBUTION: load_metadata,
        data_keys.LBWSG.CATEGORIES: load_metadata,
        data_keys.LBWSG.EXPOSURE: load_lbwsg_exposure,  ## Still 2019 age bins, but doesn't have effect past NN
        data_keys.LBWSG.RELATIVE_RISK: load_lbwsg_rr,  ## Still 2019 age bins, but doesn't have effect past NN
        data_keys.LBWSG.RELATIVE_RISK_INTERPOLATOR: load_lbwsg_interpolated_rr,  ## Still 2019 age bins, but doesn't have effect past NN
        data_keys.LBWSG.PAF: load_lbwsg_paf,  ## Still 2019 age bins, but doesn't have effect past NN
        data_keys.LBWSG.BIRTH_WEIGHT_WEALTH_DISPARITIES: load_birth_weight_wealth_disparities,
        data_keys.AFFECTED_UNMODELED_CAUSES.URI_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.OTITIS_MEDIA_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.MENINGITIS_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.ENCEPHALITIS_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_PRETERM_BIRTH_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_ENCEPHALOPATHY_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_SEPSIS_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_JAUNDICE_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.OTHER_NEONATAL_DISORDERS_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.SIDS_CSMR: load_sids_csmr,
        data_keys.AFFECTED_UNMODELED_CAUSES.LRI_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.DIARRHEAL_DISEASES_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.MEASLES_CSMR: load_standard_data,
        data_keys.AFFECTED_UNMODELED_CAUSES.MALARIA_CSMR: load_standard_data,
        # data_keys.IFA_SUPPLEMENTATION.DISTRIBUTION: load_intervention_distribution,
        # data_keys.IFA_SUPPLEMENTATION.CATEGORIES: load_intervention_categories,
        # data_keys.IFA_SUPPLEMENTATION.EXPOSURE: load_dichotomous_treatment_exposure,
        # data_keys.IFA_SUPPLEMENTATION.EXCESS_SHIFT: load_ifa_excess_shift,
        # data_keys.IFA_SUPPLEMENTATION.RISK_SPECIFIC_SHIFT: load_risk_specific_shift,
        data_keys.IRON_FORTIFICATION.BIRTH_WEIGHT_EFFECT_SIZE: load_iron_fortification_effect_on_birth_weight,
    }

    args = (lookup_key,)

    if lookup_key in NATIONAL_LEVEL_DATA_KEYS or not fetch_subnationals:
        args += (location,)
    else:
        subnational_ids = fetch_subnational_ids(location)
        args += (subnational_ids,)

    args += (mean_draw,)

    data = mapping[lookup_key](*args)
    if (
        mean_draw
        and isinstance(data, pd.DataFrame)
        and "draw_0" in data.columns
        and data["draw_0"].dtype == float
    ):
        data["mean_draw"] = data.filter(like="draw_").mean(axis=1)
        data = data.drop(columns=data.filter(like="draw_").columns)
        data = data.rename(columns={"mean_draw": "draw_0"})

    return data


def load_population_location(key: str, location: str, mean_draw: bool) -> str:
    if key != data_keys.POPULATION.LOCATION:
        raise ValueError(f"Unrecognized key {key}")

    return location


def load_population_structure(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    if location == "LMICs":
        world_bank_1 = filter_population(
            interface.get_population_structure("World Bank Low Income")
        )
        world_bank_2 = filter_population(
            interface.get_population_structure("World Bank Lower Middle Income")
        )
        population_structure = pd.concat([world_bank_1, world_bank_2])
    else:
        population_structure = filter_population(interface.get_population_structure(location))
    return population_structure


def filter_population(unfiltered: pd.DataFrame) -> pd.DataFrame:
    unfiltered = unfiltered.reset_index()
    filtered_pop = unfiltered[(unfiltered.age_end <= 5)]
    filtered_pop = filtered_pop.set_index(ARTIFACT_INDEX_COLUMNS)

    return filtered_pop


def load_age_bins(key: str, location: Union[str, List[int]], mean_draw: bool) -> pd.DataFrame:
    all_age_bins = interface.get_age_bins().reset_index()
    return (
        all_age_bins[all_age_bins.age_start < 5]
        .set_index(["age_start", "age_end", "age_group_name"])
        .sort_index()
    )


def load_demographic_dimensions(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    demographic_dimensions = interface.get_demographic_dimensions(location)
    is_under_five = demographic_dimensions.index.get_level_values("age_end") <= 5
    return demographic_dimensions[is_under_five]


def load_theoretical_minimum_risk_life_expectancy(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    return interface.get_theoretical_minimum_risk_life_expectancy()


def load_fertility_data(fertility_data_path: str) -> pd.DataFrame:
    """Load the maternal simulation's birth records.

    Accepts either results layout:

    - ``simulate run`` writes a single file, ``<run>/results/births.parquet``.
    - ``psimulate`` writes one file per task into a directory per metric,
      ``<run>/results/births/<task_id>.parquet``, and injects ``input_draw``,
      ``random_seed``, and ``scenario`` as columns. ``pd.read_parquet`` on the
      directory concatenates every file in it.

    A run root or a ``results`` directory is also accepted and resolved to the
    births data underneath it.

    The three job columns are backfilled when absent so that a single-run file still
    satisfies the filters ``FertilityLineList`` applies when reading this key back
    out of the artifact. Backfilled values pin the child model to draw 0 / seed 0 /
    baseline; use psimulate output to vary them.
    """
    if fertility_data_path is None:
        raise ValueError(
            "No fertility data path provided. The child model's population comes from "
            "the maternal simulation's birth records; pass --fertility-data-path "
            "pointing at a maternal run's 'births.parquet' or 'births/' directory."
        )

    path = _resolve_fertility_data_path(Path(fertility_data_path))
    df = pd.read_parquet(path)
    if df.empty:
        raise ValueError(f"Fertility data at '{path}' contains no birth records.")

    for column, default in (
        ("input_draw", 0),
        ("random_seed", 0),
        ("scenario", "baseline"),
    ):
        if column not in df.columns:
            logger.debug(f"Fertility data has no '{column}' column; using {default!r}.")
            df = df.assign(**{column: default})

    df = df.set_index(list(df.columns))
    return df


def _resolve_fertility_data_path(path: Path) -> Path:
    """Resolve a user-supplied path to the births data itself.

    Tolerates being handed a run root or a ``results`` directory rather than the
    births file/directory, since which of those is convenient depends on whether the
    upstream run came from ``simulate run`` or ``psimulate``.
    """
    if not path.exists():
        raise FileNotFoundError(f"Fertility data path does not exist: '{path}'.")

    if path.is_file():
        return path

    name = paths.FERTILITY_DATA_NAME
    # A metric directory of per-task parquet files.
    if any(path.glob("*.parquet")):
        return path
    # A run root or a results directory sitting above the births data.
    for candidate in (
        path / name,
        path / f"{name}.parquet",
        path / "results" / name,
        path / "results" / f"{name}.parquet",
    ):
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not find '{name}' data under '{path}'. Expected either "
        f"'{name}.parquet' or a '{name}/' directory of parquet files."
    )


def load_standard_data(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    key = EntityKey(key)
    entity = utilities.get_entity(key)

    use_2019_data_keys = [
        # data_keys.MEASLES.PREVALENCE,
        # data_keys.MEASLES.INCIDENCE_RATE,
        # data_keys.MEASLES.DISABILITY_WEIGHT,
        # data_keys.MEASLES.EMR,
        # data_keys.MEASLES.CSMR,
        # data_keys.LRI.CSMR,
    ]

    neonatal_deleted_keys = [
        # data_keys.DIARRHEA.INCIDENCE_RATE,
        # data_keys.DIARRHEA.DISABILITY_WEIGHT,
        # data_keys.MALARIA.INCIDENCE_RATE,
        # data_keys.MALARIA.DISABILITY_WEIGHT,
    ]

    both_2019_and_neonatal_deleted = [
        # data_keys.LRI.INCIDENCE_RATE,
        # data_keys.LRI.DISABILITY_WEIGHT,
    ]

    no_age = [
        data_keys.POPULATION.CRUDE_BIRTH_RATE,
    ]

    if key in use_2019_data_keys:
        data = interface.get_measure(entity, key.measure, location, 2019)
        data = data.query("year_start == 2019")

    elif key in neonatal_deleted_keys:
        data = interface.get_measure(entity, key.measure, location, metadata.GBD_EXTRACT_YEAR)
        data.loc[data.reset_index()["age_start"] < metadata.NEONATAL_END_AGE, :] = 0

    elif key in both_2019_and_neonatal_deleted:
        data = interface.get_measure(entity, key.measure, location, 2019)
        data = data.query("year_start == 2019")
        data.loc[data.reset_index()["age_start"] < metadata.NEONATAL_END_AGE, :] = 0

    else:
        data = interface.get_measure(entity, key.measure, location, metadata.GBD_EXTRACT_YEAR)

    if key not in no_age:
        data = data.query("age_start < 5")

    return data


def load_metadata(key: str, location: Union[str, List[int]], mean_draw: bool):
    key = EntityKey(key)
    entity = utilities.get_entity(key)
    entity_metadata = entity[key.measure]
    if hasattr(entity_metadata, "to_dict"):
        entity_metadata = entity_metadata.to_dict()
    if False:  # key == data_keys.WASTING.CATEGORIES:
        entity_metadata["cat2"] = "Wasting Between -3 SD and -2.5 SD (post-ensemble)"
        entity_metadata["cat2.5"] = "Wasting Between -2.5 SD and -2 SD (post-ensemble)"
    return entity_metadata


def load_categorical_paf(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    try:
        risk = {
            data_keys.WASTING.PAF: data_keys.WASTING,
            data_keys.STUNTING.PAF: data_keys.STUNTING,
            data_keys.SAM_TREATMENT.PAF: data_keys.SAM_TREATMENT,
            data_keys.MAM_TREATMENT.PAF: data_keys.MAM_TREATMENT,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    distribution_type = get_data(risk.DISTRIBUTION, location)

    if distribution_type != "dichotomous" and "polytomous" not in distribution_type:
        raise NotImplementedError(
            f"Unrecognized distribution {distribution_type} for {risk.name}. Only dichotomous and "
            f"polytomous are recognized categorical distributions."
        )

    exp = get_data(risk.EXPOSURE, location, mean_draw)

    subnational = isinstance(location, list)
    if (key == data_keys.STUNTING.PAF or key == data_keys.WASTING.PAF) and subnational:
        national_location_id = get_national_location_id(location[0])
        rr = get_data(risk.RELATIVE_RISK, national_location_id, mean_draw)
        location_names = exp.reset_index().location.unique()
        index_names = rr.index.names
        rr = rr.reset_index().drop(columns=["location"])
        rr = expand_data(rr, "location", location_names).set_index(index_names)
    else:
        rr = get_data(risk.RELATIVE_RISK, location, mean_draw)

    # paf = (sum_categories(exp * rr) - 1) / sum_categories(exp * rr)
    sum_exp_x_rr = (
        (exp * rr)
        .groupby(list(set(rr.index.names) - {"parameter"}))
        .sum()
        .reset_index()
        .set_index(rr.index.names[:-1])
    )
    paf = (sum_exp_x_rr - 1) / sum_exp_x_rr

    if key == data_keys.SAM_TREATMENT.PAF or key == data_keys.MAM_TREATMENT.PAF:
        paf.loc[paf.query("age_start < .5").index] = 0

    return paf


def load_wasting_transition_rates(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    """Read in wasting transition rates from flat file and expand to include all years."""
    national_location_id = (
        get_national_location_id(location[0])
        if isinstance(location, list)
        else utility_data.get_location_id(location)
    )
    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, national_location_id, mean_draw)
    rates = pd.read_csv(paths.WASTING_TRANSITIONS_DATA_DIR / f"{national_location_id}.csv")
    rates = rates.rename({"parameter": "transition"}, axis=1)

    # explicitly add the youngest ages data with values of 0
    min_age = rates.reset_index()["age_start"].min()
    demography = demography.query("age_start < @min_age")
    youngest_ages_data = pd.DataFrame(
        0,
        columns=pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        index=demography.index,
    )
    # add all transitions
    transitions = rates.reset_index()["transition"].unique()
    youngest_ages_data = expand_data(youngest_ages_data, "transition", transitions)

    rates["year_start"] = 2021
    rates["year_end"] = 2022
    rates = rates[youngest_ages_data.columns]
    rates = pd.concat([youngest_ages_data, rates])

    # update rate transitions into MAM to substates

    # update incidence transition names
    incidence_rates = rates.query("transition == 'inc_rate_mam'").copy()
    worse_mam_incidence_rates = incidence_rates.replace(
        {"transition": {"inc_rate_mam": "inc_rate_worse_mam"}}
    )
    rates = rates.replace({"transition": {"inc_rate_mam": "inc_rate_better_mam"}})
    rates = pd.concat([rates, worse_mam_incidence_rates])
    # update incidence transition values
    rates = rates.set_index(metadata.ARTIFACT_INDEX_COLUMNS + ["transition"]).sort_index()
    worse_mam_idx = rates.query("transition == 'inc_rate_worse_mam'").index
    better_mam_idx = rates.query("transition == 'inc_rate_better_mam'").index
    rates.loc[worse_mam_idx] = (
        rates.loc[worse_mam_idx] * data_values.WASTING.PROBABILITY_OF_CAT2
    )
    rates.loc[better_mam_idx] = rates.loc[better_mam_idx] * (
        1 - data_values.WASTING.PROBABILITY_OF_CAT2
    )

    # update remission transition names
    rates = rates.reset_index()
    remission_rates = rates.query("transition == 'ux_rem_rate_sam'").copy()
    worse_mam_remission_rates = remission_rates.replace(
        {"transition": {"ux_rem_rate_sam": "sam_to_worse_mam"}}
    )
    rates = rates.replace({"transition": {"ux_rem_rate_sam": "sam_to_better_mam"}})
    rates = pd.concat([rates, worse_mam_remission_rates])
    # update incidence transition values
    rates = rates.set_index(metadata.ARTIFACT_INDEX_COLUMNS + ["transition"]).sort_index()
    worse_mam_idx = rates.query("transition == 'sam_to_worse_mam'").index
    better_mam_idx = rates.query("transition == 'sam_to_better_mam'").index
    rates.loc[worse_mam_idx] = (
        rates.loc[worse_mam_idx] * data_values.WASTING.PROBABILITY_OF_CAT2
    )
    rates.loc[better_mam_idx] = rates.loc[better_mam_idx] * (
        1 - data_values.WASTING.PROBABILITY_OF_CAT2
    )

    return rates


def expand_data(data: pd.DataFrame, column_name: str, column_values: List) -> pd.DataFrame:
    """Equivalent to: For each column value, create a copy of data with a new column with this value. Concat these copies.
    Note: This transformation will reset the index of your data."""
    data = data.reset_index()
    if "index" in data.columns:
        data = data.drop("index", axis=1)
    new_values = pd.DataFrame({column_name: column_values}).set_index(
        pd.Index([1] * len(column_values))
    )
    data = data.set_index(pd.Index([1] * len(data))).join(new_values)
    return data


def load_wasting_birth_prevalence(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    ## Returns something subnational
    wasting_prevalence = (
        get_data(data_keys.WASTING.EXPOSURE, location, mean_draw)
        .query("age_end == 0.5")
        .droplevel(["age_start", "age_end"])
    )

    # Returns something national
    # read and process prevalence of low birth weight amongst infants who survive to 30 days
    national_location_id = (
        get_national_location_id(location[0])
        if isinstance(location, list)
        else utility_data.get_location_id(location)
    )
    lbwsg_exposure = get_data(data_keys.LBWSG.EXPOSURE, national_location_id, mean_draw)

    # Convert the LBWSG into subnational so I can use it with the wasting prevalence data
    location_names = wasting_prevalence.reset_index().location.unique()
    index_names = lbwsg_exposure.index.names
    lbwsg_exposure = lbwsg_exposure.reset_index().drop(columns=["location"])
    lbwsg_exposure = expand_data(lbwsg_exposure, "location", location_names).set_index(
        index_names
    )

    # use data from 1 to 5 month age group and sum all low birth weight category prevalences
    lbwsg_exposure = lbwsg_exposure.query(
        "parameter in @data_values.LBWSG.LOW_BIRTH_WEIGHT_CATEGORIES & age_start==0.01917808"
    )
    lbw_prevalence = lbwsg_exposure.groupby(metadata.ARTIFACT_INDEX_COLUMNS).sum()
    lbw_prevalence = lbw_prevalence.droplevel(
        ["age_start", "age_end", "year_start", "year_end"]
    )

    # calculate prevalences
    prev_cat1 = wasting_prevalence.query("parameter=='cat1'")
    prev_cat3 = wasting_prevalence.query("parameter=='cat3'")
    prev_cat4 = wasting_prevalence.query("parameter=='cat4'")
    # sum cat2 and cat2.5 for MAM
    prev_cat2 = wasting_prevalence.query("parameter=='cat2' or parameter=='cat2.5'")
    prev_cat2 = prev_cat2.groupby(["location", "sex", "year_start", "year_end"]).sum()
    prev_cat2["parameter"] = "cat2"
    prev_cat2 = prev_cat2.set_index(["parameter"], append=True)

    # relative risk of LBW on wasting
    relative_risk_draws = get_random_variable_draws(
        pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        *data_values.LBWSG.RR_ON_WASTING,
    )
    relative_risk = pd.DataFrame(
        [relative_risk_draws],
        columns=pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        index=lbw_prevalence.index,
    )

    adequate_birth_weight_cat1_probability = prev_cat1 / (
        (relative_risk * lbw_prevalence) + (1 - lbw_prevalence)
    )
    adequate_birth_weight_cat2_probability = prev_cat2 / (
        (relative_risk * lbw_prevalence) + (1 - lbw_prevalence)
    )
    adequate_birth_weight_cat3_probability = prev_cat3 + (
        (
            prev_cat1.droplevel("parameter")
            + prev_cat2.droplevel("parameter")
            - adequate_birth_weight_cat1_probability.droplevel("parameter")
            - adequate_birth_weight_cat2_probability.droplevel("parameter")
        )
        * prev_cat3
        / (prev_cat3 + prev_cat4.droplevel("parameter"))
    )
    adequate_birth_weight_cat4_probability = prev_cat4 + (
        (
            prev_cat1.droplevel("parameter")
            + prev_cat2.droplevel("parameter")
            - adequate_birth_weight_cat1_probability.droplevel("parameter")
            - adequate_birth_weight_cat2_probability.droplevel("parameter")
        )
        * prev_cat4
        / (prev_cat3.droplevel("parameter") + prev_cat4)
    )

    low_birth_weight_cat1_probability = adequate_birth_weight_cat1_probability * relative_risk
    low_birth_weight_cat2_probability = adequate_birth_weight_cat2_probability * relative_risk
    low_birth_weight_cat3_probability = prev_cat3 + (
        (
            prev_cat1.droplevel("parameter")
            + prev_cat2.droplevel("parameter")
            - low_birth_weight_cat1_probability.droplevel("parameter")
            - low_birth_weight_cat2_probability.droplevel("parameter")
        )
        * prev_cat3
        / (prev_cat3 + prev_cat4.droplevel("parameter"))
    )
    low_birth_weight_cat4_probability = prev_cat4 + (
        (
            prev_cat1.droplevel("parameter")
            + prev_cat2.droplevel("parameter")
            - low_birth_weight_cat1_probability.droplevel("parameter")
            - low_birth_weight_cat2_probability.droplevel("parameter")
        )
        * prev_cat4
        / (prev_cat3.droplevel("parameter") + prev_cat4)
    )

    adequate_bw_prevalence = pd.concat(
        [
            adequate_birth_weight_cat1_probability,
            adequate_birth_weight_cat2_probability,
            adequate_birth_weight_cat3_probability,
            adequate_birth_weight_cat4_probability,
        ]
    )
    low_bw_prevalence = pd.concat(
        [
            low_birth_weight_cat1_probability,
            low_birth_weight_cat2_probability,
            low_birth_weight_cat3_probability,
            low_birth_weight_cat4_probability,
        ]
    )

    adequate_bw_prevalence["birth_weight_status"] = "adequate_birth_weight"
    low_bw_prevalence["birth_weight_status"] = "low_birth_weight"

    birth_prevalence = pd.concat([low_bw_prevalence, adequate_bw_prevalence])
    birth_prevalence = birth_prevalence.set_index(
        "birth_weight_status", append=True
    ).sort_index()

    # distribute probability of being initialized in MAM state
    # amongst worse MAM (cat2) and better MAM (cat2.5)
    cat2_rows = birth_prevalence.query("parameter=='cat2'").copy()
    # update cat2 rows
    birth_prevalence.loc[birth_prevalence.query("parameter=='cat2'").index] = (
        cat2_rows * data_values.WASTING.PROBABILITY_OF_CAT2
    )
    # create cat2.5 rows
    cat25_rows = cat2_rows * (1 - data_values.WASTING.PROBABILITY_OF_CAT2)
    cat25_rows = (
        cat25_rows.reset_index()
        .replace({"parameter": {"cat2": "cat2.5"}})
        .set_index(birth_prevalence.index.names)
    )

    birth_prevalence = pd.concat([birth_prevalence, cat25_rows]).sort_index()

    return birth_prevalence


def _load_em_from_meid(location, meid, measure):
    location_id = utility_data.get_location_id(location)
    data = gbd.get_modelable_entity_draws(
        me_id=meid,
        location_id=location_id,
        year_id=None,
        data_type="draws",
    )
    data = data[data.measure_id == vi_globals.MEASURES[measure]]
    data = vi_utils.normalize(data, fill_value=0)
    data = data.filter(vi_globals.DEMOGRAPHIC_COLUMNS + vi_globals.DRAW_COLUMNS)
    data = vi_utils.reshape(data)
    data = vi_utils.scrub_gbd_conventions(data, location)
    data = vi_utils.split_interval(data, interval_column="age", split_column_prefix="age")
    data = vi_utils.split_interval(data, interval_column="year", split_column_prefix="year")
    return vi_utils.sort_hierarchical_data(data)


def load_duration(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    """Get duration by sampling 1000 draws from the provided distributions
    and convert from days to years. The duration will be the same for each
    demographic group."""
    try:
        distribution = {
            data_keys.DIARRHEA.DURATION: data_values.DIARRHEA_DURATION,
            # data_keys.LRI.DURATION: data_values.LRI_DURATION,
            # data_keys.MALARIA.DURATION: data_values.MALARIA_DURATION,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, location, mean_draw)
    duration_draws = (
        get_random_variable_draws(
            pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
            *distribution,
        )
        / metadata.YEAR_DURATION
    )

    duration = pd.DataFrame(
        [duration_draws],
        columns=pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        index=demography.index,
    )

    # if key == data_keys.LRI.DURATION:
    #     duration = duration.reset_index()
    #     duration["year_start"] = 2019
    #     duration["year_end"] = 2020
    #     duration = duration.set_index(
    #         ["location", "sex", "age_start", "age_end", "year_start", "year_end"]
    #     )

    return duration


def load_prevalence_from_incidence_and_duration(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    try:
        cause = {
            data_keys.DIARRHEA.PREVALENCE: data_keys.DIARRHEA,
            # data_keys.LRI.PREVALENCE: data_keys.LRI,
            # data_keys.MALARIA.PREVALENCE: data_keys.MALARIA,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    incidence_rate = get_data(cause.INCIDENCE_RATE, location, mean_draw)
    duration = get_data(cause.DURATION, location, mean_draw)
    prevalence = incidence_rate * duration

    # get enn prevalence
    birth_prevalence = data_values.BIRTH_PREVALENCE_OF_ZERO
    enn_prevalence = prevalence.query("age_start == 0")
    enn_prevalence = (birth_prevalence + enn_prevalence) / 2
    all_other_prevalence = prevalence.query("age_start != 0.0")

    prevalence = pd.concat([enn_prevalence, all_other_prevalence]).sort_index()
    return prevalence


def load_neonatal_deleted_remission_from_duration(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    """Calculate remission rate from duration and zero out neonatal age group data."""
    try:
        cause = {
            data_keys.DIARRHEA.REMISSION_RATE: data_keys.DIARRHEA,
            # data_keys.LRI.REMISSION_RATE: data_keys.LRI,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")
    step_size = 4 / 365  # years
    duration = get_data(cause.DURATION, location, mean_draw)
    remission_rate = (-1 / step_size) * np.log(1 - step_size / duration)

    remission_rate.loc[
        remission_rate.index.get_level_values("age_start") < metadata.NEONATAL_END_AGE,
        :,
    ] = 0
    return remission_rate


def load_neonatal_deleted_malaria_remission_from_duration(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    """Return 1 / duration with zero'd out neonatal age groups."""
    try:
        cause = {
            data_keys.MALARIA.REMISSION_RATE: data_keys.MALARIA,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    duration = get_data(cause.DURATION, location, mean_draw)
    data = 1 / duration
    data.loc[data.reset_index()["age_start"] < metadata.NEONATAL_END_AGE, :] = 0

    return data


def load_emr_from_csmr_and_prevalence(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    try:
        cause = {
            data_keys.DIARRHEA.EMR: data_keys.DIARRHEA,
            # data_keys.LRI.EMR: data_keys.LRI,
            # data_keys.MALARIA.EMR: data_keys.MALARIA,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    csmr = get_data(cause.CSMR, location, mean_draw)
    prevalence = get_data(cause.PREVALENCE, location, mean_draw)
    data = (csmr / prevalence).fillna(0)
    data = data.replace([np.inf, -np.inf], 0)

    if key == data_keys.DIARRHEA.EMR:
        data.loc[data.index.get_level_values("age_start") < metadata.NEONATAL_END_AGE, :] = 0
    return data


def load_neonatal_deleted_csmr(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    """Get GBD 2019 CSMR data with 2021 age groups and zero out neonatal age groups."""
    allowed_keys = [data_keys.DIARRHEA.CSMR, data_keys.LRI.CSMR, data_keys.MALARIA.CSMR]
    if key not in allowed_keys:
        raise ValueError(f"Unrecognized key {key}")

    data = load_standard_data(key, location, mean_draw)
    # data.loc[data.age_start < metadata.NEONATAL_END_AGE, :] = 0
    data.loc[data.reset_index()["age_start"] < metadata.NEONATAL_END_AGE, :] = 0
    return data


def load_post_neonatal_birth_prevalence(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    """Return post neonatal data (1 month to 6 months) as birth prevalence."""
    try:
        cause = {
            data_keys.DIARRHEA.BIRTH_PREVALENCE: data_keys.DIARRHEA,
            # data_keys.MALARIA.BIRTH_PREVALENCE: data_keys.MALARIA,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    prevalence = get_data(cause.PREVALENCE, location, mean_draw)
    is_post_neonatal = np.isclose(
        prevalence.reset_index()["age_start"], metadata.NEONATAL_END_AGE
    )
    post_neonatal_prevalence = prevalence[is_post_neonatal]
    data = post_neonatal_prevalence.droplevel(["age_start", "age_end"])

    return data


def load_underweight_exposure(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    """Read in exposure distribution data (conditional on stunting
    and wasting) from file and transform. This data looks like standard
    categorical exposure distribution data but with stunting and wasting
    parameter values in the index."""
    national_location_id = (
        get_national_location_id(location[0])
        if isinstance(location, list)
        else utility_data.get_location_id(location)
    )
    df = pd.read_csv(
        paths.UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR / f"{national_location_id}.csv"
    )
    # Fix sex values
    df = df.replace({"female": "Female", "male": "Male"})
    df = df.drop(["Unnamed: 0", "location_id"], axis=1)
    # add early neonatal data by copying late neonatal
    early_neonatal = df[df["age_group_name"] == "late_neonatal"].copy()
    early_neonatal["age_group_name"] = "early_neonatal"
    df = pd.concat([early_neonatal, df])

    # add age start and age end data instead of age group name
    age_bins = get_data(data_keys.POPULATION.AGE_BINS, location, mean_draw).reset_index()
    age_bins["age_group_name"] = age_bins["age_group_name"].str.lower().str.replace(" ", "_")
    age_start_map = dict(zip(age_bins["age_group_name"], age_bins["age_start"]))
    age_end_map = dict(zip(age_bins["age_group_name"], age_bins["age_end"]))
    df["age_start"] = df["age_group_name"].map(age_start_map)
    df["age_end"] = df["age_group_name"].map(age_end_map)
    df = df.drop("age_group_name", axis=1)

    df["year_start"] = 2021
    df["year_end"] = df["year_start"] + 1

    # define index
    df = df.rename({"underweight_parameter": "parameter"}, axis=1)
    df = df.set_index(
        metadata.ARTIFACT_INDEX_COLUMNS
        + ["stunting_parameter", "wasting_parameter", "parameter"]
    )

    # add wasting cat2.5 data by duplicating wasting cat2 data
    cat2_rows = df.query("wasting_parameter=='cat2'").copy()
    new_cat_rows = (
        cat2_rows.reset_index()
        .replace({"wasting_parameter": {"cat2": "cat2.5"}})
        .set_index(df.index.names)
    )
    df = pd.concat([df, new_cat_rows]).sort_index()
    index_names = df.index.names

    # create missing rows and fill with 0
    def cartesian_product(elements: Dict) -> pd.DataFrame:
        """Create DataFrame with cartesian product of dictionary values as index"""
        index = pd.MultiIndex.from_product(elements.values(), names=elements.keys())
        return pd.DataFrame(index=index).reset_index()

    age_bins = get_data(data_keys.POPULATION.AGE_BINS, location).reset_index()[
        ["age_start", "age_end"]
    ]
    index_elements = {
        "sex": ["Male", "Female"],
        "age_start": age_bins["age_start"],
        "year_start": list([2021]),
        "location": df.reset_index().location.unique(),
        "stunting_parameter": ["cat1", "cat2", "cat3", "cat4"],
        "wasting_parameter": ["cat1", "cat2", "cat2.5", "cat3", "cat4"],
        "parameter": ["cat1", "cat2", "cat3", "cat4"],
    }
    complete_index = cartesian_product(index_elements)
    complete_index = complete_index.merge(age_bins, on=["age_start"])
    complete_index["year_end"] = complete_index["year_start"] + 1
    df_index = df.reset_index()[
        metadata.ARTIFACT_INDEX_COLUMNS
        + ["stunting_parameter", "wasting_parameter", "parameter"]
    ]
    # Make columns be in the same order
    complete_index = complete_index[df_index.columns]
    merge_df = complete_index.merge(df_index, how="left", indicator=True)
    empty_missing_rows = merge_df.loc[merge_df["_merge"] == "left_only"].set_index(
        index_names
    )
    missing_rows = pd.DataFrame(
        0.0,
        columns=pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        index=empty_missing_rows.index,
    )
    df = pd.concat([df, missing_rows]).sort_index()
    return df.fillna(0)


def load_gbd_2021_exposure(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    # Get national location id to use national data probabilities
    entity_key = EntityKey(key)
    national_location_id = (
        get_national_location_id(location[0])
        if isinstance(location, list)
        else utility_data.get_location_id(location)
    )

    data = load_standard_data(key, location, mean_draw)
    location_names = data.reset_index().location.unique()

    if entity_key == data_keys.WASTING.EXPOSURE:
        # distribute probability of entering MAM state amongst worse MAM (cat2) and better MAM (cat2.5)
        cat2_rows = data.query("parameter=='cat2'").copy()
        # update cat2 rows
        data.loc[data.query("parameter=='cat2'").index] = (
            cat2_rows * data_values.WASTING.PROBABILITY_OF_CAT2
        )
        # create cat2.5 rows
        cat25_rows = cat2_rows * (1 - data_values.WASTING.PROBABILITY_OF_CAT2)
        cat25_rows = (
            cat25_rows.reset_index()
            .replace({"parameter": {"cat2": "cat2.5"}})
            .set_index(data.index.names)
        )

        data = pd.concat([data, cat25_rows]).sort_index()
    return data


def load_gbd_2021_rr(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    entity_key = EntityKey(key)
    entity = utilities.get_entity(entity_key)

    raw_data = load_standard_data(key, location, mean_draw)

    inc = raw_data.query('affected_measure == "incidence_rate"')
    csmr = raw_data.query('affected_measure == "cause_specific_mortality_rate"')
    emr = csmr.droplevel("affected_measure") / inc.droplevel("affected_measure")
    emr["affected_measure"] = "excess_mortality_rate"
    emr = emr.set_index("affected_measure", append=True).reorder_levels(inc.index.names)

    data = pd.concat([inc, emr])

    if key == data_keys.STUNTING.RELATIVE_RISK:
        # Remove neonatal relative risks
        neonatal_age_ends = data.index.get_level_values("age_end").unique().sort_values()[:2]
        data.loc[data.index.get_level_values("age_end").isin(neonatal_age_ends)] = 1.0
    if key == data_keys.WASTING.RELATIVE_RISK:
        # add wasting cat2.5 data by duplicating wasting cat2 data
        cat2_rows = data.query("parameter=='cat2'").copy()
        new_cat_rows = (
            cat2_rows.reset_index()
            .replace({"parameter": {"cat2": "cat2.5"}})
            .set_index(data.index.names)
        )
        data = pd.concat([data, new_cat_rows]).sort_index()
    return data


def load_cgf_paf(key: str, location: Union[str, List[int]], mean_draw: bool) -> pd.DataFrame:
    national_location_id = (
        get_national_location_id(location[0])
        if isinstance(location, list)
        else utility_data.get_location_id(location)
    )
    data = pd.read_csv(
        paths.CGF_PAFS / f"{national_location_id}.csv"
    )  # .query("location_id==@location_id")

    # add age start and age end data instead of age group name
    age_bins = get_data(data_keys.POPULATION.AGE_BINS, location, mean_draw).reset_index()
    age_bins["age_group_name"] = age_bins["age_group_name"].str.lower().str.replace(" ", "_")
    age_start_map = dict(zip(age_bins["age_group_name"], age_bins["age_start"]))
    age_end_map = dict(zip(age_bins["age_group_name"], age_bins["age_end"]))
    data["age_start"] = data["age_group_name"].map(age_start_map)
    data["age_end"] = data["age_group_name"].map(age_end_map)
    data = data.drop(["age_group_name", "location_id"], axis=1)
    data["year_start"] = 2021
    data["year_end"] = data["year_start"] + 1
    # Capitalize Sex
    data["sex"] = data["sex"].str.capitalize()

    # define index
    data = data.set_index(
        metadata.ARTIFACT_INDEX_COLUMNS + ["affected_entity", "affected_measure"]
    )
    data = data[pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS]
    return data.sort_index()


def load_pem_disability_weight(
    key: str, location: Union[str, List[int]], mean_draw: bool
) -> pd.DataFrame:
    try:
        pem_sequelae = {
            data_keys.MODERATE_PEM.DISABILITY_WEIGHT: [
                sequelae.moderate_wasting_with_edema,
                sequelae.moderate_wasting_without_edema,
            ],
            data_keys.SEVERE_PEM.DISABILITY_WEIGHT: [
                sequelae.severe_wasting_with_edema,
                sequelae.severe_wasting_without_edema,
            ],
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    prevalence_disability_weight = []
    state_prevalence = []
    for s in pem_sequelae:
        sequela_prevalence = interface.get_measure(
            s, "prevalence", location, metadata.GBD_EXTRACT_YEAR
        )
        sequela_disability_weight = interface.get_measure(
            s, "disability_weight", location, metadata.GBD_EXTRACT_YEAR
        )

        prevalence_disability_weight += [sequela_prevalence * sequela_disability_weight]
        state_prevalence += [sequela_prevalence]

    disability_weight = (sum(prevalence_disability_weight) / sum(state_prevalence)).fillna(0)
    return disability_weight


def load_pem_emr(key: str, location: Union[str, List[int]], mean_draw: bool) -> pd.DataFrame:
    emr = load_standard_data(data_keys.PEM.EMR, location, mean_draw)
    return emr


def load_pem_csmr(key: str, location: Union[str, List[int]], mean_draw: bool) -> pd.DataFrame:
    csmr = load_standard_data(data_keys.PEM.CSMR, location, mean_draw)
    return csmr


def load_pem_restrictions(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    metadata = load_metadata(data_keys.PEM.RESTRICTIONS, location, mean_draw)
    return metadata


#####################
# MAM/SAM Treatment #
#####################


# noinspection PyUnusedLocal
def load_wasting_treatment_distribution(key: str, location: str, mean_draw: bool) -> str:
    if key in [
        data_keys.SAM_TREATMENT.DISTRIBUTION,
        data_keys.MAM_TREATMENT.DISTRIBUTION,
    ]:
        return data_values.WASTING.DISTRIBUTION
    else:
        raise ValueError(f"Unrecognized key {key}")


# noinspection PyUnusedLocal
def load_wasting_treatment_categories(key: str, location: str, mean_draw: bool) -> str:
    if key in [data_keys.SAM_TREATMENT.CATEGORIES, data_keys.MAM_TREATMENT.CATEGORIES]:
        return data_values.WASTING.CATEGORIES
    else:
        raise ValueError(f"Unrecognized key {key}")


def load_wasting_treatment_exposure(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key == data_keys.SAM_TREATMENT.EXPOSURE:
        parameter = "c_sam"
    elif key == data_keys.MAM_TREATMENT.EXPOSURE:
        parameter = "c_mam"
    else:
        raise ValueError(f"Unrecognized key {key}")

    treatment_coverage = utilities.get_wasting_treatment_parameter_data(parameter, location)

    idx = get_data(data_keys.POPULATION.DEMOGRAPHY, location, mean_draw).index
    cat3 = pd.DataFrame(
        {f"draw_{i}": 0.0 for i in range(0, 1 if mean_draw else metadata.DRAW_COUNT)},
        index=idx,
    )
    cat2 = (
        pd.DataFrame(
            {f"draw_{i}": 1.0 for i in range(0, 1 if mean_draw else metadata.DRAW_COUNT)},
            index=idx,
        )
        * treatment_coverage
    )
    cat1 = 1 - cat2

    cat1["parameter"] = "cat1"
    cat2["parameter"] = "cat2"
    cat3["parameter"] = "cat3"

    exposure = pd.concat([cat1, cat2, cat3]).set_index("parameter", append=True).sort_index()

    # infants under 6 months of age should not receive treatment
    under_6_months_unexposed_idx = exposure.query("age_start < .5 & parameter=='cat1'").index
    under_6_months_exposed_idx = exposure.query("age_start < .5 & parameter!='cat1'").index
    exposure.loc[under_6_months_unexposed_idx] = 1
    exposure.loc[under_6_months_exposed_idx] = 0
    exposure = exposure[pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS]

    return exposure


def load_sam_treatment_rr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    # tmrel is defined as baseline treatment (cat_2)
    if key != data_keys.SAM_TREATMENT.RELATIVE_RISK:
        raise ValueError(f"Unrecognized key {key}")

    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, location, mean_draw).reset_index()
    sam_tx_efficacy, sam_tx_efficacy_tmrel = utilities.get_treatment_efficacy(
        demography, data_keys.WASTING.CAT1, location
    )

    # rr_t1 = t1 / t1_tmrel
    #       = (sam_tx_efficacy / sam_tx_duration) / (sam_tx_efficacy_tmrel / sam_tx_duration)
    #       = sam_tx_efficacy / sam_tx_efficacy_tmrel
    rr_sam_treated_remission = sam_tx_efficacy / sam_tx_efficacy_tmrel
    rr_sam_treated_remission[
        "affected_entity"
    ] = "severe_acute_malnutrition_to_mild_child_wasting"

    # rr_r2 = r2 / r2_tmrel
    #       = (1 - sam_tx_efficacy) * (r2_ux) / (1 - sam_tx_efficacy_tmrel) * (r2_ux)
    #       = (1 - sam_tx_efficacy) / (1 - sam_tx_efficacy_tmrel)
    rr_sam_untreated_remission = (1 - sam_tx_efficacy) / (1 - sam_tx_efficacy_tmrel)

    better_mam_rows = rr_sam_untreated_remission.copy()
    worse_mam_rows = rr_sam_untreated_remission.copy()
    better_mam_rows[
        "affected_entity"
    ] = "severe_acute_malnutrition_to_better_moderate_acute_malnutrition"
    worse_mam_rows[
        "affected_entity"
    ] = "severe_acute_malnutrition_to_worse_moderate_acute_malnutrition"
    rr_sam_untreated_remission = pd.concat([better_mam_rows, worse_mam_rows])

    rr = pd.concat([rr_sam_treated_remission, rr_sam_untreated_remission])

    rr["affected_measure"] = "transition_rate"
    rr = rr.set_index(["affected_entity", "affected_measure"], append=True)
    rr.index = rr.index.reorder_levels(
        [col for col in rr.index.names if col != "parameter"] + ["parameter"]
    )

    # no effect for simulants younger than 6 months
    rr.loc[rr.query("age_start < .5").index] = 1
    rr = rr[pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS]

    return rr.sort_index()


def load_mam_treatment_rr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    # tmrel is defined as baseline treatment (cat_2)
    if key != data_keys.MAM_TREATMENT.RELATIVE_RISK:
        raise ValueError(f"Unrecognized key {key}")

    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, location, mean_draw).reset_index()
    mam_tx_efficacy, mam_tx_efficacy_tmrel = utilities.get_treatment_efficacy(
        demography, data_keys.WASTING.CAT2, location
    )
    index = mam_tx_efficacy.index

    mam_ux_duration = data_values.WASTING.MAM_UX_RECOVERY_TIME_OVER_6MO
    mam_tx_duration = pd.Series(index=index)
    mam_tx_duration[
        index.get_level_values("age_start") < 0.5
    ] = data_values.WASTING.MAM_TX_RECOVERY_TIME_UNDER_6MO
    mam_tx_duration[0.5 <= index.get_level_values("age_start")] = get_random_variable_draws(
        mam_tx_duration[0.5 <= index.get_level_values("age_start")].index,
        *data_values.WASTING.MAM_TX_RECOVERY_TIME_OVER_6MO,
    )
    mam_tx_duration = pd.DataFrame(
        {f"draw_{i}": 1 for i in range(0, 1 if mean_draw else metadata.DRAW_COUNT)},
        index=index,
    ).multiply(mam_tx_duration, axis="index")

    # rr_r3 = r3 / r3_tmrel
    #       = (mam_tx_efficacy / mam_tx_duration) + (1 - mam_tx_efficacy / mam_ux_duration)
    #           / (mam_tx_efficacy_tmrel / mam_tx_duration) + (1 - mam_tx_efficacy_tmrel / mam_ux_duration)
    #       = (mam_tx_efficacy * mam_ux_duration + (1 - mam_tx_efficacy) * mam_tx_duration)
    #           / (mam_tx_efficacy_tmrel * mam_ux_duration + (1 - mam_tx_efficacy_tmrel) * mam_tx_duration)
    rr = (mam_tx_efficacy * mam_ux_duration + (1 - mam_tx_efficacy) * mam_tx_duration) / (
        mam_tx_efficacy_tmrel * mam_ux_duration
        + (1 - mam_tx_efficacy_tmrel) * mam_tx_duration
    )

    better_mam_rows = rr.copy()
    worse_mam_rows = rr.copy()
    better_mam_rows[
        "affected_entity"
    ] = "better_moderate_acute_malnutrition_to_mild_child_wasting"
    worse_mam_rows[
        "affected_entity"
    ] = "worse_moderate_acute_malnutrition_to_mild_child_wasting"
    rr = pd.concat([better_mam_rows, worse_mam_rows])

    rr["affected_measure"] = "transition_rate"
    rr = rr.set_index(["affected_entity", "affected_measure"], append=True)
    rr.index = rr.index.reorder_levels(
        [col for col in rr.index.names if col != "parameter"] + ["parameter"]
    )

    # no effect for simulants younger than 6 months
    rr.loc[rr.query("age_start < .5").index] = 1
    rr = rr[pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS]

    return rr.sort_index()


def load_lbwsg_exposure(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.LBWSG.EXPOSURE:
        raise ValueError(f"Unrecognized key {key}")

    entity = utilities.get_entity(data_keys.LBWSG.EXPOSURE)
    data = utilities.load_lbwsg_exposure(location)
    # This category was a mistake in GBD 2019, so drop.
    extra_residual_category = vi_globals.EXTRA_RESIDUAL_CATEGORY[entity.name]
    data = data.loc[data["parameter"] != extra_residual_category]
    idx_cols = ["location_id", "age_group_id", "year_id", "sex_id", "parameter"]
    data = data.set_index(idx_cols)[vi_globals.DRAW_COLUMNS]

    # Sometimes there are data values on the order of 10e-300 that cause
    # floating point headaches, so clip everything to reasonable values
    data = data.clip(lower=vi_globals.MINIMUM_EXPOSURE_VALUE)

    # normalize so all categories sum to 1
    total_exposure = data.groupby(["location_id", "age_group_id", "sex_id"]).transform("sum")
    data = (data / total_exposure).reset_index()
    data = reshape_to_vivarium_format(data, location)
    return data


def load_lbwsg_rr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.LBWSG.RELATIVE_RISK:
        raise ValueError(f"Unrecognized key {key}")

    data = load_standard_data(key, location, mean_draw)
    # load_standard_data pulls GBD_EXTRACT_YEAR, so the filter has to track it. A
    # hardcoded year silently empties this key whenever the extract year moves.
    data = data.query(f"year_start == {metadata.GBD_EXTRACT_YEAR}").droplevel(
        ["affected_entity", "affected_measure"]
    )
    if data.empty:
        raise ValueError(
            f"No '{key}' data for year {metadata.GBD_EXTRACT_YEAR}. The relative risk "
            "is only estimated for the neonatal age groups; check that the extract "
            "year is one the current GBD release provides this measure for."
        )
    data = data[~data.index.duplicated()]
    return data


def load_lbwsg_interpolated_rr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.LBWSG.RELATIVE_RISK_INTERPOLATOR:
        raise ValueError(f"Unrecognized key {key}")

    rr = get_data(data_keys.LBWSG.RELATIVE_RISK, location, mean_draw).reset_index()
    rr["parameter"] = pd.Categorical(rr["parameter"])
    rr = (
        rr.sort_values("parameter")
        .set_index(metadata.ARTIFACT_INDEX_COLUMNS + ["parameter"])
        .stack()
        .unstack("parameter")
        .apply(np.log)
    )

    # get category midpoints
    def get_category_midpoints(lbwsg_type: str) -> pd.Series:
        categories = get_data(
            f"risk_factor.{data_keys.LBWSG.name}.categories", location, mean_draw
        )
        return utilities.get_intervals_from_categories(lbwsg_type, categories).apply(
            lambda x: x.mid
        )

    gestational_age_midpoints = get_category_midpoints("short_gestation")
    birth_weight_midpoints = get_category_midpoints("low_birth_weight")

    # build grid of gestational age and birth weight
    def get_grid(midpoints: pd.Series, endpoints: Tuple[float, float]) -> np.array:
        grid = np.append(np.unique(midpoints), endpoints)
        grid.sort()
        return grid

    gestational_age_grid = get_grid(gestational_age_midpoints, (0.0, 42.0))
    birth_weight_grid = get_grid(birth_weight_midpoints, (0.0, 4500.0))

    def make_interpolator(log_rr_for_age_sex_draw: pd.Series) -> RectBivariateSpline:
        # Use scipy.interpolate.griddata to extrapolate to grid using nearest neighbor interpolation
        log_rr_grid_nearest = griddata(
            (gestational_age_midpoints, birth_weight_midpoints),
            log_rr_for_age_sex_draw,
            (gestational_age_grid[:, None], birth_weight_grid[None, :]),
            method="nearest",
            rescale=True,
        )
        # return a RectBivariateSpline object from the extrapolated values on grid
        return RectBivariateSpline(
            gestational_age_grid, birth_weight_grid, log_rr_grid_nearest, kx=1, ky=1
        )

    log_rr_interpolator = (
        rr.apply(make_interpolator, axis="columns")
        .apply(lambda x: pickle.dumps(x).hex())
        .unstack()
    )
    return log_rr_interpolator


def load_lbwsg_paf(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.LBWSG.PAF:
        raise ValueError(f"Unrecognized key {key}")

    df = pd.read_parquet(_resolve_lbwsg_paf_path(location))
    if "input_draw" in df.columns:
        df = df.assign(input_draw="draw_" + df.input_draw.astype(str))
    else:
        df = df.assign(input_draw="draw_0")
    df = df.pivot_table(
        "value", [c for c in df if c not in ["input_draw", "value"]], "input_draw"
    ).reset_index()
    not_needed_columns = ["scenario", "random_seed"]
    df = df.drop(columns=[c for c in df.columns if c in not_needed_columns])

    age_start_dict = {"early_neonatal": 0.0, "late_neonatal": 0.01917808}
    age_end_dict = {"early_neonatal": 0.01917808, "late_neonatal": 0.07671233}
    df["age_start"] = df["age_group"].replace(age_start_dict)
    df["age_end"] = df["age_group"].replace(age_end_dict)
    df["year_start"] = 2021
    df["year_end"] = 2022
    df = df.drop("age_group", axis=1)
    index_columns = ["sex", "age_start", "age_end", "year_start", "year_end"]
    df = df.set_index(index_columns)
    unaffected_age_groups = [(0.07671233, 1.0), (1.0, 5.0)]
    for age_start, age_end in unaffected_age_groups:
        for sex in ["Male", "Female"]:
            df.loc[(sex, age_start, age_end, 2021, 2022), :] = 0

    return df.sort_index()


def _resolve_lbwsg_paf_path(location: str) -> Path:
    """Locate the output of the LBWSG PAF calculation simulation.

    Results live under :data:`paths.LBWSG_PAF_RESULTS_ROOT`. Both layouts are handled:

    - ``simulate run`` writes ``<measure>.parquet``.
    - ``psimulate`` writes ``<measure>/<task_id>.parquet``, and nests the whole lot
      under ``<location>/<timestamp>/results/``.

    The search is recursive so that the run's timestamp directory does not have to be
    named on the command line, and so the flattening ``mv`` the old Snakefile did after
    the simulation is no longer required.
    """
    measure = paths.LBWSG_PAF_MEASURE_NAME
    location_dir = paths.LBWSG_PAF_RESULTS_ROOT / location.lower().replace(" ", "_")

    if not location_dir.exists():
        raise FileNotFoundError(
            f"No LBWSG PAF results found at '{location_dir}'. These are produced by "
            f"running the PAF calculation simulation ('data/lbwsg_paf.yaml') against "
            f"the artifact built with --for-lbwsg-pafs, and are required before the "
            f"full child artifact can be built."
        )

    # Prefer a flat file, then a metric directory, then anything nested under a run.
    candidates = [
        location_dir / f"{measure}.parquet",
        location_dir / measure,
        *sorted(location_dir.glob(f"**/{measure}.parquet")),
        *sorted(p for p in location_dir.glob(f"**/{measure}") if p.is_dir()),
    ]
    for candidate in candidates:
        if candidate.is_file() or (candidate.is_dir() and any(candidate.glob("*.parquet"))):
            return candidate

    raise FileNotFoundError(
        f"Found '{location_dir}' but no '{measure}' results inside it. Expected either "
        f"'{measure}.parquet' or a '{measure}/' directory of parquet files, at the top "
        f"level or under a run's 'results/' directory."
    )


def load_birth_weight_wealth_disparities(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    disparities = pd.read_csv(
        paths.DATA_PREP_RESULTS_ROOT
        / "birth_weight_disparities"
        / (location.lower() + ".csv"),
    ).set_index(["wealth_quintile"])

    return disparities


def load_sids_csmr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key == data_keys.AFFECTED_UNMODELED_CAUSES.SIDS_CSMR:
        key = EntityKey(key)
        entity: Cause = utilities.get_entity(key)

        # get around the validation rejecting yll only causes
        entity.restrictions.yll_only = False
        entity.restrictions.yld_age_group_id_start = metadata.AGE_GROUP.LATE_NEONATAL_ID
        entity.restrictions.yld_age_group_id_end = metadata.AGE_GROUP.LATE_NEONATAL_ID
        data = interface.get_measure(entity, key.measure, location, metadata.GBD_EXTRACT_YEAR)
        return data
    else:
        raise ValueError(f"Unrecognized key {key}")


def load_neonatal_lri_csmr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_LRI_CSMR:
        raise ValueError(f"Unrecognized key {key}")

    data = load_standard_data(data_keys.LRI.CSMR, location, mean_draw)
    data.loc[data.index.get_level_values("age_start") >= metadata.NEONATAL_END_AGE, :] = 0
    return data


def load_neonatal_diarrhea_csmr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    if key != data_keys.AFFECTED_UNMODELED_CAUSES.NEONATAL_DIARRHEAL_DISEASES_CSMR:
        raise ValueError(f"Unrecognized key {key}")

    data = load_standard_data(data_keys.DIARRHEA.CSMR, location, mean_draw)
    data.loc[data.index.get_level_values("age_start") >= metadata.NEONATAL_END_AGE, :] = 0
    return data


def load_iron_fortification_effect_on_birth_weight(key: str, location: str, mean_draw: bool):
    path = paths.DATA_PREP_RESULTS_ROOT / "iron" / "fortification_birthweight_effects.csv"

    df = pd.read_csv(path)
    return df.set_index([c for c in df.columns if c != "value"])


def load_intervention_distribution(key: str, location: str, mean_draw: bool) -> str:
    try:
        return {
            # data_keys.IFA_SUPPLEMENTATION.DISTRIBUTION: data_values.MATERNAL_CHARACTERISTICS.DISTRIBUTION,
            # data_keys.MMN_SUPPLEMENTATION.DISTRIBUTION: data_values.MATERNAL_CHARACTERISTICS.DISTRIBUTION,
            # data_keys.BEP_SUPPLEMENTATION.DISTRIBUTION: data_values.MATERNAL_CHARACTERISTICS.DISTRIBUTION,
            # data_keys.IV_IRON.DISTRIBUTION: data_values.MATERNAL_CHARACTERISTICS.DISTRIBUTION,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")


def load_intervention_categories(key: str, location: str, mean_draw: bool) -> str:
    try:
        return {
            # data_keys.IFA_SUPPLEMENTATION.CATEGORIES: data_values.MATERNAL_CHARACTERISTICS.CATEGORIES,
            # data_keys.MMN_SUPPLEMENTATION.CATEGORIES: data_values.MATERNAL_CHARACTERISTICS.CATEGORIES,
            # data_keys.BEP_SUPPLEMENTATION.CATEGORIES: data_values.MATERNAL_CHARACTERISTICS.CATEGORIES,
            # data_keys.IV_IRON.CATEGORIES: data_values.MATERNAL_CHARACTERISTICS.CATEGORIES,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")


def load_dichotomous_treatment_exposure(
    key: str, location: str, mean_draw: bool, **kwargs
) -> pd.DataFrame:
    try:
        distribution_data = {
            # data_keys.IFA_SUPPLEMENTATION.EXPOSURE: load_baseline_ifa_supplementation_coverage(
            #     location
            # ),
            # data_keys.MMN_SUPPLEMENTATION.EXPOSURE: data_values.MATERNAL_CHARACTERISTICS.BASELINE_MMN_COVERAGE,
            # data_keys.BEP_SUPPLEMENTATION.EXPOSURE: data_values.MATERNAL_CHARACTERISTICS.BASELINE_BEP_COVERAGE,
            # data_keys.IV_IRON.EXPOSURE: data_values.MATERNAL_CHARACTERISTICS.BASELINE_IV_IRON_COVERAGE,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")
    return load_dichotomous_exposure(location, distribution_data, is_risk=False, **kwargs)


def load_ifa_excess_shift(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    birth_weight_shift = load_treatment_excess_shift(key, location)
    gestational_age_shift = load_excess_gestational_age_shift(key, location)
    return pd.concat([birth_weight_shift, gestational_age_shift])


def load_treatment_excess_shift(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    try:
        distribution_data = {
            # data_keys.IFA_SUPPLEMENTATION.EXCESS_SHIFT: data_values.MATERNAL_CHARACTERISTICS.IFA_BIRTH_WEIGHT_SHIFT,
            # data_keys.MMN_SUPPLEMENTATION.EXCESS_SHIFT: data_values.MATERNAL_CHARACTERISTICS.MMN_BIRTH_WEIGHT_SHIFT,
            # data_keys.IV_IRON.EXCESS_SHIFT: data_values.MATERNAL_CHARACTERISTICS.IV_IRON_BIRTH_WEIGHT_SHIFT,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")
    return load_dichotomous_excess_shift(location, distribution_data)


def load_dichotomous_exposure(
    location: str,
    distribution_data: Union[float, pd.DataFrame],
    is_risk: bool,
) -> pd.DataFrame:
    index = get_data(data_keys.POPULATION.DEMOGRAPHY, location).index
    if type(distribution_data) == float:
        base_exposure = pd.Series(distribution_data, index=index)
        exposed = pd.DataFrame(
            {
                f"draw_{i}": base_exposure
                for i in range(1 if mean_draw else metadata.DRAW_COUNT)
            }
        )
    else:
        exposed = distribution_data

    unexposed = 1 - exposed
    exposed["parameter"] = "cat1" if is_risk else "cat2"
    unexposed["parameter"] = "cat2" if is_risk else "cat1"
    exposure = (
        pd.concat([exposed, unexposed]).set_index("parameter", append=True).sort_index()
    )
    exposure = exposure[pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS]
    return exposure


def load_dichotomous_excess_shift(
    location: str,
    distribution_data: Tuple,
) -> pd.DataFrame:
    """Load excess birth weight exposure shifts using distribution data."""
    index = get_data(data_keys.POPULATION.DEMOGRAPHY, location).index
    shift = get_random_variable_draws(
        pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
        *distribution_data,
    )
    excess_shift = reshape_shift_data(shift, index, data_keys.LBWSG.BIRTH_WEIGHT_EXPOSURE)

    return excess_shift


def load_excess_gestational_age_shift(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    """Load excess gestational age shift data from IFA and MMS from file.
    Returns the sum of the shift data in the directories defined in data_dirs."""
    try:
        data_dirs = {
            # data_keys.IFA_SUPPLEMENTATION.EXCESS_SHIFT: [paths.IFA_GA_SHIFT_DATA_DIR],
            # data_keys.MMN_SUPPLEMENTATION.EXCESS_GA_SHIFT_SUBPOP_1: [
            #     paths.MMS_GA_SHIFT_1_DATA_DIR
            # ],
            # data_keys.MMN_SUPPLEMENTATION.EXCESS_GA_SHIFT_SUBPOP_2: [
            #     paths.MMS_GA_SHIFT_1_DATA_DIR,
            #     paths.MMS_GA_SHIFT_2_DATA_DIR,
            # ],
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    index = get_data(data_keys.POPULATION.DEMOGRAPHY, location).index
    all_shift_data = [
        pd.read_csv(data_dir / f"{location.lower()}.csv") for data_dir in data_dirs
    ]
    shifts = [
        pd.Series(shift_data["value"].values, index=shift_data["draw"])
        for shift_data in all_shift_data
    ]
    if len(shifts) > 1:
        shifts[1] = shifts[1].loc[shifts[1].notnull()]
    summed_shifts = sum(shifts)  # only sum more than one Series for subpop 2

    excess_shift = reshape_shift_data(
        summed_shifts, index, data_keys.LBWSG.GESTATIONAL_AGE_EXPOSURE
    )
    excess_shift = excess_shift[
        pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS
    ]

    return excess_shift


def reshape_shift_data(
    shift: pd.Series, index: pd.Index, target: TargetString
) -> pd.DataFrame:
    """Read in draw-level shift values and return a DataFrame where the data are the shift values,
    and the index is the passed index appended with affected entity/measure and parameter data.
    """
    exposed = pd.DataFrame([shift], index=index)
    exposed["parameter"] = "cat2"
    unexposed = pd.DataFrame(
        [
            pd.Series(
                0.0,
                index=pd.Index(["draw_0"]) if mean_draw else metadata.ARTIFACT_COLUMNS,
            )
        ],
        index=index,
    )
    unexposed["parameter"] = "cat1"

    excess_shift = pd.concat([exposed, unexposed])
    excess_shift["affected_entity"] = target.name
    excess_shift["affected_measure"] = target.measure

    excess_shift = excess_shift.set_index(
        ["affected_entity", "affected_measure", "parameter"], append=True
    ).sort_index()
    return excess_shift


def load_risk_specific_shift(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    try:
        key_group: data_keys.__AdditiveRisk = {
            # data_keys.IFA_SUPPLEMENTATION.RISK_SPECIFIC_SHIFT: data_keys.IFA_SUPPLEMENTATION,
        }[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    # p_exposed * exposed_shift
    exposure = get_data(key_group.EXPOSURE, location, mean_draw)
    excess_shift = get_data(key_group.EXCESS_SHIFT, location, mean_draw)

    risk_specific_shift = (
        (exposure * excess_shift)
        .groupby(metadata.ARTIFACT_INDEX_COLUMNS + ["affected_entity", "affected_measure"])
        .sum()
    )
    return risk_specific_shift


def reshape_to_vivarium_format(df, location):
    df = vi_utils.reshape(df, value_cols=DRAW_COLUMNS)
    df = vi_utils.scrub_gbd_conventions(df, location)
    df = vi_utils.split_interval(df, interval_column="age", split_column_prefix="age")
    df = vi_utils.split_interval(df, interval_column="year", split_column_prefix="year")
    df = vi_utils.sort_hierarchical_data(df)

    return df


def fetch_subnational_ids(location: str) -> List[int]:
    location_id = utility_data.get_location_id(location)
    location_metadata = gbd.get_location_path_to_global()
    subnational_location_metadata = location_metadata.loc[
        (location_metadata["path_to_top_parent"].apply(lambda x: str(location_id) in x))
        & (location_metadata["location_id"] != location_id)
    ]
    subnational_location_ids = subnational_location_metadata["location_id"].tolist()
    return subnational_location_ids


def get_national_location_id(location_id: int) -> int:
    location_metadata = gbd.get_location_path_to_global()
    path_to_parent = location_metadata.loc[location_metadata.location_id == location_id][
        "path_to_top_parent"
    ].to_list()
    national_location_id = int([loc_id.split(",")[3] for loc_id in path_to_parent][0])
    return national_location_id
