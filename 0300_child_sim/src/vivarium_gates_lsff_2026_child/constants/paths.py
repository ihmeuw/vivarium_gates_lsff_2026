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

# The child model's population comes from the maternal simulation's birth records:
# one child simulant per maternal birth. The Snakefile writes maternal output to
# 0200_pregnancy_sim/sim_results/<vehicle>/<location>/, so that is the default place
# to look for it; override with the --fertility-data-path CLI flag.
MATERNAL_SIM_RESULTS_ROOT = REPO_ROOT / "0200_pregnancy_sim" / "sim_results"
FERTILITY_DATA_NAME = "births"


def get_default_fertility_data_path(location: str, vehicle: str) -> Path:
    """Default location of the maternal birth records for a location and vehicle.

    Returns the directory or file that :func:`data.loader.load_fertility_data` reads.
    Both layouts are supported, so this returns the directory when psimulate wrote a
    partitioned result and the single file when ``simulate run`` wrote one.
    """
    run_dir = MATERNAL_SIM_RESULTS_ROOT / vehicle / location.lower()
    partitioned = run_dir / FERTILITY_DATA_NAME
    if partitioned.is_dir():
        return partitioned
    return run_dir / f"{FERTILITY_DATA_NAME}.parquet"


UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR = CLUSTER_BASE_DIR / "raw_data/underweight_exp/"
CGF_PAFS = CLUSTER_BASE_DIR / "raw_data/cgf_pafs/"
