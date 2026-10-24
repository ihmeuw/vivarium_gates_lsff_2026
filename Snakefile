import os
import sys

from lsff_utils import config_utils, paths, snakemake_utils

configfile: "0050_config/config.yaml"

config["location_fortificant_vehicle_scenarios"] = config_utils.get_location_fortificant_vehicle_intervention_scenarios(stage="data_prep")

# Use the Snakemake config as a way to pass "globals" through all Snakefiles.
#
# Environments are the two `environment.sh` builds -- `artifact` for anything
# that reads GBD, `simulation` for anything that runs vivarium. Snakemake does
# not build them; it activates them. Override either with
#
#   snakemake --config simulation_env=<name or venv path>
#   snakemake --config artifact_env_setup='<shell that activates something else>'
#
# See lsff_utils.snakemake_utils.resolve_environments.

config = {
    "debug": "false",
    "local": "false",
    "full_scale": "false",
    # Take 0100_data_prep's committed CSVs as given. Their outputs live in the
    # repository, so a fresh clone or a branch switch can leave the notebooks
    # looking newer than the CSVs they produced and schedule the whole of data
    # prep -- and everything downstream of it -- over a timestamp rather than a
    # change. See "Snakemake flags" in the README.
    "skip_data_prep": "false",
    # Artifacts and simulation, anemia and rescaled results go to the team drive
    # under MODEL_NUMBER. write_local=true puts them in the working tree instead,
    # for archive_last_run.sh to publish. See "Where a run writes" in the README.
    "write_local": "false",
    # Write into a MODEL_NUMBER that already has output without being asked.
    "reuse_model_number": "false",
    **config,
}

config.update(snakemake_utils.resolve_environments(config))

# Recipes are not f-strings
# -------------------------
#
# Every `shell:` body in this workflow is a plain string, and Snakemake does the
# interpolation. Do not make one an f-string, however convenient it looks.
#
# Snakemake parses a Snakefile by tokenizing it and re-emitting Python. On Python
# 3.12+ an f-string is no longer one token (PEP 701) -- its literal text arrives
# as separate FSTRING_MIDDLE tokens -- and Snakemake 8.16+ loses the pieces that
# span a newline. The effect is that in a multi-line f-string, *every line
# containing no `{...}` is silently dropped from the recipe*. No error, no
# warning: the rule just runs a shorter script than the one in the file. That
# deleted `cd 0300_child_sim` and all four `rm -f dump.rdb` lines, and left
# `psimulate` to fail from the wrong directory with a click usage error.
#
# So: values computed in Python are named at the top of each Snakefile and
# referenced as `{name}` (Snakemake's formatter resolves module globals,
# attribute access like `{paths.CHILD_RESULTS_ROOT}`, and `{config[key]}`), and
# anything that has to be computed from the wildcards goes in the rule's
# `params`. `params` is the only interpolation resolved per job -- a `{name}`
# whose *value* contains `{wildcards.location}` will not be expanded, because
# Snakemake does not re-scan what it substitutes.
#
# Single-line f-strings are unaffected, which is why the `input`/`output`/`log`
# path lists still use them.

# Every recipe here is a sequence of commands, and Snakemake otherwise reports
# only the exit status of the last one. Without this, a simulation that died
# would still be followed by the step that records it as the current run, and
# the rule would be marked successful. `-u` is deliberately not set: conda's
# activation scripts read unset variables.
shell.prefix("set -eo pipefail; ")

config["debug"] = str(config.get("debug", "false")).lower() in ("t", "true", "y", "yes")
config["local"] = str(config.get("local", "false")).lower() in ("t", "true", "y", "yes")
config["full_scale"] = str(config.get("full_scale", "false")).lower() in ("t", "true", "y", "yes")
config["skip_data_prep"] = str(config.get("skip_data_prep", "false")).lower() in ("t", "true", "y", "yes")
config["write_local"] = str(config.get("write_local", "false")).lower() in ("t", "true", "y", "yes")
config["reuse_model_number"] = str(config.get("reuse_model_number", "false")).lower() in ("t", "true", "y", "yes")

# "local" or MODEL_NUMBER. Every Snakefile resolves its output roots against
# this, and the environment variables carry it to the notebooks and to
# make_artifacts, which resolve the same roots on their own. A run that writes
# to the team drive also reads its own upstream output from there.
config["output_target"] = snakemake_utils.resolve_output_target(
    config["write_local"], config["debug"]
)
to_team = config["output_target"] != paths.LOCAL_SOURCE
os.environ[paths.OUTPUT_TARGET_ENV_VAR] = config["output_target"]
if to_team:
    os.environ[paths.DATA_SOURCE_ENV_VAR] = config["output_target"]

# onstart runs only for a real run, after the DAG is built and before any job.
onstart:
    if to_team:
        snakemake_utils.confirm_model_number_reuse(
            config["output_target"], config["reuse_model_number"]
        )
        snakemake_utils.record_team_run(config["output_target"], sys.argv)

# The end-to-end pipeline: the spreadsheet and the plots are the only things
# nothing else consumes, so requiring them pulls every stage in behind them for
# the arms whose run_through is "results". Arms whose run_through is "data_prep"
# reach no results, so their data-prep products are asked for directly
# (`data_prep_targets`, defined in 0100_data_prep/Snakefile; a function because
# that file is included below), and so is the check of every data prep results
# file. See 0050_config/location_fortificant_vehicles.csv.
rule all:
    input:
        lambda wildcards: [
            "5000_analyze_results/results_spreadsheet.xlsx",
            "5000_analyze_results/executed/results_plots.ipynb",
        ] + data_prep_targets + [data_prep_results_checked]

include: "0100_data_prep/Snakefile"
include: "0200_pregnancy_sim/Snakefile"
include: "0300_child_sim/Snakefile"
include: "0400_non_pregnant_anemia_model/Snakefile"
include: "0500_neural_tube_defects_model/Snakefile"
include: "5000_analyze_results/Snakefile"
