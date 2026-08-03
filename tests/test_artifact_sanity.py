"""Layer 5: compare two artifacts, before any simulation runs.

The cheapest place to catch a data problem is the artifact. A bad key here shows
up in the final results only after two microsimulations and an aggregation stage
have smeared it across thousands of numbers and mixed it with Monte Carlo noise.
Comparing artifacts localises the problem to a single key in seconds.

This layer was written after diffing a GBD-2023 artifact against the verified
GBD-2021 one, which surfaced three things a pipeline run would have shown only as
"the DALYs moved":

  - ``risk_factor.hemoglobin.standard_deviation`` roughly doubled (max 16.9 ->
    36.1 g/L). A population hemoglobin SD of 36 is not credible, and because
    severe anemia is a far-tail quantity the error amplifies:
    ``pregnant_proportion_below_70_gL`` went up 22x, to 0.58 in the worst
    stratum, and ``hemoglobin_on_maternal_hemorrhage.paf`` 11x.
  - ``cause.maternal_disorders.ylds`` grew ~187x over childbearing ages. That is
    not a GBD revision, and it feeds one of the four DALY streams directly.
  - That same key carries 8 ``inf`` values in *both* vintages, from dividing by a
    zero maternal-disorders incidence at ages 60+. ``.fillna(0)`` does not catch
    ``inf``. Harmless while the sim runs ages 10-54, but latent.

Everything else moved within 0.47x-2.7x, which is an ordinary GBD-revision range.
That contrast is what makes the ratio check useful: the outliers stand out.

Framing matters here. The degeneracy checks are written as *regressions against a
reference artifact* rather than against an allowlist of keys permitted to be zero,
because whether zero is correct is context-dependent -- Nigeria has no baseline
rice fortification programme (legitimately 0.0) but does have bouillon (~0.52).
"No key newly became all-zero" is both sharper and needs no maintenance.

Usage::

    LSFF_ARTIFACT=/path/to/new.hdf \
    LSFF_REFERENCE_ARTIFACT=/path/to/known-good.hdf \
        pytest tests/test_artifact_sanity.py

With only LSFF_ARTIFACT set, the single-artifact checks still run and the
comparison checks skip.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ordinary GBD-revision movement between rounds was 0.47x-2.7x across every key
# in the 2021-vs-2023 comparison. 3x is comfortably outside that, so an exceedance
# means "a human should look", not necessarily "this is wrong".
RATIO_THRESHOLD = 3.0

# Keys whose values are per-draw columns rather than a single 'value'; compared on
# the first numeric column, which is enough to detect degeneracy and scale shifts.
FIRST_NUMERIC_COLUMN = 0


def _load_artifact(env_var: str):
    path = os.environ.get(env_var)
    if not path:
        pytest.skip(f"set {env_var}=/path/to/artifact.hdf")
    if not Path(path).exists():
        pytest.skip(f"{env_var} does not exist: {path}")
    artifact_module = pytest.importorskip(
        "vivarium.artifact", reason="needs an environment with the artifact library"
    )
    return artifact_module.Artifact(path)


@pytest.fixture(scope="module")
def artifact():
    return _load_artifact("LSFF_ARTIFACT")


@pytest.fixture(scope="module")
def reference_artifact():
    return _load_artifact("LSFF_REFERENCE_ARTIFACT")


def numeric_series(data) -> pd.Series | None:
    if not hasattr(data, "select_dtypes"):
        return None
    numeric = data.select_dtypes("number")
    if numeric.empty:
        return None
    return numeric.iloc[:, FIRST_NUMERIC_COLUMN]


def summarise(series: pd.Series) -> dict:
    finite = series[np.isfinite(series)]
    non_zero = finite[finite != 0]
    return {
        "rows": len(series),
        "non_finite": int((~np.isfinite(series)).sum()),
        "non_zero": int((finite != 0).sum()),
        "median_non_zero": float(non_zero.median()) if len(non_zero) else float("nan"),
    }


def artifact_keys(artifact) -> list[str]:
    return sorted(str(key) for key in artifact.keys)


def pytest_generate_tests(metafunc):
    """Parametrize over the keys of whichever artifact is under test.

    Done here rather than with a fixture so each key is its own test case and a
    failure names the key directly.
    """
    if "key" not in metafunc.fixturenames:
        return
    path = os.environ.get("LSFF_ARTIFACT")
    keys: list[str] = []
    if path and Path(path).exists():
        try:
            from vivarium.artifact import Artifact

            keys = artifact_keys(Artifact(path))
        except Exception:  # pragma: no cover - environment without the library
            keys = []
    metafunc.parametrize("key", keys or [pytest.param("(no artifact)", marks=pytest.mark.skip)])


def test_key_has_no_non_finite_values(artifact, reference_artifact, key: str) -> None:
    """No key may gain inf or NaN relative to the reference.

    `.fillna(0)` in the loaders catches NaN but not inf, so a division by a zero
    denominator survives into the artifact and then into a lookup table.
    """
    series = numeric_series(artifact.load(key))
    if series is None:
        pytest.skip(f"{key} has no numeric column")
    current = summarise(series)["non_finite"]
    if not current:
        return

    reference_keys = set(artifact_keys(reference_artifact))
    baseline = 0
    if key in reference_keys:
        reference_series = numeric_series(reference_artifact.load(key))
        if reference_series is not None:
            baseline = summarise(reference_series)["non_finite"]

    assert current <= baseline, (
        f"{key} has {current} non-finite value(s), up from {baseline} in the "
        f"reference. `.fillna(0)` does not catch inf, so a divide-by-zero upstream "
        f"reaches the artifact intact."
    )


def test_key_did_not_newly_become_all_zero(artifact, reference_artifact, key: str) -> None:
    """A key that used to carry values must not silently go flat.

    This is the fillna(0) failure mode: an index misalignment upstream becomes
    zeros with no error. Comparing against a reference avoids having to decide in
    the abstract whether zero is legitimate -- for some keys it is.
    """
    series = numeric_series(artifact.load(key))
    if series is None:
        pytest.skip(f"{key} has no numeric column")
    if summarise(series)["non_zero"]:
        return

    reference_keys = set(artifact_keys(reference_artifact))
    if key not in reference_keys:
        pytest.skip(f"{key} is not in the reference artifact")
    reference_series = numeric_series(reference_artifact.load(key))
    if reference_series is None:
        pytest.skip(f"{key} has no numeric column in the reference")

    assert not summarise(reference_series)["non_zero"], (
        f"{key} is entirely zero but carries values in the reference artifact. "
        "That is the signature of an upstream index misalignment converted to "
        "zeros by `.fillna(0)`."
    )


def test_key_magnitude_is_comparable_to_reference(
    artifact, reference_artifact, key: str
) -> None:
    """Flag keys whose scale moved far more than a GBD revision plausibly would.

    Not a correctness assertion -- a genuine revision can exceed the threshold, in
    which case widen it or record the key. It is a review trigger, and it is how
    the hemoglobin SD and maternal-disorders YLD problems were found.
    """
    if key not in set(artifact_keys(reference_artifact)):
        pytest.skip(f"{key} is not in the reference artifact")

    series = numeric_series(artifact.load(key))
    reference_series = numeric_series(reference_artifact.load(key))
    if series is None or reference_series is None:
        pytest.skip(f"{key} has no numeric column in both artifacts")

    current = summarise(series)["median_non_zero"]
    baseline = summarise(reference_series)["median_non_zero"]
    if not np.isfinite(current) or not np.isfinite(baseline) or baseline == 0:
        pytest.skip(f"{key} has no comparable non-zero median")

    ratio = current / baseline
    fold = max(ratio, 1 / ratio)
    assert fold <= RATIO_THRESHOLD, (
        f"{key} moved {ratio:.3g}x (median of non-zero values: {baseline:.6g} -> "
        f"{current:.6g}), beyond the {RATIO_THRESHOLD}x review threshold.\n"
        "  Ordinary GBD-round movement in this artifact was 0.47x-2.7x, so this is "
        "worth a look before it reaches a production run. If the revision is real, "
        "widen RATIO_THRESHOLD or record the key here."
    )
