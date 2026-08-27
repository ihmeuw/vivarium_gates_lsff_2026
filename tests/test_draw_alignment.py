"""Guards the draw-collapse bug that silently divides an artifact key by 250.

The bug
-------
``loader.get_data`` collapses 250 draw columns to a single mean when
``mean_draw=True`` -- which the Snakefile always passes, via ``--mean``::

    data["mean_draw"] = data.filter(like="draw_").mean(axis=1)
    data = data.drop(columns=data.filter(like="draw_").columns)
    data = data.rename(columns={"mean_draw": "draw_0"})

So anything fetched through ``get_data`` comes back with one draw column, while
``extra_gbd.*`` and ``load_raw_incidence_data`` return all 250. A loader that
combines both gets a column-alignment mismatch:

``load_maternal_disorders_ylds`` does exactly that::

    csmr      = get_data(MATERNAL_DISORDERS.CSMR, location, mean_draw)  # 1 column
    incidence = load_raw_incidence_data(...)                            # 250 columns
    ylds = (all_md_ylds - anemia_ylds) / (incidence - csmr)
    return ylds.fillna(0)

``incidence - csmr`` aligns on column *names*, so only ``draw_0`` matches and the
other 249 become NaN. ``.fillna(0)`` then turns them into zeros rather than
letting them raise, and ``get_data``'s outer mean averages one real value against
249 zeros -- dividing the answer by exactly 250.

Measured: the loader returns 250 draw columns with exactly **one** non-zero draw
per row, and the stored value is 250.0x smaller than the same loader's own
un-collapsed output. This is pre-existing -- the pre-migration loader has an
identical structure -- so `cause.maternal_disorders.ylds` has been ~250x too small
in every artifact built with ``--mean``, including the one behind the April-2025
published results. Impact is bounded: YLDs are 0.03% of the maternal-disorders
DALY stream, so under 0.2% of total DALYs.

Two checks
----------
``test_mixing_loaders_are_accounted_for`` reads the loader source and needs
nothing else, so it runs in any environment. It records the one known offender,
so a *new* loader combining collapsed and uncollapsed draws fails immediately.

``test_draws_are_consistently_collapsed`` actually calls the loaders and looks for
the one-non-zero-draw signature. Needs GBD access and the maternal package, so it
is marked slow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.baseline import REPO_ROOT

# Loaders known to combine `get_data()` output (collapsed to one draw when
# mean_draw=True) with an uncollapsed 250-draw source. Each entry is a live bug,
# not an accepted fact: see the module docstring. Recorded rather than left to
# fail so the suite stays green while the defect is tracked -- remove an entry
# when it is fixed and the live check below will confirm.
# (load_maternal_disorders_ylds was the founding member; fixed 2026-08-27 by
# fetching csmr through load_maternal_csmr directly, so every term carries the
# full draw set and the collapse happens once, in the outer get_data.)
KNOWN_MIXING_LOADERS = frozenset()

# get_data collapses to this many columns when mean_draw=True.
COLLAPSED_DRAW_COUNT = 1


def maternal_loader_source() -> str:
    candidates = sorted(
        (REPO_ROOT / "0200_pregnancy_sim" / "src").glob("*/data/loader.py")
    )
    assert len(candidates) == 1, (
        f"expected exactly one maternal data/loader.py, found {candidates}. A package "
        "rename probably left the old directory behind."
    )
    return candidates[0].read_text()


def loaders_mixing_draw_conventions(source: str) -> set[str]:
    """Functions that call the module-local ``get_data()`` and also pull raw draws.

    ``vi_core.get_data`` and other dotted forms are excluded deliberately -- only
    the module's own ``get_data`` performs the mean-draw collapse.
    """
    mixing = set()
    for chunk in re.split(r"\n(?=def |@)", source):
        match = re.match(r"(?:@[\w.]+\s*\n)*def (\w+)", chunk)
        if not match:
            continue
        body = chunk[match.end() :]
        collapses = re.search(r"(?<![\w.])get_data\(", body)
        uncollapsed = re.search(r"extra_gbd\.\w+\(|load_raw_incidence_data\(", body)
        if collapses and uncollapsed:
            mixing.add(match.group(1))
    return mixing


def test_mixing_loaders_are_accounted_for() -> None:
    """No *new* loader may mix the two draw conventions."""
    found = loaders_mixing_draw_conventions(maternal_loader_source())

    new = found - KNOWN_MIXING_LOADERS
    assert not new, (
        f"new loader(s) combining collapsed and uncollapsed draw columns: {sorted(new)}.\n"
        "  With mean_draw=True, get_data() returns 1 draw column while extra_gbd.* and\n"
        "  load_raw_incidence_data() return 250. Arithmetic between them aligns on column\n"
        "  names, leaves 249 columns NaN, and a downstream .fillna(0) turns those into\n"
        "  zeros -- after which the outer mean divides the result by 250.\n"
        "  Fix by fetching every term through the same convention, or by dropping the\n"
        "  fillna so the mismatch raises instead of being silently absorbed."
    )

    fixed = KNOWN_MIXING_LOADERS - found
    assert not fixed, (
        f"{sorted(fixed)} no longer mixes draw conventions -- good. Remove it from "
        "KNOWN_MIXING_LOADERS."
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "loader_name",
    [
        pytest.param(
            name,
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "known bug: mixes collapsed and uncollapsed draw columns, so the "
                    "result is divided by the draw count. xfail(strict) rather than a "
                    "hard failure so the suite stays green while it is tracked -- it "
                    "will fail loudly once fixed, prompting removal from "
                    "KNOWN_MIXING_LOADERS."
                ),
            ),
        )
        for name in sorted(KNOWN_MIXING_LOADERS)
    ],
)
def test_draws_are_consistently_collapsed(loader_name: str) -> None:
    """The live signature of the bug: exactly one non-zero draw out of 250.

    Here so a fix can be verified against real GBD data rather than by reading the
    source.
    """
    pytest.importorskip(
        "vivarium.artifact", reason="needs an environment with the modern suite"
    )
    import sys

    src = REPO_ROOT / "0200_pregnancy_sim" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    loader = pytest.importorskip(
        "vivarium_gates_lsff_2026_maternal.data.loader",
        reason="needs the maternal package importable",
    )
    keys = pytest.importorskip("vivarium_gates_lsff_2026_maternal.constants.data_keys")

    key = keys.MATERNAL_DISORDERS.YLDS
    frame = getattr(loader, loader_name)(key, "Nigeria", True)
    draw_columns = [column for column in frame.columns if column.startswith("draw_")]
    if len(draw_columns) <= COLLAPSED_DRAW_COUNT:
        pytest.skip(f"{loader_name} already returns collapsed draws")

    non_zero_per_row = (frame[draw_columns] != 0).sum(axis=1)
    degenerate = non_zero_per_row[(non_zero_per_row > 0) & (non_zero_per_row == 1)]
    assert degenerate.empty, (
        f"{loader_name} returned {len(draw_columns)} draw columns but "
        f"{len(degenerate)} row(s) have exactly ONE non-zero draw. The other "
        f"{len(draw_columns) - 1} were NaN from a column-alignment mismatch and then "
        "zero-filled, so the outer mean in get_data() will divide these rows by "
        f"{len(draw_columns)}."
    )
