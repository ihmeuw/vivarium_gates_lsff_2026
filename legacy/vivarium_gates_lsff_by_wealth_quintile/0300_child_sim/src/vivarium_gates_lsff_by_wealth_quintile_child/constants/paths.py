from pathlib import Path

import vivarium_gates_lsff_by_wealth_quintile_child
from vivarium_gates_lsff_by_wealth_quintile_child.constants import metadata

BASE_DIR = Path(vivarium_gates_lsff_by_wealth_quintile_child.__file__).resolve().parent
CLUSTER_BASE_DIR = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_by_wealth_quintile_child/"
)

ARTIFACT_ROOT = BASE_DIR / "artifacts"
MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
RAW_DATA_DIR = BASE_DIR / "data/raw"

UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR = CLUSTER_BASE_DIR / "raw_data/underweight_exp/"
CGF_PAFS = CLUSTER_BASE_DIR / "raw_data/cgf_pafs/"
