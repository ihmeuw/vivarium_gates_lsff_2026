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

from functools import cache

import numpy as np
import pandas as pd
import vivarium.gbd_mapping as gbd_mapping
import vivarium_inputs.validation.sim as validation
from joblib import Memory
from scipy import integrate, stats
from vivarium.artifact import EntityKey
from vivarium.engine.framework.randomness import get_hash
from vivarium_gbd_access import gbd
from vivarium_inputs import core as vi_core
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import interface
from vivarium_inputs import utilities as vi_utils
from vivarium_inputs import utility_data

from lsff_utils import data_processing, hemoglobin_distribution
from vivarium_gates_lsff_2026_maternal.constants import (
    data_keys,
    data_values,
    metadata,
    models,
    paths,
)
from vivarium_gates_lsff_2026_maternal.data import extra_gbd, sampling
from vivarium_gates_lsff_2026_maternal.data.utilities import get_entity
from vivarium_gates_lsff_2026_maternal.utilities import get_random_variable_draws

##Note: need to remove all instances where we limit the size of the data manually. This will be done when RT updates in the input files.

memory = Memory("./.cachedir", verbose=0)

CSV_DATA_NAMES = {
    data_keys.POPULATION.WEALTH_QUINTILE_PROBABILITIES: "wealth_quintile_probabilities",
    data_keys.VEHICLE_CONSUMPTION.ANY_CONSUMED: "{vehicle}/vehicle_consumption/any",
    data_keys.VEHICLE_CONSUMPTION.FORTIFIABILITY: "{vehicle}/vehicle_consumption/fortifiability",
    data_keys.VEHICLE_CONSUMPTION.MEAN: "{vehicle}/vehicle_consumption/amount/mean",
    data_keys.VEHICLE_CONSUMPTION.STANDARD_DEVIATION: "{vehicle}/vehicle_consumption/amount/sd",
    data_keys.IRON_FORTIFICATION.BASELINE_ANY_COVERAGE: "iron/{vehicle}/baseline_fortification/any_coverage",
    data_keys.IRON_FORTIFICATION.BASELINE_FULL_COVERAGE: "iron/{vehicle}/baseline_fortification/full_coverage",
    data_keys.IRON_FORTIFICATION.BASELINE_PARTIAL_COVERAGE_AMOUNT_MEAN: "iron/{vehicle}/baseline_fortification/partial_coverage_amount/mean",
    data_keys.IRON_FORTIFICATION.BASELINE_PARTIAL_COVERAGE_AMOUNT_SD: "iron/{vehicle}/baseline_fortification/partial_coverage_amount/sd",
    data_keys.IRON_FORTIFICATION.BASELINE_EFFECTIVENESS: "iron/{vehicle}/baseline_fortification/effectiveness",
    data_keys.IRON_FORTIFICATION.BASELINE_CONCENTRATION: "iron/{vehicle}/baseline_fortification/concentration",
    data_keys.IRON_FORTIFICATION.INTERVENTION_COVERAGE: "iron/{vehicle}/intervention/intervention_fortification/any_coverage",
    data_keys.IRON_FORTIFICATION.INTERVENTION_EFFECTIVENESS: "iron/{vehicle}/intervention/intervention_fortification/effectiveness",
    data_keys.IRON_FORTIFICATION.INTERVENTION_CONCENTRATION: "iron/{vehicle}/intervention/intervention_fortification/concentration",
    data_keys.IRON_FORTIFICATION.HEMOGLOBIN_EFFECT_SIZE: "iron/fortification_hemoglobin_effects.csv",
}


