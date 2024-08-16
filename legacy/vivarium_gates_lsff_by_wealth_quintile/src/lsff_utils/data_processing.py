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
