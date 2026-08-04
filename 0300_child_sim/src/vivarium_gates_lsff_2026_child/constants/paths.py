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

# Shared-filesystem root for this model. Data too large for the repo lives here, split
# by kind: 'data' for inputs and pipeline intermediates, 'artifacts' for the artifacts a
# simulation runs against, 'results' for simulation output. Each kind is then divided by
# model run, so bumping MODEL_NUMBER moves every path below to the new run's directories.
MODEL_ROOT = Path("/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026")
MODEL_NUMBER = "legacy"

MODEL_DATA_ROOT = MODEL_ROOT / "data" / MODEL_NUMBER
MODEL_ARTIFACT_ROOT = MODEL_ROOT / "artifacts" / MODEL_NUMBER
MODEL_RESULTS_ROOT = MODEL_ROOT / "results" / MODEL_NUMBER

# Intermediates of the LBWSG PAF calculation. The cut-down artifact that feeds it holds
# a different key set from the full child artifact -- it omits the PAF, which is what the
# calculation produces -- so the two must never share a path.
LBWSG_PAF_ARTIFACT_ROOT = MODEL_DATA_ROOT / "lbwsg_paf_artifacts"
LBWSG_PAF_RESULTS_ROOT = MODEL_DATA_ROOT / "lbwsg_pafs"
LBWSG_PAF_MEASURE_NAME = (
    "calculated_lbwsg_paf_on_cause.diarrheal_diseases.excess_mortality_rate"
)

# The artifact the child simulation runs against. NOTE: model_specifications/model_spec.yaml
# hardcodes this path, and data/lbwsg_paf.yaml hardcodes LBWSG_PAF_ARTIFACT_ROOT; YAML
# cannot read these constants, so both need updating when MODEL_NUMBER changes.
CHILD_ARTIFACT_ROOT = MODEL_ARTIFACT_ROOT / "child"

# The child model's population comes from the maternal simulation's birth records:
# one child simulant per maternal birth. Override with the --fertility-data-path flag.
MATERNAL_SIM_RESULTS_ROOT = MODEL_RESULTS_ROOT / "maternal"
FERTILITY_DATA_NAME = "births"


def get_default_fertility_data_path(location: str, vehicle: str) -> Path:
    """Default location of the maternal birth records for a location and vehicle.

    Returns the directory or file that :func:`data.loader.load_fertility_data` reads.
    Both layouts are supported, so this returns the directory when psimulate wrote a
    partitioned result and the single file when ``simulate run`` wrote one.
    """
    location_dir = MATERNAL_SIM_RESULTS_ROOT / location.lower()
    if not location_dir.is_dir():
        return location_dir / FERTILITY_DATA_NAME
    # Maternal runs are timestamp-named directories; take the most recent.
    runs = sorted((p for p in location_dir.iterdir() if p.is_dir()), reverse=True)
    for run in runs:
        for candidate in (
            run / "results" / FERTILITY_DATA_NAME,
            run / "results" / f"{FERTILITY_DATA_NAME}.parquet",
        ):
            if candidate.exists():
                return candidate
    return location_dir / FERTILITY_DATA_NAME


UNDERWEIGHT_CONDITIONAL_DISTRIBUTIONS_DIR = CLUSTER_BASE_DIR / "raw_data/underweight_exp/"
CGF_PAFS = CLUSTER_BASE_DIR / "raw_data/cgf_pafs/"
