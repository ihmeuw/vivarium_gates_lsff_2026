from pathlib import Path

import vivarium_gates_lsff_by_wealth_quintile
from vivarium_gates_lsff_by_wealth_quintile.constants import metadata

BASE_DIR = Path(vivarium_gates_lsff_by_wealth_quintile.__file__).resolve().parent

ARTIFACT_ROOT = Path(
    f"/mnt/team/simulation_science/pub/models/{metadata.PROJECT_NAME}/artifacts/"
)
MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
RESULTS_ROOT = Path(f"/share/costeffectiveness/results/{metadata.PROJECT_NAME}/")
CSV_RAW_DATA_ROOT = BASE_DIR / "data" / "raw_data"
DATA_PREP_RESULT_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results" / "pregnancies"

HEMOGLOBIN_PREGNANCY_ADJUSTMENT_FACTORS_CSV = (
    CSV_RAW_DATA_ROOT / "mean_pregnancy_adjustment_factor_draws.csv"
)
