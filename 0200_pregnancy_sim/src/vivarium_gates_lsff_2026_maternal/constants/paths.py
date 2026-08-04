from pathlib import Path

import vivarium_gates_lsff_2026_maternal
from lsff_utils import paths as shared_paths

BASE_DIR = Path(vivarium_gates_lsff_2026_maternal.__file__).resolve().parent

# The maternal artifact and simulation results live on the shared drive under the
# current model iteration, not in the repository. See lsff_utils.paths.
# NOTE: model_specifications/model_spec.yaml hardcodes ARTIFACT_ROOT; YAML cannot
# read these constants, so it needs updating when MODEL_NUMBER changes.
# tests/test_paths.py fails if it drifts.
ARTIFACT_ROOT = shared_paths.MATERNAL_ARTIFACT_ROOT
RESULTS_ROOT = shared_paths.MATERNAL_RESULTS_ROOT

MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
CSV_RAW_DATA_ROOT = BASE_DIR / "data" / "raw_data"
DATA_PREP_RESULTS_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results"

HEMOGLOBIN_PREGNANCY_ADJUSTMENT_FACTORS_CSV = (
    CSV_RAW_DATA_ROOT / "mean_pregnancy_adjustment_factor_draws.csv"
)
