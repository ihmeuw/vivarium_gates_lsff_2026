#!/usr/bin/env bash
#
# run.sh -- the six pipeline stages from the README, as editable commands.
#
# Each stage below is the same command the README documents, with the parts that
# change between runs hoisted into the EDIT HERE block. Edit that block in your
# text editor rather than retyping commands at the prompt.
#
#   ./run.sh maternal-artifact     stage 1   artifact env
#   ./run.sh maternal-sim          stage 2   simulation env
#   ./run.sh paf-artifact          stage 3   artifact env
#   ./run.sh paf-sim               stage 4   simulation env
#   ./run.sh child-artifact        stage 5   artifact env
#   ./run.sh child-sim             stage 6   simulation env
#
#   ./run.sh maternal-branch       stages 1-2
#   ./run.sh paf-branch            stages 3-4
#   ./run.sh child-branch          stages 5-6
#
#   ./run.sh restart <run_dir>     rerun only the failed tasks of a psimulate run
#   ./run.sh paths                 print every path this script would read/write
#
# To re-run the simulations against artifacts built by an earlier version of the
# project -- comparing framework changes with the input data held fixed -- point
# LEGACY_ARCHIVE at an archive_last_run.sh snapshot and run only stages 2, 4, 6:
#
#   export LEGACY_ARCHIVE=/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_by_wealth_quintile/2026_08_13_13_55_48
#   ./run.sh paths            # confirm the three artifacts resolve before running
#   ./run.sh maternal-sim
#   ./run.sh paf-sim
#   ./run.sh child-sim
#
# Every variable in the EDIT HERE block can also be overridden for a single
# invocation without touching the file:
#
#   LOCATION=india BRANCHES=full ./run.sh maternal-sim
#
# Add -n / --dry-run to any command to print what would run without running it.
#
# Activate the environment yourself first, as the README describes:
#   source environment.sh              (simulation stages: 2, 4, 6)
#   source environment.sh -t artifact  (artifact stages:   1, 3, 5)
# Add -s for the shared cluster environment. This script does not activate an
# environment for you, because environment.sh git-pulls and may rebuild.

set -euo pipefail

# =============================================================================
# EDIT HERE
# =============================================================================

# What to run.
LOCATION="${LOCATION:-nigeria}"     # india or nigeria -- the modelled set.
                                    # Ethiopia is folate-on-salt only, so it has
                                    # no maternal or child model here; it is
                                    # accepted for the LBWSG PAF stages alone.
VEHICLE="${VEHICLE:-rice}"          # rice, salt, bouillon (see 0050_config/)
BRANCHES="${BRANCHES:-small}"       # small = 30 jobs, full = 600 jobs

# Cluster resources, passed to psimulate.
PROJECT="${PROJECT:-proj_simscience}"
QUEUE="${QUEUE:-all.q}"
MEMORY_GB="${MEMORY_GB:-2}"
RUNTIME="${RUNTIME:-01:00:00}"

# Verbosity. The README uses -v for psimulate and -vvv for make_artifacts.
PSIMULATE_VERBOSITY="${PSIMULATE_VERBOSITY:--v}"
ARTIFACT_VERBOSITY="${ARTIFACT_VERBOSITY:--vvv}"

# Extra flags for every make_artifacts call. --mean collapses draws to their
# mean, which is much faster but cannot support a draw sweep. Add -a to append.
ARTIFACT_FLAGS="${ARTIFACT_FLAGS:---mean}"

# Where output goes.
#
# Left empty, every path is derived from MODEL_NUMBER in src/lsff_utils/paths.py,
# so bumping that constant repoints simulation output as well as artifacts.
#
# Set SCRATCH_ROOT to redirect the whole pipeline somewhere disposable, keeping
# the same {artifacts,data,results}/<MODEL_NUMBER>/ layout underneath. Do this
# when testing: a trial run then cannot touch the artifacts a validated set of
# results depends on.
SCRATCH_ROOT="${SCRATCH_ROOT:-}"

