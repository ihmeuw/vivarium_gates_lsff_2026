import pathlib

import pandas as pd
import yaml

# The repository's config directory. Module-level so tests can point it at a
# scratch directory.
CONFIG_DIR = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()


def get_config():
    with open(CONFIG_DIR / "config.yaml") as stream:
        config = yaml.safe_load(stream)

    return config


DEFAULT_INTERVENTION_SCENARIOS = ["intervention"]


def _custom_intervention_scenarios(config):
    """The `custom_intervention_scenarios` block, validated as location -> vehicle -> list.

    The block is keyed by (location, vehicle) because a location can carry
    vehicles with different scenario sets: nigeria's rice and bouillon programs
    use the default single intervention, while its folate-only salt program has
    25% and 100% NRV dose scenarios. A location-level list would apply the
    custom scenarios to every vehicle in that location.
    """
    custom = config.get("custom_intervention_scenarios") or {}
    for location, by_vehicle in custom.items():
        if not isinstance(by_vehicle, dict):
            raise ValueError(
                f"custom_intervention_scenarios[{location!r}] must map vehicle -> list of "
                f"scenarios (e.g. `{location}: {{salt: [intervention_25_nrv]}}`), got "
                f"{type(by_vehicle).__name__}. Scenarios are configured per "
                "(location, vehicle), not per location."
            )
        for vehicle, scenarios in by_vehicle.items():
            if isinstance(scenarios, str) or not scenarios:
                raise ValueError(
                    f"custom_intervention_scenarios[{location!r}][{vehicle!r}] must be a "
                    "non-empty list of scenario names."
                )
    return custom


def get_intervention_scenarios(location, vehicle, config=None):
    """Intervention scenarios for one (location, vehicle) pair.

    Pairs not listed under `custom_intervention_scenarios` get the single
    default "intervention" scenario. Pass `config` to use an already-loaded
    config (e.g. Snakemake's); otherwise config.yaml is read.
    """
    if config is None:
        config = get_config()
    custom = _custom_intervention_scenarios(config)
    return list(custom.get(location, {}).get(vehicle, DEFAULT_INTERVENTION_SCENARIOS))


# How far through the pipeline each arm (a row of location_fortificant_vehicles.csv)
# runs, in pipeline order. Each stage includes the ones before it.
#
# - none: listed but not run. build_extraction.py treats it as an arm the model
#   doesn't run (its GF and literature values are still compared, but nothing is
#   checked), and Snakemake builds nothing for it.
# - data_prep: the extraction build checks it, and 0100_data_prep builds its
#   inputs through effective coverage. No simulations, models or results.
# - results: the whole pipeline, through the results spreadsheet and plots.
#
# A blank value, or a file without the column, means "results".
RUN_THROUGH_STAGES = ["none", "data_prep", "results"]
DEFAULT_RUN_THROUGH = "results"


def _check_stage(stage):
    if stage not in RUN_THROUGH_STAGES:
        raise ValueError(f"unknown stage {stage!r}; expected one of {RUN_THROUGH_STAGES}")


def reaches_stage(run_through, stage):
    """Whether an arm whose run_through is `run_through` is run at `stage`."""
    _check_stage(run_through)
    _check_stage(stage)
    return RUN_THROUGH_STAGES.index(run_through) >= RUN_THROUGH_STAGES.index(stage)


