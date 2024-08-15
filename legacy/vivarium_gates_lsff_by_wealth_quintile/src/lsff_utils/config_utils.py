import pathlib

import pandas as pd
import yaml

def get_config():
    config_dir = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()

    with open(config_dir / "config.yaml") as stream:
        config = yaml.safe_load(stream)
    
    return config

def get_location_fortificant_vehicle_intervention_scenarios():
    config_dir = (pathlib.Path(__file__) / ".." / ".." / ".." / "0050_config").resolve()

    config = get_config()

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

    location_fortificant_vehicle_intervention_scenarios = location_fortificant_vehicles[
        ~location_fortificant_vehicles.location.isin(
            config["custom_intervention_scenarios"]
        )
    ].assign(intervention_scenario="intervention")

    for location, custom_intervention_scenarios in config[
        "custom_intervention_scenarios"
    ].items():
        location_fortificant_vehicle_intervention_scenarios = pd.concat(
            [
                location_fortificant_vehicle_intervention_scenarios,
                *[
                    location_fortificant_vehicles[
                        location_fortificant_vehicles.location == location
                    ].assign(intervention_scenario=scenario)
                    for scenario in custom_intervention_scenarios
                ],
            ]
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