# Which maternal run the child artifact reads births from (stage 5). Left empty,
# the most recent run under the maternal results directory is used and the
# choice is printed. Set it explicitly to pin a run:
#   MATERNAL_RUN=2026_08_18_09_14_23
MATERNAL_RUN="${MATERNAL_RUN:-}"

# Which artifact each simulation stage runs against, passed as psimulate -i.
#
# Left empty, each is derived from the paths module for the current LOCATION --
# the artifact that stage 1, 3 or 5 would have built. Passing -i explicitly
# matters: all three model specifications hardcode nigeria.hdf in their
# input_data section, so without it every simulation would run Nigeria's
# artifact regardless of LOCATION.
#
# Set any of these to run against an artifact from somewhere else.
MATERNAL_ARTIFACT="${MATERNAL_ARTIFACT:-}"
PAF_ARTIFACT="${PAF_ARTIFACT:-}"
CHILD_ARTIFACT="${CHILD_ARTIFACT:-}"

# Convenience for the common case of the above: re-running the simulations
# against a previous version of the project. Set this to an archive directory
# produced by that project's archive_last_run.sh -- a mirror of its repo tree
# filtered to .hdf and .parquet -- and the three artifact paths above are
# derived from it, in its layout rather than this project's:
#
#   <archive>/0200_pregnancy_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
#   <archive>/0300_child_sim/lbwsg_paf_mean_draw_artifacts/<location>.hdf
#   <archive>/0300_child_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
#
# Output still goes to this project's results roots, so nothing is written back
# into the archive. Run './run.sh paths' first to confirm the three resolve.
LEGACY_ARCHIVE="${LEGACY_ARCHIVE:-}"

# =============================================================================
# Below here is machinery. You should not need to edit it.
# =============================================================================

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN="${DRY_RUN:-no}"

MATERNAL_SPEC="0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/model_spec.yaml"
MATERNAL_BRANCH_DIR="0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/branches"
CHILD_SPEC="0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/model_spec.yaml"
CHILD_BRANCH_DIR="0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/branches"
PAF_SPEC="0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf.yaml"
PAF_BRANCHES="0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf_branches.yaml"

