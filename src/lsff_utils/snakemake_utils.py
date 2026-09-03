"""Helpers shared by the Snakefiles.

Kept out of the Snakefiles themselves so the rules stay readable and so the
same path logic is importable from tests and notebooks.
"""

from pathlib import Path
from shlex import quote

from lsff_utils import paths


# We use papermill to run the notebooks, instead of the built-in Snakemake integration,
# because it does not generate incremental output, nor output notebooks when there is
# an error. See https://github.com/snakemake/snakemake/pull/2857
def dict_to_papermill(d):
    return " ".join([f"-p {quote(str(k))} {quote(str(v))}" for k, v in d.items()])


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
#
# The pipeline runs in the two environments `environment.sh` builds: `artifact`
# for anything that reads GBD (data prep, artifact builds, the analysis
# notebooks) and `simulation` for anything that runs vivarium. There is no
# Snakemake-managed environment and no lockfile -- `environment.sh` and
# `pyproject.toml` are the single source of truth for what is installed.
#
# A rule cannot depend on a conda environment the way the old rules depended on
# `.venv/bin/activate`, because an environment is not a file with a useful
# mtime. That is deliberate: Snakemake no longer builds environments, so it has
# nothing to rebuild them from, and treating one as an input would only make
# every rule rerun whenever a package was installed.

ENVIRONMENT_TYPES = ("artifact", "simulation")

#: Names `environment.sh` gives the two environments (`<repo name>_<type>`).
DEFAULT_ENVIRONMENTS = {
    env_type: f"vivarium_gates_lsff_2026_{env_type}" for env_type in ENVIRONMENT_TYPES
}


def env_setup(environment: str) -> str:
    """Render the shell that activates `environment` at the top of a rule.

    `environment` is either a conda environment name (the default) or a path to
    a venv, which is how `environment.sh -s` builds the shared-environment
    overlay. A path is anything containing a separator, so
    `--config simulation_env=.venv/vivarium_gates_lsff_2026_simulation` is
    enough to switch a run over to one.
    """
    if "/" in environment:
        activate = Path(environment)
        if activate.name != "activate":
            activate = activate / "bin" / "activate"
        return f"source {quote(str(activate))}"

    # `conda activate` needs the shell hook, which a non-interactive Snakemake
    # shell has not sourced. Deriving the base rather than hardcoding it keeps
    # this working for whichever conda install is on PATH.
    return (
        'source "$(conda info --base)/etc/profile.d/conda.sh"\n'
        f"conda activate {quote(environment)}"
    )


def resolve_environments(config: dict) -> dict:
    """Fill in the environment settings a run did not override.

    Two levels of override, both via `--config`: `<type>_env` names a different
    environment or venv, and `<type>_env_setup` replaces the activation shell
    outright for anything the first cannot express.
    """
    resolved = {}
    for env_type, default in DEFAULT_ENVIRONMENTS.items():
        environment = config.get(f"{env_type}_env", default)
        setup = config.get(f"{env_type}_env_setup") or env_setup(environment)
        resolved[f"{env_type}_env"] = environment
        resolved[f"{env_type}_env_setup"] = setup
    return resolved


def freeze(inputs, frozen: bool):
    """Wrap `inputs` in `ancient()` when their stage is being taken as given.

    `ancient()` tells Snakemake to stop comparing an input's timestamp against
    the outputs, so a stage stops rerunning merely because a file it reads was
    touched. Missing outputs still schedule the stage -- this suppresses staleness,
    not the work itself, so nothing that genuinely has to be built is skipped.

    Used for the two stages whose outputs are expensive and change on a different
    clock from the model: the LBWSG PAF calculation, and data prep when a run
    opts out of it.
    """
    if not frozen:
        return list(inputs)

    # Imported here rather than at module scope: this module is also imported by
    # the tests and the analysis notebooks, which run in environments that have
    # no Snakemake.
    from snakemake.io import ancient

    return [ancient(item) for item in inputs]


# ---------------------------------------------------------------------------
# Simulation run markers
# ---------------------------------------------------------------------------
#
# See the "Run directories" section of lsff_utils.paths for why simulation rules
# are tracked by a marker file rather than by their parquet output.

#: Cap on the diff embedded in `git_commit.txt` when a run is made on a dirty
#: tree. The executed notebooks this pipeline commits carry their outputs, so an
#: unrestricted `git diff` put 8-9 MB in every run directory -- and every archived
#: copy of it. Above this the summary is kept and the diff body dropped.
MAX_EMBEDDED_DIFF_BYTES = 1_048_576


