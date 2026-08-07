"""Guard the shared-drive path layout against drift.

The model specifications hardcode the artifact they run against, because YAML
cannot read :mod:`lsff_utils.paths`. That makes the ``artifact_path`` values a
second, independent statement of where the current iteration's artifacts live --
and a stale one points a simulation at a previous iteration's data, which
produces a successful-looking run against the wrong inputs rather than an error.

These tests fail when a specification and the constants disagree, so bumping
``MODEL_NUMBER`` without updating the specifications cannot pass silently.
"""

from pathlib import Path

import pytest
import yaml

from lsff_utils import paths

REPO_ROOT = Path(__file__).resolve().parent.parent
MATERNAL_PKG = REPO_ROOT / "0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal"
CHILD_PKG = REPO_ROOT / "0300_child_sim/src/vivarium_gates_lsff_2026_child"

# Each specification and the root its artifact is expected to sit in.
SPEC_ARTIFACT_ROOTS = {
    MATERNAL_PKG / "model_specifications/model_spec.yaml": paths.MATERNAL_ARTIFACT_ROOT,
    CHILD_PKG / "model_specifications/model_spec.yaml": paths.CHILD_ARTIFACT_ROOT,
    CHILD_PKG / "data/lbwsg_paf.yaml": paths.LBWSG_PAF_ARTIFACT_ROOT,
}


def _artifact_path(spec_path: Path) -> Path:
    with spec_path.open() as f:
        spec = yaml.safe_load(f)
    return Path(spec["configuration"]["input_data"]["artifact_path"])


@pytest.mark.parametrize(
    "spec_path, expected_root",
    SPEC_ARTIFACT_ROOTS.items(),
    ids=lambda p: p.name if isinstance(p, Path) and p.suffix == ".yaml" else None,
)
def test_spec_artifact_path_matches_constants(spec_path: Path, expected_root: Path) -> None:
    rel = spec_path.relative_to(REPO_ROOT)
    assert spec_path.exists(), f"specification has moved: {rel}"
    assert _artifact_path(spec_path).parent == expected_root, (
        f"{rel} points at a different artifact root than lsff_utils.paths expects. "
        f"If MODEL_NUMBER was just bumped, update the artifact_path in this file."
    )


def test_model_number_appears_in_every_root() -> None:
    """A root that does not carry MODEL_NUMBER will not move between iterations."""
    iteration_roots = {
        "MATERNAL_ARTIFACT_ROOT": paths.MATERNAL_ARTIFACT_ROOT,
        "CHILD_ARTIFACT_ROOT": paths.CHILD_ARTIFACT_ROOT,
        "MATERNAL_RESULTS_ROOT": paths.MATERNAL_RESULTS_ROOT,
        "CHILD_RESULTS_ROOT": paths.CHILD_RESULTS_ROOT,
        "LBWSG_PAF_ARTIFACT_ROOT": paths.LBWSG_PAF_ARTIFACT_ROOT,
        "LBWSG_PAF_RESULTS_ROOT": paths.LBWSG_PAF_RESULTS_ROOT,
    }
    for name, root in iteration_roots.items():
        assert paths.MODEL_NUMBER in root.parts, f"{name} is not iteration-specific"


def test_lbwsg_paf_inputs_and_child_artifact_are_distinct() -> None:
    """The PAF calculation's artifact holds a different key set from the child's."""
    assert paths.LBWSG_PAF_ARTIFACT_ROOT != paths.CHILD_ARTIFACT_ROOT
