"""The archived specification has to keep pointing at a real artifact.

Once a run leaves the working tree that produced it, the ``artifact_path``
psimulate recorded names a file nobody else can reach -- and one that is gone as
soon as the repo is cleared for the next iteration. These tests pin the rewrite
that repoints it at the archive.
"""

from pathlib import Path

import pytest

from lsff_utils import archive_utils
from lsff_utils import paths as _paths

REPO = _paths.REPO_ROOT
TEAM = Path("/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026")
NUMBER = "model1.1"


@pytest.mark.parametrize(
    "recorded, expected",
    [
        (
            REPO / "0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf",
            TEAM / "artifacts" / NUMBER / "maternal/rice/nigeria.hdf",
        ),
        (
            REPO / "0300_child_sim/mean_draw_artifacts/bouillon/nigeria.hdf",
            TEAM / "artifacts" / NUMBER / "child/bouillon/nigeria.hdf",
        ),
        (
            REPO / "0300_child_sim/lbwsg_paf_mean_draw_artifacts/india.hdf",
            TEAM / "data" / NUMBER / "lbwsg_paf_artifacts/india.hdf",
        ),
    ],
)
def test_maps_in_repo_artifacts_into_the_archive(recorded: Path, expected: Path) -> None:
    assert archive_utils.archived_artifact_path(recorded, REPO, TEAM, NUMBER) == expected


def test_leaves_artifacts_outside_the_repo_alone() -> None:
    """A run made against a shared artifact already names a durable path."""
    outside = TEAM / "artifacts/legacy_1.0/maternal/rice/nigeria.hdf"
    assert archive_utils.archived_artifact_path(outside, REPO, TEAM, NUMBER) is None


def _spec(tmp_path: Path, artifact_path: str) -> Path:
    spec = tmp_path / "model_specification.yaml"
    spec.write_text(
        "components:\n"
        "    vivarium_public_health:\n"
        "        - Component()\n"
        "configuration:\n"
        "    input_data:\n"
        f"        artifact_path: {artifact_path}\n"
        "        input_draw_number: 0\n"
        "    time:\n"
        "        start:\n"
        "            year: 2022\n"
    )
    return spec


def test_rewrite_repoints_at_the_archive(tmp_path: Path) -> None:
    spec = _spec(
        tmp_path, str(REPO / "0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf")
    )
    result = archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER)

    assert result == TEAM / "artifacts" / NUMBER / "maternal/rice/nigeria.hdf"
    assert f"artifact_path: {result}" in spec.read_text()


def test_rewrite_records_what_actually_ran(tmp_path: Path) -> None:
    recorded = str(REPO / "0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf")
    spec = _spec(tmp_path, recorded)
    archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER)

    assert f"# archived: this run used {recorded}" in spec.read_text()


def test_rewrite_touches_nothing_else(tmp_path: Path) -> None:
    """Everything but the artifact_path line survives byte-for-byte."""
    spec = _spec(
        tmp_path, str(REPO / "0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf")
    )
    before = spec.read_text().splitlines()
    archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER)
    after = spec.read_text().splitlines()

    dropped = [l for l in before if "artifact_path" not in l]
    kept = [l for l in after if "artifact_path" not in l and not l.strip().startswith("#")]
    assert dropped == kept
    # and the file is still parseable
    import yaml

    assert (
        yaml.safe_load(spec.read_text())["configuration"]["input_data"]["input_draw_number"]
        == 0
    )


def test_rewrite_preserves_quoting_style(tmp_path: Path) -> None:
    """lbwsg_paf.yaml quotes its artifact path; the value must still be found."""
    recorded = str(REPO / "0300_child_sim/lbwsg_paf_mean_draw_artifacts/nigeria.hdf")
    spec = _spec(tmp_path, f"'{recorded}'")
    result = archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER)

    assert result == TEAM / "data" / NUMBER / "lbwsg_paf_artifacts/nigeria.hdf"


def test_rewrite_is_a_no_op_for_a_shared_artifact(tmp_path: Path) -> None:
    outside = str(TEAM / "artifacts/legacy_1.0/maternal/rice/nigeria.hdf")
    spec = _spec(tmp_path, outside)
    before = spec.read_text()

    assert archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER) is None
    assert spec.read_text() == before


def test_rewrite_is_a_no_op_without_an_artifact_path(tmp_path: Path) -> None:
    spec = tmp_path / "model_specification.yaml"
    spec.write_text("configuration:\n    input_data:\n        input_draw_number: 0\n")
    before = spec.read_text()

    assert archive_utils.rewrite_spec_artifact_path(spec, REPO, TEAM, NUMBER) is None
    assert spec.read_text() == before
