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

That guard is necessary but not sufficient, and for a long time it was the only
one. The result CSVs are *committed*, so on a clean checkout every file is present
and every comparison passes by comparing a file against itself --
``test_something_was_compared`` cannot fail, because both sides always exist. The
freshness tests at the bottom close that hole using Snakemake's own job records;
see ``tests/baseline.py``. As of 2026-08-05 this working tree is 116 fresh / 41
restored / 8 never built, i.e. layer 1 is currently meaningful for 116 of 165
files and vacuous for the rest.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from tests.baseline import (
    FRESH,
    NEVER_BUILT,
    RESTORED,
    align,
    canonical,
    deterministic_result_csvs,
    freshness,
    freshness_summary,
    is_long_format,
    read_baseline,
    read_current,
    tracked_result_csvs,
)

# Tracked result CSVs that no Snakemake rule produced in this workspace. These are
# the stale scenario-nested 0500 layout that ``model.ipynb`` no longer writes -- the
# directory is still in the tree, and ``dalys_by_scenario.ipynb``'s NTD fallback
# branch still reads ``india/rice/intervention/ylls_by_scenario.csv`` from it, so it
# silently returns outdated numbers rather than failing. Recorded as a census so a
# *new* orphan is a deliberate decision rather than an accident.
KNOWN_ORPHANED_RESULTS = frozenset(
    {
        f"0500_neural_tube_defects_model/results/{combination}/{scenario}/{measure}_by_scenario.csv"
        for combination, scenario in (
            ("ethiopia/salt", "intervention_100_nrv"),
            ("ethiopia/salt", "intervention_25_nrv"),
            ("india/rice", "intervention"),
            ("nigeria/bouillon", "intervention"),
        )
        for measure in ("ntd_cases", "ylls")
    }
)

# Below this share of tracked outputs accounted for by a Snakemake record, assume no
# meaningful run happened in this workspace (a fresh clone has no .snakemake at all)
# and skip rather than report every file as an orphan.
MINIMUM_ACCOUNTED_SHARE = 0.5


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
    from tests.baseline import STOCHASTIC_RESULTS, stochastic_result_csvs, tracked_result_csvs

    tracked = set(tracked_result_csvs())
    classified = set(deterministic_result_csvs()) | set(stochastic_result_csvs())
    assert tracked == classified, f"unclassified: {sorted(tracked - classified)}"

    unknown = STOCHASTIC_RESULTS - tracked
    assert not unknown, (
        "STOCHASTIC_RESULTS names files git does not track (typo, or the file was "
        f"renamed): {sorted(unknown)}"
    )


def pipeline_has_run_here(paths: tuple[str, ...]) -> bool:
    """Whether Snakemake has built enough of the pipeline here to reason about."""
    counts = freshness_summary(paths)
    accounted = counts[FRESH] + counts[RESTORED]
    return bool(paths) and accounted >= MINIMUM_ACCOUNTED_SHARE * len(paths)


def test_deterministic_comparison_was_against_a_real_pipeline_run() -> None:
    """The check ``test_something_was_compared`` cannot make.

    Because the result CSVs are committed, "present in the working tree" is always
    true and proves nothing. This asks the sharper question -- did Snakemake produce
    this copy, and has anything rewritten it since? -- by reading
    ``.snakemake/metadata``.

    Skips rather than fails by default, because a green suite on a clean checkout is
    legitimate: there is simply nothing to verify yet. Set ``LSFF_EXPECT_FRESH=1``
    in a rerun or CI path to demand that layer 1 actually verified something, which
    is the case where silence would be dangerous.
    """
    paths = deterministic_result_csvs()
    counts = freshness_summary(paths)
    detail = (
        f"{counts[FRESH]} fresh, {counts[RESTORED]} restored, "
        f"{counts[NEVER_BUILT]} never built, of {len(paths)} deterministic outputs"
    )

    if counts[FRESH]:
        return

    message = (
        f"Layer 1 verified nothing: {detail}. Every comparison it made was a "
        "committed file against itself.\n"
        "  'restored' means Snakemake built the file but something rewrote it "
        "afterwards -- normally the `git checkout -- */results/` that restores the "
        "baseline after a migration run.\n"
        "  'never built' means no Snakemake record exists for it here.\n"
        "  Run the pipeline before trusting a green layer 1."
    )
    if os.environ.get("LSFF_EXPECT_FRESH"):
        pytest.fail(message)
    pytest.skip(message)


def test_no_new_orphaned_tracked_results() -> None:
    """Every tracked result CSV should be something a rule actually produces.

    An orphan is committed output that no rule writes any more. It does not fail
    loudly -- it just sits in the tree serving stale numbers to whatever still reads
    it, which is exactly what the 0500 NTD fallback branch does.
    """
    paths = tracked_result_csvs()
    if not pipeline_has_run_here(paths):
        pytest.skip(
            "no substantial Snakemake run recorded in this workspace, so every file "
            "would look orphaned"
        )

    orphaned = {path for path in paths if freshness(path) == NEVER_BUILT}

    new = orphaned - KNOWN_ORPHANED_RESULTS
    assert not new, (
        f"tracked result CSV(s) that no Snakemake rule produced here: {sorted(new)}.\n"
        "  Either a rule stopped writing an output that is still committed, or the "
        "run was partial. An orphaned CSV keeps serving its old contents to anything "
        "that reads it, with no error -- add it to KNOWN_ORPHANED_RESULTS only if "
        "that is intended."
    )

    fixed = KNOWN_ORPHANED_RESULTS - orphaned
    assert not fixed, (
        f"{sorted(fixed)} is no longer orphaned -- good, if the stale scenario-nested "
        "0500 layout was cleaned up or a rule now writes it. Remove it from "
        "KNOWN_ORPHANED_RESULTS."
    )
