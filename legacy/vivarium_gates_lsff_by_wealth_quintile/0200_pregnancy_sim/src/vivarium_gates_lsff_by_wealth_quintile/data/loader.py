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

import gbd_mapping
import numpy as np
import pandas as pd
import risk_distributions
import vivarium_inputs.validation.sim as validation
from joblib import Memory
from scipy import integrate, stats
from vivarium.framework.artifact import EntityKey
from vivarium.framework.randomness import get_hash
from vivarium_gbd_access import gbd
from vivarium_inputs import core as vi_core
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import interface
from vivarium_inputs import utilities as vi_utils
from vivarium_inputs import utility_data

from vivarium_gates_lsff_by_wealth_quintile.constants import (
    data_keys,
    data_values,
    metadata,
    models,
    paths,
)
from vivarium_gates_lsff_by_wealth_quintile.data import extra_gbd, sampling
from vivarium_gates_lsff_by_wealth_quintile.data.utilities import get_entity
from vivarium_gates_lsff_by_wealth_quintile.utilities import get_random_variable_draws

##Note: need to remove all instances where we limit the size of the data manually. This will be done when RT updates in the input files.

memory = Memory("./.cachedir", verbose=0)

def get_data(lookup_key: str, location: str) -> pd.DataFrame:
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
    mapping = {
        data_keys.POPULATION.LOCATION: load_population_location,
        data_keys.POPULATION.STRUCTURE: load_population_structure,
        data_keys.POPULATION.AGE_BINS: load_age_bins,
        data_keys.POPULATION.DEMOGRAPHY: load_demographic_dimensions,
        data_keys.POPULATION.TMRLE: load_theoretical_minimum_risk_life_expectancy,
        data_keys.POPULATION.INFANT_MALE_PERCENTAGE: load_infant_male_percentage,
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
        data_keys.MATERNAL_DISORDERS.INCIDENT_PROBABILITY: load_pregnant_maternal_disorders_incidence,
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
        data_keys.IRON_FORTIFICATION.COVERAGE: load_iron_fortification_coverage,
        data_keys.IRON_FORTIFICATION.EFFECT_SIZE: load_iron_fortification_effect_size,
        data_keys.IRON_FORTIFICATION.STILLBIRTH_RR: load_iron_fortification_stillbirth_rr,
        # data_keys.POPULATION.BACKGROUND_MORBIDITY: load_background_morbidity,
    }
    return mapping[lookup_key](lookup_key, location)


def load_population_location(key: str, location: str) -> str:
    if key != data_keys.POPULATION.LOCATION:
        raise ValueError(f"Unrecognized key {key}")

    return location


def load_population_structure(key: str, location: str) -> pd.DataFrame:
    base_population_structure = interface.get_population_structure(location)
    pregnancy_end_rate_avg = get_pregnancy_end_incidence(location)
    pregnant_population_structure = (
        pregnancy_end_rate_avg.multiply(base_population_structure["value"], axis=0)
        .assign(location=location)
        .set_index("location", append=True)
    )
    return vi_utils.sort_hierarchical_data(pregnant_population_structure)


def load_age_bins(key: str, location: str) -> pd.DataFrame:
    return interface.get_age_bins()


def load_demographic_dimensions(key: str, location: str) -> pd.DataFrame:
    return interface.get_demographic_dimensions(location)


def load_theoretical_minimum_risk_life_expectancy(key: str, location: str) -> pd.DataFrame:
    return interface.get_theoretical_minimum_risk_life_expectancy()


def load_infant_male_percentage(key: str, location: str) -> pd.DataFrame:
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


def load_standard_data(key: str, location: str) -> pd.DataFrame:
    key = EntityKey(key)
    entity = get_entity(key)
    return interface.get_measure(entity, key.measure, location).droplevel("location")


# TODO: Remove this if/ when Vivarium Inputs implements the change directly
def load_raw_incidence_data(key: str, location: str) -> pd.DataFrame:
    """Temporary function to short circuit around validation issues in Vivarium Inputs"""
    key = EntityKey(key)
    entity = get_entity(key)
    data = vi_core.get_data(entity, key.measure, location)
    data = vi_utils.scrub_gbd_conventions(data, location)
    validation.validate_for_simulation(data, entity, "incidence_rate", location)
    data = vi_utils.split_interval(data, interval_column="age", split_column_prefix="age")
    data = vi_utils.split_interval(data, interval_column="year", split_column_prefix="year")
    return vi_utils.sort_hierarchical_data(data).droplevel("location")