die() { printf '\nERROR: %s\n\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*" >&2; }

# --- path resolution -------------------------------------------------------
#
# MODEL_NUMBER and the six roots come from lsff_utils.paths rather than being
# repeated here, so there is exactly one place to edit when starting a new model
# iteration. shlex.quote keeps the eval safe against paths with spaces.

_emit_paths() {
    PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" python - <<'PY'
import shlex

from lsff_utils import paths

for name in (
    "MODEL_NUMBER",
    "MATERNAL_ARTIFACT_ROOT",
    "CHILD_ARTIFACT_ROOT",
    "MATERNAL_RESULTS_ROOT",
    "CHILD_RESULTS_ROOT",
    "LBWSG_PAF_ARTIFACT_ROOT",
    "LBWSG_PAF_RESULTS_ROOT",
):
    print(f"LSFF_{name}={shlex.quote(str(getattr(paths, name)))}")
PY
}

resolve_paths() {
    local emitted
    if ! emitted="$(_emit_paths 2>/dev/null)"; then
        die "Could not import lsff_utils.paths.
Activate an environment first:  source environment.sh"
    fi
    eval "${emitted}"

    if [[ -n "${SCRATCH_ROOT}" ]]; then
        LSFF_MATERNAL_ARTIFACT_ROOT="${SCRATCH_ROOT}/artifacts/${LSFF_MODEL_NUMBER}/maternal"
        LSFF_CHILD_ARTIFACT_ROOT="${SCRATCH_ROOT}/artifacts/${LSFF_MODEL_NUMBER}/child"
        LSFF_MATERNAL_RESULTS_ROOT="${SCRATCH_ROOT}/results/${LSFF_MODEL_NUMBER}/maternal"
        LSFF_CHILD_RESULTS_ROOT="${SCRATCH_ROOT}/results/${LSFF_MODEL_NUMBER}/child"
        LSFF_LBWSG_PAF_ARTIFACT_ROOT="${SCRATCH_ROOT}/data/${LSFF_MODEL_NUMBER}/lbwsg_paf_artifacts"
        LSFF_LBWSG_PAF_RESULTS_ROOT="${SCRATCH_ROOT}/data/${LSFF_MODEL_NUMBER}/lbwsg_pafs"
    fi

    resolve_artifacts
}

# The -i argument for each simulation stage. Precedence: an explicitly set
# variable wins; then LEGACY_ARCHIVE, in the old project's layout; otherwise
# this project's own roots.
#
# The legacy layout is irregular and is reproduced here rather than guessed at:
# the maternal and child artifacts are nested under a vehicle directory, the
# LBWSG PAF artifact is not, because it is built --national and carries no
# vehicle. Directory names are 'mean_draw_artifacts', not 'artifacts'.
resolve_artifacts() {
    if [[ -n "${LEGACY_ARCHIVE}" ]]; then
        : "${MATERNAL_ARTIFACT:=${LEGACY_ARCHIVE}/0200_pregnancy_sim/mean_draw_artifacts/${VEHICLE}/${LOCATION_SLUG}.hdf}"
        : "${PAF_ARTIFACT:=${LEGACY_ARCHIVE}/0300_child_sim/lbwsg_paf_mean_draw_artifacts/${LOCATION_SLUG}.hdf}"
        : "${CHILD_ARTIFACT:=${LEGACY_ARCHIVE}/0300_child_sim/mean_draw_artifacts/${VEHICLE}/${LOCATION_SLUG}.hdf}"
    fi

    : "${MATERNAL_ARTIFACT:=${LSFF_MATERNAL_ARTIFACT_ROOT}/${LOCATION_SLUG}.hdf}"
    : "${PAF_ARTIFACT:=${LSFF_LBWSG_PAF_ARTIFACT_ROOT}/${LOCATION_SLUG}.hdf}"
    : "${CHILD_ARTIFACT:=${LSFF_CHILD_ARTIFACT_ROOT}/${LOCATION_SLUG}.hdf}"
}

# psimulate reports a missing artifact only after binding a workflow, so check
# first: the failure is otherwise slow and its message does not name the path.
require_artifact() {
    local path="$1"
    [[ "${DRY_RUN}" == "yes" ]] && return 0
    [[ -f "${path}" ]] || die "No artifact at ${path}
Build it first, or point this stage at another one. Run './run.sh paths' to see
every path in use."
}

# --- environment check -----------------------------------------------------
#
# A warning rather than a hard stop: the environment names are conventional, not
# guaranteed, and both failure modes are already loud (make_artifacts cannot
# import vivarium_inputs outside the artifact environment, and psimulate is not
# on PATH outside the simulation one).

check_env() {
    local wanted="$1" active=""
    [[ -n "${CONDA_DEFAULT_ENV:-}" ]] && active="${CONDA_DEFAULT_ENV}"
    [[ -n "${VIRTUAL_ENV:-}" ]] && active="$(basename -- "${VIRTUAL_ENV}")"

    if [[ -z "${active}" ]]; then
        note "WARNING: no environment appears to be active; expected the ${wanted} environment."
    elif [[ "${active}" != *"${wanted}"* ]]; then
        note "WARNING: active environment is '${active}', but this stage wants the ${wanted} environment."
        note "         source environment.sh$([[ ${wanted} == artifact ]] && echo ' -t artifact')"
    fi
}

# --- command execution -----------------------------------------------------

run() {
    printf '\n$ %s\n\n' "$*" >&2
    if [[ "${DRY_RUN}" == "yes" ]]; then
        return 0
    fi
    ( cd -- "${REPO_ROOT}" && "$@" )
}

# Config is validated once, up front, and resolved into variables. It is
# deliberately not done inside $(...) at the point of use: a die() there would
# exit only the subshell, and the stage would go on to run a psimulate command
# built from the missing value.
BRANCHES_FILE=""
LOCATION_SLUG=""

validate_config() {
    case "${BRANCHES}" in
        small) BRANCHES_FILE="scenarios_small.yaml" ;;
        full)  BRANCHES_FILE="scenarios.yaml" ;;
        *)     die "BRANCHES must be 'small' or 'full', got '${BRANCHES}'" ;;
    esac

    # Which locations each stage can actually run for.
    #
    # The modelled set is India and Nigeria. Ethiopia appears in the child
    # package's metadata.LOCATIONS and in the README, but is vestigial there:
    #
    #   - It has no maternal model (no maternal disorders incidence disparities
    #     extract), so stage 2 cannot run and stage 5 has no births file to pass
    #     to --fertility-data-path, which loader.load_fertility_data requires.
    #   - Its only vehicle is folate-on-salt. The child model's sole intervention
    #     is MaternalIronConsumptionFromFortification, iron acting on birthweight,
    #     and 0100_data_prep/results/iron/fortification_birthweight_effects.csv
    #     has rows for rice and bouillon only. So stage 6 raises KeyError: 'salt'
    #     -- or, worse, silently succeeds on the default --vehicle rice and shifts
    #     birthweight using a vehicle Ethiopia has no coverage data for. There are
    #     no 0100_data_prep/results/iron/**/ethiopia.csv files at all.
    #
    # Ethiopia's folate is modelled in 0500_neural_tube_defects_model, which is
    # notebooks rather than a Vivarium simulation.
    #
    # Stages 3 and 4 are the exception: the LBWSG PAF artifact is built
    # --national --for-lbwsg-pafs, which skips every location-specific and
    # maternal-dependent key, so it is pure GBD and genuinely does run for
    # Ethiopia. It is allowed with a warning, since nothing downstream can
    # consume the result.
    local stage="$1"
    local maternal_locations=" india nigeria "
    local child_locations=" india nigeria "
    local paf_locations=" ethiopia india nigeria "
    # tr rather than ${LOCATION,,}, which needs bash 4 (macOS ships bash 3.2).
    # This is also the artifact filename stem: make_artifacts sanitizes the
    # location to lower case with whitespace replaced before writing <stem>.hdf.
    local location_lower
    location_lower="$(printf '%s' "${LOCATION}" | tr '[:upper:] ' '[:lower:]_')"
    LOCATION_SLUG="${location_lower}"

    case "${stage}" in
        maternal-*)
            [[ "${maternal_locations}" == *" ${location_lower} "* ]] \
                || die "The maternal model does not run for '${LOCATION}'. Supported:${maternal_locations}"
            ;;
        child-*)
            [[ "${child_locations}" == *" ${location_lower} "* ]] \
                || die "The child model does not run for '${LOCATION}'. Supported:${child_locations}
