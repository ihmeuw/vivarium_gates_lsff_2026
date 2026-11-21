"""
Shared code for the India HCES 2023-24 extraction notebooks (01_extract_hces_rice.ipynb for rice,
02_extract_hces_wheat.ipynb for wheat).

Everything here was copied verbatim between the notebooks: reading the tab exports, building
the household table, assigning wealth quintiles, building the person-level table, and the
weighted summaries. The vehicle-specific parts (item codes, purchased share, government rice,
per-meal amounts) stay in the notebooks.

The notebooks run from this directory (Snakemake does ``cd hces`` before papermill), so they
import this as ``import hces_utils``.
"""

import pathlib

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.decomposition import PCA
from statsmodels.stats.weightstats import DescrStatsW

DATA_DIR = "/snfs1/Project/simulation_science/IND_HOUSEHOLD_CONSUMPTION_EXPENDITURE_SURVEY_HCES_2023_2024"

# The 16 columns the tab exports split the 38-byte fixed-width common ID into, with the
# fixed-width field widths used to reassemble it.
COMMON_ID_COLUMNS = [
    "survey_name",
    "year",
    "fsu_serial_no",
    "sector",
    "state",
    "nss_region",
    "district",
    "stratum",
    "sub_stratum",
    "panel",
    "sub_sample",
    "fod_sub_region",
    "sample_su_no",
    "sample_sub_division_no",
    "second_stage_stratum_no",
    "sample_household_no",
]
COMMON_ID_WIDTHS = [4, 4, 5, 1, 2, 3, 2, 2, 2, 2, 1, 4, 2, 1, 1, 2]

# Row counts from the MoSPI manifest in the package readme. A mismatch means a truncated
# Nesstar export -- they fail silently, and it happened during extraction, so always check.
MANIFEST_ROW_COUNTS = {
    1: 261_953,
    2: 1_107_221,
    3: 261_953,
    5: 12_754_437,
    7: 261_953,
    11: 261_953,
}

# Level 5 (consumption) columns. Each notebook reads level 5 with its own item-code filter.
CONSUMPTION_COLUMNS = [
    "q_num",
    "level",
    "item_code",
    "consumption_amt_home_produce",
    "consumption_value_home_produce",
    "total_consumption_amt",
    "total_consumption_value",
    "source",
    "multiplier",
]

POSSESSION_COLUMNS = [
    "tv",
    "radio",
    "laptop",
    "mobile_handset",
    "bicycle",
    "motorcycle",
    "motor_car",
    "trucks",
    "animal_cart",
    "refrigerator",
    "washing_machine",
    "air_conditioner",
]

DEMOGRAPHIC_QUINTILE_GROUPS = ["sex", "age_start", "age_end", "wealth_quintile"]
AGE_BIN_EDGES = [0, 5, 15, 30, 50, 125]


def build_common_id(df):
    """Reassemble the 38-character common ID."""
    common_id = ""
    for col, width in zip(COMMON_ID_COLUMNS, COMMON_ID_WIDTHS):
        fill_val = "0"
        side = "left"
        if col in ("sample_su_no", "sample_sub_division_no", "panel"):
            # These three arrive blank-padded on the right; any convention works
            # as long as it's consistent across levels, since the ID is only a join key.
            fill_val = " "
            side = "right"
        values = df[col].fillna(fill_val).str.pad(width, fillchar=fill_val, side=side)
        assert (values.str.len() == width).all()
        common_id = common_id + values
    return common_id


