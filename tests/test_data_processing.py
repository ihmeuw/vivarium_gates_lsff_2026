"""Unit tests for ``lsff_utils.data_processing``.

Two small functions with outsized reach. Both fail silently.

``recode_*_wealth_quintile`` is a ``Series.map`` over a hardcoded label dictionary.
An unrecognised label does not raise -- it becomes NaN. Since wealth quintile is
the stratification the entire study exists to report, and since the DHS refresh in
``TODO.md`` will re-read surveys whose category labels are not guaranteed stable,
"the labels changed" is a realistic future failure that would surface as missing
quintiles rather than an error.

``reindex_series_onto_df_by_age_groups`` joins a DHS-binned disparity series onto
GBD-binned data with an inner merge followed by a nesting filter. Its own comment
says it "depends on a GBD age group always fitting into a disparity age group",
and when that does not hold the rows are dropped with no warning. Verified below:
two rows in, one row out, no error.

That precondition is guarded by ``tests/test_gbd_assumptions.py::
test_gbd_age_bins_nest_inside_disparity_age_bins``, which watches GBD for a
straddling bin. The tests here cover the other half -- what this function does
*given* such a bin -- so the pair documents the coupling from both ends. Layer 3
tests the assumption; this tests the consequence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lsff_utils.data_processing import (
    DHS_MAPPING,
    EXTRACTION_MAPPING,
    WEALTH_QUINTILES,
    recode_dhs_wealth_quintile,
    recode_extraction_wealth_quintile,
    reindex_series_onto_df_by_age_groups,
)

# The DHS disparity bins the study uses, as asserted in test_gbd_assumptions.py.
DISPARITY_EDGES = [0, 5, 15, 30, 50, 125]


def disparity_series(name: str = "disparity") -> pd.Series:
    """One value per (sex, disparity age bin), like the DHS-derived disparities."""
    bins = list(zip(DISPARITY_EDGES[:-1], DISPARITY_EDGES[1:]))
    index = pd.MultiIndex.from_tuples(
        [
            (sex, float(start), float(end))
            for sex in ("Female", "Male")
            for start, end in bins
        ],
        names=["sex", "age_start", "age_end"],
    )
    return pd.Series(np.arange(len(index), dtype=float), index=index, name=name)


def gbd_frame(bins: list[tuple[float, float]], sexes=("Female", "Male")) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(sex, start, end) for sex in sexes for start, end in bins],
        names=["sex", "age_start", "age_end"],
    )
    return pd.DataFrame({"value": np.arange(len(index), dtype=float)}, index=index)


@pytest.mark.parametrize(
    "recode,mapping",
    [
        (recode_dhs_wealth_quintile, DHS_MAPPING),
        (recode_extraction_wealth_quintile, EXTRACTION_MAPPING),
    ],
    ids=["dhs", "extraction"],
)
def test_recode_maps_every_known_label(recode, mapping) -> None:
    """Every label the mapping declares must survive the recode, in order."""
    labels = list(mapping)

    recoded = recode(pd.Series(labels))

    assert recoded.tolist() == [mapping[label] for label in labels]
    assert recoded.notna().all(), (
        f"recoding the mapping's own keys produced NaN: "
        f"{[label for label, value in zip(labels, recoded) if pd.isna(value)]}"
    )


def test_dhs_mapping_covers_the_five_quintiles() -> None:
    """The numeric codes must be exactly 1-5, since downstream stratification and
    the ``wealth_quintile`` artifact keys assume that domain."""
    assert sorted(DHS_MAPPING.values()) == sorted(WEALTH_QUINTILES)
    assert len(DHS_MAPPING) == len(WEALTH_QUINTILES), "a DHS label maps to a duplicate code"


def test_extraction_mapping_preserves_its_aggregate_labels() -> None:
    """``Total`` and ``All (assumed same)`` are passed through unchanged on purpose
    -- the extraction sheet uses them for rows that are not quintile-specific, and
    ``prep_extracted.ipynb`` filters on them by name after recoding."""
    passthrough = {"All (assumed same)", "Total"}

    assert passthrough <= set(EXTRACTION_MAPPING.values())
    numeric = set(EXTRACTION_MAPPING.values()) - passthrough
    assert sorted(numeric) == sorted(WEALTH_QUINTILES)


@pytest.mark.parametrize(
    "recode",
    [recode_dhs_wealth_quintile, recode_extraction_wealth_quintile],
    ids=["dhs", "extraction"],
)
def test_unrecognised_wealth_label_becomes_nan_rather_than_raising(recode) -> None:
    """Characterises a silent failure, so it is a decision rather than a surprise.

    ``Series.map`` returns NaN for anything not in the dictionary. A DHS round that
    renames its wealth categories -- or a locale that capitalises them differently
    -- therefore yields all-NaN quintiles instead of an error, and the quintile
    breakdown that is the entire point of the study goes missing quietly.

    Relevant now rather than hypothetically: ``TODO.md``'s refresh plan moves India
    to DHS 2023_2024, Nigeria to 2023_2024 and Ethiopia to 2024_2025, and says to
    redo the wealth quintiles first because every other disparity is re-based on
    them.
    """
    recoded = recode(pd.Series(["poorest", "Poorest", "second poorest", None]))

    assert recoded.isna().sum() >= 2, (
        "expected unrecognised labels to become NaN; if map() now raises or fills, "
        "this test should be inverted and the callers checked for the new behaviour"
    )
    assert recoded.isna().any(), (
        "unrecognised wealth labels no longer produce NaN -- if the recode now "
        "validates its input, that is an improvement, but update this test and drop "
        "the warning in the module docstring"
    )


def test_reindex_assigns_each_gbd_bin_its_containing_disparity_value() -> None:
    """The intended behaviour: a nested GBD bin inherits its disparity bin's value."""
    series = disparity_series()
    # Bins chosen to sit strictly inside 0-5, 15-30 and 50-125 respectively.
    frame = gbd_frame([(1.0, 2.0), (20.0, 25.0), (60.0, 65.0)])

    result = reindex_series_onto_df_by_age_groups(frame, series)

    assert len(result) == len(frame), "a nested bin was dropped"
    assert result.name == series.name, f"series name lost: {result.name!r}"
    assert result.notna().all(), "nested bins produced NaN"

    lookup = series.reset_index()
    for (age_end, age_start, sex), value in result.items():
        containing = lookup[
            (lookup["sex"] == sex)
            & (lookup["age_start"] <= age_start)
            & (lookup["age_end"] >= age_end)
        ]
        assert (
            len(containing) == 1
        ), f"{sex} {age_start}-{age_end} has no unique disparity bin"
        assert value == containing["disparity"].iloc[0], (
            f"{sex} {age_start}-{age_end} got {value}, expected "
            f"{containing['disparity'].iloc[0]} from disparity bin "
            f"{containing['age_start'].iloc[0]}-{containing['age_end'].iloc[0]}"
        )


