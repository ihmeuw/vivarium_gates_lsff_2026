# Data needs

Generated from `SPEC` in `data_needs.py` by `build_extraction.py`; do not edit. Every arm the model runs gets rows for each need that applies to it (per fortificant, and per configured scenario in `scenario_definition`). How each group of rows is split, and which rows are required, is described in `data_needs.py`.

| table | data need | data point | units | applies to | required for | split | read by | notes |
|---|---|---|---|---|---|---|---|---|
| country_vehicle | Vehicle consumption by WRA -- any | percentage | % | all but HCES arms | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {vehicle}/vehicle_consumption/any | Children use this WRA value too (U5 any isn't read yet). |
| country_vehicle | Vehicle "fortifiability" (essentially amount industrially produced) | percentage | % | all | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {vehicle}/vehicle_consumption/fortifiability | India rice: one Total row, industry consolidation of purchased non-government rice. |
| country_vehicle | Vehicle consumption by WRA -- amount | mean | g/day | all but HCES arms | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {vehicle}/vehicle_consumption/amount/mean | Per capita over all WRA. Nigeria needs all five quintiles (U5 interpolation). |
| country_vehicle | Vehicle consumption by WRA -- amount | standard deviation | g/day | all but HCES arms | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {vehicle}/vehicle_consumption/amount/sd | Build check: consumers' variance must be positive. |
| country_vehicle | Vehicle consumption by U5 children -- amount | mean | g/day | all but HCES arms | Nigeria | one 'Total' | prep_extracted (Nigeria only: U5 and ages 5-15) | Female and Male rows. Not read for other countries. |
| country_vehicle | Vehicle consumption by U5 children -- amount | standard deviation | g/day | all but HCES arms | Nigeria | one 'Total' | prep_extracted (Nigeria only) |  |
| country_vehicle | Vehicle consumption by U5 children -- any | percentage | % | all but HCES arms | none | 5 quintiles + Total, or one 'All (assumed same)' | nothing yet | Kept for the planned fix that gives children their own coverage. |
| country_vehicle_fortificant | Vehicle fortification at baseline -- any | percentage | % | all | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {fortificant}/{vehicle}/baseline_fortification/any_coverage (and full) | India rice: one 'All (assumed same)' row, the share of government rice fortified. |
| country_vehicle_fortificant | Baseline effective % of fortified | percentage | % | all | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {fortificant}/{vehicle}/baseline_fortification/effectiveness |  |
| country_vehicle_fortificant | Vehicle fortification at baseline -- amount among fortified | concentration | mcg/g | all | all | 5 quintiles + Total, or one 'All (assumed same)' | prep_extracted -> {fortificant}/{vehicle}/baseline_fortification/concentration |  |
| scenario_definition | Intervention coverage % of fortifiable | percentage | % | all | all | one row | prep_extracted -> {fortificant}/{vehicle}/{scenario}/intervention_fortification/any_coverage |  |
| scenario_definition | Intervention effective % of fortified | percentage | % | all | all | one row | prep_extracted -> {fortificant}/{vehicle}/{scenario}/intervention_fortification/effectiveness |  |
| scenario_definition | Vehicle fortification in intervention -- amount among fortified | concentration | mcg/g | all | all | one row | prep_extracted -> {fortificant}/{vehicle}/{scenario}/intervention_fortification/concentration |  |
| vehicle | Iron fortification/consumption effect on hemoglobin | Mean difference | g/L | each vehicle | vehicles of arms the model runs | one row | prep_vehicle -> iron/fortification_hemoglobin_effects |  |
| vehicle | Iron fortification/consumption effect on birthweight | Mean difference | g/(mg/person-day) | each vehicle | vehicles of arms the model runs | one row | prep_vehicle -> iron/fortification_birthweight_effects |  |
