"""The ``0200`` -> ``0300`` hand-off: ``births.parquet``.

Why this file exists
--------------------
``births.parquet`` is the most load-bearing intermediate in the pipeline and had no
test of any kind. ``0300_child_sim`` runs with ``population_size: 0``: its *entire*
population arrives from this birth line list, so every child DALY, death and
low-birth-weight case in the study is downstream of this one file. It was also
never covered by the fuzzy layer, which snapshots only
``pregnancy_outcome_count``.

The cost of that gap is on record. Under GBD 2023 the partial-term share of
parturitions went 18.4% -> 46.2%, crowding live births down and shrinking the birth
line list by roughly a third. That propagated straight into the child sim, and it
was found by reading numbers by hand rather than by any test.

Like ``test_simulation_plausibility.py`` this layer needs **no baseline**, which is
what makes it useful during a migration: it asserts properties that must hold in
any run, so it works on a branch whose output is legitimately expected to differ.
Bands are wide sanity bounds, not validation targets -- their job is to catch zero,
near-zero, runaway and structurally-broken, not to pin epidemiology that moves
between GBD rounds.

Reference values, measured across all three combinations under **both** vintages
(GBD 2021 and the GBD-2023 run of 2026-08-05), which is why the bands below are
known to be loose rather than merely hoped to be:

    live-birth share       0.963 - 0.984
    median birth weight    2988 - 3154 g
    share below 2500 g     0.111 - 0.225
    median gestation       37.7 - 38.4 weeks
    sex ratio M/F          1.048 - 1.099
    maternal age range     10.7 - 54.7 years
    rows per scenario      identical to 4 decimal places in every file

That last one is a real structural invariant rather than a coincidence: the
maternal sim's fortification pathway changes hemoglobin and maternal outcomes, and
the *birth-weight* shift happens later, inside ``0300`` via LBWSG. So the scenarios
differ in the fortification-intake columns and in essentially nothing else here.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from tests.baseline import REPO_ROOT
from tests.reference_proportions import SIMULATED, sim_output_path

CHILD_SIM_SOURCE = REPO_ROOT / "0300_child_sim" / "src" / "vivarium_gates_lsff_2026_child"

# Columns the child sim reads off ``new_births`` that ``births.parquet`` does not
# supply, because vivarium's own population framework adds them when it creates the
# simulants. Everything else read from ``new_births`` must come from the parquet.
FRAMEWORK_SUPPLIED_COLUMNS = frozenset({"alive", "exit_time"})

# Wide sanity bands. See the module docstring for the measured values behind each.
LIVE_BIRTH_SHARE = (0.85, 0.999)
MEDIAN_BIRTH_WEIGHT_GRAMS = (2000.0, 4200.0)
LOW_BIRTH_WEIGHT_SHARE = (0.02, 0.45)
MEDIAN_GESTATIONAL_AGE_WEEKS = (32.0, 42.0)
SEX_RATIO_MALE_TO_FEMALE = (0.90, 1.20)
MATERNAL_AGE_YEARS = (10.0, 55.0)
LOW_BIRTH_WEIGHT_THRESHOLD_GRAMS = 2500.0

# The maternal sim does not vary who is born by scenario, so a difference here means
# something structural, not Monte Carlo noise. 2% leaves room for a future change
# that legitimately couples scenario to birth count.
MAX_SCENARIO_COUNT_SPREAD = 1.02


def load_births(location: str, vehicle: str) -> pd.DataFrame | None:
    path = sim_output_path(location, vehicle, "births")
    return pd.read_parquet(path) if path.exists() else None


@pytest.fixture(params=SIMULATED, ids=lambda pair: f"{pair[0]}-{pair[1]}", scope="module")
def births(request) -> pd.DataFrame:
    location, vehicle = request.param
    frame = load_births(location, vehicle)
    if frame is None:
        pytest.skip(
            f"no births.parquet for {location}/{vehicle} -- run the 0200 simulation first"
        )
    frame = frame.copy()
    for column in ("pregnancy_outcome", "scenario", "sex"):
        frame[column] = frame[column].astype(str)
    return frame


def live_births(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["pregnancy_outcome"] == "live_birth"]


def test_births_file_is_not_empty(births: pd.DataFrame) -> None:
    """The whole child simulation is this file's row count."""
    assert len(births) > 0, (
        "births.parquet is empty, so 0300_child_sim would run with no population at "
        "all and report zero for every child outcome without failing"
    )


