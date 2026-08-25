"""Layer 4, extended to ``0300_child_sim``: effects that must actually be applied.

Needs **no baseline**, which is the whole point -- like
``test_simulation_plausibility.py`` it asserts from first principles, so it works on
a migration branch whose output is legitimately expected to differ.

Why this exists
---------------
It was written after the fuzzy extension in ``test_child_stochastic_results.py``
flagged 32 of 60 child ratios, and localising that turned up a real regression: in
the GBD-2023 child output on disk, ``low_weight_births / live_births`` is
**byte-identical across baseline, intervention and zero** (0.11318 for all three in
nigeria/bouillon; 0.22545 in india/rice), where GBD 2021 showed the intervention
reducing it by 0.0041. The wealth gradient is gone too: Nigeria's spread across
quintiles was 1.602x under GBD 2021 and is 1.021x now, which is exactly the spread
of ``0200``'s *unadjusted* birth weights.

Both symptoms have one cause, and **it is already fixed in code -- only the output on
disk is stale.** ``components/maternal_characteristics.py`` reaches the child sim's
birth weight from two components: ``MaternalIronConsumptionFromFortification``, the
intervention's *only* channel into child outcomes, and ``WealthQuintile``, which
applies the DHS birth-weight disparity. Modern ``LBWSGRisk`` no longer exposes one
birth-exposure pipeline per axis -- it registers a single *attribute* pipeline named
for the risk (``low_birth_weight_and_short_gestation.birth_exposure``) whose value is a
frame with one column per axis -- so a modifier must target that name, shift one column,
and be registered with ``register_attribute_modifier``. Pre-fix, both components
registered a *value* modifier against ``birth_weight.birth_exposure``, a pipeline that
no longer exists.

``c1e4c28`` on ``origin/albrja/mic-7325/updates-pt2`` migrates them correctly, and was
committed **2026-08-05 14:44**. The child output on disk was written **09:26-09:58 the
same day**, about five hours earlier, so it predates its own fix -- as does everything
stage 5000 derived from it.

Consequence at the published level: nigeria/bouillon neonatal deaths averted go from
**2,999 under GBD 2021 to exactly 0.00**. Every one of the five existing layers was
blind to it -- layer 1 classifies ``neonatal_deaths`` as stochastic so does not compare
it exactly (and a difference of exactly zero is not noise), layer 2 covered no child
observer, layer 4 covered only ``0200``, and the artifact is fine because the fault was
in the wiring rather than the data.

**These tests are expected to FAIL until the child sim is rerun on pt2 at ``c1e4c28``
or later.** The action they call for is a rerun, not a code change. They are not marked
xfail: the numbers stage 5000 consumed really are wrong, and an xfail would make that
look accepted. That rerun will also be the first verification ``c1e4c28`` has had --
nothing on disk exercises it yet.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.reference_proportions import SIMULATED, child_sim_output_path, sim_output_path

# The intervention's effect on child birth weight is small but far outside Monte
# Carlo noise: at ~60-90k live births per quintile the standard error on a ~0.11-0.22
# proportion is ~0.0016, and the GBD-2021 effect was 0.0041 overall. So "any
# difference at all" is the right test -- a *zero* difference means the modifier is
# not wired up, not that the effect is small.
#
# The gradient threshold is deliberately far below both measured values (1.602x in
# nigeria/bouillon, 1.135x in india/rice under GBD 2021) because its job is to catch
# "no gradient applied", not to pin the gradient's size.
MINIMUM_QUINTILE_SPREAD = 1.05

SCENARIO_COLUMN = "maternal_scenario"


def load_child(location: str, vehicle: str, measure: str) -> pd.DataFrame | None:
    path = child_sim_output_path(location, vehicle, measure)
    return pd.read_parquet(path) if path.exists() else None


@pytest.fixture(params=SIMULATED, ids=lambda pair: f"{pair[0]}-{pair[1]}", scope="module")
def combination(request) -> tuple[str, str]:
    return request.param


@pytest.fixture(scope="module")
def low_birth_weight(combination) -> pd.DataFrame:
    """Low-weight births and live births for one combination, as plain frames."""
    location, vehicle = combination
    live = load_child(location, vehicle, "live_births")
    low = load_child(location, vehicle, "low_weight_births")
    if live is None or low is None:
        pytest.skip(
            f"no child output for {location}/{vehicle} -- run the 0300 simulation first"
        )
    return pd.DataFrame(
        {
            "live": _totals(live, [SCENARIO_COLUMN, "wealth_quintile"]),
            "low": _totals(low, [SCENARIO_COLUMN, "wealth_quintile"]),
        }
    ).reset_index()


@pytest.fixture(scope="module")
def maternal_iron_by_scenario(combination) -> pd.Series | None:
    """Mean maternal iron from fortification per scenario, off the birth line list.

    The precondition for expecting any child birth-weight effect at all. Read from
    the data rather than hardcoded, because whether the intervention changes *iron*
    is combination-specific: india/rice's intervention raises folate, so its iron
    intake is legitimately identical between baseline and intervention, and demanding
    a birth-weight difference there would be asserting something false.
    """
    location, vehicle = combination
    path = sim_output_path(location, vehicle, "births")
    if not path.exists():
        return None
    births = pd.read_parquet(path)
    return births.groupby(births["scenario"].astype(str), observed=True)[
        "iron_consumption_from_fortification_mcg"
    ].mean()


def _totals(frame: pd.DataFrame, group: list[str]) -> pd.Series:
    return frame.groupby([frame[column].astype(str) for column in group], observed=True)[
        "value"
    ].sum()


def test_low_weight_births_never_exceed_live_births(low_birth_weight) -> None:
    """Basic coherence between two observers of the same event."""
    offending = low_birth_weight[low_birth_weight["low"] > low_birth_weight["live"]]

    assert offending.empty, (
        f"low_weight_births exceeds live_births in {len(offending)} group(s):\n"
        f"{offending.to_string()}"
    )
    assert (low_birth_weight["live"] > 0).all(), (
        "a scenario x quintile cell has no live births at all, so that stratum "
        "contributes nothing to any child outcome:\n"
        f"{low_birth_weight[low_birth_weight['live'] <= 0].to_string()}"
    )


def test_intervention_changes_child_birth_weight_outcomes(
    low_birth_weight, maternal_iron_by_scenario
) -> None:
    """The intervention must reach the child simulation at all.

    ``maternal_iron_consumption_from_fortification_mcg`` on the birth line list is the
    only channel by which fortification affects child outcomes, via a
    ``birth_weight.birth_exposure`` value modifier. If that modifier is not registered,
    every scenario produces identical births and the child sim's contribution to
    DALYs averted is exactly zero -- a well-formed, plausible-looking null result.

    Only applies where the intervention actually raises maternal *iron*; see the
    ``maternal_iron_by_scenario`` fixture.
    """
    shares = (
        low_birth_weight.groupby(SCENARIO_COLUMN)[["low", "live"]]
        .sum()
        .assign(share=lambda frame: frame["low"] / frame["live"])["share"]
    )
    if "baseline" not in shares or "intervention" not in shares:
        pytest.skip(f"need baseline and intervention scenarios, found {list(shares.index)}")

    if maternal_iron_by_scenario is None:
        pytest.skip("no births.parquet, so the iron precondition cannot be established")
    iron_baseline = maternal_iron_by_scenario.get("baseline")
    iron_intervention = maternal_iron_by_scenario.get("intervention")
    if iron_baseline is None or iron_intervention is None:
        pytest.skip("births.parquet lacks baseline/intervention scenarios")
    if iron_intervention == iron_baseline:
        pytest.skip(
            "the intervention does not change maternal iron intake for this "
            f"combination (both {iron_baseline:.1f} mcg), so no child birth-weight "
            "effect is expected -- india/rice's intervention raises folate, not iron"
        )

    difference = shares["baseline"] - shares["intervention"]

    assert difference != 0.0, (
        "the intervention produces EXACTLY the same low-birth-weight share as "
        f"baseline ({shares['baseline']:.6f}), so fortification has no effect on child "
        "outcomes and child DALYs averted are identically zero.\n"
        "  This is not a small effect -- it is no effect, so the birth-exposure "
        "modifier is not reaching\n"
        "  the pipeline at all. Most likely this output predates the fix rather than "
        "being a new bug:\n"
        "  MaternalIronConsumptionFromFortification must use "
        "builder.value.register_attribute_modifier\n"
        "  on 'low_birth_weight_and_short_gestation.birth_exposure' with "
        "`required_resources=`. Modern\n"
        "  LBWSGRisk registers one attribute pipeline named for the risk, not one value "
        "pipeline per axis,\n"
        "  so the old 'birth_weight.birth_exposure' target no longer exists. Fixed by "
        "c1e4c28 on\n"
        "  origin/albrja/mic-7325/updates-pt2 -- check whether this output was produced "
        "before it, and\n"
        "  rerun 0300_child_sim if so.\n"
        "  For reference, GBD 2021 gave baseline - intervention = +0.0041 here."
    )
    assert difference > 0.0, (
        f"the intervention *increases* the low-birth-weight share by {-difference:.6f}. "
        "Iron fortification should raise birth weight, so this is a sign error in the "
        "birth-weight modifier."
    )


def test_wealth_gradient_in_low_birth_weight_is_present(low_birth_weight) -> None:
    """Low birth weight must vary by wealth quintile.

    The disparity is applied inside ``0300`` -- ``0200``'s birth weights carry no
    gradient (measured spread 1.01-1.02x in both vintages) -- so a flat child result
    means ``WealthQuintile``'s birth-weight modifier is not being applied. Wealth
    quintile is the stratification the whole study exists to report, and a flat
    result looks entirely well-formed.
    """
    baseline = low_birth_weight[low_birth_weight[SCENARIO_COLUMN] == "baseline"]
    if baseline.empty:
        pytest.skip("no baseline scenario in this output")

    share = (baseline["low"] / baseline["live"]).rename("share")
    by_quintile = dict(zip(baseline["wealth_quintile"], share))
    spread = max(by_quintile.values()) / min(by_quintile.values())

    assert spread >= MINIMUM_QUINTILE_SPREAD, (
        f"low-birth-weight share is essentially flat across wealth quintiles "
        f"(spread {spread:.3f}x, below {MINIMUM_QUINTILE_SPREAD}x): "
        f"{ {q: f'{s:.4f}' for q, s in sorted(by_quintile.items())} }.\n"
        "  0200's birth weights carry no wealth gradient by design, so this gradient "
        "comes entirely from\n"
        "  WealthQuintile's birth-exposure modifier in "
        "components/maternal_characteristics.py.\n"
        "  A spread this close to 1.0 means that modifier is not reaching the "
        "pipeline -- most likely this\n"
        "  output predates c1e4c28 on origin/albrja/mic-7325/updates-pt2, which "
        "retargets it to\n"
        "  'low_birth_weight_and_short_gestation.birth_exposure' via "
        "register_attribute_modifier. See the\n"
        "  module docstring. GBD 2021 measured 1.602x (nigeria/bouillon) and 1.135x "
        "(india/rice).\n"
        "  The gradient should put the poorest quintile at the HIGHEST low-birth-weight "
        "share."
    )

    poorest = by_quintile.get("1")
    richest = by_quintile.get("5")
    if poorest is not None and richest is not None:
        assert poorest > richest, (
            f"the poorest quintile has a lower low-birth-weight share ({poorest:.4f}) "
            f"than the richest ({richest:.4f}), which inverts the expected disparity"
        )