def get_location_fortificant_vehicles():
    """location_fortificant_vehicles.csv, validated, with `run_through` filled in.

    Every row of a (location, vehicle) pair must share one run_through value,
    because the pipeline runs each pair as a unit from coverage onwards.
    """
    df = pd.read_csv(str(CONFIG_DIR / "location_fortificant_vehicles.csv"), dtype=str).fillna(
        ""
    )
    for column in ["location", "fortificant", "vehicle"]:
        df[column] = df[column].str.strip()
    if "run_through" not in df.columns:
        df["run_through"] = ""
    df["run_through"] = (
        df.run_through.str.strip().str.lower().replace("", DEFAULT_RUN_THROUGH)
    )

    unknown = sorted(set(df.run_through) - set(RUN_THROUGH_STAGES))
    if unknown:
        raise ValueError(
            f"location_fortificant_vehicles.csv: unknown run_through value(s) {unknown}; "
            f"expected one of {RUN_THROUGH_STAGES} (or blank for {DEFAULT_RUN_THROUGH!r})"
        )
    mixed = df.groupby(["location", "vehicle"]).run_through.nunique()
    mixed = sorted(mixed[mixed > 1].index)
    if mixed:
        raise ValueError(
            "location_fortificant_vehicles.csv: every row of a (location, vehicle) pair must "
            f"have the same run_through; these differ: {mixed}"
        )
    return df


def get_location_fortificant_vehicle_intervention_scenarios(stage=None):
    """One row per (location, fortificant, vehicle, intervention_scenario).

    With `stage`, only the arms that run at that stage (see RUN_THROUGH_STAGES);
    without it, every listed arm, whatever its run_through. Per-arm questions
    (which scenarios or pathways an arm has) use every listed arm; deciding
    what to build uses a stage.
    """
    config = get_config()

    location_fortificant_vehicles = get_location_fortificant_vehicles()

    # Expand "all" fortificants
    location_fortificant_vehicles = pd.concat(
        [
            location_fortificant_vehicles[location_fortificant_vehicles.fortificant != "all"],
            *[
                location_fortificant_vehicles[
                    location_fortificant_vehicles.fortificant == "all"
                ].assign(fortificant=fortificant)
                for fortificant in config["all_fortificants"]
            ],
        ]
    )

    assert location_fortificant_vehicles["fortificant"].isin(config["all_fortificants"]).all()

    # Catch typos: a custom entry for a pair that isn't configured would
    # otherwise be silently ignored, and that pair would fall back to the
    # default scenario.
    configured_pairs = set(
        zip(location_fortificant_vehicles.location, location_fortificant_vehicles.vehicle)
    )
    unknown_pairs = [
        (location, vehicle)
        for location, by_vehicle in _custom_intervention_scenarios(config).items()
        for vehicle in by_vehicle
        if (location, vehicle) not in configured_pairs
    ]
    if unknown_pairs:
        raise ValueError(
            "custom_intervention_scenarios lists (location, vehicle) pairs that are not in "
            f"location_fortificant_vehicles.csv: {unknown_pairs}"
        )

    location_fortificant_vehicle_intervention_scenarios = (
        location_fortificant_vehicles.assign(
            intervention_scenario=[
                get_intervention_scenarios(location, vehicle, config)
                for location, vehicle in zip(
                    location_fortificant_vehicles.location,
                    location_fortificant_vehicles.vehicle,
                )
            ]
        )
        .explode("intervention_scenario")
        .reset_index(drop=True)
    )

    if stage is not None:
        _check_stage(stage)
        location_fortificant_vehicle_intervention_scenarios = location_fortificant_vehicle_intervention_scenarios[
            [
                reaches_stage(run_through, stage)
                for run_through in location_fortificant_vehicle_intervention_scenarios.run_through
            ]
        ].reset_index(
            drop=True
        )

    return location_fortificant_vehicle_intervention_scenarios


# The one arm modelled through government rice (PDS, school and anganwadi meals). Its
# partial-coverage amounts come from HCES, and prep_extracted combines its baseline coverage
# and fortifiability with the HCES government-rice shares. This is specific to India rice's
# programme, not to HCES consumption in general (config.yaml's hces_consumption).
GOVERNMENT_RICE = ("india", "rice")


