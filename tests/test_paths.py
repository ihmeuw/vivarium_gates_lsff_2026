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

import subprocess
from pathlib import Path

import pytest

from lsff_utils import paths

REPO_ROOT = Path(__file__).resolve().parent.parent

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
    assert paths.REPO_ROOT == REPO_ROOT, (
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