def read_hces_level(level_no, names, keep_id_fields=False, row_filter=None):
    """Read one 2023-24 tab export: no header, common ID split across the first 16 columns."""
    path = f"{DATA_DIR}/IND_HCES_2023_2024_LVL_{level_no:02d}_TAB_Y2026M09D03.TXT"
    kwargs = dict(
        sep="\t",
        header=None,
        names=COMMON_ID_COLUMNS + names,
        # Keep the ID fields as text: they only exist to rebuild the common ID, and
        # numeric parsing would corrupt it (leading zeros, blanks becoming floats).
        dtype={c: str for c in COMMON_ID_COLUMNS},
    )
    if row_filter is None:
        df = pd.read_csv(path, **kwargs)
        n_rows = len(df)
    else:
        # Level 5 is 12.7M rows; filter each chunk before assembling to keep memory sane.
        chunks, n_rows = [], 0
        for chunk in pd.read_csv(path, chunksize=2_000_000, **kwargs):
            n_rows += len(chunk)
            chunks.append(row_filter(chunk))
        df = pd.concat(chunks, ignore_index=True)
    assert n_rows == MANIFEST_ROW_COUNTS[level_no], (level_no, n_rows)
    df.insert(0, "common_id", build_common_id(df))
    if not keep_id_fields:
        df = df.drop(columns=COMMON_ID_COLUMNS)
    return df


def read_consumption(item_codes):
    """Read level 5 (consumption), keeping only the given item codes."""
    return read_hces_level(
        5,
        names=CONSUMPTION_COLUMNS,
        row_filter=lambda df: df[df.item_code.isin(item_codes)],
    )


def _read_level_3():
    level_3 = read_hces_level(
        3,
        names=[
            "questionnaire_no",
            "level",
            "hh_size",
            "household_member_economic_activity_last_365_days",
            "nco_2015_code",
            "nic_2008_code",
            "max_income_source_last_365_days",
            "major_income_source_self_employment_sector",
            "major_income_regular_wage_sector",
            "major_income_casual_labour_sector",
            "household_type",
            "head_religion",
            "head_social_group",
            "land_ownership",
            "land_type",
            "total_owned_land_area",
            "has_dwelling",
            "dwelling_unit_type",
            "cooking_energy_source",
            "lighting_energy_source",
            "ration_card_type",
            "rural_rent_rate_availability",
            "pmgky_benefit",
            "multiplier",
        ],
    )
    assert level_3.common_id.is_unique

    for col in ["land_ownership", "has_dwelling"]:
        level_3[col] = level_3[col].map({1: 1.0, 2: 0.0}).astype(float)

    level_3.loc[level_3.land_ownership == 0, "total_owned_land_area"] = 0

    level_3["dwelling_unit_type"] = level_3.dwelling_unit_type.map(
        {1: "owned", 2: "hired", 3: "others"}
    )
    level_3["house_ownership"] = (level_3.has_dwelling == 1) & (
        level_3.dwelling_unit_type == "owned"
    )
    level_3["cooking_energy_source"] = level_3.cooking_energy_source.map(
        {
            1: "firewood",
            2: "liquid petroleum gas",
            3: "other natural gas",
            4: "dung",
            5: "kerosene",
            6: "coal",
            7: "gobar",
            8: "other biogas",
            10: "charcoal",
            11: "electricity",
            12: "no cooking",
            9: "other",
        }
    )
    level_3["lighting_energy_source"] = level_3.lighting_energy_source.map(
        {
            1: "electricity",
            2: "kerosene",
            3: "other oil",
            4: "gas",
            5: "candle",
            6: "no lighting",
            9: "other",
        }
    )
    return level_3


def _read_level_2():
    """Level 2: one row per household member."""
    return read_hces_level(
        2,
        names=[
            "questionnaire_no",
            "level",
            "person_serial_no",
            "relation_to_head_code",
            "gender",
            "age_years",
            "marital_status_code",
            "highest_education_level_code",
            "total_years_education",
            "internet_use_last_30_days",
            "days_away_from_home_last_30_days",
            "usual_daily_meals",
            "meals_from_school_balwadi_last_30_days",
            "meals_from_employer_last_30_days",
            "meals_others_last_30_days",
            "meals_paid_last_30_days",
            "meals_at_home_last_30_days",
            "member_status_on_revisit",
            "fdq_orig_number",
            "multiplier",
        ],
    )