def get_hces_consumption_pairs(config=None):
    """(location, vehicle) pairs whose consumption comes from HCES (config.yaml hces_consumption).

    Every pair must be listed in location_fortificant_vehicles.csv.
    """
    if config is None:
        config = get_config()
    pairs = {
        (location, vehicle)
        for location, vehicles in (config.get("hces_consumption") or {}).items()
        for vehicle in vehicles
    }
    arms = get_location_fortificant_vehicles()
    listed = set(zip(arms.location, arms.vehicle))
    unknown = sorted(pairs - listed)
    if unknown:
        raise ValueError(
            "hces_consumption lists (location, vehicle) pairs that are not in "
            f"location_fortificant_vehicles.csv: {unknown}"
        )
    return pairs


def consumption_from_hces(location, vehicle, config=None):
    """Whether an arm's consumption results come from HCES rather than the extraction tables."""
    return (location, vehicle) in get_hces_consumption_pairs(config)


def get_combo_pathways(location, vehicle):
    """Which result pathways a (location, vehicle) pair produces.

    This is the single source of truth for both the 5000 Snakefile (which
    inputs to declare) and the dalys/cases notebooks (which inputs to read, via
    papermill flags). The notebooks must not decide by checking whether a file
    exists: that disagrees with Snakemake's DAG, so a job can start before a
    file it will read has been built, and a file missing by mistake is
    silently read as zeros.

    - ``has_simulations``: iron combos run the pregnancy and child sims.
    - ``has_anemia_model``: every iron combo runs the 0400 anemia model; a
      folate-only combo does only if it is listed in config.yaml's
      ``folate_anemia_vehicles`` (today: ethiopia/salt).
    - ``has_ntd_model``: folate combos run the 0500 NTD model.

    A pathway a combo lacks contributes zeros, built from the template combo's
    (india/rice) files.
    """
    combos = get_location_fortificant_vehicle_intervention_scenarios()
    fortificants = set(
        combos[(combos.location == location) & (combos.vehicle == vehicle)].fortificant
    )
    if not fortificants:
        raise ValueError(
            f"({location!r}, {vehicle!r}) is not in location_fortificant_vehicles.csv"
        )
    folate_anemia_vehicles = get_config().get("folate_anemia_vehicles") or {}
    has_iron = "iron" in fortificants
    return {
        "has_simulations": has_iron,
        "has_anemia_model": has_iron
        or vehicle in (folate_anemia_vehicles.get(location) or []),
        "has_ntd_model": "folate" in fortificants,
    }


def get_scenario_comparisons(stage="results"):
    """location_vehicle_scenario_comparisons.csv, limited to arms that run at `stage`.

    Every row must name a (location, vehicle) pair listed in
    location_fortificant_vehicles.csv, so a typo can't silently drop a comparison.
    Rows for pairs that don't reach `stage` are kept in the file but skipped here.
    """
    _check_stage(stage)
    comparisons = pd.read_csv(CONFIG_DIR / "location_vehicle_scenario_comparisons.csv")
    arms = get_location_fortificant_vehicles()
    run_through = dict(zip(zip(arms.location, arms.vehicle), arms.run_through))
    pairs = list(zip(comparisons.location, comparisons.vehicle))
    unknown = sorted(set(pair for pair in pairs if pair not in run_through))
    if unknown:
        raise ValueError(
            "location_vehicle_scenario_comparisons.csv names (location, vehicle) pairs that "
            f"are not in location_fortificant_vehicles.csv: {unknown}"
        )
    keep = [reaches_stage(run_through[pair], stage) for pair in pairs]
    return comparisons[keep].reset_index(drop=True)


def get_configured_combos(variables, stage):
    """Distinct combinations of `variables` over the arms that run at `stage`.

    `stage` is required: "data_prep" for what 0100_data_prep builds, "results"
    for what the simulations, models and results build. See RUN_THROUGH_STAGES.
    """
    location_fortificant_vehicle_intervention_scenarios = (
        get_location_fortificant_vehicle_intervention_scenarios(stage)
    )
    return [
        combo_tuple
        for _, combo_tuple in location_fortificant_vehicle_intervention_scenarios[variables]
        .drop_duplicates()
        .iterrows()
    ]
