import pathlib

import pandas as pd
import yaml


def get_location_fortificant_vehicle_scenarios():
    config_dir = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()

    with open(config_dir / "config.yaml") as stream:
        config = yaml.safe_load(stream)

    location_fortificant_vehicles = pd.read_csv(
        str(config_dir / "location_fortificant_vehicles.csv")
    )

    # Expand "all" fortificants
    location_fortificant_vehicles = pd.concat(
        [
            location_fortificant_vehicles[
                location_fortificant_vehicles.fortificant != "all"
            ],
            *[
                location_fortificant_vehicles[
                    location_fortificant_vehicles.fortificant == "all"
                ].assign(fortificant=fortificant)
                for fortificant in config["all_fortificants"]
            ],
        ]
    )

    assert (
        location_fortificant_vehicles["fortificant"]
        .isin(config["all_fortificants"])
        .all()
    )

    location_fortificant_vehicle_scenarios = location_fortificant_vehicles[
        ~location_fortificant_vehicles.location.isin(
            config["custom_intervention_scenarios"]
        )
    ].assign(scenario="intervention")

    for location, custom_intervention_scenarios in config[
        "custom_intervention_scenarios"
    ].items():
        location_fortificant_vehicle_scenarios = pd.concat(
            [
                location_fortificant_vehicle_scenarios,
                *[
                    location_fortificant_vehicles[
                        location_fortificant_vehicles.location == location
                    ].assign(scenario=scenario)
                    for scenario in custom_intervention_scenarios
                ],
            ]
        )

    return location_fortificant_vehicle_scenarios


def get_configured_combos(variables):
    location_fortificant_vehicle_scenarios = (
        get_location_fortificant_vehicle_scenarios()
    )
    return [
        combo_tuple
        for _, combo_tuple in location_fortificant_vehicle_scenarios[variables]
        .drop_duplicates()
        .iterrows()
    ]
