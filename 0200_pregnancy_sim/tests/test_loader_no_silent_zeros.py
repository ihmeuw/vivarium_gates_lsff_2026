"""Guards against index misalignment silently becoming zeros in the artifact.

Offered in support of the fix in 02158e1 ("fix bug in maternal hemorrhage data").

Background
----------
``get_pregnancy_end_incidence`` used to stamp a hardcoded ``year_start=2021,
year_end=2022`` onto the data-prep results before combining them with GBD data.
Under GBD 2023 the estimation years moved, the indices stopped aligning, the
product went NaN, and a downstream ``.fillna(0)`` turned that into zeros. The
simulation then ran happily and reported no maternal hemorrhage at all. The
``broadcast_onto`` helper fixes it, and its docstring names the hazard exactly:

    a hardcoded year silently produces an all-NaN result whenever the GBD
    release year moves on

These tests exist because *that specific bug is fixed, but the construct that
made it silent is not*. There are still six ``.fillna(0)`` calls in the loader,
five of them on live artifact keys. Any of them will convert a future index
misalignment into a plausible-looking zero rather than an error.

Three tiers, so something useful runs in every environment:

  1. ``test_fillna_zero_sites_are_accounted_for`` -- pure text, no dependencies,
     always runs. Census of the ``.fillna(0)`` calls. Fails when a new one
     appears, so adding one is a deliberate decision rather than an accident.
  2. ``test_broadcast_onto_*`` -- pure pandas unit tests of the new helper,
     including that it *raises* on a missing level instead of returning NaN.
  3. ``test_artifact_key_is_not_degenerate`` -- needs a built artifact. Asserts
     each key fed by a ``fillna(0)`` loader is not all-zero and not all-NaN.
     This is the direct check that the hemorrhage fix holds.

Verified commands (all three tiers exercised, 2026-07-31)::

    # tier 1 only -- no dependencies at all
    pytest 0200_pregnancy_sim/tests/test_loader_no_silent_zeros.py

    # tiers 1 + 2 -- needs the maternal package and lsff_utils importable
    PYTHONPATH=0200_pregnancy_sim/src:src pytest 0200_pregnancy_sim/tests/

    # all three -- add a built artifact
    LSFF_ARTIFACT=$PWD/0200_pregnancy_sim/mean_draw_artifacts/rice/india.hdf \
        PYTHONPATH=0200_pregnancy_sim/src:src pytest 0200_pregnancy_sim/tests/

Each tier was checked to fail when it should: a new `.fillna(0)` in a fresh
function trips tier 1, and zeroing
``cause.maternal_hemorrhage.incident_probability`` in a copied artifact trips
tier 3 while the other four keys keep passing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOADER = (
    REPO_ROOT
    / "0200_pregnancy_sim"
    / "src"
    / "vivarium_gates_lsff_2026_maternal"
    / "data"
    / "loader.py"
)

# Every function in loader.py that ends a data path with `.fillna(0)`, mapped to
# the artifact key it serves. `load_background_morbidity` is included for
# completeness but its key is commented out of the mapping dict, so it is dead.
FILLNA_ZERO_LOADERS = {
    "load_maternal_disorders_ylds": "cause.maternal_disorders.ylds",
    "load_pregnant_maternal_disorders_incidence_probability": (
        "cause.maternal_disorders.incident_probability"
    ),
    "load_maternal_disorders_mortality_probability": (
        "cause.maternal_disorders.mortality_probability"
    ),
    "load_pregnant_maternal_hemorrhage_incidence": (
        "cause.maternal_hemorrhage.incident_probability"
    ),
    "get_hemoglobin_data": "risk_factor.hemoglobin.mean",
    "load_background_morbidity": None,  # key commented out of the mapping
}

LIVE_KEYS = tuple(sorted(key for key in FILLNA_ZERO_LOADERS.values() if key))


def enclosing_functions_of_fillna_zero(source: str) -> set[str]:
    """Names of the functions containing a `.fillna(0)` call."""
    found = set()
    current = None
    for line in source.splitlines():
        match = re.match(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if match:
            current = match.group(1)
        if ".fillna(0)" in line and current:
            found.add(current)
    return found


def test_fillna_zero_sites_are_accounted_for() -> None:
    """Census of the silent-zero construct. Runs everywhere, needs nothing.

    `.fillna(0)` after a reindex or merge is the reason the maternal hemorrhage
    bug produced zeros instead of an exception. This does not forbid the pattern
    -- some of these genuinely want zero-filling -- it just makes the set of
    places using it explicit, so a new one is a decision someone made on purpose.
    """
    actual = enclosing_functions_of_fillna_zero(LOADER.read_text())
    expected = set(FILLNA_ZERO_LOADERS)

    new = actual - expected
    assert not new, (
        f"new `.fillna(0)` call(s) in loader.py, in: {sorted(new)}.\n"
        "  If the reindex or merge that precedes it can ever misalign, this will\n"
        "  turn that misalignment into zeros with no error -- the maternal\n"
        "  hemorrhage bug (02158e1) in a new place. Either drop the fillna and let\n"
        "  it raise, assert on the NaNs first, or add the function here to record\n"
        "  that zero-filling is intended."
    )

    gone = expected - actual
    assert not gone, (
        f"`.fillna(0)` removed from {sorted(gone)} -- good, if deliberate. "
        "Update FILLNA_ZERO_LOADERS to match."
    )


def test_broadcast_onto_repeats_across_missing_levels() -> None:
    """The fix's intended behaviour: fill in the levels the data lacks."""
    loader = pytest.importorskip(
        "vivarium_gates_lsff_2026_maternal.data.loader",
        reason="needs the maternal package importable (PYTHONPATH=0200_pregnancy_sim/src)",
    )

    data = pd.Series(
        [1.0, 2.0],
        index=pd.MultiIndex.from_tuples(
            [("Female", 15.0), ("Female", 20.0)], names=["sex", "age_start"]
        ),
    )
    target = pd.MultiIndex.from_tuples(
        [
            ("Female", 15.0, 2021),
            ("Female", 15.0, 2022),
            ("Female", 20.0, 2021),
            ("Female", 20.0, 2022),
        ],
        names=["sex", "age_start", "year_start"],
    )

    result = loader.broadcast_onto(data, target)

    assert result.notna().all(), (
        "broadcast_onto produced NaN on a target index it should cover; this is "
        "exactly the failure mode the helper exists to prevent"
    )
    assert result.loc[("Female", 15.0, 2021)] == 1.0
    assert result.loc[("Female", 15.0, 2022)] == 1.0
    assert result.loc[("Female", 20.0, 2022)] == 2.0


