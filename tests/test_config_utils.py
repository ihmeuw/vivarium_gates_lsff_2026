"""Tests for per-(location, vehicle) intervention scenarios in ``config_utils``.

``custom_intervention_scenarios`` is keyed by location *and* vehicle because a
location can mix vehicles with different scenario sets: nigeria's rice and
bouillon programs use the single default ``intervention`` scenario, while its
folate-only salt program has 25% and 100% NRV dose scenarios. Most tests here
run against a scratch config directory so they do not depend on what the
repository's config currently lists; the last group checks the committed config.
"""

import importlib.util
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from lsff_utils import config_utils

REPO_ROOT = Path(__file__).resolve().parent.parent

COMBOS_CSV = """\
location,fortificant,vehicle
nigeria,all,rice
nigeria,folate,salt
ethiopia,folate,salt
"""

CONFIG_YAML = """\
all_fortificants: ["folate", "iron"]
custom_intervention_scenarios:
  nigeria:
    salt:
      - intervention_25_nrv
      - intervention_100_nrv
  ethiopia:
    salt:
      - intervention_45_ppm
"""


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point ``config_utils`` at a scratch config directory, and return a writer for it."""
    monkeypatch.setattr(config_utils, "CONFIG_DIR", tmp_path)

    def write(config_yaml=CONFIG_YAML, combos_csv=COMBOS_CSV):
        (tmp_path / "config.yaml").write_text(textwrap.dedent(config_yaml))
        (tmp_path / "location_fortificant_vehicles.csv").write_text(combos_csv)

    write()
    return write


def _scenario_table():
    df = config_utils.get_location_fortificant_vehicle_intervention_scenarios()
    return set(
        df[["location", "fortificant", "vehicle", "intervention_scenario"]].itertuples(
            index=False, name=None
        )
    )


# ---------------------------------------------------------------------------
# get_intervention_scenarios
# ---------------------------------------------------------------------------


def test_listed_pair_gets_its_custom_scenarios(config_dir) -> None:
    assert config_utils.get_intervention_scenarios("nigeria", "salt") == [
        "intervention_25_nrv",
        "intervention_100_nrv",
    ]


def test_other_vehicle_in_same_location_keeps_default(config_dir) -> None:
    """The point of the vehicle key: nigeria/salt's scenarios must not leak onto nigeria/rice."""
    assert config_utils.get_intervention_scenarios("nigeria", "rice") == ["intervention"]


def test_unlisted_location_gets_default(config_dir) -> None:
    assert config_utils.get_intervention_scenarios("india", "rice") == ["intervention"]


def test_missing_block_means_everything_is_default(config_dir) -> None:
    config_dir(config_yaml='all_fortificants: ["folate", "iron"]\n')
    assert config_utils.get_intervention_scenarios("nigeria", "salt") == ["intervention"]


def test_explicit_config_is_used_instead_of_file(config_dir) -> None:
    config = {"custom_intervention_scenarios": {"india": {"rice": ["pds_80"]}}}
    assert config_utils.get_intervention_scenarios("india", "rice", config) == ["pds_80"]
    # ...and the file's entries are not consulted.
    assert config_utils.get_intervention_scenarios("nigeria", "salt", config) == [
        "intervention"
    ]


def test_returned_list_is_a_copy(config_dir) -> None:
    """Callers append to these lists; that must not change the default for everyone else."""
    config_utils.get_intervention_scenarios("india", "rice").append("oops")
    assert config_utils.get_intervention_scenarios("india", "rice") == ["intervention"]


@pytest.mark.parametrize(
    "block, match",
    [
        # The old location-level layout is rejected rather than misread as
        # vehicles named after scenarios.
        ({"ethiopia": ["intervention_25_nrv"]}, "must map vehicle"),
        ({"ethiopia": {"salt": []}}, "non-empty list"),
        ({"ethiopia": {"salt": "intervention_25_nrv"}}, "non-empty list"),
    ],
)
def test_malformed_block_raises(config_dir, block, match) -> None:
    config = {"custom_intervention_scenarios": block}
    with pytest.raises(ValueError, match=match):
        config_utils.get_intervention_scenarios("ethiopia", "salt", config)