def run_marker(results_root: Path, location: str, vehicle: str = None) -> str:
    """The marker a simulation rule declares as its output, as a string.

    Wildcards survive this untouched -- `location="{location}"` renders the
    literal `{location}` that Snakemake expands -- so rules can name their
    outputs with the same helper that resolves a concrete path later.
    """
    return str(paths.run_marker(results_root, location, vehicle))


def write_run_marker(results_root: Path, location: str, vehicle: str = None) -> str:
    """Shell that records the run just produced, for the end of a rule's recipe.

    Run directories are timestamp-named, so the one this run created sorts last.

    `psimulate` exiting successfully is not enough to go on: it exits 0 even when
    every one of its jobmon tasks failed, logging the failure rather than raising.
    A run whose tasks all died still leaves a timestamped directory behind, so the
    marker also checks that something was actually written to `results/` -- without
    it, an empty run gets marked current and the next stage fails on missing
    measures instead of on the simulation that produced none.

    Also writes `git_commit.txt` into the run directory. It has to be written here
    rather than at archive time: HEAD moves, and the archive would then record the
    commit it was run from instead of the one that produced the results. Snakemake
    does not care whether the tree is clean, so the diff is captured too -- without
    it a run made mid-edit is not reproducible from any commit. Large diffs are
    summarized rather than embedded; see :data:`MAX_EMBEDDED_DIFF_BYTES`.
    """
    root = paths.run_root(results_root, location, vehicle)
    marker = paths.run_marker(results_root, location, vehicle)
    commit_file = f'{quote(str(root))}/"$run"/{paths.GIT_COMMIT_FILE_NAME}'
    # The `-d` test is what makes an unmatched glob an error rather than a marker
    # naming the literal pattern: a simulation that produced no run directory has
    # failed, and the rule has to fail with it rather than leave a marker
    # pointing at nothing for the next stage to trip over.
    #
    # `|| true` is what lets the `if` below do the failing. An unmatched glob
    # leaves the `-d` test as the loop's last command, so the loop -- and, under
    # `pipefail`, the whole pipeline -- exits non-zero; without this the rule's
    # `set -e` would abort at the assignment and the message would never print.
    return f"""run=$(for candidate in {quote(str(root))}/*/; do
            [ -d "$candidate" ] && basename "$candidate"
        done | sort | tail -1) || true
        if [ -z "$run" ]; then
            echo "No run directory was created under {root}" >&2
            exit 1
        fi
        if [ -z "$(ls -A {quote(str(root))}/"$run"/results 2>/dev/null)" ]; then
            echo "psimulate wrote no results under {root}/$run -- its jobmon workflow" >&2
            echo "failed. psimulate exits 0 in that case (it only logs the failure), so" >&2
            echo "this check is what keeps a run that produced nothing from being marked" >&2
            echo "current and consumed by the next stage." >&2
            exit 1
        fi
        {{
            echo "commit:  $(git rev-parse HEAD)"
            echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
            echo "date:    $(date '+%Y-%m-%d %H:%M:%S %z')"
            if git diff --quiet HEAD; then
                echo "tree:    clean"
            else
                echo "tree:    DIRTY -- summary of uncommitted changes follows"
                echo
                git diff --stat HEAD
                echo
                diff_bytes=$(git diff HEAD | wc -c)
                if [ "$diff_bytes" -le {MAX_EMBEDDED_DIFF_BYTES} ]; then
                    echo "--- full diff ($diff_bytes bytes) ---"
                    git diff HEAD
                else
                    echo "Full diff omitted: $diff_bytes bytes exceeds the"
                    echo "{MAX_EMBEDDED_DIFF_BYTES} byte cap. Recover it with 'git diff' against"
                    echo "the commit above, or commit before running to avoid this."
                fi
            fi
        }} > {commit_file}
        printf '%s\\n' "$run" > {quote(str(marker))}"""


def read_run_marker(results_root: Path, location: str, vehicle: str = None) -> str:
    """Shell substitution expanding to the run directory a marker names."""
    root = paths.run_root(results_root, location, vehicle)
    marker = paths.run_marker(results_root, location, vehicle)
    return f'{quote(str(root))}/"$(cat {quote(str(marker))})"'