def load_metadata(key: str, location: str):
    key = EntityKey(key)
    entity = get_entity(key)
    entity_metadata = entity[key.measure]
    if hasattr(entity_metadata, "to_dict"):
        entity_metadata = entity_metadata.to_dict()
    return entity_metadata


def load_categorical_paf(key: str, location: str) -> pd.DataFrame:
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

    exp = get_data(risk.EXPOSURE, location)
    rr = get_data(risk.RELATIVE_RISK, location)

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


def get_pregnancy_end_incidence(location: str) -> pd.DataFrame:
    asfr = get_data(data_keys.PREGNANCY.ASFR, location)
    sbr = get_data(data_keys.PREGNANCY.SBR, location)
    sbr = sbr.reset_index(level="year_end", drop=True).reindex(asfr.index, level="year_start")
    incidence_c995 = get_data(data_keys.PREGNANCY.RAW_INCIDENCE_RATE_MISCARRIAGE, location)
    incidence_c374 = get_data(data_keys.PREGNANCY.RAW_INCIDENCE_RATE_ECTOPIC, location)
    pregnancy_end_rate = (
        asfr + asfr.multiply(sbr["value"], axis=0) + incidence_c995 + incidence_c374
    )
    return pregnancy_end_rate.reorder_levels(asfr.index.names)


def load_asfr(key: str, location: str) -> pd.DataFrame:
    asfr = load_standard_data(key, location)
    asfr = asfr.reset_index()
    asfr_pivot = asfr.pivot(
        index=[col for col in metadata.ARTIFACT_INDEX_COLUMNS if col != "location"],
        columns="parameter",
        values="value",
    )
    seed = f"{key}_{location}"
    asfr_draws = sampling.generate_vectorized_lognormal_draws(asfr_pivot, seed)
    return asfr_draws


def load_sbr(key: str, location: str) -> pd.DataFrame:
    sbr = load_standard_data(key, location)
    sbr = sbr.reorder_levels(["parameter", "year_start", "year_end"]).loc["mean_value"]
    return sbr


##############
# LBWSG Data #
##############


def load_lbwsg_exposure(key: str, location: str) -> pd.DataFrame:
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


def load_maternal_csmr(key: str, location: str) -> pd.DataFrame:
    key = EntityKey(key)
    entity = get_entity(key)
    entity.restrictions.yll_age_group_id_end = 15
    return interface.get_measure(entity, key.measure, location).droplevel("location")