def _read_level_7(household_members_raw):
    level_7 = read_hces_level(
        7,
        names=[
            "questionnaire_no",
            "level",
            "kerosene",
            "lpg_subsidy",
            "num_lpg_subsidy",
            "free_electricity",
            "attend_education",
            "num_attend_govt_ed",
            "num_attend_priv_ed",
            "free_textbooks",
            "num_free_textbooks",
            "free_stationary",
            "num_free_stationary",
            "free_school_bag",
            "num_free_school_bag",
            "other_free_items",
            "num_other_free_items",
            "fee_waiver",
            "num_fee_waiver",
            "pmjay_beneficiary",
            "num_pmjay_beneficiaries",
            "hospitalization_last_365_days",
            "medical_treatment_benefit",
            "num_medical_benefit",
            "medical_benefit_amount",
            "online_purchase_1",
            "online_purchase_2",
            "online_purchase_3",
            "online_purchase_4",
            "online_purchase_5",
            "multiplier",
        ],
    )
    assert level_7.common_id.is_unique

    # Level 2 asks every member about internet use in the last 30 days, and we use
    # "any member used the internet" as the household indicator.
    household_internet = (
        (household_members_raw.internet_use_last_30_days == 1)
        .astype(float)
        .groupby(household_members_raw.common_id)
        .max()
        .rename("internet")
    )
    return level_7.merge(household_internet, on="common_id", how="left", validate="1:1")


def _read_level_11():
    level_11 = read_hces_level(
        11,
        names=[
            "questionnaire_no",
            "level",
            "online_clothing",
            "online_footwear",
            "online_furniture",
            "online_mobile_handset",
            "online_personal_goods",
            "online_recreation_goods",
            "online_cooking_household",
            "online_crockery",
            "online_sports_goods",
            "online_med_equip",
            "online_bedding",
            "free_laptop",
            "num_free_laptop",
            "free_tablet",
            "num_free_tablet",
            "free_mobile",
            "num_free_mobile",
            "free_bicycle",
            "num_free_bicycle",
            "free_motorcycle",
            "num_free_motorcycle",
            "free_clothing",
            "num_free_clothing",
            "free_footwear",
            "num_free_footwear",
            "other_free_items_dgq",
            "num_other_free_items_dgq",
            *POSSESSION_COLUMNS,
            "multichannel_tv_type",
            "multiplier",
        ],
    )
    assert level_11.common_id.is_unique
    for col in POSSESSION_COLUMNS:
        level_11[col] = level_11[col].fillna(0.0)
    return level_11


def load_households():
    """
    Read the household-level tab exports and merge them into one row per household.

    Returns ``(households, household_members_raw)``. Level 2 (one row per member) is read
    once, for the household internet indicator, and returned so the notebook can reuse it
    for individual consumption.
    """
    level_1 = read_hces_level(
        1,
        names=[
            "questionnaire_no",
            "level",
            "survey_code",
            "reason_for_substitution_code",
            "multiplier",
        ],
        keep_id_fields=True,
    )
    assert level_1.common_id.is_unique

    level_3 = _read_level_3()
    household_members_raw = _read_level_2()
    level_7 = _read_level_7(household_members_raw)
    level_11 = _read_level_11()

    level_specific_columns = ["level", "questionnaire_no"]

    def drop_level_specific(df):
        return df[[c for c in df.columns if c not in level_specific_columns]]

    household_levels = [level_1, level_3, level_7, level_11]
    households = drop_level_specific(household_levels[0])
    for additional_level in household_levels[1:]:
        common_columns = (set(households.columns) & set(additional_level.columns)) - {
            "common_id"
        }
        households = households.merge(
            drop_level_specific(additional_level),
            on="common_id",
            validate="1:1",
            how="outer",
        )
        for column in common_columns:
            assert (households[f"{column}_x"] == households[f"{column}_y"]).all()
            households[column] = households[f"{column}_x"]
            households = households.drop(columns=[f"{column}_x", f"{column}_y"])

    households["sector"] = households.sector.map({"1": "rural", "2": "urban"})
    return households, household_members_raw


