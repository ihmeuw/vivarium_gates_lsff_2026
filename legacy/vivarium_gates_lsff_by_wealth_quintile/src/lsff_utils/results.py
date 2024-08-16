import pandas as pd

def aggregate_by_scenario(df):
    return (
        df.groupby(["scenario", "input_draw", "wealth_quintile"])
        .value.sum()
        .groupby(["scenario", "wealth_quintile"])
        .mean()
    )

def aggregate_by_cause_and_scenario(df):
    result = (
        df.groupby(["scenario", "entity", "input_draw", "wealth_quintile"])
        .value.sum()
        .groupby(["scenario", "entity", "wealth_quintile"])
        .mean()
    )
    return result[result.index.get_level_values("entity") != "all_causes"]

def expand_to_all_scenarios(df, scenarios):
    if df.scenario.nunique() > 1:
        df = df[df.scenario == df.scenario.iloc[0]]

    return pd.concat([
        df.assign(scenario=scenario) for scenario in scenarios
    ])