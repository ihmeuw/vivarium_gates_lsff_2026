"""Helpers for comparing pipeline outputs against a committed baseline.

The committed result CSVs *are* the reference: they were produced by the
April-2025 production run and verified to regenerate byte-identically on
2026-07-30 (see the "Reproduction status" section of CLAUDE.md). These helpers
read the reference out of git so there is no second copy to keep in sync.

Set ``LSFF_BASELINE_REF`` to compare against something other than ``HEAD`` --
during a migration, point it at the pre-migration tag or commit.
"""

from __future__ import annotations

import io
import os
import subprocess
from functools import cache
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

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
