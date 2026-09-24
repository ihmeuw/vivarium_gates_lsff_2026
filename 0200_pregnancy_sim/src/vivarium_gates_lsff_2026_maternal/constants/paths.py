from pathlib import Path

import vivarium_gates_lsff_2026_maternal
from lsff_utils import paths as shared_paths

BASE_DIR = Path(vivarium_gates_lsff_2026_maternal.__file__).resolve().parent

# The maternal artifact and simulation results are written in-repo and published
# to the team drive by archive_last_run.sh. See lsff_utils.paths.
ARTIFACT_ROOT = shared_paths.MATERNAL_ARTIFACT_ROOT
RESULTS_ROOT = shared_paths.MATERNAL_RESULTS_ROOT

MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
CSV_RAW_DATA_ROOT = BASE_DIR / "data" / "raw_data"
DATA_PREP_RESULTS_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results"

# Stored release-33 hemoglobin pulls, shared with vivarium_gates_mncnh (MIC-7476).
HEMOGLOBIN_RELEASE_33_DATA_DIR = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_mncnh/data/hemoglobin_release33"
)