def test_every_scenario_and_quintile_has_births(births: pd.DataFrame) -> None:
    """A missing cell means that stratum contributes no children, which reads as a
    real finding rather than a broken run -- wealth quintile is the study's
    reporting dimension."""
    cells = births.groupby(["scenario", "wealth_quintile"], observed=True).size()

    scenarios = sorted(births["scenario"].unique())
    quintiles = sorted(births["wealth_quintile"].astype(str).unique())
    assert len(quintiles) == 5, f"expected 5 wealth quintiles, found {quintiles}"
    assert len(cells) == len(scenarios) * 5, (
        f"expected {len(scenarios) * 5} scenario x quintile cells, found {len(cells)}. "
        f"Missing: "
        f"{sorted({(s, q) for s in scenarios for q in quintiles} - set(cells.index.map(lambda k: (str(k[0]), str(k[1])))))}"
    )
    assert cells.min() > 0, f"empty cells: {cells[cells == 0].index.tolist()}"


def test_columns_the_child_sim_reads_are_all_present(births: pd.DataFrame) -> None:
    """The hand-off contract, read from the consumer rather than hardcoded.

    Parses every ``new_births["..."]`` access out of the child sim's source and
    requires the parquet to supply it. Catches a column added on the reading side,
    or renamed on the writing side, in seconds -- instead of after two Slurm
    simulations, as a ``KeyError`` deep in a psimulate log.

    Uses the same technique as ``test_gbd_assumptions.py``: read the assumption from
    the code that owns it, so the test follows an edit rather than going stale.
    """
    sources = list(CHILD_SIM_SOURCE.rglob("*.py"))
    assert sources, f"no child sim sources found under {CHILD_SIM_SOURCE}"

    # Whitespace-normalised because several of these accesses wrap across lines.
    accessed: set[str] = set()
    for source in sources:
        flattened = re.sub(r"\s+", " ", source.read_text())
        accessed.update(re.findall(r'new_births\[\s*"([A-Za-z_0-9]+)"\s*\]', flattened))

    assert accessed, (
        "found no new_births[...] accesses at all -- the child sim may have changed "
        "how it consumes the birth line list, in which case this test needs rewriting "
        "rather than deleting"
    )

    required = accessed - FRAMEWORK_SUPPLIED_COLUMNS
    missing = sorted(required - set(births.columns))
    assert not missing, (
        f"0300_child_sim reads {missing} off the birth line list, but births.parquet "
        f"does not contain them. Present: {sorted(births.columns)}.\n"
        "  Either 0200's observer stopped emitting the column, or the child sim gained "
        "a read that 0200 was never updated to supply. If vivarium's population "
        "framework provides it rather than the parquet, add it to "
        "FRAMEWORK_SUPPLIED_COLUMNS with a note saying so."
    )


def test_no_missing_values_in_consumed_columns(births: pd.DataFrame) -> None:
    """NaN here becomes a NaN simulant attribute, which propagates silently through
    LBWSG rather than raising."""
    null_counts = births.isna().sum()
    offending = null_counts[null_counts > 0]

    assert offending.empty, (
        f"births.parquet has missing values: {offending.to_dict()}. These become NaN "
        "attributes on child simulants."
    )


def test_pregnancy_outcomes_are_only_live_births_and_stillbirths(
    births: pd.DataFrame,
) -> None:
    """Partial-term pregnancies never reach parturition, so they must not appear in
    the birth line list; and both real outcomes must be present."""
    outcomes = set(births["pregnancy_outcome"].unique())

    assert outcomes == {"live_birth", "stillbirth"}, (
        f"unexpected birth outcomes {sorted(outcomes)}. Partial-term pregnancies "
        "leaking into the line list would inflate the child sim's population with "
        "pregnancies that never produced a birth."
    )


def test_live_birth_share_is_plausible(births: pd.DataFrame) -> None:
    """Equivalently, the stillbirth rate. This is the quantity the GBD-2023
    stillbirth-ratio covariate rename moved, so it is worth watching directly."""
    low, high = LIVE_BIRTH_SHARE
    for scenario, block in births.groupby("scenario", observed=True):
        share = len(live_births(block)) / len(block)
        assert low <= share <= high, (
            f"{scenario}: live births are {share:.4f} of the line list, outside "
            f"[{low}, {high}]. Implied stillbirth rate {1 - share:.4f}."
        )


def test_birth_weight_distribution_is_physiological(births: pd.DataFrame) -> None:
    """Median and low-birth-weight share only.

    Deliberately not the extremes: LBWSG draws a continuous value within an
    open-ended top category, so the observed maximum reaches ~9998 g and the minimum
    ~0.2 g in every run, old and new. Those tails are an artefact of the category
    sampling, not a data problem, and banding them would either fail always or have
    to be absurdly wide.
    """
    low, high = MEDIAN_BIRTH_WEIGHT_GRAMS
    share_low, share_high = LOW_BIRTH_WEIGHT_SHARE

    for scenario, block in births.groupby("scenario", observed=True):
        alive = live_births(block)
        median = float(alive["birth_weight"].median())
        assert low <= median <= high, (
            f"{scenario}: median live birth weight {median:.0f} g outside "
            f"[{low:.0f}, {high:.0f}]"
        )

        share = float((alive["birth_weight"] < LOW_BIRTH_WEIGHT_THRESHOLD_GRAMS).mean())
        assert share_low <= share <= share_high, (
            f"{scenario}: {share:.4f} of live births below "
            f"{LOW_BIRTH_WEIGHT_THRESHOLD_GRAMS:.0f} g, outside "
            f"[{share_low}, {share_high}]. This share is what the child sim's "
            "low_weight_births observer is built on."
        )


