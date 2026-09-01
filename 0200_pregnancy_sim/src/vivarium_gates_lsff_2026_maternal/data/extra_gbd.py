from vivarium.gbd_mapping import sequelae
from vivarium_gbd_access import constants as gbd_constants
from vivarium_gbd_access.gbd.base_data import get_draws
from vivarium_gbd_access.utilities import cache
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import utility_data

from vivarium_gates_lsff_2026_maternal.constants import data_keys, metadata
from vivarium_gates_lsff_2026_maternal.data import utilities


@cache
def load_lbwsg_exposure(location: str):
    entity = utilities.get_entity(data_keys.LBWSG.EXPOSURE)
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        gbd_id_type="rei_id",
        gbd_id=entity.gbd_id,
        source=gbd_constants.SOURCES.EXPOSURE,
        location_id=location_id,
        year_id=2022,
        sex_id=gbd_constants.SEX.MALE + gbd_constants.SEX.FEMALE,
        age_group_id=164,  # Birth prevalence
        release_id=gbd_constants.RELEASE_IDS.GBD_2021,  # LBWSG not re-estimated for GBD 2023
    )
    return data


@cache
def get_all_cause_yld_rate(location: str):
    entity = utilities.get_entity("cause.all_causes.ylds")
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        "cause_id",
        entity.gbd_id,
        source=gbd_constants.SOURCES.COMO,
        location_id=location_id,
        release_id=gbd_constants.RELEASE_IDS.GBD_2023,
        measure_id=vi_globals.MEASURES["YLDs"],
        metric_id=3,  # rate
    )
    return data


@cache
def get_maternal_disorder_ylds(location: str, metric_id=None):
    entity = utilities.get_entity(data_keys.MATERNAL_DISORDERS.YLDS)
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        "cause_id",
        entity.gbd_id,
        source=gbd_constants.SOURCES.COMO,
        location_id=location_id,
        year_id=2023,
        release_id=gbd_constants.RELEASE_IDS.GBD_2023,
        measure_id=vi_globals.MEASURES["YLDs"],
        metric_id=metric_id,
    )
    return data


@cache
def get_anemia_ylds(location: str, metric_id=None):
    anemia_sequelae = [
        sequelae.mild_anemia_due_to_maternal_hemorrhage,
        sequelae.moderate_anemia_due_to_maternal_hemorrhage,
        sequelae.severe_anemia_due_to_maternal_hemorrhage,
    ]
    anemia_ids = [s.gbd_id for s in anemia_sequelae]
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        "sequela_id",
        anemia_ids,
        source=gbd_constants.SOURCES.COMO,
        location_id=location_id,
        year_id=2023,
        release_id=gbd_constants.RELEASE_IDS.GBD_2023,
        measure_id=vi_globals.MEASURES["YLDs"],
        metric_id=metric_id,
    )
    return data


@cache
def get_anemia_yld_rate(location: str):
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        "rei_id",
        192,
        source=gbd_constants.SOURCES.COMO,
        location_id=location_id,
        release_id=gbd_constants.RELEASE_IDS.GBD_2023,
        measure_id=vi_globals.MEASURES["YLDs"],
        metric_id=3,
    )
    return data


@cache
def get_hemoglobin_exposure_data(key: str, location: str):
    source = {
        data_keys.HEMOGLOBIN.MEAN: gbd_constants.SOURCES.EXPOSURE,
        data_keys.HEMOGLOBIN.STANDARD_DEVIATION: gbd_constants.SOURCES.EXPOSURE_SD,
    }[key]
    location_id = utility_data.get_location_id(location)
    data = get_draws(
        gbd_id_type="rei_id",
        gbd_id=376,
        source=source,
        location_id=location_id,
        year_id=metadata.GBD_EXTRACT_YEAR,
        sex_id=gbd_constants.SEX.FEMALE,
        # Release 33 estimates are already for the pregnant population, so no
        # pregnancy correction factor is applied downstream.
        release_id=metadata.GBD_2023_SPECIAL_PUBLICATIONS_RELEASE_ID,
    )
    return data


@cache
def get_hemoglobin_maternal_disorders_rr():
    """Relative risk associated with one g/dL decrease in hemoglobin concentration below 12 g/dL"""
    # Left on GBD 2021: the 2023 RRs changed enough to require model updates we do not
    # plan to make. NO does the same.
    data = get_draws(
        gbd_id_type="rei_id",
        gbd_id=95,
        release_id=gbd_constants.RELEASE_IDS.GBD_2021,
        year_id=2021,
        sex_id=2,
        source="rr",
        status="best",
    )
    # Subset to a single sub-cause as the get_draws call returns values for 10 sub-causes within the
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