def test_broadcast_onto_raises_instead_of_returning_nan() -> None:
    """A missing level must be loud.

    The point of the helper over stamping a fixed year is that an index it cannot
    cover is an error, not a quietly NaN-filled result that a later fillna(0)
    converts into zeros.
    """
    loader = pytest.importorskip(
        "vivarium_gates_lsff_2026_maternal.data.loader",
        reason="needs the maternal package importable (PYTHONPATH=0200_pregnancy_sim/src)",
    )

    data = pd.Series(
        [1.0],
        index=pd.MultiIndex.from_tuples(
            [("Female", 15.0)], names=["sex", "wealth_quintile"]
        ),
    )
    target = pd.MultiIndex.from_tuples(
        [("Female", 2021)], names=["sex", "year_start"]  # no wealth_quintile level
    )

    with pytest.raises(ValueError, match="missing the level"):
        loader.broadcast_onto(data, target)


@pytest.fixture(scope="module")
def artifact():
    path = os.environ.get("LSFF_ARTIFACT")
    if not path:
        pytest.skip("set LSFF_ARTIFACT=/path/to/<location>.hdf to check a built artifact")
    if not Path(path).exists():
        pytest.skip(f"LSFF_ARTIFACT does not exist: {path}")
    artifact_module = pytest.importorskip(
        "vivarium.artifact", reason="needs the artifact library"
    )
    return artifact_module.Artifact(path)


@pytest.mark.parametrize("key", LIVE_KEYS)
def test_artifact_key_is_not_degenerate(artifact, key: str) -> None:
    """Each key fed by a `fillna(0)` loader must carry real values.

    An all-zero or all-NaN key is the signature of an upstream index
    misalignment that fillna(0) swallowed. For reference, on a verified GBD 2021
    artifact `cause.maternal_hemorrhage.incident_probability` has mean 0.011,
    max 0.110, and 45 of 250 rows non-zero -- the zeros there are age/quintile
    combinations outside childbearing years, which is expected.
    """
    available = {str(k) for k in artifact.keys}
    if key not in available:
        pytest.skip(f"{key} not in this artifact")

    data = artifact.load(key)
    numeric = data.select_dtypes("number") if hasattr(data, "select_dtypes") else None
    if numeric is None or numeric.empty:
        pytest.skip(f"{key} has no numeric columns to check")
    values = numeric.iloc[:, 0]

    assert not values.isna().all(), (
        f"{key} is entirely NaN -- an upstream index misalignment that fillna(0) "
        "did not even catch"
    )
    assert (values != 0).any(), (
        f"{key} is entirely zero. That is the maternal hemorrhage failure mode: an\n"
        "  index misalignment upstream, converted to zeros by `.fillna(0)` with no\n"
        "  error. Check that the data-prep results and the GBD data being combined\n"
        "  share the index levels they are joined on -- see broadcast_onto and the\n"
        "  note in get_pregnancy_end_incidence."
    )
