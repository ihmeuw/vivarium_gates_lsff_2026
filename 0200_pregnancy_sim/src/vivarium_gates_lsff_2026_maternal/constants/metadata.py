from typing import NamedTuple

import pandas as pd

####################
# Project metadata #
####################

PROJECT_NAME = "vivarium_gates_lsff_2026_maternal"
CLUSTER_PROJECT = "proj_simscience_prod"

CLUSTER_QUEUE = "all.q"
# Resources for one location's artifact build. Memory is in GB and cores is a
# count, as NativeSpecification expects; they are not SLURM-formatted strings.
MAKE_ARTIFACT_MEM = 10
MAKE_ARTIFACT_CPU = 1
MAKE_ARTIFACT_RUNTIME = "3:00:00"

# Ethiopia is excluded: the maternal model is not run there and has no data prep CSV.
LOCATIONS = ["Nigeria", "India"]

ARTIFACT_INDEX_COLUMNS = [
    "sex",
    "age_start",
    "age_end",
    "year_start",
    "year_end",
]


GBD_EXTRACT_YEAR = 2023
GBD_2023_SPECIAL_PUBLICATIONS_RELEASE_ID = 33

# GBD 2023 provides 250 draws (GBD 2021 provided 500). Keys sourced from GBD are
# built with this many draw columns, so it bounds the draws a simulation can request.
DRAW_COUNT = 250
ARTIFACT_COLUMNS = pd.Index([f"draw_{i}" for i in range(DRAW_COUNT)])


class __Scenarios(NamedTuple):
    zero_coverage: str
    baseline: str
    mms: str
    universal_bep: str
    targeted_bep_ifa: str
    targeted_bep_mms: str


SCENARIOS = __Scenarios(*__Scenarios._fields)
