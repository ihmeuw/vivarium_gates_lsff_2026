"""Shared fixtures for the regression harness.

``--runslow``, ``--runweekly`` and the ``slow``/``cluster`` markers come from the
pytest plugin in ``vivarium-testing-utils``, which registers itself via a
``pytest11`` entry point. Note that plugin imports ``pytest_mock`` without
declaring it, so ``pytest-mock`` must be installed or the plugin is silently
skipped and ``--runslow`` disappears.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests.baseline import REPO_ROOT, baseline_ref

# Make `lsff_utils` importable even where the project was never `pip install -e .`'d.
# .test_venv is the case in practice: it exists to host vivarium-testing-utils, and
# without this every test importing lsff_utils fails at *collection*, which aborts
# the whole session rather than skipping -- so the fuzzy layer that .test_venv exists
# for never ran either. test_draw_alignment.py already does the same thing for
# 0200_pregnancy_sim/src.
if importlib.util.find_spec("lsff_utils") is None:  # pragma: no cover - env dependent
    _src = str(REPO_ROOT / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

try:  # available in .test_venv, absent from the artifact env
    from vivarium.testing_utils import FuzzyChecker
except ImportError:  # pragma: no cover - depends which venv is active
    FuzzyChecker = None


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def output_directory() -> Path:
    """Where FuzzyChecker writes its per-run diagnostics CSV."""
    path = REPO_ROOT / "tests" / ".diagnostics"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def fuzzy_checker(output_directory: Path):
    """Skips rather than errors when vivarium-testing-utils is unavailable.

    The suite has to run in two environments: .test_venv has the fuzzy checker
    but no GBD access, and the artifact env (.venv) has GBD access but cannot
    host vivarium-testing-utils, whose modern ``vivarium.*`` namespace collides
    with the old-generation ``vivarium`` package there.
    """
    if FuzzyChecker is None:
        pytest.skip("vivarium-testing-utils not installed in this environment")

    checker = FuzzyChecker()

    yield checker

    checker.save_diagnostic_output(output_directory)


def pytest_configure(config: pytest.Config) -> None:
    """Register ``slow`` when the vivarium-testing-utils plugin is not loaded.

    That plugin normally owns the marker (and the --runslow flag), but it cannot
    be installed in the artifact environment, where the GBD-facing tests run.
    Without this, pytest there warns about an unknown mark.
    """
    if not config.pluginmanager.hasplugin("vivarium_testing_utils"):
        config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Make the comparison target and its meaningfulness visible in the output.

    Comparing against the wrong baseline silently is one way this harness could
    mislead; the other is comparing committed files against themselves and reading
    the green as verification. The freshness line says how much of layer 1 is
    actually checking anything -- see tests/baseline.py.
    """
    lines = [f"lsff baseline ref: {baseline_ref()}"]
    try:
        from tests.baseline import freshness_summary, tracked_result_csvs

        counts = freshness_summary(tracked_result_csvs())
        lines.append(
            "lsff tracked result freshness: "
            + ", ".join(f"{count} {state}" for state, count in counts.items() if count)
            + "  (only 'fresh' makes a layer-1 comparison meaningful)"
        )
    except Exception as error:  # pragma: no cover - never block collection over a header
        lines.append(f"lsff tracked result freshness: unavailable ({error})")
    return lines