def test_reindex_returns_the_union_of_both_index_level_sets() -> None:
    """The result is indexed by the union of the frame's and the series' level
    names, sorted -- note the sort, which reorders levels alphabetically rather
    than preserving the input order."""
    series = disparity_series()
    frame = gbd_frame([(20.0, 25.0)])

    result = reindex_series_onto_df_by_age_groups(frame, series)

    assert list(result.index.names) == sorted({"sex", "age_start", "age_end"})


def test_reindex_silently_drops_a_gbd_bin_that_straddles_a_disparity_boundary() -> None:
    """The documented hazard, pinned.

    ``(10, 20)`` crosses the disparity edge at 15, so it satisfies neither
    ``age_start >= age_start_series`` nor ``age_end <= age_end_series`` for a single
    disparity bin, and the inner merge plus nesting filter discards it. No
    exception, no warning, and the caller gets a shorter series than it passed in.

    This is what ``test_gbd_assumptions.py::
    test_gbd_age_bins_nest_inside_disparity_age_bins`` exists to prevent, by
    watching GBD's bins for exactly this shape. If that test ever fails, this is
    what the failure would have cost.
    """
    series = disparity_series()
    frame = gbd_frame([(10.0, 20.0), (20.0, 25.0)], sexes=("Female",))

    result = reindex_series_onto_df_by_age_groups(frame, series)

    assert len(result) < len(frame), (
        "a straddling age bin now survives the reindex -- if the function learned to "
        "split or apportion it, that is a real improvement; update this test and the "
        "note in data_processing.py"
    )
    assert (20.0, 25.0) not in [(start, end) for end, start, _ in result.index] or len(
        result
    ) == 1, "expected only the nested bin to survive"


def test_reindex_broadcasts_a_series_that_has_no_age_levels() -> None:
    """The ``align`` branch, which had a real bug: taking ``align(df)[1]`` instead of
    ``[0]`` returned the *frame's* own values and dropped the series entirely.

    Values are asserted explicitly here rather than just checking for non-NaN,
    because that bug produced a perfectly well-formed result of the right shape --
    it was only wrong.
    """
    series = pd.Series(
        [9.0, 8.0], index=pd.Index(["Female", "Male"], name="sex"), name="no_age_levels"
    )
    frame = gbd_frame([(5.0, 10.0), (20.0, 25.0)])

    result = reindex_series_onto_df_by_age_groups(frame, series)

    assert result.name == series.name, (
        f"expected the series' name {series.name!r} to survive the broadcast, got "
        f"{result.name!r}. A name taken from the frame's own column is the first sign "
        "that align() returned the wrong element of its (left, right) pair."
    )
    assert set(np.unique(result.dropna().values)) == {9.0, 8.0}, (
        f"expected the series' values broadcast over the frame's index, got "
        f"{sorted(set(result.dropna().values))}. Values matching the frame's own "
        "column mean align() is returning the wrong element of its (left, right) pair."
    )
    for key, value in result.items():
        sex = key[0] if isinstance(key, tuple) else key
        assert value == series[sex], f"{key} got {value}, expected {series[sex]}"
