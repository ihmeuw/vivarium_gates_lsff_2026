"""Flatten a psimulate run's results into single per-metric parquet files.

Modern psimulate writes ``<run>/results/<metric>/<task_id>.parquet`` -- one file
per task, with ``input_draw``, ``random_seed``, and ``scenario`` injected as
columns -- where older versions wrote a single ``<run>/results/<metric>.parquet``.
The snakemake rules and analysis notebooks expect the flat layout, so this
concatenates each per-metric directory into ``<parent>/<metric>.parquet``
(and moves any already-flat files up unchanged, so both layouts are accepted).

Usage: python -m lsff_utils.flatten_results <parent>

where ``<parent>`` is the directory holding one or more ``<run>/results``
trees, e.g. ``0200_pregnancy_sim/sim_results/<vehicle>/<location>``.
"""

import sys
from pathlib import Path

import pandas as pd


def flatten_results(parent: Path) -> None:
    run_results = sorted(parent.glob("*/results"))
    if not run_results:
        raise FileNotFoundError(f"No '*/results' directories found under '{parent}'.")
    for results_dir in run_results:
        for item in sorted(results_dir.iterdir()):
            if item.is_dir():
                pd.read_parquet(item).to_parquet(parent / f"{item.name}.parquet")
            elif item.suffix == ".parquet":
                item.rename(parent / item.name)


if __name__ == "__main__":
    flatten_results(Path(sys.argv[1]))
