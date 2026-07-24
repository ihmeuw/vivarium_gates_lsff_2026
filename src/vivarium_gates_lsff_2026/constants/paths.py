from pathlib import Path

import vivarium_gates_lsff_2026
from vivarium_gates_lsff_2026.constants import metadata

BASE_DIR = Path(vivarium_gates_lsff_2026.__file__).resolve().parent

ARTIFACT_ROOT = Path(f"/mnt/team/simulation_science/pub/models/{metadata.PROJECT_NAME}/artifacts/")

