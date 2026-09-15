from gbd.enums import Measures, Metrics
from vivarium.gbd_mapping import sequelae
from vivarium_gbd_access import constants as gbd_constants
from vivarium_gbd_access import gbd
from vivarium_gbd_access.gbd import measures
from vivarium_gbd_access.gbd.base_data import get_machinery_estimates
from vivarium_gbd_access.utilities import cache
from vivarium_inputs import utility_data

from vivarium_gates_lsff_2026_maternal.constants import data_keys, metadata
from vivarium_gates_lsff_2026_maternal.data import utilities


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
    location_id = utility_data.get_location_id(location)
    # Release 33 estimates are already for the pregnant population, so no
    # pregnancy correction factor is applied downstream.
    release_id = metadata.GBD_2023_SPECIAL_PUBLICATIONS_RELEASE_ID
    if key == data_keys.HEMOGLOBIN.MEAN:
        data = measures.get_exposure(
            entity_id=376,
            location_id=location_id,
            year_id=metadata.GBD_EXTRACT_YEAR,
            data_type="draws",
            sex_id=gbd_constants.SEX.FEMALE,
            release_id=release_id,
        )
    else:
        # NOTE: no sex_id argument, so the female subset is taken below instead.
        data = measures.get_exposure_standard_deviation(
            risk_id=376,
            location_id=location_id,
            year_id=metadata.GBD_EXTRACT_YEAR,
            data_type="draws",
            release_id=release_id,
        )
        data = data[data["sex_id"] == gbd_constants.SEX.FEMALE]
    return data


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
