"""Guard the path layout against drift.

The pipeline writes inside the repository and ``archive_last_run.sh`` publishes a
run to the team drive under ``MODEL_NUMBER``. Two things have to stay true for
that to work, and neither is obvious from reading a single file:

* the in-repo roots must stay inside the repository, and must *not* carry a model
  iteration number -- the archive supplies the versioning, and a number in the
  repo path would put the specifications back in the business of tracking it;
* the in-repo roots must stay gitignored, because they hold large binaries and
  psimulate's per-run metadata.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

import lsff_utils.paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_paths_from_checkout():
    """Load ``paths`` from this checkout rather than from wherever it is installed.

    These invariants are properties of the source layout, and ``paths.REPO_ROOT``
    is derived from ``__file__``. Under an editable install that is the checkout,
    but CI installs a copy into site-packages, where ``REPO_ROOT`` resolves to
    ``<env>/lib/pythonX.Y`` and every in-repo root becomes meaningless. Loading
    the file by path makes these tests independent of the install mode.
    """
    source = REPO_ROOT / "src" / "lsff_utils" / "paths.py"
    spec = importlib.util.spec_from_file_location("_lsff_paths_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = _load_paths_from_checkout()

# Every root the pipeline writes to, and whether runs land in timestamped
# subdirectories underneath it.
IN_REPO_ROOTS = {
    "MATERNAL_ARTIFACT_ROOT": paths.MATERNAL_ARTIFACT_ROOT,
    "CHILD_ARTIFACT_ROOT": paths.CHILD_ARTIFACT_ROOT,
    "MATERNAL_RESULTS_ROOT": paths.MATERNAL_RESULTS_ROOT,
    "CHILD_RESULTS_ROOT": paths.CHILD_RESULTS_ROOT,
    "LBWSG_PAF_ARTIFACT_ROOT": paths.LBWSG_PAF_ARTIFACT_ROOT,
    "LBWSG_PAF_RESULTS_ROOT": paths.LBWSG_PAF_RESULTS_ROOT,
}


def test_repo_root_is_this_repository() -> None:
    """``REPO_ROOT`` must resolve to the checkout the module was loaded from.

    Checked against the *installed* ``lsff_utils`` when that is this checkout --
    i.e. an editable install. A non-editable install puts a copy in
    site-packages, where ``REPO_ROOT`` cannot resolve to a repository at all;
    that is an environment property rather than a defect in the layout, so it
    skips instead of failing.
    """
    installed = Path(lsff_utils.paths.__file__).resolve()
    if REPO_ROOT not in installed.parents:
        pytest.skip(
            f"lsff_utils is imported from {installed.parent}, not this checkout, "
            f"so REPO_ROOT cannot resolve to a repository. Install editable to "
            f"exercise this."
        )
    assert lsff_utils.paths.REPO_ROOT == REPO_ROOT, (
        "paths.REPO_ROOT is derived from __file__; it has drifted from the "
        "repository this test lives in, which usually means the module moved."
    )


@pytest.mark.parametrize("name, root", IN_REPO_ROOTS.items())
def test_roots_are_inside_the_repository(name: str, root: Path) -> None:
    assert paths.REPO_ROOT in root.parents, f"{name} is not inside the repository"


@pytest.mark.parametrize("name, root", IN_REPO_ROOTS.items())
def test_roots_do_not_carry_the_model_number(name: str, root: Path) -> None:
    """A number in an in-repo path would make every iteration move these roots.

    That is the archive's job. It also drags the model specifications along, since
    YAML cannot read these constants and has to restate the artifact path.
    """
    assert paths.MODEL_NUMBER not in root.parts, (
        f"{name} carries MODEL_NUMBER. The in-repo layout is iteration-agnostic; "
        f"MODEL_NUMBER labels the archive only."
    )


@pytest.mark.parametrize("name, root", IN_REPO_ROOTS.items())
def test_roots_are_gitignored(name: str, root: Path) -> None:
    """Pipeline output must never be committable.

    ``git check-ignore`` is the authority here rather than reading .gitignore,
    because the patterns are directory-anchored and precedence matters.
    """
    probe = root / "probe.parquet"
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(probe)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"{name} is not gitignored ({probe.relative_to(REPO_ROOT)}). Pipeline "
        f"output would be committable."
    )


def test_lbwsg_paf_inputs_and_child_artifact_are_distinct() -> None:
    """The PAF calculation's artifact holds a different key set from the child's."""
    assert paths.LBWSG_PAF_ARTIFACT_ROOT != paths.CHILD_ARTIFACT_ROOT


def test_archive_target_is_the_team_drive() -> None:
    """The archive is the versioned, shared record; it does not live in the repo."""
    assert paths.TEAM_ARCHIVE_ROOT.is_absolute()
    assert paths.REPO_ROOT not in paths.TEAM_ARCHIVE_ROOT.parents
    assert paths.MODEL_NUMBER, "MODEL_NUMBER labels the archive and cannot be empty"


def test_run_marker_sits_beside_the_run_directories() -> None:
    """`latest_run` and the archive script both rely on this arrangement."""
    root = paths.run_root(paths.MATERNAL_RESULTS_ROOT, "Nigeria", "rice")
    marker = paths.run_marker(paths.MATERNAL_RESULTS_ROOT, "Nigeria", "rice")

    assert marker.parent == root
    assert marker.name == paths.RUN_MARKER_NAME
    # Locations are lowercased and de-spaced so a wildcard and a display name
    # resolve to the same directory.
    assert root.name == "nigeria"


@pytest.mark.parametrize(
    "root", list(lsff_utils.paths.ARCHIVE_DESTINATIONS), ids=lambda p: p.name
)
def test_archive_root_mirrors_the_archive_script(root: Path) -> None:
    """``archive_root`` is the read side of the copy the script performs.

    The V&V notebooks resolve their inputs through it, so it has to land on the
    same directory ``archive_last_run.sh`` wrote to. Checked against
    ``archive_utils``, which is what the script itself calls -- so both sides come
    from the installed package rather than the checkout copy loaded above.
    """
    from lsff_utils import archive_utils

    installed = lsff_utils.paths
    probe = root / "vehicle" / "location.hdf"
    expected = archive_utils.archived_artifact_path(
        probe, installed.REPO_ROOT, installed.TEAM_ARCHIVE_ROOT, installed.MODEL_NUMBER
    )
    assert installed.archive_root(root) / "vehicle" / "location.hdf" == expected


def test_archive_root_is_keyed_on_the_model_number() -> None:
    """The iteration is the archive's versioning, and it is the only thing to bump."""
    archived = paths.archive_root(paths.CHILD_RESULTS_ROOT, "model9.9")
    assert "model9.9" in archived.parts
    assert paths.TEAM_ARCHIVE_ROOT in archived.parents
    assert paths.archive_root(paths.CHILD_RESULTS_ROOT) == paths.archive_root(
        paths.CHILD_RESULTS_ROOT, paths.MODEL_NUMBER
    )


