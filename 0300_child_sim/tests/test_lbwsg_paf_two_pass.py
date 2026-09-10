"""Guards the plumbing between the two LBWSG PAF passes.

The late neonatal PAF is only right if pass 2's mortality is deflated by pass 1's
early neonatal PAF, and that value travels via a parquet file and a generated model
spec. These tests pin the file's frame to what the risk effect validates against,
and the spec generation to a faithful copy-plus-path.
"""

import pandas as pd
import pytest
import yaml

from vivarium_gates_lsff_2026_child.data.run_lbwsg_paf_two_pass import (
    CALIBRATION_COLUMNS,
    build_calibration_frame,
    write_pass2_spec,
)

SPEC_PATH = "src/vivarium_gates_lsff_2026_child/data/lbwsg_paf.yaml"


@pytest.fixture
def pass1_paf() -> pd.Series:
    index = pd.MultiIndex.from_product(
        [["early_neonatal", "late_neonatal"], ["Female", "Male"]],
        names=["age_group", "sex"],
    )
    return pd.Series([0.86, 0.85, 0.62, 0.56], index=index, name="value")


def test_calibration_frame_carries_the_early_neonatal_paf_per_sex(pass1_paf):
    frame = build_calibration_frame(pass1_paf)
    assert list(frame.columns) == CALIBRATION_COLUMNS
    assert frame.set_index("sex")["value"].to_dict() == {"Female": 0.86, "Male": 0.85}
    # Applied at every age: only early neonatal mortality precedes an observation,
    # so a single value per sex is sufficient -- but it must span the sim's ages.
    assert (frame["age_start"] == 0.0).all() and (frame["age_end"] >= 0.02).all()


def test_calibration_frame_rejects_degenerate_pafs(pass1_paf):
    with pytest.raises(ValueError, match="Implausible"):
        build_calibration_frame(pass1_paf * 0.0)


def test_calibration_columns_match_the_risk_effects_contract():
    """The runner writes what LBWSGPAFCalculationRiskEffect validates against."""
    import inspect

    from vivarium_gates_lsff_2026_child.components.lbwsg import (
        LBWSGPAFCalculationRiskEffect,
    )

    source = inspect.getsource(LBWSGPAFCalculationRiskEffect.get_calibration_constant_data)
    for column in CALIBRATION_COLUMNS:
        assert f'"{column}"' in source


def test_pass2_spec_is_the_spec_plus_the_calibration_path(tmp_path):
    spec = tmp_path / "lbwsg_paf.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "components": {"pkg": ["Population()"]},
                "configuration": {
                    "time": {"step_size": 7},
                    "lbwsg_paf_calibration": {"enn_paf_path": ""},
                },
            }
        )
    )
    calibration = tmp_path / "enn_paf.parquet"
    out = tmp_path / "pass2.yaml"
    write_pass2_spec(spec, calibration, out)

    generated = yaml.safe_load(out.read_text())
    assert generated["configuration"]["lbwsg_paf_calibration"]["enn_paf_path"] == str(
        calibration.resolve()
    )
    # Everything else survives untouched.
    generated["configuration"]["lbwsg_paf_calibration"]["enn_paf_path"] = ""
    assert generated == yaml.safe_load(spec.read_text())


def test_paf_output_search_is_scoped_to_the_location(tmp_path):
    """Concurrent per-location workflows share these roots; the newest file across
    the whole root can belong to the other location's run."""
    import os
    import time

    from vivarium_gates_lsff_2026_child.constants import paths as child_paths
    from vivarium_gates_lsff_2026_child.data.run_lbwsg_paf_two_pass import find_paf_output

    def write(rel: str, mtime: float):
        p = tmp_path / rel / (child_paths.LBWSG_PAF_MEASURE_NAME + ".parquet")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        os.utime(p, (mtime, mtime))
        return p

    now = time.time()
    ours = write("nigeria/run_1/results", now - 60)
    write("india/run_2/results", now)  # newer, but the other location's

    assert find_paf_output(tmp_path, "nigeria") == ours