def load_maternal_disorders_ylds(key: str, location: str) -> pd.DataFrame:
    groupby_cols = ["age_group_id", "sex_id", "year_id"]
    draw_cols = vi_globals.DRAW_COLUMNS

    all_md_ylds = extra_gbd.get_maternal_disorder_ylds(location)
    all_md_ylds = all_md_ylds[groupby_cols + draw_cols]
    all_md_ylds = reshape_to_vivarium_format(all_md_ylds, location)

    anemia_ylds = extra_gbd.get_anemia_ylds(location)
    anemia_ylds = anemia_ylds.groupby(groupby_cols)[draw_cols].sum().reset_index()
    anemia_ylds = reshape_to_vivarium_format(anemia_ylds, location)

    csmr = get_data(data_keys.MATERNAL_DISORDERS.CSMR, location)
    incidence = load_raw_incidence_data(
        data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location
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


def load_pregnant_maternal_disorders_incidence(key: str, location: str):
    total_incidence = get_data(data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location)
    pregnancy_end_rate = get_pregnancy_end_incidence(location)
    maternal_disorders_incidence = total_incidence / pregnancy_end_rate
    ## We have to normalize, since this comes to a probability with some values > 1
    maternal_disorders_incidence = maternal_disorders_incidence.applymap(
        lambda value: 1 if value > 1 else value
    )
    return maternal_disorders_incidence.fillna(0)


def load_maternal_disorders_mortality_probability(key: str, location: str):
    total_csmr = get_data(data_keys.MATERNAL_DISORDERS.CSMR, location)
    total_incidence = get_data(data_keys.MATERNAL_DISORDERS.RAW_INCIDENCE_RATE, location)
    mortality_probability = total_csmr / total_incidence
    return mortality_probability.fillna(0)


def load_pregnant_maternal_hemorrhage_incidence(key: str, location: str):
    mh_incidence = get_data(data_keys.MATERNAL_HEMORRHAGE.RAW_INCIDENCE_RATE, location)
    mh_csmr = get_data(data_keys.MATERNAL_HEMORRHAGE.CSMR, location)
    pregnancy_end_rate = get_pregnancy_end_incidence(location)
    maternal_hemorrhage_incidence = (mh_incidence - mh_csmr) / pregnancy_end_rate
    ## I'm not as sure we need to normalize here, but we may as well.
    maternal_hemorrhage_incidence = maternal_hemorrhage_incidence.applymap(
        lambda value: 1 if value > 1 else value
    )
    return maternal_hemorrhage_incidence.fillna(0)


def load_hemoglobin_maternal_hemorrhage_rr(key: str, location: str) -> pd.DataFrame:
    if key != data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    distribution = data_values.RR_MATERNAL_HEMORRHAGE_ATTRIBUTABLE_TO_HEMOGLOBIN
    dist = sampling.get_lognorm_from_quantiles(*distribution)
    # Get a DataFrame with the desired index
    demographic_dimensions = get_data(data_keys.POPULATION.DEMOGRAPHY, location)

    rng = np.random.default_rng(get_hash(f"{key}_{location}"))
    draw_count = vi_globals.NUM_DRAWS
    maternal_hemorrhage_rr = pd.DataFrame(
        np.tile(
            dist.rvs(size=draw_count, random_state=rng), (len(demographic_dimensions), 1)
        ),
        columns=vi_globals.DRAW_COLUMNS,
        index=demographic_dimensions.index,
    )
    return maternal_hemorrhage_rr


def load_hemoglobin_maternal_hemorrhage_paf(key: str, location: str) -> pd.DataFrame:
    if key != data_keys.MATERNAL_HEMORRHAGE.PAF_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    rr = get_data(data_keys.MATERNAL_HEMORRHAGE.RR_ATTRIBUTABLE_TO_HEMOGLOBIN, location)
    proportion = get_data(
        data_keys.HEMOGLOBIN.PREGNANT_PROPORTION_WITH_HEMOGLOBIN_BELOW_70, location
    )
    return (rr * proportion + (1 - proportion) - 1) / (rr * proportion + (1 - proportion))


def load_hemoglobin_maternal_disorders_rr(key: str, location: str) -> pd.DataFrame:
    if key != data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN:
        raise ValueError(f"Unrecognized key {key}")

    groupby_cols = ["age_group_id", "sex_id", "year_id"]
    draw_cols = vi_globals.DRAW_COLUMNS
    rr = extra_gbd.get_hemoglobin_maternal_disorders_rr()
    rr = rr.groupby(groupby_cols)[draw_cols].sum().reset_index()
    rr = reshape_to_vivarium_format(rr, location)
    return rr


def generate_hemoglobin_maternal_disorders_paf(key: str, location: str) -> pd.DataFrame:
    # Generate a PAF of hemoglobin on maternal disorders *among pregnant and lactating
    # women and people* (PLW).
    # This used to be done on the research side, see
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/hemoglobin_maternal_disorder_pafs/PAF%20calculation%20investigation%20-%20national%20locations.ipynb
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/Generate%20weights.ipynb
    # https://github.com/ihmeuw/vivarium_research_iv_iron/blob/48caab2eede9d5ccf45af2bf9926c3665dc536b5/parameter_aggregation/hemoglobin_maternal_disorder_pafs/PAF%20aggregation.ipynb
    # It was then copied into NO:
    # https://github.com/ihmeuw/vivarium_research_nutrition_optimization/blob/90d24a8299cd18ef5f79b48af9cd98ace864c073/data_prep/hemoglobin_maternal_disorder_pafs/PAF%20aggregation.ipynb
    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, location)

    hemoglobin_mean_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.MEAN, location), location,
    )
    hemoglobin_std_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.STANDARD_DEVIATION, location), location,
    )

    hemoglobin_rr = _add_location(
        get_data(data_keys.MATERNAL_DISORDERS.RR_ATTRIBUTABLE_TO_HEMOGLOBIN, location).pipe(
            _among_wra
        ),
        location,
    )

    # The GBD risk called "iron deficiency" is measured in hemoglobin
    risk = gbd_mapping.risk_factors.iron_deficiency
    tmrel = 120  # TODO: Get this at the draw level from GBD!

    pafs = pd.DataFrame(columns=vi_globals.DRAW_COLUMNS, index=demography.index, dtype=float)

    for draw in pafs.columns:
        for index in pafs.index:
            assert (
                (index in hemoglobin_mean_plw.index)
                == (index in hemoglobin_std_plw.index)
                == (index in hemoglobin_rr.index)
            )
            if index in hemoglobin_mean_plw.index:
                # NOTE: This is an unusual ensemble distribution. We should add functionality to the
                # EnsembleDistribution class to make this easier.
                mean = hemoglobin_mean_plw.loc[index][draw]
                sd = hemoglobin_std_plw.loc[index][draw]

                hemoglobin_distribution_gamma_part, hemoglobin_distribution_mgumbel_part = _hemoglobin_distribution_parts_from_mean_sd(mean, sd)

                def pdf(x):
                    return data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.GAMMA_DISTRIBUTION_WEIGHT * hemoglobin_distribution_gamma_part.pdf(
                        x
                    ) + data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.MIRROR_GUMBEL_DISTRIBUTION_WEIGHT * hemoglobin_distribution_mgumbel_part.pdf(
                        x
                    )

                rr = hemoglobin_rr.loc[index][draw]
                with np.errstate(under="ignore"):
                    weighted_burden = integrate.quad(
                        lambda x: (
                            pdf(x) * rr ** (max(x - tmrel, 0) / risk.relative_risk_scalar)
                        ),
                        0,
                        data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.XMAX,
                        epsabs=0.0001,
                    )[0]

                pafs.loc[index, draw] = (weighted_burden - 1) / weighted_burden
            else:
                pafs.loc[index, draw] = 0.0

        assert pafs[draw].notnull().all()

    return pafs


