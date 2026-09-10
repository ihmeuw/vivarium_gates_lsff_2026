"""Guards the category ordering in ``load_lbwsg_interpolated_rr``.

``griddata`` pairs the RR columns positionally with the gestational-age and
birth-weight midpoint Series. The midpoints come from ``gbd_mapping`` in numeric
category order; the RR columns come from a ``pd.Categorical`` sort. If the two
orderings disagree, every RR lands on the wrong cell and nothing raises.
"""

import numpy as np
import pandas as pd
import pytest

from vivarium_gates_lsff_2026_child.constants import metadata

gbd_mapping = pytest.importorskip("vivarium.gbd_mapping")

INDEX_COLUMNS = [
    "location",
    "sex",
    "age_start",
    "age_end",
    "year_start",
    "year_end",
]


@pytest.fixture
def categories() -> list[str]:
    lbwsg = gbd_mapping.risk_factors.low_birth_weight_and_short_gestation
    return list(lbwsg.categories.to_dict().keys())


def _build_rr_columns(categories: list[str], category_order: list[str] | None) -> list[str]:
    """Reproduce the column ordering the loader gives ``griddata``."""
    rr = pd.DataFrame(
        [
            {
                "location": "Nigeria",
                "sex": sex,
                "age_start": 0.0,
                "age_end": 0.01917808,
                "year_start": 2021,
                "year_end": 2022,
                "parameter": category,
                "draw_0": 1.0,
            }
            for sex in ("Female", "Male")
            for category in categories
        ]
    )
    rr["parameter"] = pd.Categorical(rr["parameter"], category_order)
    rr = (
        rr.sort_values("parameter")
        .set_index(INDEX_COLUMNS + ["parameter"])
        .stack()
        .unstack("parameter")
        .apply(np.log)
    )
    return list(rr.columns)


def test_draw_count_covers_every_lbwsg_category(categories):
    """``range(DRAW_COUNT)`` is the ordering key; it must span every category."""
    highest = max(int(category.removeprefix("cat")) for category in categories)
    assert highest < metadata.DRAW_COUNT


def test_rr_columns_match_category_metadata_order(categories):
    """The loader's ordering must agree with the midpoint Series' ordering."""
    ordering = [f"cat{i}" for i in range(metadata.DRAW_COUNT)]
    assert _build_rr_columns(categories, ordering) == categories


def test_unordered_categorical_would_scramble(categories):
    """The regression this guards: a bare ``pd.Categorical`` sorts lexicographically."""
    scrambled = _build_rr_columns(categories, None)
    assert scrambled != categories
    assert scrambled == sorted(categories)
