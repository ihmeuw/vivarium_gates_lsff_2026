"""Unit tests for the psimulate results collector.

`lsff_utils.collect_results` restores the interface every downstream stage
depends on -- one `<observer>.parquet` per observer, next to the other stage
outputs -- from whichever layout the simulation actually wrote.

It exists because modern vivarium-cluster-tools changed that layout: the old
suite wrote `<run>/results/<observer>.parquet`, and the modern one writes a
partitioned dataset, `<run>/results/<observer>/<hash>.parquet`, one part per
task. The Snakefiles' old `mv ./*/results/*.parquet .` silently matched nothing
against the new layout, failing the rule with a bare `mv: cannot stat` after a
*successful* simulation -- and Snakemake then deleted the good results.

So these tests pin both layouts, and pin that an unrecognized shape fails loudly
rather than producing a partial collection. There is no cluster or GBD
dependency, so they run in any environment.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lsff_utils.collect_results import collect, find_results_directory


def write_parquet(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"value": values}).to_parquet(path)


def test_partitioned_observer_is_concatenated(tmp_path):
    """The modern layout: one part per task, concatenated into one file."""
    results = tmp_path / "2026_08_04_08_40_21" / "results"
    write_parquet(results / "births" / "aaaa.parquet", [1, 2])
    write_parquet(results / "births" / "bbbb.parquet", [3])
    destination = tmp_path / "flat"
    destination.mkdir()

    assert collect(tmp_path, destination) == {"births": 3}
    collected = pd.read_parquet(destination / "births.parquet")
    assert sorted(collected["value"]) == [1, 2, 3]


def test_flat_observer_is_moved(tmp_path):
    """The debug and local modes still write a single file per observer."""
    results = tmp_path / "2026_08_04_08_40_21" / "results"
    write_parquet(results / "births.parquet", [1, 2, 3])
    destination = tmp_path / "flat"
    destination.mkdir()

    collect(tmp_path, destination)
    assert sorted(pd.read_parquet(destination / "births.parquet")["value"]) == [1, 2, 3]


def test_ambiguous_run_directory_fails(tmp_path):
    """`psimulate restart` reuses the run directory, so two means stale output."""
    for stamp in ("2026_08_04_08_40_21", "2026_08_04_09_10_00"):
        write_parquet(tmp_path / stamp / "results" / "births" / "aaaa.parquet", [1])

    with pytest.raises(SystemExit, match="expected exactly one"):
        find_results_directory(tmp_path)


def test_missing_run_directory_fails(tmp_path):
    with pytest.raises(SystemExit, match="expected exactly one"):
        find_results_directory(tmp_path)


def test_empty_results_directory_fails(tmp_path):
    """A run that produced no observers must not look like a successful collection."""
    (tmp_path / "2026_08_04_08_40_21" / "results").mkdir(parents=True)
    destination = tmp_path / "flat"
    destination.mkdir()

    with pytest.raises(SystemExit, match="no observer results"):
        collect(tmp_path, destination)