def _only_mean(df):
    return df[(df.index.get_level_values("parameter") == "mean_value")].droplevel("parameter")


def _among_wra(df):
    return df[
        (df.index.get_level_values("sex") == "Female")
        & (df.index.get_level_values("age_start") >= 15)
        & (df.index.get_level_values("age_end") <= 55)
    ]


def get_moderate_hemorrhage_probability(key: str, location: str) -> pd.DataFrame:
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


def get_hemoglobin_data(key: str, location: str) -> pd.DataFrame:
    me_id = {
        data_keys.HEMOGLOBIN.MEAN: 10487,
        data_keys.HEMOGLOBIN.STANDARD_DEVIATION: 10488,
    }[key]
    correction_factors = data_values.PREGNANCY_CORRECTION_FACTORS[key]

    location_id = utility_data.get_location_id(location)
    hemoglobin_data = gbd.get_modelable_entity_draws(me_id=me_id, location_id=location_id)

    existing_draw_cols = [col for col in hemoglobin_data if col.startswith("draw_")]
    extra_draw_cols = [
        col for col in existing_draw_cols if col not in vi_globals.DRAW_COLUMNS
    ]
    hemoglobin_data = hemoglobin_data.drop(columns=extra_draw_cols, errors="ignore")

    hemoglobin_data = reshape_to_vivarium_format(hemoglobin_data, location)
    return hemoglobin_data * correction_factors


