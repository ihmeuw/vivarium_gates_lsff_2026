"""Shared fixtures for the regression harness.

``--runslow``, ``--runweekly`` and the ``slow``/``cluster`` markers come from the
pytest plugin in ``vivarium-testing-utils``, which registers itself via a
``pytest11`` entry point. Note that plugin imports ``pytest_mock`` without
declaring it, so ``pytest-mock`` must be installed or the plugin is silently
skipped and ``--runslow`` disappears.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.baseline import REPO_ROOT, baseline_ref

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


def pytest_report_header(config: pytest.Config) -> str:
    """Make the comparison target visible in the test output. Comparing against
    the wrong baseline silently is the main way this harness could mislead."""
    return f"lsff baseline ref: {baseline_ref()}"
