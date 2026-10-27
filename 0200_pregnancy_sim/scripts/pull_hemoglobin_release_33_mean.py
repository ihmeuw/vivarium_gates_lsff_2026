"""Pull the release 33 pregnant hemoglobin mean (ME 28869) into the stored-file format.

Writes hemoglobin_exposure_{location}.parquet with the same columns as the files in
HEMOGLOBIN_RELEASE_33_DATA_DIR. Run on the cluster, then copy the output into that
folder. If a stored file already exists for the location, the pull is compared to it.
"""

import argparse
import os
from pathlib import Path

import pandas as pd
from vivarium_gbd_access import gbd
from vivarium_inputs import utility_data

from vivarium_gates_lsff_2026_maternal.constants import paths

ME_ID = 28869
MODEL_VERSION_ID = 926437
REI_ID = 376
RELEASE_ID = 33
YEAR_ID = 2023
FEMALE = 2
COLUMNS = [
    "rei_id",
    "modelable_entity_id",
    "location_id",
    "year_id",
    "age_group_id",
    "sex_id",
    "measure_id",
    "metric_id",
    "parameter",
]


def pull_mean(location: str) -> pd.DataFrame:
    location_id = utility_data.get_location_id(location.title())
    data = gbd.get_modelable_entity_draws(
        me_id=ME_ID,
        location_id=location_id,
        year_id=YEAR_ID,
        data_type="draws",
        release_id=RELEASE_ID,
    )
    data = data[data["sex_id"] == FEMALE].assign(rei_id=REI_ID, parameter="continuous")
    versions = data["model_version_id"].unique().tolist()
    assert versions == [MODEL_VERSION_ID], f"Expected model version {MODEL_VERSION_ID}, got {versions}"
    draws = [c for c in data.columns if c.startswith("draw_")]
    return (
        data[COLUMNS + draws + ["model_version_id"]]
        .sort_values("age_group_id")
        .reset_index(drop=True)
    )


def compare_to_stored(data: pd.DataFrame, stored_path: Path) -> None:
    stored = pd.read_parquet(stored_path)
    assert list(data.columns) == list(stored.columns), "Columns differ from the stored file"
    assert sorted(data["age_group_id"]) == sorted(stored["age_group_id"]), "Age groups differ"
    draws = [c for c in data.columns if c.startswith("draw_")]
    merged = data.merge(stored, on="age_group_id", suffixes=("", "_stored"))
    max_diff = max((merged[d] - merged[f"{d}_stored"]).abs().max() for d in draws)
    print(f"Max absolute difference from {stored_path}: {max_diff}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("locations", nargs="+", help="Location names, e.g. india nigeria")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(f"/mnt/share/scratch/users/{os.environ['USER']}/hemoglobin_release33"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for location in args.locations:
        filename = f"hemoglobin_exposure_{location.lower()}.parquet"
        data = pull_mean(location)
        print(f"{location}: {data.shape[0]} rows, {data.shape[1]} columns")
        stored_path = paths.HEMOGLOBIN_RELEASE_33_DATA_DIR / filename
        if stored_path.exists():
            compare_to_stored(data, stored_path)
        data.to_parquet(args.output_dir / filename)
        print(f"Wrote {args.output_dir / filename}")


if __name__ == "__main__":
    main()
