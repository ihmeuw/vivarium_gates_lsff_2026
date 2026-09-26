"""Validate the hand-extracted input CSVs in 0100_data_prep/extraction/data/."""

import csv

import pytest

from lsff_utils.extraction import EXTRACTION_DATA_DIR, TABLES, extraction_path, load_extraction


def test_every_csv_is_a_known_table():
    on_disk = {p.stem for p in EXTRACTION_DATA_DIR.glob("*.csv")}
    assert on_disk == set(TABLES)


@pytest.mark.parametrize("table", TABLES)
def test_table_loads_and_validates(table):
    df = load_extraction(table)
    assert len(df) > 0


@pytest.mark.parametrize("table", TABLES)
def test_rows_have_header_width(table):
    with open(extraction_path(table), newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    widths = {len(r) for r in rows}
    assert widths == {len(rows[0])}, f"{table}.csv has rows of widths {sorted(widths)}"


def test_progress_refers_to_known_tables():
    progress = load_extraction("progress")
    assert set(progress["Table"]) <= set(TABLES) - {"progress"}