Ethiopia is listed in the child package's metadata.LOCATIONS and in the README,
but has no iron vehicle and no maternal births, so neither the child artifact
nor the child simulation can be built for it. See validate_config in this file."
            ;;
        paf-*)
            [[ "${paf_locations}" == *" ${location_lower} "* ]] \
                || die "The LBWSG PAF stages do not run for '${LOCATION}'. Supported:${paf_locations}"
            if [[ "${location_lower}" == "ethiopia" ]]; then
                note "WARNING: the LBWSG PAF builds and runs for Ethiopia, but no child"
                note "         artifact or simulation can consume it -- Ethiopia has no"
                note "         iron vehicle. This output will not feed anything."
            fi
            ;;
    esac
}

# psimulate's cluster flags, identical for all three simulation stages.
cluster_flags() {
    printf '%s' "-P ${PROJECT} -m ${MEMORY_GB} -r ${RUNTIME} -q ${QUEUE} ${PSIMULATE_VERBOSITY}"
}

# The most recent run directory under a psimulate results location. Run
# directories are timestamped, so lexical order is chronological order.
latest_run() {
    local dir="$1" newest
    [[ -d "${dir}" ]] || die "No results directory at ${dir}
Has the upstream stage finished?"
    newest="$(find "${dir}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
    [[ -n "${newest}" ]] || die "No run directories under ${dir}"
    basename -- "${newest}"
}