def get_hemoglobin_below_70(key: str, location: str):
    demography = get_data(data_keys.POPULATION.DEMOGRAPHY, location)

    hemoglobin_mean_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.MEAN, location), location,
    )
    hemoglobin_std_plw = _reformat_hemoglobin_data(
        get_data(data_keys.HEMOGLOBIN.STANDARD_DEVIATION, location), location,
    )

    result = pd.DataFrame(
        columns=vi_globals.DRAW_COLUMNS, index=demography.index, dtype=float
    )

    for draw in result.columns:
        for index in demography.index:
            if index in hemoglobin_mean_plw.index and index in hemoglobin_std_plw.index:
                mean = hemoglobin_mean_plw.loc[index][draw]
                sd = hemoglobin_std_plw.loc[index][draw]
                
                hemoglobin_distribution_gamma_part, hemoglobin_distribution_mgumbel_part = _hemoglobin_distribution_parts_from_mean_sd(
                    mean, sd
                )

                def cdf(x):
                    gamma_cdf = hemoglobin_distribution_gamma_part.cdf(x)
                    # NOTE: There is a bug in this CDF function -- it is reversed!
                    # https://github.com/ihmeuw/risk_distributions/issues/62
                    mgumbel_cdf = (1 - hemoglobin_distribution_mgumbel_part.cdf(x))
                    return data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.GAMMA_DISTRIBUTION_WEIGHT * gamma_cdf + data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.MIRROR_GUMBEL_DISTRIBUTION_WEIGHT * mgumbel_cdf

                with np.errstate(under="ignore"):
                    under_70 = cdf(70)

                result.loc[index, draw] = under_70
            else:
                result.loc[index, draw] = 0.0

        assert result[draw].notnull().all()

    return result

def _hemoglobin_distribution_parts_from_mean_sd(mean, sd):
    # NOTE: This is an unusual ensemble distribution. We should add functionality to the
    # EnsembleDistribution class to make this easier.
    x_min = 0
    x_max = data_values.HEMOGLOBIN_DISTRIBUTION_PARAMETERS.XMAX
    gamma_params = risk_distributions.risk_distributions.Gamma.get_parameters(
        mean=mean, sd=sd
    )
    # NOTE: We have to override these, otherwise Gamma is overly conservative in what values
    # are computable
    # https://github.com/ihmeuw/risk_distributions/issues/61
    gamma_params["x_min"] = x_min
    gamma_params["x_max"] = x_max
    hemoglobin_distribution_gamma_part = (
        risk_distributions.risk_distributions.Gamma(gamma_params)
    )

    # NOTE: Forced to duplicate https://github.com/ihmeuw/risk_distributions/blob/a9ed9d7e8372590018355012a7a7ffefa87b0819/src/risk_distributions/risk_distributions.py#L428-L434
    # because it doesn't permit the custom x_min and x_max, and these are used in calculating the others
    mgumbel_params = {
        "loc": [x_max - mean - (np.euler_gamma * np.sqrt(6) / np.pi * sd)],
        "scale": [np.sqrt(6) / np.pi * sd],
        "x_min": [x_min],
        "x_max": [x_max],
    }
    hemoglobin_distribution_mgumbel_part = (
        risk_distributions.risk_distributions.MirroredGumbel(mgumbel_params)
    )
    return hemoglobin_distribution_gamma_part, hemoglobin_distribution_mgumbel_part

def _reformat_hemoglobin_data(data, location):
    data = data.droplevel(
        ["measure_id", "metric_id", "model_version_id", "modelable_entity_id"]
    ).pipe(_among_wra)
    return _add_location(data, location)

def _add_location(data, location):
    return (
        data.reset_index()
        .assign(location=location)
        .set_index(["location"] + data.index.names)
    )

##########################
# Maternal interventions #
##########################


def load_iron_fortification_coverage(key: str, location: str) -> pd.DataFrame:
    df = pd.read_csv(
        paths.CSV_RAW_DATA_ROOT
        / "baseline_iron_fortification_coverage"
        / (location + ".csv"),
        index_col=0,
    )
    df = df.drop(columns=["location_id", "location_name"]).set_index(["draw"]).T
    return df


def load_iron_fortification_effect_size(key: str, location: str) -> pd.DataFrame:
    loc, scale = data_values.IRON_FORTIFICATION_EFFECT_SIZE
    dist = stats.norm(loc, scale)
    rng = np.random.default_rng(get_hash(f"iron_fortification_effect_size_{location}"))
    draw_count = vi_globals.NUM_DRAWS
    iron_fortification_effect_size = pd.DataFrame(
        [dist.rvs(size=draw_count, random_state=rng)],
        columns=vi_globals.DRAW_COLUMNS,
        index=["value"],
    )
    return iron_fortification_effect_size


def load_iron_fortification_stillbirth_rr(key: str, location: str) -> pd.DataFrame:
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
