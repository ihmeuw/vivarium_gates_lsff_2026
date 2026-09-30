# Nigeria / wheat / iron and folate: placeholder data (MIC-7549, SSCI-2784)

The Nigeria wheat arm is wired into the pipeline with placeholder values so it
can run end to end before the real data arrive. Every placeholder is a copy of the
matching Nigeria rice value for the same fortificant. Every placeholder row in
`Data Extraction Sheet.xlsx` has `Data source` set to `DUMMY (<ticket>)` and a note
saying which row it was copied from, so they can be found by filtering on that column.
The iron and shared consumption rows are tagged `DUMMY (MIC-7549)`; the folate rows
are tagged `DUMMY (SSCI-2784)`.
Until the real values replace them, the wheat results are the rice results under
another name, and they should not be reported.

The arm carries both iron and folic acid (`nigeria,all,wheat` in
`0050_config/location_fortificant_vehicles.csv`). Iron runs through the simulations
and the non-pregnant anemia model; folic acid runs through the NTD model only, as for
Nigeria rice.

## Values to replace

Each group below is a set of rows on one sheet of the extraction workbook.

| Sheet | Data need | Breakdown the pipeline expects | Placeholder (from rice) |
|---|---|---|---|
| Country-Vehicle Extraction | Vehicle consumption by WRA -- any | % of WRA consuming, by wealth quintile plus a total | 33.6%–67.6% by quintile, 53.6% total |
| Country-Vehicle Extraction | Vehicle consumption by WRA -- amount (mean and standard deviation) | g/day, by wealth quintile plus a total | means 11.5–53.7 g/day, SDs 24.8–40.1 g/day |
| Country-Vehicle Extraction | Vehicle consumption by U5 children -- any | % of U5 consuming, by wealth quintile plus a total | same as WRA |
| Country-Vehicle Extraction | Vehicle consumption by U5 children -- amount (mean and standard deviation) | g/day, by sex (female, male and total), no wealth breakdown | means 19.0 / 22.0 / 20.5, SDs 24.0 / 27.3 / 25.6 |
| Country-Vehicle Extraction | Vehicle "fortifiability" | % industrially produced, one value | 74% |
| Country-Vehicle-Fort Extraction | Vehicle fortification at baseline -- any (iron) | % of vehicle fortified today | 0% |
| Country-Vehicle-Fort Extraction | Vehicle fortification at baseline -- amount among fortified (iron) | mcg/g | 0 |
| Country-Vehicle-Fort Extraction | Baseline effective % of fortified (iron) | % | 80% |
| Scenario Definition Extraction | Intervention coverage % of fortifiable (iron, "Intervention") | % | 95% |
| Scenario Definition Extraction | Intervention effective % of fortified (iron, "Intervention") | % | 95% |
| Scenario Definition Extraction | Vehicle fortification in intervention -- amount among fortified (iron, "Intervention") | mcg/g | 40 |
| Vehicle Extraction | Iron fortification/consumption effect on hemoglobin (Wheat) | g/L mean difference | 3.25 (rice meta-analysis) |
| Vehicle Extraction | Iron fortification/consumption effect on birthweight (Wheat) | g per mg/person-day | 1.67 (same value used for every vehicle) |

The folate rows (tagged `DUMMY (SSCI-2784)`):

| Sheet | Data need | Breakdown the pipeline expects | Placeholder (from rice) |
|---|---|---|---|
| Country-Vehicle-Fort Extraction | Vehicle fortification at baseline -- any (folate) | % of vehicle fortified today | 0% |
| Country-Vehicle-Fort Extraction | Vehicle fortification at baseline -- amount among fortified (folate) | mcg/g | 0 |
| Country-Vehicle-Fort Extraction | Baseline effective % of fortified (folate) | % | 80% |
| Scenario Definition Extraction | Intervention coverage % of fortifiable (folate, "Intervention") | % | 95% |
| Scenario Definition Extraction | Intervention effective % of fortified (folate, "Intervention") | % | 95% |
| Scenario Definition Extraction | Vehicle fortification in intervention -- amount among fortified (folate, "Intervention") | mcg/g | 1.69 |

The shapes matter because data prep checks them. For Nigeria, U5 consumption amounts
are split by wealth using the WRA gradient, so the WRA amount rows need all five
quintiles, and the U5 amount rows need female and male values. Intervention coverage
times fortifiability has to be at least baseline coverage in every quintile, or the
coverage calculation stops.

## Questions for research

1. Baseline fortification. My understanding is that Nigeria already mandates iron
   and folic acid fortification of wheat flour, so a 0% baseline is probably wrong
   for both. Please confirm the baseline coverage, the concentration, and how
   effective the existing program is, for each fortificant.
2. Baseline year. For India rice, the model treats 2021 (the GBD hemoglobin year)
   as unfortified, because that program rolled out afterwards. Does an existing
   Nigerian wheat program predate 2021, so that GBD hemoglobin already reflects it?
   If it doesn't, the model needs the same adjustment for Nigeria wheat. The same
   question applies to folate: the NTD model (`0500_neural_tube_defects_model/model.ipynb`)
   assumes the baseline folate intake data already include today's baseline
   fortification, except for India rice, which it special-cases.
3. Effect sizes. Is there a wheat-specific hemoglobin effect, or should wheat reuse
   an existing one? The same question applies to the birthweight effect.
4. Scenarios. Is the default baseline-vs-intervention comparison the only one wanted,
   or does wheat need custom scenarios the way Ethiopia salt has them? Custom
   scenarios for an iron arm need code changes in the pregnancy sim, not just data.

## When the real data arrive

Replace the placeholder rows in the workbook (keep the same data need, units and
breakdown labels), then rerun data prep and everything downstream. Delete this file
once no `DUMMY (MIC-7549)` or `DUMMY (SSCI-2784)` rows remain.
