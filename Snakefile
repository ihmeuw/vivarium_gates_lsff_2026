from lsff_utils import config_utils

configfile: "0050_config/config.yaml"

config["location_fortificant_vehicle_scenarios"] = config_utils.get_location_fortificant_vehicle_intervention_scenarios()

# Use the Snakemake config as a way to pass "globals" through all Snakefiles

# NOTE: The env_setup strings are spliced into rule shell commands, which snakemake
# runs through its own str.format pass -- they must not contain literal braces.
# The `set +u` guard is needed because conda's activation scripts reference unset
# variables, and snakemake shells run under bash strict mode (`set -euo pipefail`).
config = {
    "env_input": [".snakemake_envs/artifact/.build_complete"],
    # JUPYTER_PATH makes papermill's `-k python3` resolve to this env's kernel;
    # without it, a user-level kernelspec in ~/.local/share/jupyter/kernels
    # shadows the env's and the notebooks run under the wrong python.
    "env_setup": """
set +u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate ./.snakemake_envs/artifact
set -u
export JUPYTER_PATH="$CONDA_PREFIX/share/jupyter"
""",
    "simulation_running_env_input": [".snakemake_envs/simulation/.build_complete"],
    "simulation_running_env_setup": """
set +u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate ./.snakemake_envs/simulation
set -u
""",
    "debug": "false",
    "local": "false",
    "full_scale": "false",
    **config,
}

config["debug"] = str(config.get("debug", "false")).lower() in ("t", "true", "y", "yes")
config["local"] = str(config.get("local", "false")).lower() in ("t", "true", "y", "yes")
config["full_scale"] = str(config.get("full_scale", "false")).lower() in ("t", "true", "y", "yes")

rule all:
    input: ["5000_analyze_results/results_spreadsheet.xlsx", "5000_analyze_results/executed/results_plots.ipynb"]

include: "0100_data_prep/Snakefile"
include: "0200_pregnancy_sim/Snakefile"
include: "0300_child_sim/Snakefile"
include: "0400_non_pregnant_anemia_model/Snakefile"
include: "0500_neural_tube_defects_model/Snakefile"
include: "5000_analyze_results/Snakefile"

# The two environments mirror the supported `environment.sh` / `make build-env`
# workflow (see README.rst), post vivarium-monorepo migration:
#   - "artifact" type: data-prep notebooks, artifact building, and results
#     processing. The papermill/notebook stack from requirements.txt is layered
#     on top, since `make build-env` does not install it.
#   - "simulation" type: running simulations (psimulate/jobmon).
# Both are conda environments built by `make build-env` into repo-local paths so
# snakemake can track and rebuild them. The pre-migration venvs built from
# pip_lock.txt / simulation_running_pip_lock.txt no longer resolve against this
# code (cluster tools moved to `vivarium.cluster_tools`, etc.); `make build-env`
# resolves live, so those lock files and the update_packages mode are retired.
# A freeze of what each build resolved is recorded inside the env directory.

rule general_venv:
    input:
        [
            "pyproject.toml",
            "0200_pregnancy_sim/pyproject.toml",
            "0300_child_sim/pyproject.toml",
            "python_versions.json",
            "requirements.txt",
        ]
    output: [".snakemake_envs/artifact/.build_complete"]
    shell:
        """
        rm -rf .snakemake_envs/artifact
        make build-env type=artifact path=$PWD/.snakemake_envs/artifact force=yes
        set +u
        source "$(conda info --base)/etc/profile.d/conda.sh"
        conda activate ./.snakemake_envs/artifact
        set -u
        pip install --extra-index-url https://artifactory.ihme.washington.edu/artifactory/api/pypi/pypi-shared/simple -r requirements.txt
        pip freeze -l > .snakemake_envs/artifact/pip_freeze.txt
        touch .snakemake_envs/artifact/.build_complete
        """

rule simulation_running_venv:
    input:
        [
            "pyproject.toml",
            "0200_pregnancy_sim/pyproject.toml",
            "0300_child_sim/pyproject.toml",
            "python_versions.json",
            # Not a real dependency: concurrent `conda create` runs corrupt the
            # shared package cache (~/miniconda3/pkgs), so the two env builds
            # must not run in parallel.
            ".snakemake_envs/artifact/.build_complete",
        ]
    output: [".snakemake_envs/simulation/.build_complete"]
    shell:
        """
        rm -rf .snakemake_envs/simulation
        make build-env type=simulation path=$PWD/.snakemake_envs/simulation force=yes
        set +u
        source "$(conda info --base)/etc/profile.d/conda.sh"
        conda activate ./.snakemake_envs/simulation
        set -u
        pip freeze -l > .snakemake_envs/simulation/pip_freeze.txt
        touch .snakemake_envs/simulation/.build_complete
        """