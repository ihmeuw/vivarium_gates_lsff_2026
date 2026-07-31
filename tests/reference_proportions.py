"""Layer 2 support: count-based proportions from the microsimulation output.

Why this exists
---------------
The stage-5000 CSVs cannot support a statistical regression test. They are
rescaled to national population, so their "counts" are scaled estimates, not
sample sizes -- treating them as binomial counts would claim absurd precision.
The real sample sizes live in the simulation output parquet at simulation scale.

But those parquet files are gitignored, and the April-2025 run's copies are gone
(the newest archive under /mnt/team/.../vivarium_gates_lsff_by_wealth_quintile/
is 2024_08_16). So there is no historical raw output to compare against. Instead
we snapshot the *proportions* -- small, human-readable, reviewable in a diff --
from a verified run and commit that as the reference.

Regenerate with:

    python -m tests.reference_proportions

Only do that from a run you have reason to trust, and review the diff: this file
is the thing every future comparison is judged against.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tests.baseline import REPO_ROOT

REFERENCE_PATH = REPO_ROOT / "tests" / "reference" / "sim_proportions.csv"

# Locations that run the iron microsimulations. Ethiopia is folate-only.
SIMULATED = (("india", "rice"), ("nigeria", "rice"), ("nigeria", "bouillon"))

# Measures expressed as a composition: each sub_entity's share of the group total.
# Restricted to observers that emit genuine integer counts, so the binomial model
# the fuzzy checker assumes actually holds. Person-time measures are excluded --
# they are continuous, not counts.
COMPOSITION_MEASURES = ("pregnancy_outcome_count",)

# What the proportion is taken within. sub_entity is the numerator dimension.
GROUP_BY = ("scenario", "wealth_quintile")


def sim_output_path(location: str, vehicle: str, measure: str) -> Path:
    return (
        REPO_ROOT
        / "0200_pregnancy_sim"
        / "sim_results"
        / vehicle
        / location
        / f"{measure}.parquet"
    )


def compute_proportions(location: str, vehicle: str, measure: str) -> pd.DataFrame | None:
    """Numerator/denominator per (group, sub_entity), summed over seeds and ages.

    Summing across random seeds is what makes the sample size large enough to be
    informative: each seed is an independent replicate of the same target
    proportion, so pooling them is legitimate here.
    """
    path = sim_output_path(location, vehicle, measure)
    if not path.exists():
        return None

    raw = pd.read_parquet(path)
    group = list(GROUP_BY)
    counts = (
        raw.groupby(group + ["sub_entity"], observed=True)["value"].sum().rename("numerator")
    )
    totals = counts.groupby(group, observed=True).sum().rename("denominator")
    frame = counts.reset_index().merge(totals.reset_index(), on=group)

    non_integer = frame["numerator"] % 1 != 0
    if non_integer.any():
        raise ValueError(
            f"{path} yields non-integer counts; it is not a valid binomial "
            f"numerator (offending rows: {int(non_integer.sum())})"
        )

    frame["numerator"] = frame["numerator"].astype(int)
    frame["denominator"] = frame["denominator"].astype(int)
    return frame.assign(location=location, vehicle=vehicle, measure=measure)


def collect_all() -> pd.DataFrame:
    frames = [
        frame
        for location, vehicle in SIMULATED
        for measure in COMPOSITION_MEASURES
        if (frame := compute_proportions(location, vehicle, measure)) is not None
    ]
    if not frames:
        raise SystemExit(
            "No simulation output found. Run the pipeline before regenerating the "
            "reference."
        )
    columns = [
        "location",
        "vehicle",
        "measure",
        *GROUP_BY,
        "sub_entity",
        "numerator",
        "denominator",
    ]
    return (
        pd.concat(frames, ignore_index=True)[columns]
        .sort_values(columns)
        .reset_index(drop=True)
    )


def load_reference() -> pd.DataFrame | None:
    if not REFERENCE_PATH.exists():
        return None
    return pd.read_csv(REFERENCE_PATH)


def main() -> None:
    frame = collect_all()
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(REFERENCE_PATH, index=False)
    print(f"wrote {len(frame)} reference proportions to {REFERENCE_PATH}")
    print(
        frame.assign(proportion=frame.numerator / frame.denominator)
        .groupby(["location", "vehicle", "measure"])
        .agg(groups=("proportion", "size"), min_denominator=("denominator", "min"))
        .to_string()
    )


if __name__ == "__main__":
    main()
