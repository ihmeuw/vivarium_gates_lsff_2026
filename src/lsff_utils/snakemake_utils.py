"""Helpers shared by the Snakefiles.

Kept out of the Snakefiles themselves so the rules stay readable and so the
same path logic is importable from tests and notebooks.
"""

import builtins
import sys
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


def output_path(in_repo_root: Path, *parts: str, target: str) -> str:
    """A pipeline output as a rule output, written to ``target`` (see :func:`paths.output_root`).

    Local paths are repo-relative and team-drive paths are absolute, the same
    as :func:`source_path` renders them, so an input matches the rule that
    produces it.
    """
    root = paths.output_root(in_repo_root, target)
    if target == paths.LOCAL_SOURCE:
        root = root.relative_to(paths.REPO_ROOT)
    return str(root.joinpath(*parts))


def source_path(in_repo_root: Path, *parts: str, source: str) -> str:
    """A pipeline output as a rule input, read from ``source`` (see :func:`paths.source_root`).

    An archived input has a producing rule only when this run writes to the
    same model number. Otherwise it is read as it is.
    """
    paths.source_root(in_repo_root, source)
    return output_path(in_repo_root, *parts, target=source)


# ---------------------------------------------------------------------------
# Writing to the team drive
# ---------------------------------------------------------------------------

#: Written into each ``<kind>/<MODEL_NUMBER>`` directory that a run writes to directly.
TEAM_RUN_INFO_NAME = "pipeline_run_info.txt"

#: Written by ``archive_last_run.sh``. Its presence marks an archived iteration.
ARCHIVE_INFO_NAME = "archive_info.txt"

ARCHIVE_KINDS = ("artifacts", "data", "results")


def resolve_output_target(write_local: bool, debug: bool) -> str:
    """Where a run writes: the working tree, or the team drive under MODEL_NUMBER.

    The team drive is the default. A debug run always writes to the working
    tree. The archive script never overwrites an archived iteration, so a run
    cannot write into one, and it refuses an ``LSFF_DATA_SOURCE`` that names a
    different iteration from the one being written.
    """
    if write_local or debug:
        return paths.LOCAL_SOURCE

    target = paths.MODEL_NUMBER
    if not paths.TEAM_ARCHIVE_ROOT.is_dir():
        raise ValueError(
            f"{paths.TEAM_ARCHIVE_ROOT} is not reachable from this machine. Pass "
            f"--config write_local=true to write to the working tree instead."
        )
    source = paths.data_source(default=target)
    if source != target:
        raise ValueError(
            f"This run writes {target}, but {paths.DATA_SOURCE_ENV_VAR}='{source}'. "
            f"Unset {paths.DATA_SOURCE_ENV_VAR}, so the analysis reads the run it "
            f"belongs to."
        )
    archived = [
        str(info)
        for kind in ARCHIVE_KINDS
        if (info := paths.TEAM_ARCHIVE_ROOT / kind / target / ARCHIVE_INFO_NAME).exists()
    ]
    if archived:
        raise ValueError(
            f"{target} was published by archive_last_run.sh ({', '.join(archived)}), "
            f"and the archive is append-only. Bump MODEL_NUMBER in "
            f"src/lsff_utils/paths.py to write a new iteration."
        )
    return target


def existing_team_output(target: str) -> str | None:
    """A description of what is already written under ``target``, or None if nothing is."""
    used = [
        directory
        for kind in ARCHIVE_KINDS
        if (directory := paths.TEAM_ARCHIVE_ROOT / kind / target).is_dir()
        and any(directory.iterdir())
    ]
    if not used:
        return None
    info = used[0] / TEAM_RUN_INFO_NAME
    if not info.exists():
        return f"{', '.join(str(d) for d in used)} already has output."
    records = [r.strip() for r in info.read_text().split("---") if r.strip()]
    last = records[-1] if records else "(no record)"
    return f"{target} was already written to. Its last run was:\n{last}"


def confirm_model_number_reuse(target: str, reuse: bool) -> None:
    """Ask before a run writes into a model number that already has output.

    ``reuse_model_number=true`` skips the question, for resumed runs and for
    runs with no terminal to answer it.
    """
    existing = existing_team_output(target)
    if existing is None or reuse:
        return

    message = (
        f"{existing}\n\nThis run would rebuild stale outputs in place. Bump "
        f"MODEL_NUMBER in src/lsff_utils/paths.py to start a new iteration instead."
    )
    if not sys.stdin.isatty():
        raise SystemExit(
            f"{message}\nNo terminal to confirm from. Pass --config "
            f"reuse_model_number=true to write into {target} anyway."
        )
    print(message, file=sys.stderr)
    answer = builtins.input(f"Write into {target}? [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        raise SystemExit(f"Stopped. Nothing was written to {target}.")


def record_team_run(target: str, command: list[str]) -> None:
    """Append who started this run, when, from what tree, and with what command.

    This is the direct-write counterpart of ``archive_info.txt``. Each run
    directory also gets its own ``git_commit.txt``.
    """
    import datetime
    import getpass
    import socket
    import subprocess

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(paths.REPO_ROOT), *args], capture_output=True, text=True
        )

    clean = git("diff", "--quiet", "HEAD").returncode == 0
    record = "\n".join(
        [
            f"started:   {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M:%S %z}",
            f"by:        {getpass.getuser()}@{socket.gethostname()}",
            f"from:      {paths.REPO_ROOT}",
            f"commit:    {git('rev-parse', 'HEAD').stdout.strip()}",
            f"tree:      {'clean' if clean else 'DIRTY (see each run git_commit.txt for its diff)'}",
            f"command:   {' '.join(quote(arg) for arg in command)}",
            "---",
            "",
        ]
    )
    for kind in ARCHIVE_KINDS:
        dest = paths.TEAM_ARCHIVE_ROOT / kind / target
        dest.mkdir(parents=True, exist_ok=True)
        with (dest / TEAM_RUN_INFO_NAME).open("a") as f:
            f.write(record)


def write_run_marker(results_root: Path, location: str, vehicle: str = None) -> str:
    """Shell that records the run just produced, for the end of a rule's recipe.

    Run directories are timestamp-named, so the one this run created sorts last.
    Only names matching :data:`paths.RUN_DIR_GLOB` are considered: an old,
    non-timestamped folder left in the run root (e.g. `ylls/`) would otherwise
    sort after every timestamp and be checked -- and marked -- instead.

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
    return f"""run=$(for candidate in {quote(str(root))}/{paths.RUN_DIR_GLOB}/; do
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
