from pathlib import Path

import vivarium_gates_lsff_2026_child
from lsff_utils import paths as shared_paths

BASE_DIR = Path(vivarium_gates_lsff_2026_child.__file__).resolve().parent
REPO_ROOT = (BASE_DIR / ".." / ".." / "..").resolve()

MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
RAW_DATA_DIR = BASE_DIR / "data/raw_data"
DATA_PREP_RESULTS_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results"

# In-repo locations, re-exported from lsff_utils.paths so this package and the
# maternal package cannot drift apart. The specifications no longer name an
# artifact: it is always supplied with -i.
CHILD_ARTIFACT_ROOT = shared_paths.CHILD_ARTIFACT_ROOT
CHILD_RESULTS_ROOT = shared_paths.CHILD_RESULTS_ROOT
LBWSG_PAF_ARTIFACT_ROOT = shared_paths.LBWSG_PAF_ARTIFACT_ROOT
LBWSG_PAF_RESULTS_ROOT = shared_paths.LBWSG_PAF_RESULTS_ROOT

LBWSG_PAF_MEASURE_NAME = (
    "calculated_lbwsg_paf_on_cause.diarrheal_diseases.excess_mortality_rate"
)

# The child model's population comes from the maternal simulation's birth records:
# one child simulant per maternal birth. The maternal run to read is named explicitly
# with --fertility-data-path so that each child artifact records which run produced it;
# data.loader._resolve_fertility_data_path accepts a run root, a results directory, or
# the births data itself.
MATERNAL_SIM_RESULTS_ROOT = shared_paths.MATERNAL_RESULTS_ROOT
FERTILITY_DATA_NAME = "births"

# Raw inputs that are not iteration-specific: they are extractions this model
# consumes as-is, so they sit outside the artifacts/data/results layout.
CLUSTER_BASE_DIR = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026_child/"
)
UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR = CLUSTER_BASE_DIR / "raw_data/underweight_exp/"
CGF_PAFS = CLUSTER_BASE_DIR / "raw_data/cgf_pafs/"
