import pandas as pd
from gbd.enums import Measures, Metrics
from loguru import logger
from vivarium.gbd_mapping import sequelae
from vivarium_gbd_access import constants as gbd_constants
from vivarium_gbd_access import gbd
from vivarium_gbd_access.gbd import measures
from vivarium_gbd_access.gbd.base_data import get_machinery_estimates
from vivarium_gbd_access.utilities import cache
from vivarium_inputs import utility_data

from vivarium_gates_lsff_2026_maternal.constants import data_keys, metadata, paths
from vivarium_gates_lsff_2026_maternal.data import utilities

HEMOGLOBIN_RELEASE_ID = 33
HEMOGLOBIN_PREGNANT_MEAN_ME_ID = 28869


@cache
def load_lbwsg_exposure(location: str):
    entity = utilities.get_entity(data_keys.LBWSG.EXPOSURE)
    location_id = utility_data.get_location_id(location)
    data = measures.get_birth_exposure(
        entity_id=entity.gbd_id,
        location_id=location_id,
        year_id=2022,
        data_type="draws",
        release_id=gbd_constants.RELEASE_IDS.GBD_2021,  # LBWSG not re-estimated for GBD 2023
    )
    return data


@cache
def get_all_cause_yld_rate(location: str):
    entity = utilities.get_entity("cause.all_causes.ylds")
    location_id = utility_data.get_location_id(location)
    release_id = gbd_constants.RELEASE_IDS.GBD_2023
    # NOTE: an omitted dimension defaults to an aggregate, so all are passed explicitly.
    data = get_machinery_estimates(
        entity="cause",
        entity_id=entity.gbd_id,
        release_id=release_id,
        estimates="draws",
        measure_id=[Measures.YLD],
        metric_id=Metrics.RATE,
        location_id=location_id,
        sex_id=gbd_constants.SEX.MALE + gbd_constants.SEX.FEMALE,
        age_group_id=gbd.get_age_group_id(release_id),
        year_id=metadata.GBD_EXTRACT_YEAR,
    )
    return data


@cache
def get_maternal_disorder_ylds(location: str):
    entity = utilities.get_entity(data_keys.MATERNAL_DISORDERS.YLDS)
    location_id = utility_data.get_location_id(location)
    release_id = gbd_constants.RELEASE_IDS.GBD_2023
    data = get_machinery_estimates(
        entity="cause",
        entity_id=entity.gbd_id,
        release_id=release_id,
        estimates="draws",
        measure_id=[Measures.YLD],
        metric_id=Metrics.RATE,
        location_id=location_id,
        sex_id=gbd_constants.SEX.MALE + gbd_constants.SEX.FEMALE,
        age_group_id=gbd.get_age_group_id(release_id),
        year_id=metadata.GBD_EXTRACT_YEAR,
    )
    return data


@cache
def get_anemia_ylds(location: str):
    anemia_sequelae = [
        sequelae.mild_anemia_due_to_maternal_hemorrhage,
        sequelae.moderate_anemia_due_to_maternal_hemorrhage,
        sequelae.severe_anemia_due_to_maternal_hemorrhage,
    ]
    anemia_ids = [s.gbd_id for s in anemia_sequelae]
    location_id = utility_data.get_location_id(location)
    release_id = gbd_constants.RELEASE_IDS.GBD_2023
    data = get_machinery_estimates(
        entity="sequela",
        entity_id=anemia_ids,
        release_id=release_id,
        estimates="draws",
        measure_id=[Measures.YLD],
        metric_id=Metrics.RATE,
        location_id=location_id,
        sex_id=gbd_constants.SEX.MALE + gbd_constants.SEX.FEMALE,
        age_group_id=gbd.get_age_group_id(release_id),
        year_id=metadata.GBD_EXTRACT_YEAR,
    )
    return data


@cache
def get_anemia_yld_rate(location: str):
    location_id = utility_data.get_location_id(location)
    release_id = gbd_constants.RELEASE_IDS.GBD_2023
    # The impairment-cause pair restricts to cause 294 in the query, so callers no
    # longer filter on cause_id themselves.
    data = get_machinery_estimates(
        entity="impairment-cause",
        entity_id=[192, 294],
        release_id=release_id,
        estimates="draws",
        measure_id=[Measures.YLD],
        metric_id=Metrics.RATE,
        location_id=location_id,
        sex_id=gbd_constants.SEX.MALE + gbd_constants.SEX.FEMALE,
        age_group_id=gbd.get_age_group_id(release_id),
        year_id=metadata.GBD_EXTRACT_YEAR,
    )
    return data


@cache
def get_hemoglobin_exposure_data(key: str, location: str):
    # Release 33 estimates are already for the pregnant population, so no
    # pregnancy correction factor is applied downstream.
    if key == data_keys.HEMOGLOBIN.MEAN:
        location_id = utility_data.get_location_id(location)
        return gbd.get_modelable_entity_draws(
            me_id=HEMOGLOBIN_PREGNANT_MEAN_ME_ID,
            location_id=location_id,
            year_id=metadata.GBD_EXTRACT_YEAR,
            data_type="draws",
            release_id=HEMOGLOBIN_RELEASE_ID,
        )
    # TODO: pull the SD live (ME 10488) once the release-33 pull works.
    path = (
        paths.HEMOGLOBIN_RELEASE_33_DATA_DIR
        / f"hemoglobin_exposure_sd_{location.lower()}.parquet"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. The release-33 hemoglobin SD can't be pulled live yet; "
            "see the README in HEMOGLOBIN_RELEASE_33_DATA_DIR."
        )
    logger.warning(f"Reading {key} from stored release-33 capture at {path}.")
    return pd.read_parquet(path)


@cache
def get_hemoglobin_maternal_disorders_rr(location: str):
    """Relative risk associated with one g/dL decrease in hemoglobin concentration below 12 g/dL"""
    # Relative risks do not vary by location, but get_relative_risk requires one.
    location_id = utility_data.get_location_id(location)
    # Left on GBD 2021: the 2023 RRs changed enough to require model updates we do not
    # plan to make. NO does the same.
    data = measures.get_relative_risk(
        risk_id=95,
        location_id=location_id,
        year_id=2021,
        data_type="draws",
        release_id=gbd_constants.RELEASE_IDS.GBD_2021,
    )
    # Subset to a single sub-cause as the call returns values for 10 sub-causes within the
    # maternal disorders parent cause
    # The RRs are all the same
    assert (
        (
            data.groupby(
                [
                    c
                    for c in data.columns
                    if "draw" not in c and c != "cause_id" and c != "exposure"
                ]
            )
            .nunique()
            .filter(like="draw")
            == 1
        )
        .all()
        .all()
    )
    data = data[data["cause_id"] == 367]
    return data
