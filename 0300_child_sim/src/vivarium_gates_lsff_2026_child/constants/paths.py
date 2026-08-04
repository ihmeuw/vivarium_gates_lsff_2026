from pathlib import Path

import vivarium_gates_lsff_2026_child
from vivarium_gates_lsff_2026_child.constants import metadata

BASE_DIR = Path(vivarium_gates_lsff_2026_child.__file__).resolve().parent
CLUSTER_BASE_DIR = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026_child/"
)

ARTIFACT_ROOT = BASE_DIR / "artifacts"
MODEL_SPEC_DIR = BASE_DIR / "model_specifications"
RAW_DATA_DIR = BASE_DIR / "data/raw_data"
DATA_PREP_RESULTS_ROOT = BASE_DIR / ".." / ".." / ".." / "0100_data_prep" / "results"

REPO_ROOT = (BASE_DIR / ".." / ".." / "..").resolve()

# Shared-filesystem root for this model's inputs and intermediate outputs. Results are
# too large to keep in the repo, and the LBWSG PAF artifact and the full child artifact
# have different key sets, so they get separate subdirectories rather than one path.
LEGACY_DATA_ROOT = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/data/legacy"
)

LBWSG_PAF_ARTIFACT_ROOT = LEGACY_DATA_ROOT / "lbwsg_paf_artifacts"
LBWSG_PAF_RESULTS_ROOT = LEGACY_DATA_ROOT / "lbwsg_pafs"
LBWSG_PAF_MEASURE_NAME = (
    "calculated_lbwsg_paf_on_cause.diarrheal_diseases.excess_mortality_rate"
)
CHILD_ARTIFACT_ROOT = LEGACY_DATA_ROOT / "child_artifacts"

# The child model's population comes from the maternal simulation's birth records:
# one child simulant per maternal birth. Override with the --fertility-data-path flag.
MATERNAL_SIM_RESULTS_ROOT = LEGACY_DATA_ROOT / "maternal"
FERTILITY_DATA_NAME = "births"


def get_default_fertility_data_path(location: str, vehicle: str) -> Path:
    """Default location of the maternal birth records for a location and vehicle.

    Returns the directory or file that :func:`data.loader.load_fertility_data` reads.
    Both layouts are supported, so this returns the directory when psimulate wrote a
    partitioned result and the single file when ``simulate run`` wrote one.
    """
    run_dir = MATERNAL_SIM_RESULTS_ROOT / location.lower() / vehicle
    partitioned = run_dir / FERTILITY_DATA_NAME
    if partitioned.is_dir():
        return partitioned
    return run_dir / f"{FERTILITY_DATA_NAME}.parquet"


UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR = CLUSTER_BASE_DIR / "raw_data/underweight_exp/"
CGF_PAFS = CLUSTER_BASE_DIR / "raw_data/cgf_pafs/"