# ---------------------------------------------------------------------------
# get_location_fortificant_vehicle_intervention_scenarios
# ---------------------------------------------------------------------------


def test_scenarios_expand_per_location_vehicle(config_dir) -> None:
    assert _scenario_table() == {
        # "all" expands to both fortificants, each with the default scenario
        ("nigeria", "folate", "rice", "intervention"),
        ("nigeria", "iron", "rice", "intervention"),
        # nigeria/salt gets its own scenarios, and not the default
        ("nigeria", "folate", "salt", "intervention_25_nrv"),
        ("nigeria", "folate", "salt", "intervention_100_nrv"),
        ("ethiopia", "folate", "salt", "intervention_45_ppm"),
    }


def test_no_duplicate_rows(config_dir) -> None:
    df = config_utils.get_location_fortificant_vehicle_intervention_scenarios()
    assert not df.duplicated().any()
    assert df.index.is_unique


def test_custom_entry_for_unconfigured_pair_raises(config_dir) -> None:
    """A typo'd location or vehicle would otherwise silently fall back to the default."""
    # Appended under custom_intervention_scenarios, alongside the real nigeria entry.
    config_dir(config_yaml=CONFIG_YAML + "  nigera:\n    salt: [intervention_25_nrv]\n")
    with pytest.raises(ValueError, match="nigera"):
        config_utils.get_location_fortificant_vehicle_intervention_scenarios()


def test_configured_combos_follow_scenarios(config_dir) -> None:
    combos = config_utils.get_configured_combos(
        ["location", "vehicle", "intervention_scenario"]
    )
    assert sorted(tuple(c) for c in combos) == sorted(
        [
            ("nigeria", "rice", "intervention"),
            ("nigeria", "salt", "intervention_25_nrv"),
            ("nigeria", "salt", "intervention_100_nrv"),
            ("ethiopia", "salt", "intervention_45_ppm"),
        ]
    )


# ---------------------------------------------------------------------------
# The committed config
# ---------------------------------------------------------------------------


def _load_config_utils_from_checkout():
    """Load ``config_utils`` from this checkout so it reads this checkout's ``0050_config``.

    ``CONFIG_DIR`` is derived from ``__file__``; under a non-editable install
    (as in CI) it would point into site-packages. See ``test_paths.py``.
    """
    source = REPO_ROOT / "src" / "lsff_utils" / "config_utils.py"
    spec = importlib.util.spec_from_file_location("_lsff_config_utils_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_config_loads_and_is_consistent() -> None:
    """The committed config parses, and every custom entry names a configured pair."""
    checkout_config_utils = _load_config_utils_from_checkout()
    df = checkout_config_utils.get_location_fortificant_vehicle_intervention_scenarios()
    assert not df.duplicated().any()
    for location, vehicle in (
        df[["location", "vehicle"]].drop_duplicates().itertuples(index=False)
    ):
        scenarios = set(
            df[(df.location == location) & (df.vehicle == vehicle)].intervention_scenario
        )
        assert scenarios == set(
            checkout_config_utils.get_intervention_scenarios(location, vehicle)
        )


def test_scenario_comparisons_reference_configured_scenarios() -> None:
    """Every row of location_vehicle_scenario_comparisons.csv must name scenarios that exist.

    The results spreadsheet and plots look these scenarios up by name, so a
    comparison naming an unconfigured scenario fails only at the end of a run.
    """
    checkout_config_utils = _load_config_utils_from_checkout()
    comparisons = pd.read_csv(
        checkout_config_utils.CONFIG_DIR / "location_vehicle_scenario_comparisons.csv"
    )
    for row in comparisons.itertuples(index=False):
        available = {"zero", "baseline"} | set(
            checkout_config_utils.get_intervention_scenarios(row.location, row.vehicle)
        )
        assert {row.baseline, row.intervention} <= available, row
