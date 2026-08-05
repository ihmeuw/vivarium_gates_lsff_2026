from lsff_utils import config_utils

configfile: "0050_config/config.yaml"

config["location_fortificant_vehicle_scenarios"] = config_utils.get_location_fortificant_vehicle_intervention_scenarios()

# Use the Snakemake config as a way to pass "globals" through all Snakefiles

# One environment now serves both roles. The old split existed because the
# vivarium generation used for running simulations needed pandas 2.2.2 while GBD's
# db_queries needed 1.5.3; the modern suite pins pandas 1.5.3 via
# vivarium-dependencies[numpy_lt_2,pandas], so both sides agree and the artifact
# env and the simulation env can be the same venv. Both config keys are kept and
# pointed at it so no stage Snakefile needs to change.
#
# Deliberately NOT named .venv: the old-generation .venv and
# .simulation_running_venv are what reproduce the April-2025 results, and keeping
# them runnable is useful while the migration is in flight. Collapse this to
# .venv once the migration lands.
MODERN_VENV = ".venv_modern"

# lsff_utils.paths points the artifact/data/results roots at the shared team drive.
# A pipeline run writes into those roots, which would overwrite whatever a colleague's
# run left there, and IHME policy treats those paths as read-only. So redirect them
# into the working tree for pipeline runs. Absolute because every rule cds elsewhere.
#
# This is a bridge, not the destination: the Snakefiles keep intermediates in-tree
# while the packages expect them on the shared drive. Deciding where they belong is
# still open -- see the note in src/lsff_utils/paths.py.
import os
LOCAL_MODEL_ROOT = os.path.join(os.path.abspath("."), ".model_root")

config = {
    "env_input": [f"{MODERN_VENV}/bin/activate"],
    "env_setup": f"""
source {MODERN_VENV}/bin/activate
export LSFF_MODEL_ROOT={LOCAL_MODEL_ROOT}
""",
    "simulation_running_env_input": [f"{MODERN_VENV}/bin/activate"],
    "simulation_running_env_setup": f"""
source {MODERN_VENV}/bin/activate
export LSFF_MODEL_ROOT={LOCAL_MODEL_ROOT}
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

update_packages = config.get("update_packages", "n").lower() in ("t", "true", "y", "yes")

if update_packages:
    # The sub-package setup.py files are the source of truth for the suite
    # versions; the `data` extra pulls vivarium-inputs, vivarium-cluster-tools,
    # drmaa, vivarium-testing-utils and papermill. The sims themselves are
    # installed non-editable and then uninstalled, keeping only their
    # dependencies, because they must be run in-tree via PYTHONPATH -- see the
    # note in CLAUDE.md about DATA_PREP_RESULTS_ROOT.
    rule modern_venv_from_scratch:
        input: ["0200_pregnancy_sim/setup.py", "0300_child_sim/setup.py", "requirements.txt"]
        output: [directory(f"{MODERN_VENV}/"), f"{MODERN_VENV}/bin/activate"]
        shell:
            f"""
            python -m venv {MODERN_VENV}
            source {MODERN_VENV}/bin/activate
            pip install --upgrade pip
            pip install ./0200_pregnancy_sim[data]
            pip uninstall -y vivarium_gates_lsff_2026_maternal
            pip install ./0300_child_sim[data]
            pip uninstall -y vivarium_gates_lsff_2026_child
            # Notebook/analysis stack, plus pytest-mock: the vivarium-testing-utils
            # pytest plugin imports it without declaring it, and without it the
            # plugin is silently skipped and --runslow disappears.
            pip install ploomber-engine jupyter openpyxl matplotlib statsmodels \
                scikit-learn seaborn xlsxwriter pytest-mock
            pip install -e . --no-deps
            pip freeze -l | grep -v '\\-e ' | grep -v 'file:///' > modern_pip_lock.txt
            touch {MODERN_VENV} {MODERN_VENV}/bin/activate # Should be newer than the lockfile
            """
else:
    rule modern_venv:
        input: ["modern_pip_lock.txt"]
        output: [directory(f"{MODERN_VENV}/"), f"{MODERN_VENV}/bin/activate"]
        shell:
            f"""
            python -m venv {MODERN_VENV}
            source {MODERN_VENV}/bin/activate
            pip install -r modern_pip_lock.txt
            pip install -e . --no-deps
            """