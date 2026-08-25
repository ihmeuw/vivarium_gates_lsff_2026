"""Unit tests for ``lsff_utils.results``, the stage-5000 aggregation helpers.

Three functions, all load-bearing for the published numbers and none previously
tested.

``aggregate_by_scenario`` / ``aggregate_by_cause_and_scenario`` sum within
``(scenario, [entity,] input_draw, wealth_quintile)`` and then take the mean over
draws. That second step is why the result CSVs carry point estimates and no
uncertainty columns -- the intervals are collapsed before anything is written. The
tests below pin the sum-then-mean order, because sum-then-mean and mean-then-sum
differ whenever the number of rows per draw is not constant, and nothing else in
the repo would notice the difference.

``expand_to_all_scenarios`` is the zero-fill mechanism behind the India/rice
schema-template coupling: ``dalys_by_scenario.ipynb`` and
``cases_by_scenario.ipynb`` read the India/rice file as a schema donor and expand a
zeroed copy of it across scenarios whenever a fortificant/location combination has
no output of its own. So its behaviour decides the shape of every zero-filled
combination, including all of Ethiopia's iron rows.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lsff_utils.results import (
    aggregate_by_cause_and_scenario,
    aggregate_by_scenario,
    expand_to_all_scenarios,
)


def long_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_aggregate_by_scenario_sums_within_a_draw_then_averages_over_draws() -> None:
    """The order matters and is not recoverable from the output.

    Here each draw has a different number of rows: draw 0 has two rows summing to
    10, draw 1 has one row of 20. Sum-then-mean gives (10 + 20) / 2 = 15.
    Mean-then-sum would give (5 + 20) = 25. Only the first is correct for counts.
    """
    frame = long_frame(
        [
            {"scenario": "baseline", "input_draw": 0, "wealth_quintile": 1, "value": 4.0},
            {"scenario": "baseline", "input_draw": 0, "wealth_quintile": 1, "value": 6.0},
            {"scenario": "baseline", "input_draw": 1, "wealth_quintile": 1, "value": 20.0},
        ]
    )

    result = aggregate_by_scenario(frame)

    assert result.loc[("baseline", 1)] == pytest.approx(15.0), (
        f"expected sum-within-draw then mean-over-draws = 15.0, got "
        f"{result.loc[('baseline', 1)]}. 25.0 would mean the mean is being taken "
        "before the sum."
    )


def test_aggregate_by_scenario_keeps_scenarios_and_quintiles_separate() -> None:
    """Quintile is the study's reporting stratification, so it must never be
    collapsed; scenario separation is what makes a comparison possible at all."""
    frame = long_frame(
        [
            {"scenario": s, "input_draw": 0, "wealth_quintile": q, "value": float(v)}
            for v, (s, q) in enumerate(
                [(s, q) for s in ("baseline", "intervention") for q in (1, 5)]
            )
        ]
    )

    result = aggregate_by_scenario(frame)

    assert set(result.index) == {
        ("baseline", 1),
        ("baseline", 5),
        ("intervention", 1),
        ("intervention", 5),
    }
    assert list(result.index.names) == ["scenario", "wealth_quintile"]


def test_aggregate_by_cause_and_scenario_drops_all_causes() -> None:
    """``all_causes`` is an aggregate row present alongside its own components, so
    including it would double the totals."""
    frame = long_frame(
        [
            {
                "scenario": "baseline",
                "entity": entity,
                "input_draw": 0,
                "wealth_quintile": 1,
                "value": 1.0,
            }
            for entity in ("all_causes", "maternal_disorders", "diarrheal_diseases")
        ]
    )

    result = aggregate_by_cause_and_scenario(frame)

    entities = set(result.index.get_level_values("entity"))
    assert "all_causes" not in entities, "all_causes survived, so totals are double counted"
    assert entities == {"maternal_disorders", "diarrheal_diseases"}


def test_aggregate_by_cause_and_scenario_averages_over_draws_per_entity() -> None:
    frame = long_frame(
        [
            {
                "scenario": "baseline",
                "entity": "maternal_disorders",
                "input_draw": draw,
                "wealth_quintile": 1,
                "value": value,
            }
            for draw, value in [(0, 10.0), (1, 30.0)]
        ]
    )

    result = aggregate_by_cause_and_scenario(frame)

    assert result.loc[("baseline", "maternal_disorders", 1)] == pytest.approx(20.0)


def test_aggregate_collapses_draws_so_no_uncertainty_survives() -> None:
    """Pins the reason the result CSVs have no interval columns.

    Recorded as a test rather than a comment because it is a recurring question:
    two draws that differ widely produce a single number with no spread attached,
    so any request to report uncertainty needs new machinery rather than a new
    column.
    """
    frame = long_frame(
        [
            {"scenario": "baseline", "input_draw": draw, "wealth_quintile": 1, "value": value}
            for draw, value in [(0, 1.0), (1, 99.0)]
        ]
    )

    result = aggregate_by_scenario(frame)

    assert isinstance(result, pd.Series)
    assert result.loc[("baseline", 1)] == pytest.approx(50.0)
    assert "input_draw" not in (result.index.names or [])


def test_expand_to_all_scenarios_replicates_a_single_scenario() -> None:
    """One copy of the input per requested scenario, with everything else intact."""
    frame = long_frame(
        [
            {"scenario": "baseline", "wealth_quintile": q, "value": 0.0}
            for q in (1, 2, 3, 4, 5)
        ]
    )
    scenarios = ["zero", "baseline", "intervention"]

    result = expand_to_all_scenarios(frame, scenarios)

    assert set(result["scenario"]) == set(scenarios)
    assert len(result) == len(frame) * len(scenarios)
    for scenario in scenarios:
        block = result[result["scenario"] == scenario]
        assert sorted(block["wealth_quintile"]) == [
            1,
            2,
            3,
            4,
            5,
        ], f"{scenario} lost quintiles: {sorted(block['wealth_quintile'])}"
        assert (block["value"] == 0.0).all()


def test_expand_to_all_scenarios_uses_one_scenario_as_the_template() -> None:
    """When the donor frame already holds several scenarios, only the first row's
    scenario is kept before replicating -- otherwise the schema donor's own
    scenarios would multiply with the requested ones.

    The India/rice files used as donors do carry all three scenarios, so this branch
    is the one that actually runs in the pipeline.
    """
    frame = long_frame(
        [
            {"scenario": "baseline", "wealth_quintile": 1, "value": 7.0},
            {"scenario": "baseline", "wealth_quintile": 2, "value": 8.0},
            {"scenario": "intervention", "wealth_quintile": 1, "value": 100.0},
            {"scenario": "intervention", "wealth_quintile": 2, "value": 200.0},
        ]
    )

    result = expand_to_all_scenarios(frame, ["zero", "baseline"])

    assert len(result) == 4, f"expected 2 template rows x 2 scenarios, got {len(result)}"
    assert set(result["scenario"]) == {"zero", "baseline"}
    # The template is the *first* scenario in the frame, so the intervention values
    # must not appear anywhere in the output.
    assert 100.0 not in set(result["value"]), (
        "values from a non-template scenario leaked into the expansion; the donor's "
        "own scenarios are being crossed with the requested ones"
    )
    assert sorted(result["value"]) == [7.0, 7.0, 8.0, 8.0]


def test_expand_to_all_scenarios_preserves_a_zeroed_schema() -> None:
    """The actual pipeline use: a zeroed donor expanded across scenarios must keep
    every column and every stratum, since the whole point is to supply a
    schema-compatible block of zeros for a combination with no model output."""
    donor = long_frame(
        [
            {
                "scenario": "baseline",
                "entity": entity,
                "wealth_quintile": q,
                "measure": "dalys",
                "value": 123.0,
            }
            for entity in ("maternal_disorders", "lbwsg")
            for q in (1, 2)
        ]
    ).assign(value=0.0)

    result = expand_to_all_scenarios(donor, ["zero", "baseline", "intervention"])

    assert list(result.columns) == list(donor.columns), "column layout changed"
    assert (result["value"] == 0.0).all()
    assert len(result) == 12
    for scenario in ("zero", "baseline", "intervention"):
        block = result[result["scenario"] == scenario]
        assert set(zip(block["entity"], block["wealth_quintile"])) == {
            ("maternal_disorders", 1),
            ("maternal_disorders", 2),
            ("lbwsg", 1),
            ("lbwsg", 2),
        }
