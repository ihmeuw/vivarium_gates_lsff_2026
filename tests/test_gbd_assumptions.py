"""Layer 3: assumptions about GBD that would otherwise fail silently.

Layers 1 and 2 detect *changed output*. These tests detect a changed *input
contract* -- cases where GBD moves a category, sequela, or age boundary
underneath code that hardcodes it. All three of these fail quietly rather than
loudly if left unguarded: they drop rows, shift a denominator, or omit a disease,
without raising anything.

Each check reads the project's assumption from its actual source of truth (the
notebook or constants module that owns it) rather than duplicating the values
here, so the test follows the code if someone edits it.

Requires GBD access, and runs in either generation's environment:

    source .venv_modern/bin/activate && pytest tests/test_gbd_assumptions.py
    source .venv/bin/activate        && pytest tests/test_gbd_assumptions.py

Running in both matters more than it looks. The two rounds disagree about which
sequelae exist, so each environment exercises a different input contract -- and
the ``gbd_mapping`` fixture had to learn the modern ``vivarium.gbd_mapping`` name
before these ran in ``.venv_modern`` at all. Until then two of the three checks
skipped there, silently, which is the failure mode this whole file exists to
prevent.

They skip cleanly wherever no gbd_mapping is available, including .test_venv.
They are not marked ``slow``: the GBD lookups are cached and take seconds, and
``--runslow`` does not exist in the old artifact env anyway, since that flag comes
from the vivarium-testing-utils pytest plugin.
"""

from __future__ import annotations

import importlib
import json
import re

import pytest

from tests.baseline import REPO_ROOT

# Genetic and endocrine anemias present in gbd_mapping but in neither of the
# 0400 notebook's responsiveness buckets, measured against GBD 2021. Recorded so
# that a *new* omission fails while these known ones do not spam every run.
#
# These look like they belong in the non-iron-responsive bucket, and leaving them
# out is not neutral. The notebook builds the iron-responsive group as a
# *residual*: only the non-responsive list is ever pulled, and
# `iron_responsive_distributions` is the total hemoglobin distribution minus the
# non-responsive part. So a sequela in neither list is treated as iron-responsive
# and receives the fortification hemoglobin shift, which overstates the modelled
# benefit rather than shrinking the population.
#
# That is not a rounding error here: combined prevalence of these 26 in Nigeria is
# 0.0182 at its peak (mean 0.0049), against total anemia prevalence around 0.5 --
# so roughly 3-4% of anemia. Whether this is deliberate scoping or an oversight is
# an open question for the anemia model owner; the notebook's own provenance
# comment says the lists were adapted from another repo and "not checked in
# extreme detail".
KNOWN_UNCOVERED_ANEMIA_SEQUELAE = frozenset(
    {
        "controlled_medically_managed_heart_failure_due_to_other_hemoglobinopathies_and_hemolytic_anemias",
        "mild_heart_failure_due_to_other_hemoglobinopathies_and_hemolytic_anemias",
        "moderate_heart_failure_due_to_other_hemoglobinopathies_and_hemolytic_anemias",
        "severe_heart_failure_due_to_other_hemoglobinopathies_and_hemolytic_anemias",
        "other_hemoglobinopathies_and_hemolytic_anemias_residual",
        "g6pd_deficiency_with_mild_anemia",
        "g6pd_deficiency_with_moderate_anemia",
        "g6pd_deficiency_with_severe_anemia",
        "hemoglobin_e_beta_thalassemia_with_mild_anemia",
        "hemoglobin_e_beta_thalassemia_with_moderate_anemia",
        "hemoglobin_e_beta_thalassemia_with_severe_anemia",
        "hemoglobin_h_disease_with_mild_anemia",
        "hemoglobin_h_disease_with_moderate_anemia",
        "hemoglobin_h_disease_with_severe_anemia",
        "mild_anemia_due_to_beta_thalassemia_major",
        "moderate_anemia_due_to_beta_thalassemia_major",
        "severe_anemia_due_to_beta_thalassemia_major",
        "mild_anemia_due_to_hyperthyroidism",
        "moderate_anemia_due_to_hyperthyroidism",
        "severe_anemia_due_to_hyperthyroidism",
        "mild_anemia_due_to_hypothyroidism",
        "moderate_anemia_due_to_hypothyroidism",
        "severe_anemia_due_to_hypothyroidism",
        "mild_anemia_due_to_other_endocrine_metabolic_blood_immune_disorders",
        "moderate_anemia_due_to_other_endocrine_metabolic_blood_immune_disorders",
        "severe_anemia_due_to_other_endocrine_metabolic_blood_immune_disorders",
    }
)