@cache
def get_data(
    lookup_key: str, location: str, mean_draw: bool, vehicle: str = None
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
    if lookup_key == data_keys.VEHICLE.NAME:
        return vehicle

    if lookup_key in CSV_DATA_NAMES.keys():
        return load_csv_data(lookup_key, location, mean_draw, vehicle)

    mapping = {
        data_keys.POPULATION.LOCATION: load_population_location,
        data_keys.POPULATION.STRUCTURE: load_population_structure,
        data_keys.POPULATION.AGE_BINS: load_age_bins,
        data_keys.POPULATION.DEMOGRAPHY: load_demographic_dimensions,
        data_keys.POPULATION.TMRLE: load_theoretical_minimum_risk_life_expectancy,
        data_keys.POPULATION.INFANT_MALE_PERCENTAGE: load_infant_male_percentage,
        data_keys.POPULATION.ALL_CAUSE_MORTALITY_RATE: load_standard_data,
        data_keys.PREGNANCY.ASFR: load_asfr,
        data_keys.PREGNANCY.SBR: load_sbr,
        data_keys.PREGNANCY.RAW_INCIDENCE_RATE_MISCARRIAGE: load_raw_incidence_data,
        data_keys.PREGNANCY.RAW_INCIDENCE_RATE_ECTOPIC: load_raw_incidence_data,
        data_keys.LBWSG.DISTRIBUTION: load_metadata,
        data_keys.LBWSG.CATEGORIES: load_metadata,
        data_keys.LBWSG.EXPOSURE: load_lbwsg_exposure,
        data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE: load_raw_incidence_data,
        data_keys.MATERNAL_DISORDERS.CSMR: load_maternal_csmr,
        data_keys.MATERNAL_DISORDERS.MORTALITY_PROBABILITY: load_maternal_disorders_mortality_probability,
        data_keys.MATERNAL_DISORDERS.INCIDENT_PROBABILITY: load_pregnant_maternal_disorders_incidence_probability,
        data_keys.MATERNAL_DISORDERS.YLDS: load_maternal_disorders_ylds,
        data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN: load_hemoglobin_maternal_disorders_rr,
        data_keys.MATERNAL_DISORDERS.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN: memory.cache(
            generate_hemoglobin_maternal_disorders_paf
        ),
        data_keys.MATERNAL_HEMORRHAGE.RAW_INCIDENCE_RATE: load_raw_incidence_data,
        data_keys.MATERNAL_HEMORRHAGE.CSMR: load_maternal_csmr,
        data_keys.MATERNAL_HEMORRHAGE.INCIDENT_PROBABILITY: load_pregnant_maternal_hemorrhage_incidence,
        data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN: load_hemoglobin_maternal_hemorrhage_rr,
        data_keys.MATERNAL_HEMORRHAGE.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN: load_hemoglobin_maternal_hemorrhage_paf,
        data_keys.MATERNAL_HEMORRHAGE.MODERATE_HEMORRHAGE_PROBABILITY: get_moderate_hemorrhage_probability,
        data_keys.HEMOGLOBIN.MEAN: get_hemoglobin_data,
        data_keys.HEMOGLOBIN.STANDARD_DEVIATION: get_hemoglobin_data,
        data_keys.HEMOGLOBIN.PREGNANT_PROPORTION_WITH_HEMOGLOBIN_BELOW_70: get_hemoglobin_below_70,
        # data_keys.POPULATION.BACKGROUND_MORBIDITY: load_background_morbidity,
    }
    data = mapping[lookup_key](lookup_key, location, mean_draw)
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


def load_population_structure(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    # Use precomputed population from data prep instead of GBD interface
    total_csv = (
        paths.DATA_PREP_RESULTS_ROOT / "population" / "total" / (location.lower() + ".csv")
    )
    # NOTE: The data prep notebook drops year_start/year_end from
    # vivarium_inputs.get_population_structure output, so the year bin has to be restamped
    # here. It must match GBD_EXTRACT_YEAR: this key is the rate-aggregation weight for every
    # GBD-sourced rate, and those carry [GBD_EXTRACT_YEAR, GBD_EXTRACT_YEAR + 1). A literal
    # 2021/2022 here left population.structure unable to join against any of them -- invisible
    # to the simulation, which extrapolates from whatever bin exists, but it breaks the
    # automated V&V weighting (see 5000_analyze_results/validation/README.md).
    base_population_structure = (
        pd.read_csv(total_csv)
        .assign(
            year_start=metadata.GBD_EXTRACT_YEAR,
            year_end=metadata.GBD_EXTRACT_YEAR + 1,
        )
        .set_index(["sex", "age_start", "age_end", "year_start", "year_end"])
    )
    pregnancy_end_rate = broadcast_onto(
        get_pregnancy_end_incidence(location, mean_draw), base_population_structure.index
    )
    # NOTE: A "value" column rather than "draw_0" -- see the note in load_csv_data.
    pregnant_population_structure = (
        base_population_structure["value"].mul(pregnancy_end_rate).to_frame("value")
    )
    if "location" not in pregnant_population_structure.index.names:
        pregnant_population_structure = pregnant_population_structure.assign(
            location=location
        ).set_index("location", append=True)
    return vi_utils.sort_hierarchical_data(pregnant_population_structure)


def load_age_bins(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    return interface.get_age_bins()


def load_demographic_dimensions(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    return interface.get_demographic_dimensions(location)


def load_theoretical_minimum_risk_life_expectancy(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    return interface.get_theoretical_minimum_risk_life_expectancy()


def load_infant_male_percentage(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    # We do not propagate uncertainty here, but GBD actually gives us this covariate with no uncertainty.
    live_births_by_sex = interface.get_measure(
        gbd_mapping.covariates.live_births_by_sex, "estimate", location
    ).pipe(_only_mean)
    live_births_overall = live_births_by_sex.groupby(
        [c for c in live_births_by_sex.index.names if c != "sex"]
    ).sum()
    return (
        live_births_by_sex.pipe(
            lambda df: df[df.index.get_level_values("sex") == "Male"]
        ).droplevel("sex")
        / live_births_overall
    )


def load_standard_data(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    key = EntityKey(key)
    entity = get_entity(key)
    return interface.get_measure(entity, key.measure, location).droplevel("location")


# TODO: Remove this if/ when Vivarium Inputs implements the change directly
def load_raw_incidence_data(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    """Temporary function to short circuit around validation issues in Vivarium Inputs"""
    key = EntityKey(key)
    entity = get_entity(key)
    years = None
    data_type = vi_utils.DataType(key.measure, "draws")
    data = vi_core.get_data(entity, key.measure, location, years, data_type)
    data = vi_utils.scrub_gbd_conventions(data, location)
    validation.validate_for_simulation(
        data,
        entity,
        "incidence_rate",
        location,
        years,
        data_type.value_columns,
    )
    data = vi_utils.split_interval(data, interval_column="age", split_column_prefix="age")
    data = vi_utils.split_interval(data, interval_column="year", split_column_prefix="year")
    return vi_utils.sort_hierarchical_data(data).droplevel("location")


def load_metadata(key: str, location: str, mean_draw: bool):
    key = EntityKey(key)
    entity = get_entity(key)
    entity_metadata = entity[key.measure]
    if hasattr(entity_metadata, "to_dict"):
        entity_metadata = entity_metadata.to_dict()
    return entity_metadata


def load_categorical_paf(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    try:
        risk = {
            # todo add keys as needed
            data_keys.KEYGROUP.PAF: data_keys.KEYGROUP,
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
    return paf


##################
# Pregnancy Data #
##################


def get_pregnancy_end_incidence(location: str, mean_draw: bool) -> pd.Series:
    """Load the rate at which pregnancies end, by sex and age group.

    The data prep results are a single point estimate with no year or draw
    dimension, so this returns a Series indexed only by the demographic columns
    the CSV provides. Callers combining it with GBD data must broadcast it onto
    that data's index with :func:`broadcast_onto`.
    """
    path = paths.DATA_PREP_RESULTS_ROOT / "pregnancy/incidence" / (location.lower() + ".csv")
    df = pd.read_csv(path)
    return df.set_index([c for c in df.columns if c != "value"])["value"]


def broadcast_onto(data: pd.Series, index: pd.MultiIndex) -> pd.Series:
    """Broadcast a Series onto a target index using the levels the two share.

    Data prep results carry no 'year_start'/'year_end' levels while GBD data does,
    so combining the two requires repeating the former across the latter's years.
    Broadcasting is used in preference to stamping a fixed year onto the data prep
    results because a hardcoded year silently produces an all-NaN result whenever
    the GBD release year moves on.
    """
    levels = list(data.index.names)
    missing = set(levels) - set(index.names)
    if missing:
        raise ValueError(
            f"Cannot broadcast data indexed by {levels} onto an index that is "
            f"missing the level(s) {sorted(missing)}."
        )
    aligned = data.reindex(
        pd.MultiIndex.from_arrays(
            [index.get_level_values(level) for level in levels], names=levels
        )
    )
    if aligned.isna().all():
        raise ValueError(
            f"Broadcasting data indexed by {levels} onto the target index produced "
            "no overlapping rows."
        )
    return pd.Series(aligned.to_numpy(), index=index, name=data.name)


def load_asfr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    asfr = load_standard_data(key, location, mean_draw)
    asfr = asfr.reset_index()
    asfr_pivot = asfr.pivot(
        index=[col for col in metadata.ARTIFACT_INDEX_COLUMNS if col != "location"],
        columns="parameter",
        values="value",
    )
    seed = f"{key}_{location}"
    asfr_draws = sampling.generate_vectorized_lognormal_draws(asfr_pivot, seed)
    return asfr_draws


def load_sbr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    sbr = load_standard_data(key, location, mean_draw)
    sbr = sbr.reorder_levels(["parameter", "year_start", "year_end"]).loc["mean_value"]
    return sbr


##############
# LBWSG Data #
##############


def load_lbwsg_exposure(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    entity = get_entity(data_keys.LBWSG.EXPOSURE)
    data = extra_gbd.load_lbwsg_exposure(location)
    # This category was a mistake in GBD 2019, so drop.
    extra_residual_category = vi_globals.EXTRA_RESIDUAL_CATEGORY[entity.name]
    data = data.loc[data["parameter"] != extra_residual_category]
    idx_cols = ["location_id", "sex_id", "parameter"]
    data = data.set_index(idx_cols)[vi_globals.DRAW_COLUMNS]

    # Sometimes there are data values on the order of 10e-300 that cause
    # floating point headaches, so clip everything to reasonable values
    data = data.clip(lower=vi_globals.MINIMUM_EXPOSURE_VALUE)

    # normalize so all categories sum to 1
    total_exposure = data.groupby(["location_id", "sex_id"]).transform("sum")
    data = (data / total_exposure).reset_index()
    data = reshape_to_vivarium_format(data, location)
    return data


###########################
# Maternal Disorders Data #
###########################


def load_maternal_csmr(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    key = EntityKey(key)
    entity = get_entity(key)
    entity.restrictions.yll_age_group_id_end = 15
    return interface.get_measure(entity, key.measure, location).droplevel("location")


def load_maternal_disorders_ylds(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    groupby_cols = ["age_group_id", "sex_id", "year_id"]
    draw_cols = vi_globals.DRAW_COLUMNS

    all_md_ylds = extra_gbd.get_maternal_disorder_ylds(location)
    all_md_ylds = all_md_ylds[groupby_cols + draw_cols]
    all_md_ylds = reshape_to_vivarium_format(all_md_ylds, location)

    anemia_ylds = extra_gbd.get_anemia_ylds(location)
    anemia_ylds = anemia_ylds.groupby(groupby_cols)[draw_cols].sum().reset_index()
    anemia_ylds = reshape_to_vivarium_format(anemia_ylds, location)

    csmr = get_data(data_keys.MATERNAL_DISORDERS.CSMR, location, mean_draw)
    incidence = load_raw_incidence_data(
        data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location, mean_draw
    )
    idx_cols = incidence.index.names
    incidence = incidence.reset_index()
    #   Update incidence for 55-59 year age group to match 50-54 year age group
    to_duplicate = incidence.loc[(incidence.sex == "Female") & (incidence.age_start == 50.0)]
    to_duplicate["age_start"] = 55.0
    to_duplicate["age_end"] = 60.0
    to_drop = incidence.loc[(incidence.sex == "Female") & (incidence.age_start == 55.0)]
    incidence = (
        pd.concat([incidence.drop(to_drop.index), to_duplicate])
        .set_index(idx_cols)
        .sort_index()
    )
    ylds = (all_md_ylds - anemia_ylds) / (incidence - csmr)
    return ylds.fillna(0)


def load_pregnant_maternal_disorders_incidence_probability(
    key: str, location: str, mean_draw: bool
):
    total_incidence = get_data(
        data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location, mean_draw
    )
    pregnancy_end_rate = broadcast_onto(
        get_pregnancy_end_incidence(location, mean_draw), total_incidence.index
    )
    maternal_disorders_incidence = total_incidence.div(pregnancy_end_rate, axis=0)

    disparities = (
        pd.read_csv(
            paths.DATA_PREP_RESULTS_ROOT
            / "maternal_disorders_incidence_disparities"
            / (location.lower() + ".csv"),
        )
        .set_index(["sex", "wealth_quintile"])
        .value
    )

    result = _distribute_by_disparities_multiplicative(
        maternal_disorders_incidence.dropna(how="all"), disparities, location
    ).clip(upper=1)
    return result.reindex(
        _demographics_with_wealth(location).droplevel("location").index
    ).fillna(0)


def _distribute_by_disparities_multiplicative(
    quantity: pd.DataFrame, disparities: pd.DataFrame, location: str
):
    # NOTE: The recovery assertion below is vacuously true for an empty quantity,
    # so an upstream misalignment would otherwise be written to the artifact as an
    # all-zero key rather than failing the build.
    if quantity.empty:
        raise ValueError(
            "Cannot distribute an empty quantity by disparities. This usually means "
            "an upstream merge or division produced all NaNs."
        )
    wealth_quintile_probabilities = (
        get_data(data_keys.POPULATION.WEALTH_QUINTILE_PROBABILITIES, location, mean_draw=True)
        .reset_index()
        .melt(id_vars=["sex", "age_start", "age_end"], var_name="wealth_quintile")
        .assign(wealth_quintile=lambda df: df.wealth_quintile.astype(int))
        .set_index(["sex", "age_start", "age_end", "wealth_quintile"])
        .value
    )
    # Normalize disparities
    disparities = disparities.div(
        disparities.groupby(
            [c for c in disparities.index.names if c != "wealth_quintile"]
        ).sum()
    )

    raw = quantity.mul(
        data_processing.reindex_series_onto_df_by_age_groups(quantity, disparities),
        axis=0,
    ).dropna(how="all")

    # How much we need to scale to recover the original quantities
    rescale_factor = (
        raw.mul(
            data_processing.reindex_series_onto_df_by_age_groups(
                raw, wealth_quintile_probabilities
            ),
            axis=0,
        )
        .groupby(["sex", "age_start", "age_end", "year_start", "year_end"])
        .sum()
        .div(quantity)
    )

    result = raw.div(rescale_factor)

    # We have recovered the original quantities (ignoring rows where quantity is NaN,
    # since those quintile rows are dropped by dropna and groupby().sum() returns 0)
    q_vals = quantity.sort_index().values
    ws_vals = (
        result.mul(
            data_processing.reindex_series_onto_df_by_age_groups(
                result, wealth_quintile_probabilities
            ),
            axis=0,
        )
        .groupby(["sex", "age_start", "age_end", "year_start", "year_end"])
        .sum()
        .sort_index()
        .values
    )
    valid = ~np.isnan(q_vals)
    assert np.allclose(ws_vals[valid], q_vals[valid])

    return result


def _distribute_by_disparities_additive(
    quantity: pd.DataFrame, disparities: pd.DataFrame, location: str
):
    wealth_quintile_probabilities = (
        get_data(data_keys.POPULATION.WEALTH_QUINTILE_PROBABILITIES, location, mean_draw=True)
        .reset_index()
        .melt(id_vars=["sex"], var_name="wealth_quintile")
        .set_index(["sex", "wealth_quintile"])
        .value
    )

    raw = quantity.add(disparities, axis=0).dropna(how="all")
    # How much we need to shift to recover the original quantities
    rescale_factor = (
        raw.mul(wealth_quintile_probabilities, axis=0)
        .groupby(["sex", "age_start", "age_end", "year_start", "year_end"])
        .sum()
        .subtract(quantity)
    )

    result = raw.subtract(rescale_factor)

    # We have recovered the original quantities
    assert np.allclose(
        result.mul(wealth_quintile_probabilities, axis=0)
        .groupby(["sex", "age_start", "age_end", "year_start", "year_end"])
        .sum()
        .sort_index()
        .values,
        quantity.sort_index().values,
    )

    return result


def _demographics_with_wealth(location: str) -> pd.DataFrame:
    demographic_dimensions = get_data(
        data_keys.POPULATION.DEMOGRAPHY, location, mean_draw=True
    ).reset_index()
    return (
        demographic_dimensions.assign(key=1)
        .merge(
            pd.DataFrame({"wealth_quintile": data_processing.WEALTH_QUINTILES, "key": 1}),
            on="key",
        )
        .drop(columns=["key"])
        .pipe(lambda df: df.set_index(list(df.columns)))
    )


def load_maternal_disorders_mortality_probability(key: str, location: str, mean_draw: bool):
    total_csmr = get_data(data_keys.MATERNAL_DISORDERS.CSMR, location, mean_draw)
    total_incidence = get_data(
        data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location, mean_draw
    )
    mortality_probability = total_csmr / total_incidence
    return mortality_probability.fillna(0)


def load_pregnant_maternal_hemorrhage_incidence(key: str, location: str, mean_draw: bool):
    mh_incidence = get_data(
        data_keys.MATERNAL_HEMORRHAGE.RAW_INCIDENCE_RATE, location, mean_draw
    )
    mh_csmr = get_data(data_keys.MATERNAL_HEMORRHAGE.CSMR, location, mean_draw)
    pregnancy_end_rate = broadcast_onto(
        get_pregnancy_end_incidence(location, mean_draw), mh_incidence.index
    )
    maternal_hemorrhage_incidence = (mh_incidence - mh_csmr).div(pregnancy_end_rate, axis=0)

    disparities = (
        pd.read_csv(
            paths.DATA_PREP_RESULTS_ROOT
            / "maternal_disorders_incidence_disparities"
            / (location.lower() + ".csv"),
        )
        .set_index(["sex", "wealth_quintile"])
        .value
    )

    result = _distribute_by_disparities_multiplicative(
        maternal_hemorrhage_incidence.dropna(how="all"), disparities, location
    ).clip(upper=1)
    return result.reindex(
        _demographics_with_wealth(location).droplevel("location").index
    ).fillna(0)


def load_hemoglobin_maternal_hemorrhage_rr(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    if key != data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    distribution = data_values.RR_MATERNAL_HEMORRHAGE_ATTRIBUTABLE_TO_HEMOGLOBIN
    dist = sampling.get_lognorm_from_quantiles(*distribution)
    # Get a DataFrame with the desired index
    demographic_dimensions = get_data(data_keys.POPULATION.DEMOGRAPHY, location, mean_draw)

    rng = np.random.default_rng(get_hash(f"{key}_{location}"))
    draw_count = vi_globals.NUM_DRAWS
    maternal_hemorrhage_rr = pd.DataFrame(
        np.tile(
            dist.rvs(size=draw_count, random_state=rng),
            (len(demographic_dimensions), 1),
        ),
        columns=vi_globals.DRAW_COLUMNS,
        index=demographic_dimensions.index,
    )
    return maternal_hemorrhage_rr


def load_hemoglobin_maternal_hemorrhage_paf(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    if key != data_keys.MATERNAL_HEMORRHAGE.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    rr = get_data(
        data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN, location, mean_draw
    )
    proportion = get_data(
        data_keys.HEMOGLOBIN.PREGNANT_PROPORTION_WITH_HEMOGLOBIN_BELOW_70,
        location,
        mean_draw,
    )
    return (rr * proportion + (1 - proportion) - 1) / (rr * proportion + (1 - proportion))


def load_hemoglobin_maternal_disorders_rr(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    if key != data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    groupby_cols = ["age_group_id", "sex_id", "year_id"]
    draw_cols = vi_globals.DRAW_COLUMNS
    rr = extra_gbd.get_hemoglobin_maternal_disorders_rr()
    rr = rr.groupby(groupby_cols)[draw_cols].sum().reset_index()
    rr = reshape_to_vivarium_format(rr, location)
    return rr


def generate_hemoglobin_maternal_disorders_paf(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    # Generate a PAF of hemoglobin on maternal disorders *among pregnant and lactating
    # women and people* (PLW).
    # This used to be done on the research side, see
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/hemoglobin_maternal_disorder_pafs/PAF%20calculation%20investigation%20-%20national%20locations.ipynb
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/Generate%20weights.ipynb
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/hemoglobin_maternal_disorder_pafs/PAF%20aggregation.ipynb
    # It was then copied into NO:
    # https://github.com/ihmeuw/vivarium_research_nutrition_optimization/blob/90d24a8299cd18ef5f79b48af9cd98ace864c073/data_prep/hemoglobin_maternal_disorder_pafs/PAF%20aggregation.ipynb
    demography = _demographics_with_wealth(location)

    hemoglobin_mean_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.MEAN, location, mean_draw),
        location,
    )
    hemoglobin_std_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.STANDARD_DEVIATION, location, mean_draw),
        location,
    )

    hemoglobin_rr = _add_location(
        get_data(
            data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN,
            location,
            mean_draw,
        ).pipe(_among_wra),
        location,
    )
    # The RR is a biological constant and does not vary by year. Drop year levels so
    # the lookup works regardless of which GBD estimation year the RR was pulled from.
    hemoglobin_rr = hemoglobin_rr.droplevel(["year_start", "year_end"])

    pafs = pd.DataFrame(
        columns=["draw_0"] if mean_draw else vi_globals.DRAW_COLUMNS,
        index=demography.index,
        dtype=float,
    )

    for draw in pafs.columns:
        for index in pafs.index:
            # Drop wealth_quintile and year to look up the time-invariant RR
            loc, sex, age_start, age_end = index[0], index[1], index[2], index[3]
            index_without_wealth = index[:-1]
            rr_index = (loc, sex, age_start, age_end)
            assert (index in hemoglobin_mean_plw.index) == (index in hemoglobin_std_plw.index)
            assert (index in hemoglobin_mean_plw.index) == (rr_index in hemoglobin_rr.index)
            if index in hemoglobin_mean_plw.index:
                mean = hemoglobin_mean_plw.loc[index][draw]
                sd = hemoglobin_std_plw.loc[index][draw]
                rr = hemoglobin_rr.loc[rr_index][draw]

                pafs.loc[index, draw] = _hemoglobin_paf(mean, sd, rr)
            else:
                pafs.loc[index, draw] = 0.0

        assert pafs[draw].notnull().all()
        print(f"{draw} done")

    return pafs


@cache
def _hemoglobin_paf(mean: float, sd: float, rr: float) -> float:
    # NOTE: This is an unusual ensemble distribution. We should add functionality to the
    # EnsembleDistribution class to make this easier.
    # The GBD risk called "iron deficiency" is measured in hemoglobin
    risk = gbd_mapping.risk_factors.iron_deficiency
    tmrel = 120  # TODO: Get this at the draw level from GBD!

    pdf = hemoglobin_distribution.hemoglobin_pdf_from_mean_sd(mean, sd)

    with np.errstate(under="ignore"):
        weighted_burden = integrate.quad(
            lambda x: (pdf(x) * rr ** (max(x - tmrel, 0) / risk.relative_risk_scalar)),
            0,
            hemoglobin_distribution.XMAX,
            epsabs=0.0001,
        )[0]

    return (weighted_burden - 1) / weighted_burden


def _only_mean(df):
    return df[(df.index.get_level_values("parameter") == "mean_value")].droplevel("parameter")


def _among_wra(df):
    return df[
        (df.index.get_level_values("sex") == "Female")
        & (df.index.get_level_values("age_start") >= 15)
        & (df.index.get_level_values("age_end") <= 55)
    ]


def get_moderate_hemorrhage_probability(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    hemorrhage_dist_params = data_values.PROBABILITY_MODERATE_MATERNAL_HEMORRHAGE
    # Clip a bit higher than zero to avoid underflow error
    dist = sampling.get_truncnorm_from_quantiles(*hemorrhage_dist_params, lower_clip=0.1)
    # random seed
    rng = np.random.default_rng(get_hash(f"hemorrhage_severity"))
    draw_count = vi_globals.NUM_DRAWS
    moderate_hemorrhage_probability = pd.DataFrame(
        [dist.rvs(size=draw_count, random_state=rng)],
        columns=vi_globals.DRAW_COLUMNS,
        index=["probability"],
    )

    return moderate_hemorrhage_probability


###########################
# Background Morbidity    #
###########################


def load_background_morbidity(key: str, location: str) -> pd.DataFrame:
    all_cause_yld_rate = extra_gbd.get_all_cause_yld_rate(location)
    all_cause_yld_rate = all_cause_yld_rate[
        vi_globals.DEMOGRAPHIC_COLUMNS + vi_globals.DRAW_COLUMNS
    ]
    all_cause_yld_rate = reshape_to_vivarium_format(all_cause_yld_rate, location)

    all_anemia_yld_rate = extra_gbd.get_anemia_yld_rate(location)
    all_anemia_yld_rate = all_anemia_yld_rate.loc[all_anemia_yld_rate.cause_id == 294][
        vi_globals.DEMOGRAPHIC_COLUMNS + vi_globals.DRAW_COLUMNS
    ]
    all_anemia_yld_rate = reshape_to_vivarium_format(all_anemia_yld_rate, location)

    all_md_yld_rate = extra_gbd.get_maternal_disorder_ylds(location, metric_id=3)
    all_md_yld_rate = all_md_yld_rate[
        vi_globals.DEMOGRAPHIC_COLUMNS + vi_globals.DRAW_COLUMNS
    ]
    all_md_yld_rate = reshape_to_vivarium_format(all_md_yld_rate, location)

    anemia_sequelae_yld_rate = extra_gbd.get_anemia_ylds(location, metric_id=3)
    anemia_sequelae_yld_rate = (
        anemia_sequelae_yld_rate.groupby(vi_globals.DEMOGRAPHIC_COLUMNS)[
            vi_globals.DRAW_COLUMNS
        ]
        .sum()
        .reset_index()
    )
    anemia_sequelae_yld_rate = reshape_to_vivarium_format(anemia_sequelae_yld_rate, location)

    pop_md_yld_rate = all_md_yld_rate - anemia_sequelae_yld_rate
    final = all_cause_yld_rate - all_anemia_yld_rate - pop_md_yld_rate
    return final.fillna(0)


###########################
# Hemoglobin Data         #
###########################


def get_hemoglobin_data(key: str, location: str, mean_draw: bool) -> pd.DataFrame:
    me_id = {
        data_keys.HEMOGLOBIN.MEAN: 10487,
        data_keys.HEMOGLOBIN.STANDARD_DEVIATION: 10488,
    }[key]
    correction_factors = data_values.PREGNANCY_CORRECTION_FACTORS[key]
    if mean_draw:
        correction_factors = pd.Series([correction_factors.mean()], index=["draw_0"])

    location_id = utility_data.get_location_id(location)
    hemoglobin_data = gbd.get_modelable_entity_draws(
        me_id=me_id,
        location_id=location_id,
        year_id=None,
        data_type="draws",
    )

    existing_draw_cols = [col for col in hemoglobin_data if col.startswith("draw_")]
    extra_draw_cols = [
        col for col in existing_draw_cols if col not in vi_globals.DRAW_COLUMNS
    ]
    hemoglobin_data = reshape_to_vivarium_format(
        hemoglobin_data.drop(columns=extra_draw_cols, errors="ignore"), location
    )
    if mean_draw:
        hemoglobin_data = hemoglobin_data.mean(axis=1).rename("draw_0").to_frame()

    hemoglobin_data = hemoglobin_data.droplevel(
        ["measure_id", "metric_id", "model_version_id", "modelable_entity_id"]
    )
    hemoglobin_data = hemoglobin_data[
        (hemoglobin_data.index.get_level_values("sex") == "Female")
        & (hemoglobin_data.index.get_level_values("age_start") >= 10)
        & (hemoglobin_data.index.get_level_values("age_end") <= 55)
    ]
    adjusted = hemoglobin_data * correction_factors

    disparity_path = {
        data_keys.HEMOGLOBIN.MEAN: "hemoglobin/mean_disparities",
        data_keys.HEMOGLOBIN.STANDARD_DEVIATION: "hemoglobin/sd_disparities",
    }[key]

    disparities = pd.read_csv(
        paths.DATA_PREP_RESULTS_ROOT / disparity_path / (location.lower() + ".csv"),
    )
    disparities = disparities.set_index(
        [c for c in disparities.columns if c != "value"]
    ).value

    # NOTE: Using disparities from non-pregnant 10-15 year olds!
    result = _distribute_by_disparities_multiplicative(
        adjusted.dropna(how="all"),
        disparities[
            (disparities.index.get_level_values("pregnant") == "pregnant")
            | (disparities.index.get_level_values("age_end") == 15)
        ].droplevel("pregnant"),
        location,
    )
    return result.reindex(
        _demographics_with_wealth(location).droplevel("location").index
    ).fillna(0)


def get_hemoglobin_below_70(key: str, location: str, mean_draw: bool):
    demography = _demographics_with_wealth(location)

    hemoglobin_mean_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.MEAN, location, mean_draw),
        location,
    )
    hemoglobin_std_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.STANDARD_DEVIATION, location, mean_draw),
        location,
    )

    result = pd.DataFrame(
        columns=["draw_0"] if mean_draw else vi_globals.DRAW_COLUMNS,
        index=demography.index,
        dtype=float,
    )

    for draw in result.columns:
        result[draw] = np.nan
        full_data_index = demography.index.intersection(
            hemoglobin_mean_plw.index
        ).intersection(hemoglobin_std_plw.index)
        cdf = hemoglobin_distribution.hemoglobin_cdf_from_mean_sd(
            hemoglobin_mean_plw.loc[full_data_index, draw].values,
            hemoglobin_std_plw.loc[full_data_index, draw].values,
        )
        with np.errstate(under="ignore"):
            result.loc[full_data_index, draw] = cdf([70] * len(full_data_index)).values

        non_full_data_index = demography.index.difference(full_data_index)
        result.loc[non_full_data_index, draw] = 0.0

        assert result[draw].notnull().all()

    return result


def _reformat_hemoglobin_data(data, location):
    data = data.pipe(_among_wra)
    return _add_location(data, location)


def _add_location(data, location):
    return (
        data.reset_index()
        .assign(location=location)
        .set_index(["location"] + data.index.names)
    )


def load_csv_data(key: str, location: str, mean_draw: bool, vehicle: str) -> pd.DataFrame:
    name = CSV_DATA_NAMES[key]
    if "{vehicle}" in name:
        name = name.replace("{vehicle}", vehicle)
    path = paths.DATA_PREP_RESULTS_ROOT / name
    if path.is_dir():
        path = path / (location.lower() + ".csv")
    df = pd.read_csv(path)
    if "sex" in df.columns:
        df = df[df.sex == "Female"]
    if "pregnant" in df.columns:
        # NOTE: Using non-pregnant under-15s and over-50s!
        df = df[(df.pregnant == "pregnant") | (df.age_end == 15) | (df.age_start == 50)].drop(
            columns=["pregnant"]
        )
    # NOTE: Keep the single column named "value" rather than "draw_0". These data prep
    # results are point estimates with no draw dimension, and a "value" column is
    # draw-agnostic: the artifact's "draw == N" filter leaves it untouched. Naming it
    # "draw_0" makes every draw other than 0 select zero columns, which surfaces
    # downstream as "KeyError: 'value'" during setup.
    return df.set_index([c for c in df.columns if c != "value"])


##########################
# Maternal interventions #
##########################


def load_iron_fortification_stillbirth_rr(
    key: str, location: str, mean_draw: bool
) -> pd.DataFrame:
    try:
        distribution = data_values.INTERVENTION_STILLBIRTH_RRS[key]
    except KeyError:
        raise ValueError(f"Unrecognized key {key}")

    dist = sampling.get_lognorm_from_quantiles(*distribution)
    # Don't hash on key because we want simulants to have the same percentile
    # for MMS RR as for BEP
    rng = np.random.default_rng(get_hash(f"stillbirth_rr_{location}"))
    draw_count = vi_globals.NUM_DRAWS
    stillbirth_rr = pd.DataFrame(
        [dist.rvs(size=draw_count, random_state=rng)],
        columns=vi_globals.DRAW_COLUMNS,
        index=["relative_risk"],
    )
    return stillbirth_rr


##############
#   Helpers  #
##############


def reshape_to_vivarium_format(df, location):
    df = vi_utils.reshape(df, value_cols=vi_globals.DRAW_COLUMNS)
    df = vi_utils.scrub_gbd_conventions(df, location)
    df = vi_utils.split_interval(df, interval_column="age", split_column_prefix="age")
    df = vi_utils.split_interval(df, interval_column="year", split_column_prefix="year")
    df = vi_utils.sort_hierarchical_data(df)
    df.index = df.index.droplevel("location")
    return df
