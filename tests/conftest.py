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
from vivarium.testing_utils import FuzzyChecker

from tests.baseline import REPO_ROOT, baseline_ref


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
def fuzzy_checker(output_directory: Path) -> FuzzyChecker:
    checker = FuzzyChecker()

    yield checker

    checker.save_diagnostic_output(output_directory)


def pytest_report_header(config: pytest.Config) -> str:
    """Make the comparison target visible in the test output. Comparing against
    the wrong baseline silently is the main way this harness could mislead."""
    return f"lsff baseline ref: {baseline_ref()}"