# Anemia sequelae that GBD 2023 *added*, and that the 0400 notebook therefore
# classifies into neither bucket. Kept separate from the GBD-2021 backlog above
# because these are a live consequence of the round change, not inherited scope:
# GBD 2021 exposes 2088 sequelae with no `puerperal_sepsis_with_*_anemia`, GBD 2023
# exposes 2106 with all three.
#
# This is the case the check below was written for -- an added sequela falls into
# the residual and is therefore treated as iron-responsive, receiving a
# fortification benefit it may not be entitled to. Recorded rather than left
# failing so the rest of the suite stays legible, but it is an open decision for
# the anemia model owner, not a settled exclusion. Anemia accompanying puerperal
# sepsis is plausibly inflammatory rather than iron-deficiency, which would put it
# in the non-responsive bucket, but that is a judgement for whoever owns the model.
#
# Magnitude, unlike the 26 above, is negligible: combined prevalence in Nigeria is
# 2.7e-06 at its peak. Puerperal sepsis is a postpartum condition and 0400 models
# the non-pregnant population, so that is unsurprising. Recorded because the
# classification should still be deliberate, not because the numbers move.
UNCLASSIFIED_GBD_2023_ANEMIA_SEQUELAE = frozenset(
    {
        "puerperal_sepsis_with_mild_anemia",
        "puerperal_sepsis_with_moderate_anemia",
        "puerperal_sepsis_with_severe_anemia",
    }
)

# Both buckets of "we know about this one". Separate constants above so the reason
# for each is legible; combined here because the check treats them alike.
RECORDED_UNCOVERED_ANEMIA_SEQUELAE = (
    KNOWN_UNCOVERED_ANEMIA_SEQUELAE | UNCLASSIFIED_GBD_2023_ANEMIA_SEQUELAE
)

# Sequela names containing "anemia" that describe its *absence*.
ABSENCE_MARKERS = ("without_anemia", "with_no_anemia", "no_anemia")

LOW_BIRTH_WEIGHT_GRAMS = 2500

# Birth-weight interval from an LBWSG category description, e.g.
# "... - [40, 42+] wks, [2000, 2500) g". The gestational-age half uses both
# "[a, b)" and "[a, b+]" forms, so only the grams half is matched.
BIRTH_WEIGHT_PATTERN = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*[)\]]\s*g")


# The modern suite moved `gbd_mapping` under the `vivarium` namespace. Both names
# are tried because this file has to run in either generation's environment, and
# skipping on the old name alone silently switched off the two checks below --
# exactly the two guarding the GBD-2023 changes that fail without an error.
GBD_MAPPING_MODULES = ("gbd_mapping", "vivarium.gbd_mapping")


@pytest.fixture(scope="module")
def gbd_mapping():
    for name in GBD_MAPPING_MODULES:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    pytest.skip(f"needs one of {', '.join(GBD_MAPPING_MODULES)}")


def notebook_source(path: str) -> str:
    cells = json.loads((REPO_ROOT / path).read_text())["cells"]
    return "\n".join("".join(cell["source"]) for cell in cells)


def child_sim_data_values_source() -> str:
    """The child sim's data_values.py source, whatever the package is called.

    Read as text rather than imported. The module absolute-imports its own package,
    which in turn imports the Vivarium suite, so importing it would tie this test to
    whichever suite generation is installed -- and the whole point is to run it in
    the artifact environment, which has GBD access. The package has also been
    renamed once already (``vivarium_gates_lsff_by_wealth_quintile_child`` ->
    ``vivarium_gates_lsff_2026_child``), so resolve the name from the filesystem.
    """
    src = REPO_ROOT / "0300_child_sim" / "src"
    candidates = sorted(src.glob("*/constants/data_values.py"))
    assert len(candidates) == 1, (
        f"expected exactly one child-sim constants/data_values.py under {src}, found "
        f"{[str(c.relative_to(src)) for c in candidates]}. A rename probably left the "
        "old directory behind."
    )
    return candidates[0].read_text()