# --- stages ----------------------------------------------------------------

stage_maternal_artifact() {
    check_env artifact
    # shellcheck disable=SC2046  # word splitting of ARTIFACT_FLAGS is intended
    run make_artifacts -p maternal -l "${LOCATION}" \
        --vehicle "${VEHICLE}" \
        -o "${LSFF_MATERNAL_ARTIFACT_ROOT}" \
        ${ARTIFACT_FLAGS} "${ARTIFACT_VERBOSITY}"
}

stage_maternal_sim() {
    check_env simulation
    require_artifact "${MATERNAL_ARTIFACT}"
    # shellcheck disable=SC2046
    run psimulate run \
        "${MATERNAL_SPEC}" \
        "${MATERNAL_BRANCH_DIR}/${BRANCHES_FILE}" \
        -i "${MATERNAL_ARTIFACT}" \
        -o "${LSFF_MATERNAL_RESULTS_ROOT}" \
        $(cluster_flags)
}

stage_paf_artifact() {
    check_env artifact
    # shellcheck disable=SC2046
    run make_artifacts -p child -l "${LOCATION}" \
        --for-lbwsg-pafs --national \
        -o "${LSFF_LBWSG_PAF_ARTIFACT_ROOT}" \
        ${ARTIFACT_FLAGS} "${ARTIFACT_VERBOSITY}"
}

stage_paf_sim() {
    check_env simulation
    require_artifact "${PAF_ARTIFACT}"
    # shellcheck disable=SC2046
    run psimulate run \
        "${PAF_SPEC}" \
        "${PAF_BRANCHES}" \
        -i "${PAF_ARTIFACT}" \
        -o "${LSFF_LBWSG_PAF_RESULTS_ROOT}" \
        $(cluster_flags)
}

stage_child_artifact() {
    check_env artifact

    local maternal_dir run_id births
    maternal_dir="${LSFF_MATERNAL_RESULTS_ROOT}/${LOCATION}"

    if [[ -n "${MATERNAL_RUN}" ]]; then
        run_id="${MATERNAL_RUN}"
    else
        run_id="$(latest_run "${maternal_dir}")"
        note "Using the most recent maternal run: ${run_id}"
        note "Pin a different one with MATERNAL_RUN=<run>."
    fi

    births="${maternal_dir}/${run_id}/results/births"
    if [[ "${DRY_RUN}" != "yes" && ! -e "${births}" ]]; then
        die "No births output at ${births}
Stage 2 must finish before the child artifact can be built."
    fi

    # The stage 4 PAF results are found automatically under the paths module's
    # LBWSG_PAF_RESULTS_ROOT; the build logs which run it used and takes the most
    # recent, so check that line when more than one is present.
    # shellcheck disable=SC2046
    run make_artifacts -p child -l "${LOCATION}" \
        --vehicle "${VEHICLE}" --national \
        -o "${LSFF_CHILD_ARTIFACT_ROOT}" \
        --fertility-data-path "${births}" \
        ${ARTIFACT_FLAGS} "${ARTIFACT_VERBOSITY}"
}

stage_child_sim() {
    check_env simulation
    require_artifact "${CHILD_ARTIFACT}"
    # shellcheck disable=SC2046
    run psimulate run \
        "${CHILD_SPEC}" \
        "${CHILD_BRANCH_DIR}/${BRANCHES_FILE}" \
        -i "${CHILD_ARTIFACT}" \
        -o "${LSFF_CHILD_RESULTS_ROOT}" \
        $(cluster_flags)
}

