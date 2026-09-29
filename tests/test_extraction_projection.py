"""The committed CSV projection must match the Data Extraction Sheet.

If this fails, someone edited the workbook (or the projection) without
regenerating: python -m lsff_utils.extraction_projection
"""

from pathlib import Path

from lsff_utils import extraction_projection

# Relative to this file, not paths.REPO_ROOT: CI installs lsff_utils
# non-editable, so REPO_ROOT points into site-packages.
WORKBOOK = Path(__file__).resolve().parents[1] / "0100_data_prep/extraction/Data Extraction Sheet.xlsx"


def test_projection_in_sync_with_workbook():
    problems = extraction_projection.check(WORKBOOK.with_name(WORKBOOK.stem + ".d"), WORKBOOK)
    assert not problems, (
        "Data Extraction Sheet.d/ is out of sync with the workbook; "
        "regenerate with `python -m lsff_utils.extraction_projection`: " + "; ".join(problems)
    )