def test_gestational_age_is_plausible(births: pd.DataFrame) -> None:
    low, high = MEDIAN_GESTATIONAL_AGE_WEEKS
    for scenario, block in births.groupby("scenario", observed=True):
        median = float(live_births(block)["gestational_age"].median())
        assert (
            low <= median <= high
        ), f"{scenario}: median gestational age {median:.2f} weeks outside [{low}, {high}]"


def test_sex_ratio_is_plausible(births: pd.DataFrame) -> None:
    """A ratio far from 1 would mean the sex assignment is broken; the child sim
    stratifies on sex, so this feeds every child result."""
    low, high = SEX_RATIO_MALE_TO_FEMALE
    for scenario, block in births.groupby("scenario", observed=True):
        females = int((block["sex"] == "Female").sum())
        assert females > 0, f"{scenario}: no female births"
        ratio = int((block["sex"] == "Male").sum()) / females
        assert (
            low <= ratio <= high
        ), f"{scenario}: male-to-female birth ratio {ratio:.3f} outside [{low}, {high}]"


def test_maternal_age_is_within_the_simulated_range(births: pd.DataFrame) -> None:
    """``0200`` models women 10-54, so a birth outside that means the line list has
    picked up rows from somewhere it should not have."""
    low, high = MATERNAL_AGE_YEARS
    ages = births["maternal_age"]

    assert float(ages.min()) >= low and float(ages.max()) <= high, (
        f"maternal age spans [{ages.min():.1f}, {ages.max():.1f}], outside the "
        f"modelled [{low}, {high}]"
    )


def test_scenarios_have_comparable_birth_counts(births: pd.DataFrame) -> None:
    """The line list's size must not depend on the scenario.

    Fortification acts on hemoglobin and on maternal outcomes; the birth-weight
    effect is applied later, in ``0300``. So all three scenarios draw the same
    births -- measured identical to four decimal places in every file, under both
    vintages. A scenario that lost births would silently shrink that arm of the
    child simulation and make the intervention look better or worse than it is.
    """
    counts = births.groupby("scenario", observed=True).size()

    assert counts.min() > 0, f"a scenario has no births at all: {counts.to_dict()}"
    spread = counts.max() / counts.min()
    assert spread <= MAX_SCENARIO_COUNT_SPREAD, (
        f"birth counts differ by {spread:.4f}x across scenarios ({counts.to_dict()}), "
        f"above the {MAX_SCENARIO_COUNT_SPREAD}x allowance. In this model the "
        "scenarios should draw the same births and differ only in fortification "
        "intake."
    )


def test_zero_scenario_has_no_fortification_intake(births: pd.DataFrame) -> None:
    """``zero`` is the no-fortification counterfactual, so its intake must be
    exactly zero -- any leak understates the intervention's measured effect."""
    zero = births[births["scenario"] == "zero"]
    if zero.empty:
        pytest.skip("no 'zero' scenario in this run")

    intake = zero["iron_consumption_from_fortification_mcg"]
    assert float(intake.abs().max()) == 0.0, (
        f"the zero-fortification scenario carries non-zero iron intake "
        f"(max {intake.max():.3f} mcg), so the counterfactual is contaminated"
    )


def test_some_scenario_actually_delivers_fortification(births: pd.DataFrame) -> None:
    """Guards a silent null result.

    ``iron_consumption_from_fortification_mcg`` is the *only* channel by which
    fortification reaches the child sim's birth-weight shift. If it were zero
    everywhere the intervention would be perfectly inert, and the pipeline would
    report a well-formed no-effect result rather than failing.

    Note this cannot be tightened to "intervention exceeds baseline": for
    India/rice the intervention raises *folate*, so iron intake is legitimately
    identical between baseline and intervention there.
    """
    intake = births.groupby("scenario", observed=True)[
        "iron_consumption_from_fortification_mcg"
    ].max()

    assert float(intake.max()) > 0.0, (
        "no scenario delivers any iron from fortification, so the modelled "
        "intervention cannot affect birth weight at all. Check the coverage and "
        "concentration inputs feeding components/intervention.py -- a zeroed "
        f"artifact key would look exactly like this. Per-scenario maxima: "
        f"{intake.to_dict()}"
    )
