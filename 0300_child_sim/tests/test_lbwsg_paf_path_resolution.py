"""Tests for the LBWSG PAF results path resolution.

The resolver has to handle two output layouts (flat ``simulate run`` outputs and
timestamped ``psimulate`` run directories). When both are present at once the flat
file is usually a stale leftover from the pre-run-directory layout, and silently
preferring it once served scramble-era PAFs into a rebuilt child artifact -- so
coexistence must be an error, never a silent choice.
"""
from pathlib import Path

import pandas as pd
import pytest

from vivarium_gates_lsff_2026_child.constants import paths
from vivarium_gates_lsff_2026_child.data import loader

MEASURE = paths.LBWSG_PAF_MEASURE_NAME


def _write_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"value": [0.5]}).to_parquet(path)


@pytest.fixture
def paf_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LBWSG_PAF_RESULTS_ROOT", tmp_path)
    return tmp_path


def test_resolves_newest_run_directory(paf_root):
    _write_parquet(paf_root / "kenya/2026_01_01_00_00_00/results" / MEASURE / "a.parquet")
    _write_parquet(paf_root / "kenya/2026_02_02_00_00_00/results" / MEASURE / "a.parquet")
    resolved = loader._resolve_lbwsg_paf_path("kenya")
    assert "2026_02_02_00_00_00" in str(resolved)


def test_resolves_flat_file_when_alone(paf_root):
    flat = paf_root / "kenya" / f"{MEASURE}.parquet"
    _write_parquet(flat)
    assert loader._resolve_lbwsg_paf_path("kenya") == flat


def test_raises_when_flat_and_run_outputs_coexist(paf_root):
    _write_parquet(paf_root / "kenya" / f"{MEASURE}.parquet")
    _write_parquet(paf_root / "kenya/2026_02_02_00_00_00/results" / MEASURE / "a.parquet")
    with pytest.raises(RuntimeError, match="Ambiguous LBWSG PAF results"):
        loader._resolve_lbwsg_paf_path("kenya")