def parse_low_birth_weight_categories(source: str) -> set[str]:
    match = re.search(
        r"LOW_BIRTH_WEIGHT_CATEGORIES\s*(?::[^=]+)?=\s*\[(.*?)\]", source, re.DOTALL
    )
    assert match, (
        "could not find LOW_BIRTH_WEIGHT_CATEGORIES in the child sim's data_values.py "
        "-- if it was renamed or restructured, update this test rather than deleting it"
    )
    return set(re.findall(r'"(cat\d+)"', match.group(1)))


def test_gbd_age_bins_nest_inside_disparity_age_bins() -> None:
    """The wealth-quintile disparity joins assume GBD age bins nest.

    src/lsff_utils/data_processing.py::reindex_series_onto_df_by_age_groups
    matches a GBD age group to a disparity age group with
    ``age_start >= age_start_series and age_end <= age_end_series``, noting
    "Depends on a GBD age group always fitting into a disparity age group". If a
    GBD bin straddles a DHS bin edge it matches nothing and the row is dropped by
    the merge -- no error, just a quietly smaller dataset. Every quintile
    disparity in the project flows through this.
    """
    get_age_bins = pytest.importorskip(
        "vivarium_inputs.utility_data", reason="needs the artifact environment (.venv)"
    ).get_age_bins

    source = notebook_source("0100_data_prep/dhs/common.ipynb")
    match = re.search(r"age_bin_edges\s*=\s*\[([\d,\s]+)\]", source)
    assert match, (
        "could not find age_bin_edges in 0100_data_prep/dhs/common.ipynb -- if it "
        "was renamed, update this test rather than deleting it"
    )
    edges = [int(value) for value in match.group(1).split(",") if value.strip()]

    straddling = [
        (row.age_group_name, row.age_start, row.age_end)
        for row in get_age_bins().itertuples()
        if sum(
            edges[i] <= row.age_start and row.age_end <= edges[i + 1]
            for i in range(len(edges) - 1)
        )
        != 1
    ]
    assert not straddling, (
        f"{len(straddling)} GBD age bins do not nest inside exactly one DHS "
        f"disparity bin {edges}, so the disparity merge will silently drop them:\n"
        + "\n".join(f"    {name}: [{start}, {end})" for name, start, end in straddling)
    )


def test_low_birth_weight_categories_still_mean_low_birth_weight(gbd_mapping) -> None:
    """The hardcoded LBWSG category list must still be exactly the sub-2500g set.

    0300_child_sim hardcodes 30 ``catNN`` strings as "low birth weight". LBWSG
    category numbering is not stable across GBD rounds, so a renumbering would
    leave the names valid but the meaning wrong -- silently reclassifying birth
    weights. Checking the interval in each category's description, rather than
    just that the name exists, is what makes this catch a renumbering.
    """
    listed = parse_low_birth_weight_categories(child_sim_data_values_source())
    assert len(listed) > 20, f"only parsed {len(listed)} categories; check the regex"
    categories = (
        gbd_mapping.risk_factors.low_birth_weight_and_short_gestation.categories.to_dict()
    )

    missing_from_gbd = listed - set(categories)
    assert (
        not missing_from_gbd
    ), f"categories hardcoded in 0300 no longer exist in GBD: {sorted(missing_from_gbd)}"

    upper_bound = {}
    for name, description in categories.items():
        match = BIRTH_WEIGHT_PATTERN.search(description)
        if match:
            upper_bound[name] = float(match.group(2))

    unparsed = listed - set(upper_bound)
    assert not unparsed, (
        "could not read a birth-weight interval from these categories' descriptions, "
        f"so their meaning cannot be verified: {sorted(unparsed)}\n"
        f"  example description: {categories[sorted(unparsed)[0]]!r}"
    )

    too_heavy = {name for name in listed if upper_bound[name] > LOW_BIRTH_WEIGHT_GRAMS}
    assert not too_heavy, (
        f"listed as low birth weight but GBD says the interval extends above "
        f"{LOW_BIRTH_WEIGHT_GRAMS}g -- categories were probably renumbered: "
        + ", ".join(f"{name} ({categories[name]})" for name in sorted(too_heavy))
    )

    should_be_listed = {
        name for name, bound in upper_bound.items() if bound <= LOW_BIRTH_WEIGHT_GRAMS
    } - listed
    assert not should_be_listed, (
        f"GBD has sub-{LOW_BIRTH_WEIGHT_GRAMS}g categories absent from the hardcoded "
        f"list, so those births are not counted as low birth weight: "
        f"{sorted(should_be_listed)}"
    )


