from pathlib import Path

import vivarium_gates_lsff_2026_maternal
from vivarium_gates_lsff_2026_maternal.constants import metadata

BASE_DIR = Path(vivarium_gates_lsff_2026_maternal.__file__).resolve().parent

ARTIFACT_ROOT = BASE_DIR / "artifacts"
MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
RESULTS_ROOT = Path(f"/share/costeffectiveness/results/{metadata.PROJECT_NAME}/")
CSV_RAW_DATA_ROOT = BASE_DIR / "data" / "raw_data"
DATA_PREP_RESULTS_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results"

HEMOGLOBIN_PREGNANCY_ADJUSTMENT_FACTORS_CSV = (
    CSV_RAW_DATA_ROOT / "mean_pregnancy_adjustment_factor_draws.csv"
)
