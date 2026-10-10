"""Validate the extraction tables: the base layer (data/) and the generated layer (generated/)."""

import csv

import pytest

from lsff_utils.extraction import (
    EXTRACTION_DATA_DIR,
    EXTRACTION_GENERATED_DIR,
    GENERATED_TABLES,
    TABLES,
    extraction_path,
    load_extraction,
)

LAYERS = [(table, True) for table in TABLES] + [(table, False) for table in GENERATED_TABLES]
IDS = [f"{'data' if base else 'generated'}/{table}" for table, base in LAYERS]


def test_every_csv_is_a_known_table():
    assert {p.stem for p in EXTRACTION_DATA_DIR.glob("*.csv")} == set(TABLES)
    assert {p.stem for p in EXTRACTION_GENERATED_DIR.glob("*.csv")} == set(GENERATED_TABLES)


@pytest.mark.parametrize("table, base", LAYERS, ids=IDS)
def test_table_loads_and_validates(table, base):
    df = load_extraction(table, base=base)
    assert len(df) > 0


@pytest.mark.parametrize("table, base", LAYERS, ids=IDS)
def test_rows_have_header_width(table, base):
    with open(extraction_path(table, base), newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    widths = {len(r) for r in rows}
    assert widths == {len(rows[0])}, f"{table}.csv has rows of widths {sorted(widths)}"


def test_progress_refers_to_known_tables():
    progress = load_extraction("progress")
    assert set(progress["Table"]) <= set(TABLES) - {"progress"}