def assign_wealth_quintiles(households, diagnostics=False):
    """
    Assign each household a wealth quintile from an asset index.

    The index is a PCA score of household assets, fit separately for urban and rural
    households and put on a common scale by regressing the national score on each sector's
    score. Quintile cutoffs are weighted by population (household size x survey multiplier),
    so each quintile holds about a fifth of people, not of households.

    Returns ``(wealth_info, wealth_predictors)``: a DataFrame indexed like ``households`` with
    the predictors, the scores and ``wealth_quintile``, and the names of the predictor columns
    (after the energy sources are expanded to dummies). With ``diagnostics=True``, shows the
    PCA loadings and the OLS summaries, which are only available during the fit.
    """
    from IPython.display import display

    wealth_info = households[
        [
            "sector",
            "hh_size",
            "multiplier",
            # Section/level 4
            "land_ownership",
            # 'total_owned_land_area',
            "has_dwelling",
            "house_ownership",
            "cooking_energy_source",
            "lighting_energy_source",
            # Any member used the internet in the last 30 days (level 2)
            "internet",
            # Section 4.3
            *POSSESSION_COLUMNS,
        ]
    ].copy()

    for column in ["cooking_energy_source", "lighting_energy_source"]:
        dummies = pd.get_dummies(wealth_info[column], prefix=column)
        wealth_info = wealth_info.drop(column, axis=1)
        wealth_info = pd.concat([wealth_info, dummies], axis=1)

    non_predictors = ["sector", "multiplier", "hh_size"]
    wealth_predictors = [c for c in wealth_info.columns if c not in non_predictors]

    # National score
    pca = PCA(n_components=1)
    pca.fit(wealth_info.drop(columns=non_predictors).dropna(how="any"))
    if diagnostics:
        print("national")
        display(
            pd.DataFrame(
                {
                    "column": wealth_info.drop(columns=non_predictors).columns,
                    "scores": pd.Series(pca.components_[0]).astype(float),
                }
            ).sort_values("scores")
        )
    wealth_info["common_score"] = pca.transform(wealth_info.drop(columns=non_predictors))

    # Score within each sector
    for sector in ["urban", "rural"]:
        sector_rows = wealth_info.sector == sector
        pca = PCA(n_components=1)
        pca.fit(wealth_info[sector_rows][wealth_predictors].dropna(how="any"))
        if diagnostics:
            print(sector)
            display(
                pd.DataFrame(
                    {
                        "column": wealth_predictors,
                        "scores": pd.Series(pca.components_[0]).astype(float),
                    }
                ).sort_values("scores")
            )
        wealth_info.loc[sector_rows, f"{sector}_score"] = pca.transform(
            wealth_info[sector_rows][wealth_predictors]
        )

    # Put each sector's score on the national scale
    for sector in ["urban", "rural"]:
        sector_rows = wealth_info.sector == sector
        fit = sm.OLS(
            wealth_info[sector_rows][["common_score"]],
            sm.add_constant(wealth_info[sector_rows][[f"{sector}_score"]]),
        ).fit()
        if diagnostics:
            print(sector)
            print(fit.summary2())
        wealth_info.loc[sector_rows, "combined_score"] = fit.predict(
            sm.add_constant(wealth_info[sector_rows][[f"{sector}_score"]])
        )

    wealth_info["weighted_household_size"] = wealth_info.hh_size * wealth_info.multiplier
    quintile_cutoffs = DescrStatsW(
        data=wealth_info.combined_score,
        weights=wealth_info.weighted_household_size,
    ).quantile(probs=np.linspace(0, 1, 6))

    wealth_info["wealth_quintile"] = pd.cut(
        wealth_info.combined_score,
        quintile_cutoffs,
        labels=[1, 2, 3, 4, 5],
        include_lowest=True,
    )
    assert wealth_info.wealth_quintile.notnull().all()
    return wealth_info, wealth_predictors


