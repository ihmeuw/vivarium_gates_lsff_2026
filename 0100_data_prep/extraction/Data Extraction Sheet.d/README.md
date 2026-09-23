# Text projection of `Data Extraction Sheet.xlsx`

**Generated files — do not hand-edit.** The workbook next door is the editing
surface; these CSVs exist so that changes to it show up as reviewable
row-level diffs in git and on GitHub, instead of "Binary files differ".

- One CSV per sheet, named by a slug of the sheet name.
- Data sheets are written in a canonical key order (see `SHEET_KEYS` in
  `lsff_utils.extraction_projection`), so the same edit always produces the
  same diff no matter where rows sit in the workbook. Progress/reference
  sheets are dumped in raw row order.
- Formula cells appear at their cached value (what `pandas.read_excel`
  sees); `_formulas.csv` additionally lists every formula with its cached
  value, so edits to formulas themselves are visible.
- Newlines inside cells are escaped as `\n`; floats use their shortest
  round-trip representation.

After editing the workbook:

    python -m lsff_utils.extraction_projection

To verify sync (also enforced by `tests/test_extraction_projection.py`):

    python -m lsff_utils.extraction_projection --check
