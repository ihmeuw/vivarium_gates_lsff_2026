# Scenarios

Each model produces results for three kinds of scenario:

- `zero`: no fortification at all;
- `baseline`: fortification as it is today;
- one or more intervention scenarios: the scaled-up program. By default an arm has a single
  scenario called `intervention`.

Only the intervention scenarios are configurable (`config_utils.get_intervention_scenarios`).
`zero` and `baseline` are built into each component separately. Results compare pairs of
scenarios, listed in `0050_config/location_vehicle_scenario_comparisons.csv`.

## Where each component gets its scenarios

| Component | Scenarios |
|---|---|
| Pregnancy sim (`0200`) | Fixed in `model_specifications/branches/scenarios.yaml` (`zero`, `baseline`, `intervention`), passed to `psimulate` by the Snakefile. |
| Child sim (`0300`) | Fixed in its `branches/scenarios.yaml`: `maternal_scenario` is `zero`, `baseline`, `intervention`; `child_scenario` is always `baseline`. |
| Non-pregnant anemia (`0400`, iron and folate notebooks) | Intervention scenarios from `config_utils`; `zero` and `baseline` are computed in the notebook and labelled when the outputs are combined. |
| NTD model (`0500`) | As `0400`, in `model.ipynb`. |
| Analysis (`5000`) | `dalys_by_scenario.ipynb` and `cases_by_scenario.ipynb` use the configured intervention scenarios plus `zero` and `baseline`. |

## What `zero` means

`zero` removes all fortification, including fortification assumed to be already reflected in
the GBD or survey inputs. Each model first subtracts that built-in effect:

- **Pregnancy sim** (`components/intervention.py`): in `zero`, each simulant's fortification
  and concentration are 0. Separately, a "2021" fortification status is drawn (always 0 for
  India, whose PDS roll-out came later), and its hemoglobin benefit is subtracted from GBD 2021
  hemoglobin. `baseline` and `intervention` then add their own benefit back. The component's
  default scenario is `baseline`.
- **Child sim:** `zero` uses the maternal iron intake from the pregnancy sim's `zero`
  scenario. The child sim has no fortification of its own.
- **Non-pregnant anemia, iron** (`non_pregnant_anemia.ipynb`): the iron-responsive hemoglobin
  distribution is shifted down by 2021 effective coverage × the hemoglobin effect, then mixed
  with the non-responsive part.
- **Non-pregnant anemia, folate, and NTD:** zero folate intake = baseline intake − effective
  baseline coverage × consumption × concentration. For India the coverage used is the
  pre-roll-out value, 0, so zero intake equals the survey intake. RBC or serum folate, and from
  it NTD risk or anemia, are recomputed at zero intake.

## Adding an intervention scenario

For example, a second concentration for one fortificant:

1. **Config.** List the scenarios in `0050_config/config.yaml` under
   `custom_intervention_scenarios`, keyed by location, then vehicle (see Ethiopia salt).
   Scenarios belong to a (location, vehicle) pair, not to a fortificant: every fortificant of
   that vehicle gets every scenario.
2. **Names.** A scenario's name is the extraction table's `Scenario` label, lowercased with
   non-word characters collapsed to `_` ("Intervention - 25% NRV" → `intervention_25_nrv`).
3. **Extraction rows.** Add the scenario's rows to the base table
   `0100_data_prep/extraction/data/scenario_definition.csv`: intervention coverage,
   effectiveness and concentration, for **each** fortificant of the vehicle. The build fills
   coverage and effectiveness from GF (√ of 2035 compliance). Literature rows are matched by
   scenario label, so the label in the literature workbook must match, or add a typo fix to
   `TYPO_FIXES` in `extraction/integration/common.py`. Rebuild with `build_extraction.py`.
4. **Comparisons.** Add a row to `0050_config/location_vehicle_scenario_comparisons.csv`.
   `custom_name` is free text; avoid commas, as the file isn't quoted.

Data prep, the coverage notebook, `0400` and `0500` loop over the configured scenarios, so they
need no changes. Arms with iron need more; see below.

### Arms with iron

Currently only a folate-only arm (Ethiopia salt) has extra scenarios. An arm with iron also
runs the pregnancy (`0200`) and child (`0300`) sims, which support only `zero`, `baseline` and
`intervention`. That name is hard-coded in the sims' `scenarios.yaml` branch files, in
`0200 .../components/intervention.py` (`self.scenario == "intervention"`), in the `0200` data
loader paths (`iron/{vehicle}/intervention/...`), and in the `0300` observers.

**The failure is silent.** `dalys_by_scenario.ipynb` and `cases_by_scenario.ipynb` add the
pathways with `fill_value=0`, so a scenario with no sim results gets zero pregnancy and
neonatal burden and appears to avert far more DALYs than it does.

There are two ways to handle it:

- **Reuse the `intervention` sim results** when the new scenario's iron inputs are identical to
  `intervention`'s (e.g. it changes only folate, which the sims don't model). Map the scenario
  to `intervention`'s sim results in the `5000` rescale step (or in `dalys_by_scenario` and
  `cases_by_scenario`), and add a check that the iron inputs really are identical. No extra
  cluster compute.
- **Add the scenario to both sims**: the branch files, the hard-coded `"intervention"` checks,
  the loader paths and the observers. Needed whenever iron differs between scenarios; costs a
  full extra scenario run.

Either way, check `dalys_by_scenario.csv` afterwards: the new scenario's pregnancy and neonatal
rows should not be zero.
