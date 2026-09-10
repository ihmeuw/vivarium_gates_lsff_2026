"""
=====
Paths
=====

Filesystem locations for the LSFF modeling pipeline.

The pipeline reads and writes inside the repository, beside the package that
produces each thing::

    0200_pregnancy_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
    0200_pregnancy_sim/sim_results/<vehicle>/<location>/<run>/
    0300_child_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
    0300_child_sim/sim_results/<vehicle>/<location>/<run>/
    0300_child_sim/lbwsg_paf_mean_draw_artifacts/<location>.hdf
    0300_child_sim/lbwsg_pafs/<location>/<run>/

All six are gitignored: they hold large binaries and psimulate's per-run
metadata, none of which belongs in version control.

Nothing here carries a model iteration number. The repository holds the run you
are working on; ``archive_last_run.sh`` publishes it to the team drive under
:data:`MODEL_NUMBER`, and that archive is the versioned record::

    /mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/
    |-- artifacts/<MODEL_NUMBER>/{maternal,child}/<vehicle>/<location>.hdf
    |-- data/<MODEL_NUMBER>/{lbwsg_paf_artifacts,lbwsg_pafs}/
    `-- results/<MODEL_NUMBER>/{maternal,child}/<vehicle>/<location>/<run>/

:func:`archive_root` maps an in-repo root to its archived counterpart, so a
reader of a published iteration -- the V&V notebooks -- names the root it wants
and lets :data:`MODEL_NUMBER` supply the rest::

    results = latest_results(archive_root(CHILD_RESULTS_ROOT), location, vehicle)

Because the in-repo paths do not move between iterations, Snakemake no longer
rebuilds a stage just because a number was bumped -- it reruns on changed inputs
or changed recipe code, which is what its staleness tracking is for. Starting a
new iteration therefore means: archive what you have, bump MODEL_NUMBER, then
clear the in-repo roots (or ``--forcerun`` the stages you want rebuilt). See the
"Starting a New Model Iteration" section of the README.

These constants live in ``lsff_utils`` rather than in either simulation package
because the two packages have to agree on them. The child model's population
comes from the maternal model's birth records, so the child artifact build reads
out of the same ``results/`` directory the maternal simulation wrote to.
"""

from pathlib import Path

#: Repository root, derived from this file's location: <repo>/src/lsff_utils/paths.py.
REPO_ROOT = Path(__file__).resolve().parents[2]

MATERNAL_PKG_ROOT = REPO_ROOT / "0200_pregnancy_sim"
CHILD_PKG_ROOT = REPO_ROOT / "0300_child_sim"

MATERNAL_ARTIFACT_ROOT = MATERNAL_PKG_ROOT / "mean_draw_artifacts"
CHILD_ARTIFACT_ROOT = CHILD_PKG_ROOT / "mean_draw_artifacts"

MATERNAL_RESULTS_ROOT = MATERNAL_PKG_ROOT / "sim_results"
CHILD_RESULTS_ROOT = CHILD_PKG_ROOT / "sim_results"

# The PAF calculation runs as its own simulation between the two artifact builds.
# Its cut-down artifact omits the PAF that the calculation produces, so it must
# never share a path with the full child artifact.
LBWSG_PAF_ARTIFACT_ROOT = CHILD_PKG_ROOT / "lbwsg_paf_mean_draw_artifacts"
LBWSG_PAF_RESULTS_ROOT = CHILD_PKG_ROOT / "lbwsg_pafs"


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

#: Label the archive files this iteration under. Bump it to start a new one.
MODEL_NUMBER = "model1.1.2"

#: Team-drive root that ``archive_last_run.sh`` publishes to.
TEAM_ARCHIVE_ROOT = Path("/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026")

#: Records the commit a run was produced on. Written into each run directory by
#: the simulation rules, so it travels with the run when it is archived.
GIT_COMMIT_FILE_NAME = "git_commit.txt"

# Where each in-repo root lands in the archive. The repository groups outputs by
# the package that produced them; the archive groups them by kind and iteration,
# so the two layouts do not correspond and the mapping has to be written down.
# Destination is <team>/<kind>/<MODEL_NUMBER>/<subpath>/<the rest of the path>.
ARCHIVE_DESTINATIONS = {
    MATERNAL_ARTIFACT_ROOT: ("artifacts", "maternal"),
    CHILD_ARTIFACT_ROOT: ("artifacts", "child"),
    LBWSG_PAF_ARTIFACT_ROOT: ("data", "lbwsg_paf_artifacts"),
    LBWSG_PAF_RESULTS_ROOT: ("data", "lbwsg_pafs"),
    MATERNAL_RESULTS_ROOT: ("results", "maternal"),
    CHILD_RESULTS_ROOT: ("results", "child"),
}

