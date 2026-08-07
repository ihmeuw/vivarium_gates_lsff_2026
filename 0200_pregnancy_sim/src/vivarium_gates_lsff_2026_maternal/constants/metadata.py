from typing import NamedTuple

import pandas as pd

####################
# Project metadata #
####################

PROJECT_NAME = "vivarium_gates_lsff_2026_maternal"
CLUSTER_PROJECT = "proj_simscience_prod"

CLUSTER_QUEUE = "all.q"
MAKE_ARTIFACT_MEM = "10G"
MAKE_ARTIFACT_CPU = "1"
MAKE_ARTIFACT_RUNTIME = "3:00:00"
MAKE_ARTIFACT_SLEEP = 10

LOCATIONS = ["Ethiopia", "Nigeria", "India"]

ARTIFACT_INDEX_COLUMNS = [
    "sex",
    "age_start",
    "age_end",
    "year_start",
    "year_end",
]

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