def test_anemia_sequela_lists_cover_gbd(gbd_mapping) -> None:
    """The 0400 responsiveness split must still account for every anemia sequela.

    A renamed or removed sequela raises AttributeError in the notebook, which is
    loud. An *added* one is silent, and not neutral: the notebook pulls prevalence
    only for the non-responsive list and builds the iron-responsive group as the
    residual, so anything in neither list is treated as iron-responsive and gets
    the fortification hemoglobin shift. An unclassified non-responsive sequela
    therefore overstates the modelled benefit. This is the check that makes that
    case loud.

    Caveat on what this check can enforce: it compares against sequelae named
    anywhere in the notebook, but only `non_iron_responsive_anemia_sequelae` is
    actually consumed -- `iron_responsive_anemia_sequelae` is referenced solely by
    `len()`. So adding a sequela to the iron-responsive list silences this check
    without changing the model. That is the right default, since the residual
    already treats it as responsive, but it means a green run means "classified",
    not "classified correctly".
    """
    source = notebook_source("0400_non_pregnant_anemia_model/non_pregnant_anemia.ipynb")
    listed = set(re.findall(r"sequelae\.([a-z0-9_]+)", source))
    assert len(listed) > 100, (
        f"only found {len(listed)} sequela references in the notebook; the lists were "
        "probably restructured and this test needs updating"
    )

    available = {name for name in dir(gbd_mapping.sequelae) if not name.startswith("_")}

    stale = listed - available
    assert not stale, (
        f"the notebook names sequelae that no longer exist in gbd_mapping, so it will "
        f"raise AttributeError: {sorted(stale)}"
    )

    present_anemia = {
        name
        for name in available
        if "anemia" in name and not any(marker in name for marker in ABSENCE_MARKERS)
    }
    uncovered = present_anemia - listed

    newly_uncovered = uncovered - RECORDED_UNCOVERED_ANEMIA_SEQUELAE
    assert not newly_uncovered, (
        f"{len(newly_uncovered)} anemia sequelae are in GBD but in neither the "
        f"iron-responsive nor the non-responsive list, so the model's residual treats "
        f"them as iron-responsive and gives them a fortification benefit: "
        f"{sorted(newly_uncovered)}\n"
        "Classify them, or record them with a reason -- in "
        "UNCLASSIFIED_GBD_2023_ANEMIA_SEQUELAE if the round added them, otherwise in "
        "KNOWN_UNCOVERED_ANEMIA_SEQUELAE."
    )

    # Only recorded sequelae that this GBD round actually exposes can be judged, so
    # intersect with present_anemia first. Without that, running against GBD 2021 --
    # which has no `puerperal_sepsis_with_*_anemia` at all -- would demand their
    # removal, and running against 2023 would demand they be put back. The cost is
    # that a sequela GBD drops entirely lingers in the constant rather than
    # prompting cleanup; that is the cheaper of the two failure modes.
    now_covered = RECORDED_UNCOVERED_ANEMIA_SEQUELAE & present_anemia & listed
    assert not now_covered, (
        "these were recorded as uncovered but the notebook now classifies them; "
        f"remove them from the recorded sets: {sorted(now_covered)}"
    )
