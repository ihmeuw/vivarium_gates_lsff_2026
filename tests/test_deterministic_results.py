"""Layer 1: deterministic stages must reproduce the baseline exactly.

Everything outside the microsimulations is deterministic given the same inputs:
the DHS/HCES extraction, the coverage calculations, the folate/NTD model, and
Ethiopia's analysis stage. On 2026-07-30 all 150 of these regenerated
byte-identically to the April-2025 committed baseline, so we can demand exact
equality rather than a tolerance. Any difference at all is a real signal.

These tests compare what is in the working tree against what is committed, so
they are only meaningful after a pipeline run. Files the pipeline has not
produced are skipped, and ``test_something_was_compared`` fails if that leaves
nothing to check -- otherwise a green run could mean "verified" or "tested
nothing at all", which are very different things.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.baseline import (
    align,
    canonical,
    deterministic_result_csvs,
    is_long_format,
    read_baseline,
    read_current,
)


@pytest.mark.parametrize("path", deterministic_result_csvs())
def test_deterministic_result_matches_baseline(path: str) -> None:
    baseline = read_baseline(path)
    if baseline is None:
        pytest.skip(f"no baseline for {path} at this ref")
    current = read_current(path)
    if current is None:
        pytest.skip(f"{path} not present -- pipeline stage has not been run")

    assert list(current.columns) == list(baseline.columns), (
        f"{path}: column layout changed\n"
        f"  baseline: {list(baseline.columns)}\n"
        f"  current:  {list(current.columns)}"
    )

    if canonical(baseline).equals(canonical(current)):
        return

    # Something moved. Long-format frames can say exactly which rows and by how
    # much; wide frames (wealth_quintile_probabilities) only get a summary.
    if not is_long_format(baseline):
        pytest.fail(
            f"{path}: values changed in a stage that should be deterministic "
            f"(wide-format file, {len(baseline)} rows; inspect with "
            f"`git diff -- {path}`)"
        )

    merged = align(baseline, current)

    only_baseline = merged.index[merged["_merge"] == "left_only"].tolist()
    only_current = merged.index[merged["_merge"] == "right_only"].tolist()
    assert not only_baseline and not only_current, (
        f"{path}: the set of rows changed\n"
        f"  dropped ({len(only_baseline)}): {only_baseline[:5]}\n"
        f"  added   ({len(only_current)}): {only_current[:5]}"
    )

    both = merged[merged["_merge"] == "both"]
    differing = both[both["value_baseline"] != both["value_current"]]
    worst = (
        (differing["value_current"] - differing["value_baseline"])
        .abs()
        .sort_values(ascending=False)
        .head(5)
        .index
    )
    detail = "\n".join(
        f"    {key}: baseline={differing.loc[key, 'value_baseline']!r} "
        f"current={differing.loc[key, 'value_current']!r}"
        for key in worst
    )
    pytest.fail(
        f"{path}: {len(differing)} of {len(both)} values changed in a stage that "
        f"should be deterministic.\n  largest differences:\n{detail}"
    )


def test_something_was_compared() -> None:
    """Guard against a vacuously green run."""
    compared = [
        path
        for path in deterministic_result_csvs()
        if read_current(path) is not None and read_baseline(path) is not None
    ]
    assert compared, (
        "No deterministic outputs were available to compare. Run the pipeline "
        "first (`snakemake --cores 4`), or this suite proves nothing."
    )


def test_stochastic_classification_is_complete() -> None:
    """Every tracked result CSV is classified exactly once.

    Prevents a renamed or newly added output from quietly falling outside both
    the exact and the fuzzy checks.
    """
    from tests.baseline import (
        STOCHASTIC_RESULTS,
        stochastic_result_csvs,
        tracked_result_csvs,
    )

    tracked = set(tracked_result_csvs())
    classified = set(deterministic_result_csvs()) | set(stochastic_result_csvs())
    assert tracked == classified, f"unclassified: {sorted(tracked - classified)}"

    unknown = STOCHASTIC_RESULTS - tracked
    assert not unknown, (
        "STOCHASTIC_RESULTS names files git does not track (typo, or the file was "
        f"renamed): {sorted(unknown)}"
    )