stage_restart() {
    check_env simulation
    local run_dir="${1:-}"
    [[ -n "${run_dir}" ]] || die "Usage: ./run.sh restart <run_dir>"
    # shellcheck disable=SC2046
    run psimulate restart "${run_dir}" $(cluster_flags)
}

show_paths() {
    cat <<EOF

  MODEL_NUMBER          ${LSFF_MODEL_NUMBER}
  location              ${LOCATION}
  vehicle               ${VEHICLE}
  branches              ${BRANCHES} (${BRANCHES_FILE})
$([[ -n "${SCRATCH_ROOT}" ]] && echo "  SCRATCH_ROOT          ${SCRATCH_ROOT}")
$([[ -n "${LEGACY_ARCHIVE}" ]] && echo "  LEGACY_ARCHIVE        ${LEGACY_ARCHIVE}")

  Artifact builds write to (stages 1, 3, 5):

  1  maternal artifact  ${LSFF_MATERNAL_ARTIFACT_ROOT}
  3  paf artifact       ${LSFF_LBWSG_PAF_ARTIFACT_ROOT}
  5  child artifact     ${LSFF_CHILD_ARTIFACT_ROOT}

  Simulations read (psimulate -i) $(artifact_status "${MATERNAL_ARTIFACT}" "${PAF_ARTIFACT}" "${CHILD_ARTIFACT}")

  2  maternal      $(mark "${MATERNAL_ARTIFACT}")
  4  paf           $(mark "${PAF_ARTIFACT}")
  6  child         $(mark "${CHILD_ARTIFACT}")

  Simulations write to:

  2  maternal results   ${LSFF_MATERNAL_RESULTS_ROOT}
  4  paf results        ${LSFF_LBWSG_PAF_RESULTS_ROOT}
  6  child results      ${LSFF_CHILD_RESULTS_ROOT}

EOF
}

# Annotate each artifact with whether it is actually there, so 'paths' answers
# "will this run?" and not merely "what would it type?".
mark() {
    if [[ -f "$1" ]]; then printf 'FOUND    %s' "$1"; else printf 'MISSING  %s' "$1"; fi
}

artifact_status() {
    local path
    for path in "$@"; do
        [[ -f "${path}" ]] || { printf '%s' "-- some are missing:"; return; }
    done
    printf '%s' "-- all present:"
}

# Print the header comment block: everything after the shebang up to the first
# line that is not a comment. Derived rather than a hardcoded line range, so
# editing the header cannot silently truncate or overrun the help text.
usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
}

# --- dispatch --------------------------------------------------------------

main() {
    local args=()
    for arg in "$@"; do
        case "${arg}" in
            -n|--dry-run) DRY_RUN="yes" ;;
            -h|--help)    usage; exit 0 ;;
            *)            args+=("${arg}") ;;
        esac
    done

    [[ ${#args[@]} -gt 0 ]] || { usage; exit 1; }

    validate_config "${args[0]}"
    resolve_paths

    case "${args[0]}" in
        maternal-artifact) stage_maternal_artifact ;;
        maternal-sim)      stage_maternal_sim ;;
        paf-artifact)      stage_paf_artifact ;;
        paf-sim)           stage_paf_sim ;;
        child-artifact)    stage_child_artifact ;;
        child-sim)         stage_child_sim ;;

        maternal-branch)   stage_maternal_artifact; stage_maternal_sim ;;
        paf-branch)        stage_paf_artifact; stage_paf_sim ;;
        child-branch)      stage_child_artifact; stage_child_sim ;;

        restart)           stage_restart "${args[1]:-}" ;;
        paths)             show_paths ;;

        *) die "Unknown command '${args[0]}'. Run './run.sh --help' for the list." ;;
    esac
}

main "$@"
