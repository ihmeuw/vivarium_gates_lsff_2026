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

import sys
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

# ---------------------------------------------------------------------------
# 0300_child_sim
# ---------------------------------------------------------------------------
# The child sim had no coverage in the fuzzy layer at all, despite producing the
# study's child DALYs, deaths and low-birth-weight cases. Its observers do not fit
# the composition model above: `live_births`, `low_weight_births` and `deaths` are
# separate files with no `sub_entity` to take a share within, so these are expressed
# as *ratios between two count observers* instead. Each denominator event either is
# or is not a numerator event, so the binomial model the fuzzy checker assumes still
# holds -- arguably more cleanly than for a composition.
#
# Excluded on purpose: `person_time`, `birth_weight_sum` and `gestational_age_sum`
# are continuous, not counts; `ylds` is identically zero (pre-existing, not a
# migration regression -- most disability-causing components are commented out); and
# the `deaths` composition by sub_entity is degenerate because `stillborn` is 0
# everywhere, so `other_causes` carries a share of exactly 1.
CHILD_SIM_RESULTS_ROOT = REPO_ROOT / "0300_child_sim" / "sim_results"

# GBD-2021 child output survives only here, and only for two of the three
# combinations: the rule's `rm -rf` overwrote rice/nigeria before anyone thought to
# preserve it. Gitignored, and it exists nowhere else -- see CLAUDE.md.
PRESERVED_GBD_2021_CHILD_ROOT = REPO_ROOT / ".child_results_gbd2021_reference"

# Deliberately a *separate* file from sim_proportions.csv. That one is the only
# surviving record of published pregnancy-sim behaviour and must not be rewritten
# while the GBD-2023 findings are open; appending child rows would mean regenerating
# it. Keeping them apart means the child reference can be (re)generated freely.
CHILD_REFERENCE_PATH = REPO_ROOT / "tests" / "reference" / "child_sim_proportions.csv"

# (numerator observer, denominator observer).
CHILD_RATIO_MEASURES = (
    ("low_weight_births", "live_births"),
    ("deaths", "live_births"),
)

# The child sim stratifies on `child_scenario` x `maternal_scenario` rather than a
# single `scenario`. child_scenario is ['baseline'] only, so maternal_scenario is the
# axis that varies and is renamed to `scenario` here to keep one set of column names
# across both simulations.
CHILD_SCENARIO_COLUMN = "maternal_scenario"


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


def child_sim_output_path(
    location: str, vehicle: str, measure: str, root: Path | None = None
) -> Path:
    return (root or CHILD_SIM_RESULTS_ROOT) / vehicle / location / f"{measure}.parquet"


def ratio_measure_name(numerator: str, denominator: str) -> str:
    return f"{numerator}_per_{denominator}"


def compute_child_proportions(
    location: str,
    vehicle: str,
    numerator_measure: str,
    denominator_measure: str,
    root: Path | None = None,
) -> pd.DataFrame | None:
    """One numerator/denominator per (scenario, wealth_quintile).

    Summed over seeds, ages and sexes. Pooling seeds is what makes the sample size
    informative -- each is an independent replicate of the same target proportion.
    ``deaths`` is summed over its ``sub_entity`` too, so the measure is all-cause.
    """
    numerator_path = child_sim_output_path(location, vehicle, numerator_measure, root)
    denominator_path = child_sim_output_path(location, vehicle, denominator_measure, root)
    if not numerator_path.exists() or not denominator_path.exists():
        return None

    group = [CHILD_SCENARIO_COLUMN, "wealth_quintile"]

    def totals(path: Path, name: str) -> pd.Series:
        raw = pd.read_parquet(path)
        missing = set(group) - set(raw.columns)
        if missing:
            raise ValueError(f"{path} is missing expected column(s) {sorted(missing)}")
        return raw.groupby(group, observed=True)["value"].sum().rename(name)

    numerator = totals(numerator_path, "numerator")
    denominator = totals(denominator_path, "denominator")

    frame = (
        pd.concat([numerator, denominator], axis=1)
        .reset_index()
        .rename(columns={CHILD_SCENARIO_COLUMN: "scenario"})
    )
    frame = frame.dropna(subset=["numerator", "denominator"])

    for column in ("numerator", "denominator"):
        non_integer = frame[column] % 1 != 0
        if non_integer.any():
            raise ValueError(
                f"{numerator_path if column == 'numerator' else denominator_path} yields "
                f"non-integer counts; not a valid binomial {column} "
                f"(offending rows: {int(non_integer.sum())})"
            )
        frame[column] = frame[column].astype(int)

    exceeding = frame[frame["numerator"] > frame["denominator"]]
    if not exceeding.empty:
        raise ValueError(
            f"{numerator_measure} exceeds {denominator_measure} in "
            f"{len(exceeding)} group(s), so it cannot be a proportion of it:\n"
            f"{exceeding.to_string()}"
        )

    return frame.assign(
        location=location,
        vehicle=vehicle,
        measure=ratio_measure_name(numerator_measure, denominator_measure),
        sub_entity=numerator_measure,
    )


def collect_all_child(root: Path | None = None) -> pd.DataFrame:
    frames = [
        frame
        for location, vehicle in SIMULATED
        for numerator, denominator in CHILD_RATIO_MEASURES
        if (
            frame := compute_child_proportions(
                location, vehicle, numerator, denominator, root
            )
        )
        is not None
    ]
    if not frames:
        raise SystemExit(
            f"No child simulation output found under {root or CHILD_SIM_RESULTS_ROOT}."
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


def load_child_reference() -> pd.DataFrame | None:
    if not CHILD_REFERENCE_PATH.exists():
        return None
    return pd.read_csv(CHILD_REFERENCE_PATH)


def main_child() -> None:
    """Snapshot the child reference from the preserved GBD-2021 output.

    Defaults to ``.child_results_gbd2021_reference`` rather than the live results
    directory, so the reference records *published-era* behaviour rather than
    whatever happens to be on disk. Only two of the three combinations survive
    there; the third simply has no reference rows and its checks do not run.
    """
    root = PRESERVED_GBD_2021_CHILD_ROOT
    if not root.exists():
        raise SystemExit(
            f"{root} does not exist. It holds the only surviving GBD-2021 child "
            "output and is gitignored; without it there is nothing trustworthy to "
            "snapshot. Pass the live results root explicitly only if you mean to "
            "baseline the current vintage."
        )
    frame = collect_all_child(root)
    CHILD_REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CHILD_REFERENCE_PATH, index=False)
    print(f"wrote {len(frame)} child reference proportions to {CHILD_REFERENCE_PATH}")
    print(
        frame.assign(proportion=frame.numerator / frame.denominator)
        .groupby(["location", "vehicle", "measure"])
        .agg(
            groups=("proportion", "size"),
            min_proportion=("proportion", "min"),
            max_proportion=("proportion", "max"),
            min_denominator=("denominator", "min"),
        )
        .to_string()
    )


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
    # Two references, regenerated separately and on purpose. `--child` reads the
    # preserved GBD-2021 child output; the default rewrites the pregnancy reference,
    # which must not happen while the GBD-2023 findings are open.
    if "--child" in sys.argv[1:]:
        main_child()
    else:
        main()