def load_household_members(household_members_raw, households):
    """
    One row per household member with complete data, with sex, age group and wealth quintile.

    ``households`` must already have ``wealth_quintile``. Transgender members get a null
    ``sex``, because the survey doesn't record their sex.
    """
    household_members = household_members_raw[
        ["common_id", "gender", "age_years", "multiplier"]
        + [c for c in household_members_raw.columns if "meals" in c]
    ]

    # Null is effectively 0 for these high-missingness columns, even though there are
    # actual zeros too.
    for col in [
        "meals_from_school_balwadi_last_30_days",
        "meals_from_employer_last_30_days",
        "meals_others_last_30_days",
        "meals_paid_last_30_days",
    ]:
        household_members[col] = household_members[col].fillna(0)

    # Complete-case analysis
    household_members = household_members.dropna(how="any").copy()

    household_members["gender"] = household_members.gender.map(
        {1: "Male", 2: "Female", 3: "Transgender"}
    )
    household_members = household_members.merge(
        households[["common_id", "wealth_quintile"]],
        on="common_id",
        validate="m:1",
        how="left",
    )
    assert household_members.wealth_quintile.notnull().all()

    household_members["sex"] = household_members.gender.replace({"Transgender": np.nan})
    age_group = pd.IntervalIndex(
        pd.cut(
            household_members.age_years,
            AGE_BIN_EDGES,
            right=False,
            include_lowest=True,
        )
    )
    household_members["age_start"] = age_group.left
    household_members["age_end"] = age_group.right
    return household_members


def add_total_meals(household_members):
    """
    Add ``meals``: each member's total meals in the last 30 days, at home and away.

    Vehicle amounts are measured per household, then shared out to members in proportion
    to their meals, so this total is what splits a household's consumption between people.
    """
    household_members["meals"] = (
        household_members.meals_at_home_last_30_days.fillna(0)
        + household_members.meals_from_employer_last_30_days.fillna(0)
        + household_members.meals_from_school_balwadi_last_30_days.fillna(0)
        + household_members.meals_paid_last_30_days.fillna(0)
        + household_members.meals_others_last_30_days.fillna(0)
    )
    return household_members


# https://stackoverflow.com/a/2415343/ with some tweaks
def weighted_avg_and_std(values, weights):
    """
    Return the weighted average and standard deviation.

    The weights are in effect first normalized so that they sum to 1 (and so they must not
    all be 0).

    values, weights -- NumPy ndarrays with the same shape.
    """
    is_nan = np.isnan(values)
    values = values[~is_nan]
    # The tab exports parse the multiplier as int64, and weights.sum()**2 overflows
    # int64 in the effective-sample-size line; promote to float.
    weights = weights[~is_nan].astype(float)
    average = np.average(values, weights=weights)
    # Fast and numerically precise:
    variance = np.average((values - average) ** 2, weights=weights)
    return pd.Series(
        {
            "mean": average,
            "sd": np.sqrt(variance),
            # https://ngreifer.github.io/WeightIt/reference/ESS.html
            "effective_sample_size": (weights.sum() ** 2) / (weights**2).sum(),
        }
    )


def weighted_summary(df, values, weights=lambda df: df.multiplier, by=DEMOGRAPHIC_QUINTILE_GROUPS):
    """
    Weighted mean, SD and effective sample size of ``values(group)`` within each group.

    ``values`` and ``weights`` take a group's rows and return an array, for example
    ``lambda df: df.wheat_g_per_day`` and ``lambda df: df.multiplier * df.wheat``. ``by``
    defaults to sex, age group and wealth quintile, the stratification the results files use.
    """
    return (
        df.groupby(by, observed=True)
        .apply(lambda group: weighted_avg_and_std(values(group), weights=weights(group)))
        .sort_index()
    )


def save_data(series, name, vehicle, results_dir="../results"):
    """Write ``series`` to ``{results_dir}/{name}/india.csv`` in the results file format."""
    path = f"{results_dir}/{name}/india.csv"
    pathlib.Path(path).parent.mkdir(exist_ok=True, parents=True)
    (
        series.rename("value")
        .reset_index()
        .assign(vehicle_name=vehicle)
        .to_csv(path, index=False)
    )