#: Roots holding timestamped simulation runs, archived one run at a time.
RUN_ROOTS = (MATERNAL_RESULTS_ROOT, CHILD_RESULTS_ROOT, LBWSG_PAF_RESULTS_ROOT)


def archive_root(in_repo_root: Path, model_number: str = MODEL_NUMBER) -> Path:
    """Where ``archive_last_run.sh`` publishes what ``in_repo_root`` holds.

    The inverse of the copy the archive script performs, so anything reading a
    published iteration -- the V&V notebooks -- names the in-repo root it wants
    and gets the archived counterpart, rather than restating the archive layout.
    Everything below the root keeps its shape, so :func:`artifact_path`,
    :func:`latest_run` and :func:`latest_results` work against either side.
    """
    try:
        kind, subpath = ARCHIVE_DESTINATIONS[in_repo_root]
    except KeyError:
        raise KeyError(
            f"'{in_repo_root}' is not archived. Pass one of the roots in "
            f"ARCHIVE_DESTINATIONS: {[str(root) for root in ARCHIVE_DESTINATIONS]}."
        ) from None
    return TEAM_ARCHIVE_ROOT / kind / model_number / subpath


def archived_model_numbers(kind: str = "results") -> list[str]:
    """Iterations published under one archive kind, oldest label first."""
    root = TEAM_ARCHIVE_ROOT / kind
    return sorted(p.name for p in root.glob("*") if p.is_dir())


def artifact_path(artifact_root: Path, location: str, vehicle: str | None = None) -> Path:
    """The artifact for one location (and vehicle, if the root is keyed by one)."""
    root = artifact_root if vehicle is None else artifact_root / vehicle
    return root / f"{location.lower().replace(' ', '_')}.hdf"


# ---------------------------------------------------------------------------
# Run directories
# ---------------------------------------------------------------------------
#
# vivarium names each simulation run after the artifact it ran against and the
# moment it was launched: `<results_dir>/<artifact stem>/<timestamp>/results/`.
# Because artifacts are named `<location>.hdf` and are passed with `-o` pointed
# at the vehicle directory, a run lands at
#
#     <root>/<vehicle>/<location>/<timestamp>/results/
#
# Snakemake cannot name that timestamp in advance, and a rule needs an output
# path it can name. Each simulation rule therefore writes RUN_MARKER_NAME next
# to the run directories once the run succeeds, holding the name of the run it
# just produced. The marker is what Snakemake tracks, what `latest_run` reads,
# and what the archive script uses to pick the run to publish.

RUN_MARKER_NAME = "latest_run.txt"


def run_root(results_root: Path, location: str, vehicle: str | None = None) -> Path:
    """The directory holding every run for one location (and vehicle, if any)."""
    root = results_root if vehicle is None else results_root / vehicle
    return root / location.lower().replace(" ", "_")


def run_marker(results_root: Path, location: str, vehicle: str | None = None) -> Path:
    """Path of the marker naming the most recent successful run."""
    return run_root(results_root, location, vehicle) / RUN_MARKER_NAME


def latest_run(results_root: Path, location: str, vehicle: str | None = None) -> Path:
    """The run directory named by the marker, falling back to the newest run.

    The fallback matters because runs launched by hand -- outside Snakemake, which
    is how a single location usually gets rerun -- leave no marker. Run
    directories are timestamp-named, so the newest sorts last.
    """
    root = run_root(results_root, location, vehicle)
    marker = root / RUN_MARKER_NAME
    if marker.exists():
        run = root / marker.read_text().strip()
        if run.exists():
            return run

    runs = sorted(p for p in root.glob("*") if p.is_dir())
    if not runs:
        raise FileNotFoundError(
            f"No simulation runs found under '{root}'. Expected at least one "
            f"timestamped run directory, produced by 'psimulate run -o "
            f"{root.parent}' -- or, under the archive, published there by "
            f"archive_last_run.sh."
        )
    return runs[-1]


def latest_results(results_root: Path, location: str, vehicle: str | None = None) -> Path:
    """The ``results`` directory of the run :func:`latest_run` resolves to."""
    return latest_run(results_root, location, vehicle) / "results"


def measure_path(results_dir: Path, measure: str) -> Path:
    """Locate one observer's output within a run's ``results`` directory.

    Two layouts are in circulation and both are readable by ``pd.read_parquet``:
    ``simulate run`` writes a single ``<measure>.parquet``, while ``psimulate``
    writes a ``<measure>/`` directory of one parquet file per task. Which one a
    given set of results uses depends on how it was produced, so callers ask for
    the measure by name and let this sort it out.
    """
    flat = results_dir / f"{measure}.parquet"
    if flat.exists():
        return flat

    sharded = results_dir / measure
    if sharded.is_dir():
        return sharded

    raise FileNotFoundError(
        f"No '{measure}' output under '{results_dir}'. Expected either "
        f"'{measure}.parquet' or a '{measure}/' directory of parquet files."
    )
