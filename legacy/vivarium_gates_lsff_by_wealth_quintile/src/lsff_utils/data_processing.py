WEALTH_QUINTILES = [1, 2, 3, 4, 5]

DHS_MAPPING = {
    "poorest": 1,
    "poorer": 2,
    "middle": 3,
    "richer": 4,
    "richest": 5,
}
assert set(DHS_MAPPING.values()) == set(WEALTH_QUINTILES)

EXTRACTION_MAPPING = {
    "Lowest": 1,
    "Second": 2,
    "Middle": 3,
    "Fourth": 4,
    "Highest": 5,
    "All (assumed same)": "All (assumed same)",
    "Total": "Total",
}
assert set(EXTRACTION_MAPPING.values()) == set(WEALTH_QUINTILES) | {
    "All (assumed same)",
    "Total",
}


def recode_dhs_wealth_quintile(series):
    return series.map(DHS_MAPPING)


def recode_extraction_wealth_quintile(series):
    return series.map(EXTRACTION_MAPPING)

def reindex_series_onto_df_by_age_groups(df, series):
    if "age_start" not in series.index.names:
        return series.align(df)[1]
    # NOTE: Age groups can be different! Is there a more Vivarium way to do this, with a lookup table maybe?
    common = list(set(df.index.names) & set(series.index.names))
    result = (
        df.reset_index()
        .merge(
            series.rename("series_value").reset_index(),
            on=[c for c in common if c not in ("age_start", "age_end")],
            suffixes=("", "_series"),
        )
        # NOTE: Depends on a GBD age group always fitting into a disparity age group
        .pipe(
            lambda df: df[
                (df.age_start >= df.age_start_series)
                & (df.age_end <= df.age_end_series)
            ]
        )
        .pipe(lambda df: df.drop(columns=df.filter(like="_series").columns))
    )
    result = result.set_index(
        sorted(list(set(df.index.names) | set(series.index.names)))
    )
    return result.series_value.rename(series.name)