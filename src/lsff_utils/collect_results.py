"""Flatten a psimulate run's results into one parquet file per observer.

Why this exists
---------------
The old suite wrote each observer's results as a single file,
``<run>/results/<observer>.parquet``, and both simulation rules finished with
``mv ./*/results/*.parquet .`` to lift them next to the other stage outputs.

Modern vivarium-cluster-tools instead writes a *partitioned dataset* per
observer -- ``<run>/results/<observer>/<hash>.parquet``, one part per task, so 30
parts for 10 seeds x 3 scenarios. The old ``mv`` glob matches nothing against
that layout, which fails the rule under bash strict mode.

Everything downstream of the simulations -- the ``5000_analyze_results``
notebooks, the committed baseline CSVs, and the regression harness -- reads
``sim_results/<vehicle>/<location>/<observer>.parquet``. So the fix belongs here,
restoring that interface, rather than in every consumer.

Concatenating the parts reproduces the old file: verified against a GBD-2021
reference run, 30 parts concatenate to exactly the reference's 40,500 rows with
the same columns, since each part carries its own ``scenario`` / ``random_seed``
/ ``input_draw`` values. Column *order* differs (``input_draw`` and
``random_seed`` are swapped); consumers select by name, so this does not reorder
them to match.

Both layouts are handled, because the ``debug`` and ``local`` pipeline modes run
``simulate`` and ``local_psimulate.py`` respectively and still emit flat files.

The parts are left in place rather than deleted: the simulation rules already
``rm -rf`` the whole results directory before each run, so they do not
accumulate across runs. They do mean a full-scale run holds each observer twice
on disk, and that ``archive_last_run.sh`` will rsync both copies.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq


def find_results_directory(run_parent: Path) -> Path:
    """Locate the ``<timestamp>/results`` directory beneath ``run_parent``.

    ``psimulate restart`` reuses the original run directory rather than making a
    new one, so exactly one is expected. More than one means an earlier run was
    not cleaned up and the caller would otherwise silently collect the wrong one.
    """
    candidates = sorted(path for path in run_parent.glob("*/results") if path.is_dir())
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one '*/results' directory under {run_parent.resolve()}, "
            f"found {len(candidates)}: {[str(path) for path in candidates]}"
        )
    return candidates[0]


def concatenate_dataset(part_directory: Path, destination: Path) -> int:
    """Stream a partitioned observer directory into a single parquet file.

    Streamed batch by batch rather than concatenated in memory because a
    full-scale run partitions each observer across 600 parts (200 seeds x 3
    scenarios), and the birth line list is the whole simulated population.
    """
    dataset = ds.dataset(part_directory, format="parquet")
    rows = 0
    with pq.ParquetWriter(destination, dataset.schema) as writer:
        for batch in dataset.to_batches():
            writer.write_batch(batch)
            rows += batch.num_rows
    return rows


def collect(run_parent: Path, destination: Path) -> dict[str, int]:
    results = find_results_directory(run_parent)
    collected = {}
    for entry in sorted(results.iterdir()):
        if entry.is_dir():
            target = destination / f"{entry.name}.parquet"
            collected[entry.name] = concatenate_dataset(entry, target)
        elif entry.suffix == ".parquet":
            # The debug and local modes still write flat files.
            shutil.move(str(entry), destination / entry.name)
            collected[entry.stem] = -1
    if not collected:
        raise SystemExit(f"no observer results found in {results.resolve()}")
    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "run_parent",
        type=Path,
        help="directory containing the timestamped psimulate run directory",
    )
    parser.add_argument(
        "destination", type=Path, help="where to write <observer>.parquet files"
    )
    args = parser.parse_args()

    for name, rows in collect(args.run_parent, args.destination).items():
        print(f"collected {name}.parquet" + (f" ({rows:,} rows)" if rows >= 0 else ""))


if __name__ == "__main__":
    main()
