"""Unit tests for the pipeline fan-out defined in ``0050_config/``.

``lsff_utils.config_utils`` expands three declarative config files into the set of
``(location, fortificant, vehicle, intervention_scenario)`` combinations that every
Snakefile loops over. It is the single point where "which analyses exist" is
decided, and it had no test.

A fault here is quiet in a specific way: a dropped combination does not raise, it
just means a location or a fortificant never gets built, and Snakemake reports
success for the rules it was asked about. Nothing downstream notices a missing
branch of the fan-out -- there is no manifest to compare against.

The tests split into two kinds:

  - the expansion rules (``fortificant: all``, per-location custom intervention
    scenarios), checked against the config rather than against hardcoded answers,
    so editing ``0050_config/`` updates the expectation instead of breaking it; and
  - the *contract the Snakefiles rely on*, in particular that
    ``get_configured_combos`` returns rows that unpack positionally in the order
    requested. Every caller does ``for (location, vehicle) in ...``, so a column
    reordering would silently swap them.

Plus one cross-file consistency check, which is the kind of failure this config
layout actually invites: ``location_vehicle_scenario_comparisons.csv`` names
scenarios by hand, and nothing otherwise verifies those names against the ones the
fan-out produces.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lsff_utils.config_utils import (
    get_config,
    get_configured_combos,
    get_location_fortificant_vehicle_intervention_scenarios,
)
from tests.baseline import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "0050_config"

# The base scenarios every combination has, independent of the intervention
# fan-out. These are the `intervention.scenario` values in
# 0200_pregnancy_sim/.../branches/scenarios.yaml.
BASE_SCENARIOS = frozenset({"zero", "baseline"})


@pytest.fixture(scope="module")
def expansion() -> pd.DataFrame:
    return get_location_fortificant_vehicle_intervention_scenarios()


@pytest.fixture(scope="module")
def declared_grid() -> pd.DataFrame:
    return pd.read_csv(CONFIG_DIR / "location_fortificant_vehicles.csv")


def test_all_fortificant_is_fully_expanded(expansion, declared_grid) -> None:
    """``fortificant: all`` must become one row per entry in ``all_fortificants``,
    and the literal ``all`` must not survive into the fan-out.

    ``all`` leaking through would produce paths like ``results/all/rice/`` that no
    rule knows how to build.
    """
    fortificants = set(get_config()["all_fortificants"])

    assert "all" not in set(expansion["fortificant"]), (
        "the literal fortificant 'all' survived expansion; downstream rules would "
        "build a nonexistent results/all/... path"
    )
    assert set(expansion["fortificant"]) <= fortificants, (
        f"expansion produced fortificants outside all_fortificants: "
        f"{sorted(set(expansion['fortificant']) - fortificants)}"
    )

    for row in declared_grid[declared_grid["fortificant"] == "all"].itertuples():
        produced = set(
            expansion[
                (expansion["location"] == row.location)
                & (expansion["vehicle"] == row.vehicle)
            ]["fortificant"]
        )
        assert produced == fortificants, (
            f"{row.location}/{row.vehicle} is declared 'all' but expanded to "
            f"{sorted(produced)} instead of {sorted(fortificants)}"
        )


def test_explicit_fortificants_are_not_broadened(expansion, declared_grid) -> None:
    """A row naming one fortificant must not pick up the others.

    This is the Ethiopia/salt case: it is folate-only by study design, and giving
    it an iron pathway would silently invent an analysis -- salt is deliberately
    absent from ``0200``'s ``--vehicle`` choices, so the sim could not run it.
    """
    for row in declared_grid[declared_grid["fortificant"] != "all"].itertuples():
        produced = set(
            expansion[
                (expansion["location"] == row.location)
                & (expansion["vehicle"] == row.vehicle)
            ]["fortificant"]
        )
        assert produced == {row.fortificant}, (
            f"{row.location}/{row.vehicle} declares only {row.fortificant!r} but "
            f"expanded to {sorted(produced)}"
        )


def test_custom_intervention_scenarios_replace_the_default(expansion) -> None:
    """A location with custom scenarios gets exactly those and *not* the default.

    Ethiopia's ``intervention_25_nrv``/``intervention_100_nrv`` exist only in the
    notebook models -- ``0200``'s ``components/intervention.py`` recognises only the
    literal ``"intervention"`` -- so emitting a plain ``intervention`` row for
    Ethiopia would schedule an analysis with no implementation behind it.
    """
    custom = get_config()["custom_intervention_scenarios"]

    for location, scenarios in custom.items():
        produced = set(expansion[expansion["location"] == location]["intervention_scenario"])
        assert produced == set(scenarios), (
            f"{location} should get exactly {sorted(scenarios)} but got "
            f"{sorted(produced)}"
        )
        assert "intervention" not in produced or "intervention" in scenarios, (
            f"{location} has custom intervention scenarios but still received the "
            "default 'intervention' as well"
        )

    for location in set(expansion["location"]) - set(custom):
        produced = set(expansion[expansion["location"] == location]["intervention_scenario"])
        assert produced == {"intervention"}, (
            f"{location} has no custom scenarios so it should get exactly "
            f"{{'intervention'}}, but got {sorted(produced)}"
        )


def test_every_declared_row_reaches_the_expansion(expansion, declared_grid) -> None:
    """No ``(location, vehicle)`` pair may be dropped.

    The failure this guards is silent: a lost pair means that analysis is simply
    never built, and no rule fails.
    """
    declared = set(
        map(tuple, declared_grid[["location", "vehicle"]].drop_duplicates().values)
    )
    produced = set(map(tuple, expansion[["location", "vehicle"]].drop_duplicates().values))

    assert (
        declared == produced
    ), f"dropped: {sorted(declared - produced)}; invented: {sorted(produced - declared)}"


def test_expansion_has_no_duplicate_rows(expansion) -> None:
    """Duplicates would make Snakemake declare the same target twice, and would
    double-count anything that aggregates over the fan-out."""
    duplicated = expansion[expansion.duplicated()]
    assert duplicated.empty, f"duplicate rows in the fan-out:\n{duplicated.to_string()}"


@pytest.mark.parametrize(
    "variables",
    [
        ["location", "vehicle"],
        ["location", "vehicle", "fortificant"],
        ["location", "vehicle", "fortificant", "intervention_scenario"],
    ],
)
def test_configured_combos_unpack_in_the_requested_order(variables) -> None:
    """The contract every Snakefile depends on.

    Callers write ``for (location, vehicle) in get_configured_combos(["location",
    "vehicle"])``, so the returned rows must iterate in exactly the requested
    column order. If that order ever came from the frame's own layout instead, the
    loop would bind ``location = "rice"`` and build paths with the levels swapped --
    which produces wrong paths, not an error.

    The three parametrisations are the three call sites in the Snakefiles
    (0100_data_prep/Snakefile:96,104,112 and 5000_analyze_results/Snakefile:119).
    """
    combos = get_configured_combos(variables)
    assert combos, f"no combinations returned for {variables}"

    expansion = get_location_fortificant_vehicle_intervention_scenarios()
    expected = {tuple(row) for row in expansion[variables].drop_duplicates().values}

    unpacked = set()
    for combo in combos:
        values = tuple(combo)
        assert len(values) == len(variables), (
            f"requested {len(variables)} variables but a row unpacks to "
            f"{len(values)}: {values}"
        )
        # Positional order, checked by name: combo[i] must be variables[i]'s value.
        for position, variable in enumerate(variables):
            assert values[position] == combo[variable], (
                f"position {position} of the unpacked row is {values[position]!r} but "
                f"{variable!r} is {combo[variable]!r} -- get_configured_combos no "
                "longer returns columns in the requested order, and every Snakefile "
                "unpacks these positionally"
            )
        unpacked.add(values)

    assert unpacked == expected, (
        f"combos for {variables} do not match the deduplicated expansion; "
        f"missing {sorted(expected - unpacked)}, unexpected {sorted(unpacked - expected)}"
    )


def test_configured_combos_are_deduplicated() -> None:
    """Requesting a subset of columns must collapse the rows that differ only in
    the columns not requested."""
    combos = get_configured_combos(["location", "vehicle"])
    as_tuples = [tuple(combo) for combo in combos]

    assert len(as_tuples) == len(set(as_tuples)), f"duplicates in {as_tuples}"


def test_config_is_found_regardless_of_working_directory(tmp_path, monkeypatch) -> None:
    """``config_utils`` resolves ``0050_config/`` relative to ``__file__``, which
    makes it the one part of the codebase that works from any cwd. Snakemake rules
    ``cd`` into stage directories before running, so that property is load-bearing.
    """
    monkeypatch.chdir(tmp_path)

    assert get_config()["all_fortificants"], "config unreadable from an unrelated cwd"
    assert not get_location_fortificant_vehicle_intervention_scenarios().empty


def test_reported_comparisons_name_scenarios_the_fan_out_produces(expansion) -> None:
    """Cross-check the two config files that have to agree by hand.

    ``location_vehicle_scenario_comparisons.csv`` selects which baseline/intervention
    pairs get reported in the spreadsheet, naming scenarios as free text. Nothing
    else checks those names against the ones the fan-out actually produces, so a
    typo or a renamed scenario yields a comparison that matches no data.
    """
    comparisons = pd.read_csv(CONFIG_DIR / "location_vehicle_scenario_comparisons.csv")

    for row in comparisons.itertuples():
        available = set(
            expansion[
                (expansion["location"] == row.location)
                & (expansion["vehicle"] == row.vehicle)
            ]["intervention_scenario"]
        )
        assert available, (
            f"{row.location}/{row.vehicle} is compared in "
            "location_vehicle_scenario_comparisons.csv but is not in the fan-out at all"
        )

        allowed = available | BASE_SCENARIOS
        for column, scenario in (
            ("baseline", row.baseline),
            ("intervention", row.intervention),
        ):
            assert scenario in allowed, (
                f"{row.location}/{row.vehicle}: {column}={scenario!r} is not a scenario "
                f"this combination produces. Available: {sorted(allowed)}. Either the "
                "name is a typo or 0050_config/config.yaml and "
                "location_vehicle_scenario_comparisons.csv have drifted apart."
            )
