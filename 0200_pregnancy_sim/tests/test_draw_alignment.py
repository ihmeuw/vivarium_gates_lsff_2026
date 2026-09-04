"""Guards against mixing draw conventions in the maternal loaders.

``get_data`` collapses draws to a single ``draw_0`` when ``mean_draw`` is set, while
``load_raw_incidence_data`` and the ``extra_gbd`` pulls always return every draw.
Combining the two aligns on column name, and a ``fillna(0)`` downstream turns the
resulting NaN into zeros -- which the collapse then averages in, scaling the key down by
the draw count instead of raising.
"""

import numpy as np
import pandas as pd
import pytest

DRAW_COUNT = 250
DRAW_COLUMNS = [f"draw_{i}" for i in range(DRAW_COUNT)]

INDEX = pd.MultiIndex.from_tuples(
    [("Female", 25.0, 30.0)], names=["sex", "age_start", "age_end"]
)


def _frame(value: float) -> pd.DataFrame:
    return pd.DataFrame(value, index=INDEX, columns=DRAW_COLUMNS, dtype=float)


def _collapse(data: pd.DataFrame) -> pd.Series:
    """What ``get_data`` does to a loader's return value when ``mean_draw`` is set."""
    return data.filter(like="draw_").mean(axis=1)


def test_mixing_conventions_scales_by_the_draw_count():
    """The failure mode, stated numerically so the guard below has something to catch."""
    numerator = _frame(0.010) - _frame(0.002)
    incidence = _frame(0.650)
    csmr = _frame(0.001)
    collapsed_csmr = csmr.mean(axis=1).rename("draw_0").to_frame()

    consistent = _collapse((numerator / (incidence - csmr)).fillna(0)).iloc[0]
    mixed = _collapse((numerator / (incidence - collapsed_csmr)).fillna(0)).iloc[0]

    assert consistent / mixed == pytest.approx(DRAW_COUNT)


def test_fillna_is_what_hides_the_mismatch():
    """Without the fillna the mismatch is 249 NaN, not a quiet rescaling."""
    incidence = _frame(0.650)
    collapsed_csmr = _frame(0.001).mean(axis=1).rename("draw_0").to_frame()
    difference = incidence - collapsed_csmr

    assert difference.notna().sum(axis=1).iloc[0] == 1
    assert len(difference.columns) == DRAW_COUNT


def test_assert_same_draw_columns_rejects_a_mismatch():
    loader = pytest.importorskip("vivarium_gates_lsff_2026_maternal.data.loader")

    full = _frame(1.0)
    collapsed = full.mean(axis=1).rename("draw_0").to_frame()

    loader._assert_same_draw_columns(a=full, b=full.copy())
    with pytest.raises(ValueError, match="different draw columns"):
        loader._assert_same_draw_columns(a=full, b=collapsed)


def test_childbearing_age_guard_rejects_a_zero_filled_row():
    loader = pytest.importorskip("vivarium_gates_lsff_2026_maternal.data.loader")

    index = pd.MultiIndex.from_tuples(
        [("Female", 10.0, 15.0), ("Female", 25.0, 30.0), ("Male", 25.0, 30.0)],
        names=["sex", "age_start", "age_end"],
    )
    data = pd.DataFrame(0.1, index=index, columns=["draw_0"])

    loader._assert_covers_childbearing_ages(data, "test key")

    data.loc[("Female", 10.0, 15.0), "draw_0"] = 0.0
    with pytest.raises(ValueError, match="childbearing-age rows"):
        loader._assert_covers_childbearing_ages(data, "test key")

    # Males and out-of-range ages may legitimately be zero-filled.
    data.loc[("Female", 10.0, 15.0), "draw_0"] = 0.1
    data.loc[("Male", 25.0, 30.0), "draw_0"] = 0.0
    loader._assert_covers_childbearing_ages(data, "test key")


def test_no_unexpected_nan_in_a_consistent_division():
    """Sanity check that the fix leaves no NaN behind for real rows."""
    numerator = _frame(0.010) - _frame(0.002)
    denominator = _frame(0.650) - _frame(0.001)
    assert not np.isnan(numerator / denominator).any().any()