def test_archive_root_rejects_an_unarchived_root() -> None:
    with pytest.raises(KeyError, match="is not archived"):
        paths.archive_root(paths.REPO_ROOT / "not_a_pipeline_output")


def test_run_lookup_works_against_the_archive(tmp_path: Path) -> None:
    """The notebooks call ``latest_run`` on an archived root, not an in-repo one.

    That works because the archive keeps the layout below the root and the script
    copies the marker across; this pins both halves of that arrangement.
    """
    archived = tmp_path / paths.archive_root(paths.CHILD_RESULTS_ROOT).relative_to("/")
    run = archived / "bouillon" / "nigeria" / "2026_08_28_20_20_09"
    (run / "results").mkdir(parents=True)
    (run.parent / paths.RUN_MARKER_NAME).write_text(f"{run.name}\n")

    assert paths.latest_run(archived, "Nigeria", "bouillon") == run
    assert paths.latest_results(archived, "Nigeria", "bouillon") == run / "results"


def test_artifact_path_normalizes_the_location() -> None:
    """Locations reach these helpers as wildcards and as display names alike."""
    root = paths.archive_root(paths.CHILD_ARTIFACT_ROOT)
    assert paths.artifact_path(root, "Nigeria", "bouillon") == root / "bouillon/nigeria.hdf"
    assert paths.artifact_path(root, "South Africa", "rice").name == "south_africa.hdf"
    # The PAF artifacts are not keyed by vehicle.
    paf_root = paths.archive_root(paths.LBWSG_PAF_ARTIFACT_ROOT)
    assert paths.artifact_path(paf_root, "nigeria") == paf_root / "nigeria.hdf"


MATERNAL_PKG = REPO_ROOT / "0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal"
CHILD_PKG = REPO_ROOT / "0300_child_sim/src/vivarium_gates_lsff_2026_child"

SPECS = [
    MATERNAL_PKG / "model_specifications/model_spec.yaml",
    CHILD_PKG / "model_specifications/model_spec.yaml",
    CHILD_PKG / "data/lbwsg_paf.yaml",
]


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: str(p.parent.name))
def test_specs_do_not_hardcode_an_artifact(spec_path: Path) -> None:
    """The artifact comes from -i, never from the specification.

    Any value written here is an absolute path into one working tree: wrong for
    every other clone, and silently stale once the layout moves -- which produces
    a successful-looking run against the wrong inputs rather than an error. The
    Snakemake rules always pass -i, and a run's own model_specification.yaml
    records what it actually used.
    """
    import yaml

    assert spec_path.exists(), f"specification has moved: {spec_path.relative_to(REPO_ROOT)}"
    with spec_path.open() as f:
        spec = yaml.safe_load(f)

    assert "artifact_path" not in spec["configuration"]["input_data"], (
        f"{spec_path.relative_to(REPO_ROOT)} hardcodes an artifact_path. Pass the "
        f"artifact with -i instead."
    )
