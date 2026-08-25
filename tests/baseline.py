"""Helpers for comparing pipeline outputs against a committed baseline.

The committed result CSVs *are* the reference: they were produced by the
April-2025 production run and verified to regenerate byte-identically on
2026-07-30 (see the "Reproduction status" section of CLAUDE.md). These helpers
read the reference out of git so there is no second copy to keep in sync.

Set ``LSFF_BASELINE_REF`` to compare against something other than ``HEAD`` --
during a migration, point it at the pre-migration tag or commit.

Freshness
---------
Layer 1 compares the working tree against git, and the result CSVs are *committed*.
So on a clean checkout every file is present and every comparison passes by
comparing a file against itself -- which is indistinguishable, from the exit code,
from a real verification. ``freshness`` answers "did the pipeline actually produce
this file here?" by reading Snakemake's own job records in ``.snakemake/metadata``,
whose filenames are the urlsafe-base64 of the output path. A file whose mtime is
meaningfully later than the ``endtime`` Snakemake recorded has been rewritten since
the run -- in practice by the ``git checkout`` that restores the baseline after a
migration run -- so it is no longer that run's output.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

SNAKEMAKE_METADATA = REPO_ROOT / ".snakemake" / "metadata"

# Snakemake records endtime after writing the output, so a fresh file's mtime is at
# or just before it. 60s absorbs clock skew on the shared filesystem without coming
# near the hours-long gap a git restore leaves.
FRESHNESS_TOLERANCE_SECONDS = 60.0

FRESH = "fresh"
RESTORED = "restored"
NEVER_BUILT = "never_built"
MISSING = "missing"

# Outputs whose values depend on the microsimulations and therefore vary with the
# random seed. Measured on 2026-07-30: these are exactly the 15 tracked result
# CSVs that differed after a full rerun, while the other 150 were byte-identical.
# `ntd_cases_by_scenario.csv` is absent on purpose -- it is copied through from
# the deterministic NTD model. Ethiopia is absent because it is folate-only and
# runs no simulation.
#
# Anything NOT listed here is checked for exact equality. That default is
# deliberate: a new output file fails loudly until someone classifies it.
STOCHASTIC_RESULTS = frozenset(
    f"5000_analyze_results/results/{location}/{vehicle}/{measure}_by_scenario.csv"
    for location, vehicle in (("india", "rice"), ("nigeria", "rice"), ("nigeria", "bouillon"))
    for measure in (
        "dalys",
        "maternal_disorders_incident_cases",
        "neonatal_deaths",
        "pregnant_anemia_prevalence",
        "prevalent_anemia_cases",
    )
)


def baseline_ref() -> str:
    return os.environ.get("LSFF_BASELINE_REF", "HEAD")


@cache
def tracked_result_csvs() -> tuple[str, ...]:
    """Every result CSV git knows about, repo-relative and sorted."""
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "*/results/*.csv"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return tuple(sorted(out))


def deterministic_result_csvs() -> tuple[str, ...]:
    return tuple(p for p in tracked_result_csvs() if p not in STOCHASTIC_RESULTS)


def stochastic_result_csvs() -> tuple[str, ...]:
    """Tracked CSVs classified as stochastic. Intersected with what git actually
    tracks so a typo in STOCHASTIC_RESULTS cannot silently drop a file."""
    return tuple(p for p in tracked_result_csvs() if p in STOCHASTIC_RESULTS)


def snakemake_record(path: str) -> dict | None:
    """Snakemake's job record for ``path``, or None if it never built it here.

    ``.snakemake/metadata`` keys entries by the urlsafe-base64 of the repo-relative
    output path.
    """
    encoded = base64.urlsafe_b64encode(path.encode()).decode()
    record = SNAKEMAKE_METADATA / encoded
    if not record.is_file():
        return None
    try:
        return json.loads(record.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, binascii.Error):
        return None


def freshness(path: str) -> str:
    """Whether the working-tree copy of ``path`` is this workspace's pipeline output.

    Returns one of ``FRESH`` (Snakemake built it and nothing has rewritten it since),
    ``RESTORED`` (built, but the file on disk is newer than the run -- a git checkout,
    a manual edit), ``NEVER_BUILT`` (no Snakemake record) or ``MISSING``.

    Only ``FRESH`` makes a layer-1 comparison meaningful. The others all compare a
    committed file against itself.
    """
    full = REPO_ROOT / path
    if not full.exists():
        return MISSING

    record = snakemake_record(path)
    if record is None:
        return NEVER_BUILT
    if record.get("incomplete"):
        return RESTORED

    endtime = record.get("endtime")
    if endtime is None:
        return NEVER_BUILT
    if full.stat().st_mtime > float(endtime) + FRESHNESS_TOLERANCE_SECONDS:
        return RESTORED
    return FRESH


def freshness_summary(paths: tuple[str, ...]) -> dict[str, int]:
    counts = {FRESH: 0, RESTORED: 0, NEVER_BUILT: 0, MISSING: 0}
    for path in paths:
        counts[freshness(path)] += 1
    return counts


def read_baseline(path: str, ref: str | None = None) -> pd.DataFrame | None:
    """The committed version of ``path``, or None if it does not exist at ``ref``."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{ref or baseline_ref()}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return pd.read_csv(io.StringIO(result.stdout))


def read_current(path: str) -> pd.DataFrame | None:
    """The working-tree version of ``path``, or None if the pipeline has not
    produced it."""
    full = REPO_ROOT / path
    if not full.exists():
        return None
    return pd.read_csv(full)


def is_long_format(frame: pd.DataFrame) -> bool:
    """Most result CSVs are long format with a single ``value`` column, but the
    ``wealth_quintile_probabilities`` files are wide, with one column per
    quintile. Only long-format frames can be compared as proportions."""
    return "value" in frame.columns


def canonical(frame: pd.DataFrame) -> pd.DataFrame:
    """A row-order-independent form, so comparison tests multiset equality.

    Sorting by every column is safe as a canonical form: if two frames hold the
    same rows they sort identically, and if any value differs the sorted frames
    differ too.
    """
    return frame.sort_values(list(frame.columns)).reset_index(drop=True)


def key_columns(frame: pd.DataFrame) -> list[str]:
    """The index-like columns of a long-format result frame (everything but the
    measured value)."""
    return [c for c in frame.columns if c != "value"]


def align(baseline: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Join baseline and current on their key columns.

    Returns a frame indexed by the key columns with ``value_baseline`` and
    ``value_current`` columns, plus a ``_merge`` indicator so callers can detect
    rows present in only one side.
    """
    keys = key_columns(baseline)
    return baseline.merge(
        current,
        on=keys,
        how="outer",
        suffixes=("_baseline", "_current"),
        indicator=True,
    ).set_index(keys)
