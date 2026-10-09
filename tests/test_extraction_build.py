"""The committed generated extraction tables must equal a fresh build.

generated/ is written only by 0100_data_prep/extraction/integration/build_extraction.py.
A commit that changes its inputs (the base tables in data/, lit_long.csv, gf_long.csv,
decisions.csv, 0050_config/location_fortificant_vehicles.csv or the build code) without
rebuilding, or that edits generated/ by hand, fails here. Fix it by rebuilding:

    cd 0100_data_prep/extraction/integration && python build_extraction.py
"""

import sys

import pytest

from lsff_utils.extraction import EXTRACTION_DIR, EXTRACTION_GENERATED_DIR

INTEGRATION_DIR = EXTRACTION_DIR / "integration"


@pytest.fixture(scope="module")
def fresh_build():
    sys.path.insert(0, str(INTEGRATION_DIR))
    try:
        import build_extraction
    finally:
        sys.path.remove(str(INTEGRATION_DIR))
    return build_extraction, build_extraction.build()


def test_build_passes_checks(fresh_build):
    _, b = fresh_build
    assert not b.problems, "the build's checks fail: " + "; ".join(b.problems)


def test_generated_tables_are_up_to_date(fresh_build):
    module, b = fresh_build
    stale = module.stale_tables(b.tables, EXTRACTION_GENERATED_DIR)
    assert not stale, (
        f"generated/ is out of date ({', '.join(stale)}); rebuild with "
        "`cd 0100_data_prep/extraction/integration && python build_extraction.py`"
    )
