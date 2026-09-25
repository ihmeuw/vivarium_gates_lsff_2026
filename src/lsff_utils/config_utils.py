import pathlib

import pandas as pd
import yaml


def get_config():
    config_dir = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()

    with open(config_dir / "config.yaml") as stream:
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


def get_location_fortificant_vehicle_intervention_scenarios():
    config_dir = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()

    config = get_config()

    location_fortificant_vehicles = pd.read_csv(
        str(config_dir / "location_fortificant_vehicles.csv")
    )

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

    return location_fortificant_vehicle_intervention_scenarios


def get_configured_combos(variables):
    location_fortificant_vehicle_intervention_scenarios = (
        get_location_fortificant_vehicle_intervention_scenarios()
    )
    return [
        combo_tuple
        for _, combo_tuple in location_fortificant_vehicle_intervention_scenarios[variables]
        .drop_duplicates()
        .iterrows()
    ]
