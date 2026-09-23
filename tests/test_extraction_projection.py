"""The committed CSV projection must match the Data Extraction Sheet.

If this fails, someone edited the workbook (or the projection) without
regenerating: python -m lsff_utils.extraction_projection
"""

from lsff_utils import extraction_projection


def test_projection_in_sync_with_workbook():
    problems = extraction_projection.check()
    assert not problems, (
        "Data Extraction Sheet.d/ is out of sync with the workbook; "
        "regenerate with `python -m lsff_utils.extraction_projection`: "
        + "; ".join(problems)
    )
