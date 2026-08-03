# CLAUDE.md

## What this project is

Research code for IHME's Gates-funded study of **large-scale food fortification (LSFF)
impact by wealth quintile**. It estimates the health benefit of adding iron and/or folic
acid to staple food vehicles, broken out by wealth quintile, for four
location/vehicle pairs:

| Location | Vehicle  | Fortificants  |
|----------|----------|---------------|
| India    | rice     | iron, folate  |
| Nigeria  | bouillon | iron, folate  |
| Nigeria  | rice     | iron, folate  |
| Ethiopia | salt     | folate only   |

Outputs are DALYs, anemia cases/prevalence, maternal disorder incident cases, neonatal
deaths, and neural tube defect (NTD) cases, per scenario per wealth quintile, collected
into `5000_analyze_results/results_spreadsheet.xlsx` plus plots.

This is **not a single Python package**. It is a Snakemake pipeline whose stages are
numbered top-level directories, mixing Jupyter notebooks (data prep, closed-form models,
analysis) with two Vivarium microsimulations.

## Read this first: the repo is mid-migration

The git history was imported from the predecessor repo
`vivarium_gates_lsff_by_wealth_quintile` into a fresh `vivarium` model-template scaffold
in July 2026 (`2783716`, `5ab6730`). Two generations of tooling now coexist and several
things on `main` are inconsistent:

- **`README.rst` is unmodified template boilerplate.** It documents
  `src/vivarium_gates_lsff_2026/{constants,model_specifications,artifacts}`,
  a `make_artifacts` console script, and `pytest --runslow`. None of those exist on
  `main` — `src/` contains only `lsff_utils`. Do not follow it.
- The real usage documentation was the old repo's `README.md`, deleted in `4f15336`.
  Recover it with `git show 4f15336^:README.md`; its content is folded into this file.
- `pyproject.toml` declares `make_artifacts = "vivarium_gates_lsff_2026.tools.cli:make_artifacts"`,
  pointing at a module that does not exist on `main`.
- **Vivarium version conflict.** Top-level `pyproject.toml` requires the new suite
  (`vivarium-engine>=5.5.3`, `vivarium-public-health>=6.4.5`), while
  `0200_pregnancy_sim/setup.py` pins the old generation (`vivarium>=2.0.0`,
  `vivarium_public_health>=2.1.0`) and the `Snakefile` installs vivarium from the
  `@release-candidate-spring` branches. The sub-simulation code targets the old APIs.
- **`0200_pregnancy_sim` has mixed import namespaces on `main` and probably cannot import
  cleanly.** `components/hemoglobin.py` and `components/observers.py` import from the new
  `vivarium.engine.*` / `vivarium.public_health.*` layout, while every other module in
  `0200` and `0300` imports the old `vivarium.framework.*` / `vivarium_public_health.*`.
  `components/__init__.py` imports both. If you hit an `ImportError` here, it is
  pre-existing, not something you broke.
- **Active migration branch:** `origin/albrja/mic-7325/framework-updates-pt1` ports the
  sub-sims to the new suite, adds `src/vivarium_gates_lsff_2026/tools/cli.py`, and renames
  the packages:
  `vivarium_gates_lsff_by_wealth_quintile` → `vivarium_gates_lsff_2026_maternal`,
  `vivarium_gates_lsff_by_wealth_quintile_child` → `vivarium_gates_lsff_2026_child`.
  **Check whether that branch has landed before editing sub-sim code, the top-level CLI,
  or anything that names a package.**

## Pipeline stages

Everything is driven by Snakemake from the repo root. `rule all` targets
`5000_analyze_results/results_spreadsheet.xlsx` and
`5000_analyze_results/executed/results_plots.ipynb`.

| Stage | What it does |
|-------|--------------|
| `0050_config/` | Declarative config that defines the whole fan-out (see below). No code. |
| `0100_data_prep/` | Notebooks that extract and reshape inputs: DHS (`dhs/`), household consumption/expenditure surveys (`hces/`), a manual extraction spreadsheet (`extraction/Data Extraction Sheet.xlsx`), GBD population/pregnancy (`population/`), and effective-coverage calculation by quintile and scenario (`coverage_calculation/`). Writes CSVs under `0100_data_prep/results/`. |
| `0200_pregnancy_sim/` | Vivarium microsimulation of pregnancy, hemoglobin/anemia, maternal disorders, and birth outcomes. Builds an HDF artifact, then runs `psimulate`. |
| `0300_child_sim/` | Vivarium microsimulation of under-5 outcomes (LBWSG, wasting, causes). **Depends on `0200`'s `births.parquet`.** |
| `0400_non_pregnant_anemia_model/` | Closed-form notebook model of anemia in non-pregnant people (a distribution-shift calculation, not a microsim). |
| `0500_neural_tube_defects_model/` | Closed-form notebook model of folic-acid-preventable NTDs. |
| `5000_analyze_results/` | Rescales sim output to population scale, then aggregates everything into per-scenario DALYs/cases CSVs, the results spreadsheet, and plots. |

Numbering leaves gaps deliberately; `5000` is the terminal analysis stage.

The `0300_child_sim` chain is longer than it looks:
`artifact_for_lbwsg_pafs` → `lbwsg_pafs` (a whole `psimulate` run whose only purpose is
computing LBWSG PAFs) → `child_artifacts` (consumes `0200`'s births) → `child_simulations`.

### Iron and folate take different routes

This is the single most important structural fact. The two microsimulations model the
**iron** pathway only. The **folate** pathway is entirely closed-form notebooks. See
`dalys_by_scenario_inputs` / `cases_by_scenario_inputs` in `5000_analyze_results/Snakefile:47,76`:

- iron → `0200_pregnancy_sim` + `0300_child_sim` + `0400_non_pregnant_anemia_model`
- folate → `0500_neural_tube_defects_model` (+ `0400`'s folate variant)

So Ethiopia (salt, folate-only) never runs the microsims at all; it goes through
`non_pregnant_anemia_folate.ipynb` and the NTD model. Don't look for Ethiopia in the sim
results. Relatedly, `0200`'s CLI restricts `--vehicle` to `["rice", "bouillon"]` — salt is
deliberately absent, not an oversight, and the Ethiopia-specific
`intervention_25_nrv` / `intervention_100_nrv` scenarios exist only in the notebook models
(`components/intervention.py` only recognizes the literal `"intervention"`).

### The two Vivarium sims

`0200_pregnancy_sim` (package `vivarium_gates_lsff_by_wealth_quintile`) models pregnancy for
women 10–54 in 2025 on 7-day steps: a pregnancy state machine, continuous hemoglobin
exposure and derived anemia, maternal disorders and hemorrhage at parturition, and a
newborn line list. Fortification enters as a `hemoglobin.exposure` value modifier computed
from vehicle grams/day (zero-inflated normal) × coverage × concentration × effectiveness.
Default stratification is `[age_group, wealth_quintile, anemia_status_at_birth]`; it emits
`births.parquet` for the child sim.

`0300_child_sim` (package `..._child`) models under-5 outcomes for 2025–2029 on 4-day steps
with `population_size: 0` — the entire population arrives from `0200`'s birth line list.
It models LBWSG (shifted by maternal iron-from-fortification and by wealth quintile),
diarrheal disease, and mortality from a list of 13 unmodeled causes. Stratification is
`[age_group, sex, wealth_quintile]`.

**Scenario names are declared in three places and only the branches YAML is real.** Ignore
`constants/metadata.py`'s `SCENARIOS` (leftover from a BEP-era project) and
`constants/scenarios.py` (a `BASELINE`-only stub). The live scenarios are in
`model_specifications/branches/scenarios.yaml`: `intervention.scenario` of
`[zero, baseline, intervention]` for `0200`, and `child_scenario` × `maternal_scenario`
for `0300`. `scenarios.yaml` and `scenarios_small.yaml` differ **only** in seed count
(200 vs 10); the `full_scale` config flag picks between them.

**Uncertainty comes from random seeds, not draws.** Both branch files set
`input_draw_count: 1` / `input_draws: [0]`, and artifacts are built with `--mean` into
`mean_draw_artifacts/` — i.e. mean-draw inputs, varied over 200 random seeds. So
`input_draw` is always `0` in sim output, and stochastic uncertainty is seed-based.
(`constants/metadata.py`'s `DRAW_COUNT = 500` is not what runs.)

## Where the fan-out is defined

Do not hardcode locations or vehicles in Snakefiles. The grid lives in `0050_config/`:

- `location_fortificant_vehicles.csv` — the `(location, fortificant, vehicle)` grid.
  `fortificant: all` expands to `config.yaml`'s `all_fortificants`.
- `config.yaml` — `all_fortificants: [folate, iron]` and `custom_intervention_scenarios`
  (Ethiopia uses `intervention_25_nrv` and `intervention_100_nrv` instead of the default
  single `intervention` scenario).
- `location_vehicle_scenario_comparisons.csv` — which baseline/intervention pairs get
  reported, plus display names for the spreadsheet.

`src/lsff_utils/config_utils.py` expands these into combinations; the Snakefiles call
`get_configured_combos([...])` and `get_location_fortificant_vehicle_intervention_scenarios()`.
Adding a location or vehicle means editing the CSV, not the rules.

**But the config is not universally respected.** `calculate_effective_coverage_by_quintile_and_scenario.ipynb`
hardcodes its own `scenarios = {"india": [...], "nigeria": [...], "ethiopia": [...]}` dict
instead of calling `config_utils`, and `prep_extracted.ipynb` carries a
`# TODO: Deduplicate this list with the Snakefiles`. If you change `0050_config/`, grep the
notebooks for the same literals or they will silently disagree.

## Environments — two venvs, and one trap

Two separate virtual environments exist because Vivarium and GBD's `db_queries` require
incompatible pandas versions:

- `.venv` — general/artifact-building env (`requirements.txt`, locked in `pip_lock.txt`)
- `.simulation_running_venv` — for running the microsims (`simulation_running_pip_lock.txt`)

**Trap:** the Snakefiles hardcode `.venv/bin/activate` and
`.simulation_running_venv/bin/activate`. The new template's `source environment.sh -s`
creates `.venv/<package>_<type>/bin/activate` instead — a *different* layout that the
pipeline will not find. For pipeline work, use the old documented route:

```bash
conda create --prefix .conda_env --file conda_lock.txt   # linux-64 x86 only
conda activate ./.conda_env
pip install -e . --no-deps        # NOTE: --no-deps is required, see below
snakemake                         # Snakemake builds the two venvs itself
```

**`pip install -e .` must be run with `--no-deps`.** The old repo's root `setup.py` had
`install_requires=[]`, so this step only ever put `lsff_utils` on the path. The
model-template `pyproject.toml` that replaced it declares the full new Vivarium suite, so a
bare `pip install -e .` now pulls in `vivarium-engine`, `vivarium-public-health` 6.x and
friends, replaces conda's pandas with a PyPI wheel that fails to load
(`GLIBCXX_3.4.29 not found` against this cluster's libstdc++), and silently downgrades
numpy 2.0.1 → 1.26.4. The same fix is needed in all four `pip install -e .` lines in the
`Snakefile`, or both venvs get the same corruption on top of the pinned lockfiles.

Also note `environment.sh` runs `git fetch --all` and `git pull origin <branch>` as a side
effect of being sourced.

Regenerate the lockfiles with `snakemake --config update_packages=yes` — that is the only
path that rewrites `pip_lock.txt` / `simulation_running_pip_lock.txt`.

## Running the pipeline

```bash
snakemake                              # approximate scale (scenarios_small.yaml)
snakemake --config full_scale=yes      # full scale (scenarios.yaml)
snakemake --config local=yes           # run sims locally via local_psimulate.py, not Slurm
snakemake --config debug=yes           # 1 draw, `simulate` instead of `psimulate`, --pdb,
                                       # papermill ploomber debug engine
snakemake --profile profiles/debug     # same debug config + jobs=1
```

Boolean configs accept `yes/y/true/t` (case-insensitive).

Cluster runs submit with `-P proj_simscience -m 2 -r 01:00:00 -q all.q`.
`local_psimulate.py` is a hand-rolled multiprocessing stand-in for `psimulate` that
replicates the branch-config/results-column handling of
`vivarium_cluster_tools`' work horse.

**This only works on the IHME cluster** — it reads GBD and GHDx data and submits to Slurm.

Vivarium emits an enormous volume of duplicate `psimulate` logs. If you are running
somewhere you cannot afford tens of gigabytes of logs (e.g. your home directory), run this
in a second terminal:

```bash
watch 'truncate -s 0 */sim_results/*/*/*/logs/*/*/*'
```

`archive_last_run.sh` rsyncs the `*.hdf` / `*.parquet` outputs plus `git status`/`git diff`
to a timestamped directory under `/mnt/team/simulation_science/pub/models/`.

## Notebooks are pipeline steps

Notebooks are executed with **papermill**, not Snakemake's built-in notebook integration —
deliberately, because that integration produces no incremental output and no output
notebook on error (see the comment in `src/lsff_utils/snakemake_utils.py`).

The convention: the source notebook lives at the stage root, and the executed copy is
written to `<stage>/executed/<...wildcards...>/<notebook>.ipynb` and registered as the
Snakemake `log:`. Parameters are passed as `-p location <loc> -p vehicle <veh>
-p fortificant <fort>`, so every parameterized notebook has a `parameters`-tagged cell.
Rules `cd` into the notebook's directory first, so notebook-relative paths assume that cwd.

**Executed notebooks are committed with their outputs.** That is why `.git` is ~660 MB.

Recorded kernel display names in the notebooks are inconsistent and misleading (some say
`simulation_running`, some `.venv`, one says `Python 3 (ipykernel)`). Snakemake runs all of
them under `.venv` with `papermill -k python3`; nothing registers a named kernel.

### The two closed-form models

`0400_non_pregnant_anemia_model` is a hemoglobin-distribution-shift calculation, not a
microsim: pull GBD hemoglobin mean/SD draws, redistribute across quintiles using the DHS
disparities while preserving the population-weighted GBD total, split the population into
iron-responsive vs. non-responsive using GBD anemia sequela prevalences, shift the ensemble
distribution for the covered fraction, re-integrate against anemia thresholds, convert to
YLDs. `non_pregnant_anemia_folate.ipynb` (Ethiopia/salt only) is a separate
folate → serum folate → hemoglobin chain whose own markdown describes it as "extremely
speculative" — treat its numbers accordingly.

`0500_neural_tube_defects_model` projects **2030** NTD-affected pregnancies by quintile
using forecasted population from `db_queries.get_population(..., forecasted_pop=True)`
(assembled by hand because `vivarium_inputs` cannot fetch forecasted population), then
back-calculates RBC folate from NTD risk via the Crider 2014 / Daly 1995 log-odds
equations. It is dense with GBD-Compare-extracted literals whose provenance is only a
comment with an `http://ihmeuw.org/...` short link. Note `s_dist_deaths_by_wealth` is
currently all 1s for every location — i.e. **no wealth gradient in NTD death rate**.

### External data the pipeline reads

All IHME-internal, all read by absolute path, none versioned by this repo:

- DHS Stata files under `/snfs1/DATA/DHS_PROG_DHS/{IND,NGA,ETH}/...` — exact filenames
  hardcoded per location
- India HCES fixed-width extracts under
  `/snfs1/DATA/Incoming Data/IND/HOUSEHOLD_CONSUMPTION_EXPENDITURE_SURVEY_HCES/2022_2023/`,
  parsed with hand-specified column widths
- `/share/mnch/anemia/code/reference/model/anemia_thresholds.csv` — another team's
  directory, unversioned
- GBD 2021 disability weights at
  `/mnt/team/simulation_science/costeffectiveness/auxiliary_data/GBD_2021/.../all.hdf`
- GBD via `vivarium_inputs`, `vivarium_gbd_access.gbd`, `db_queries`, `gbd_mapping`
- `0100_data_prep/extraction/Data Extraction Sheet.xlsx` — in-repo, hand-maintained,
  4 sheets; the literature-extraction source of truth
- HCES documentation and the DHS↔HCES variable crosswalk exist **only on SharePoint**
  (links in `hces/01_extract_hces.ipynb` markdown). `file:///J:/...` references in comments
  are documentation, not code paths.

## Shape of the final results

The stage-`5000` CSVs are long-format point estimates —
`(scenario, entity, wealth_quintile) → value` — with **no uncertainty columns**.
`lsff_utils/results.py` sums within `(scenario, entity, input_draw, wealth_quintile)` and
then averages over draws, so intervals are collapsed before anything is written. If a
request involves reporting uncertainty, that machinery does not exist yet.

## What is committed vs generated

`.gitignore` excludes `*.hdf`, `*.parquet`, `.venv`, `.simulation_running_venv`,
`.snakemake`, `*.rdb`. But the CSVs under `<stage>/results/` and the executed notebooks
**are** committed. Rerunning the pipeline therefore shows up as diffs in tracked result
files — that is expected, and rerunning to refresh them is a normal part of a change.
Because parquet is ignored, `0400_.../results/` and `5000_.../results/rescaled_*` do not
exist at all on a fresh clone.

**The committed CSVs are load-bearing, not just a record.** Two ways:

- Several notebooks (`dhs/common.ipynb`, `dhs/maternal_mortality_*.ipynb`,
  `extraction/prep_vehicle.ipynb`) call `to_csv` into `../results/<subdir>/` with **no**
  `mkdir`. They only work because the tracked CSVs already put those directories on disk.
  If you add a new output subdirectory, add the `mkdir` — most other notebooks do.
- `dalys_by_scenario.ipynb` and `cases_by_scenario.ipynb` zero-fill missing
  fortificant/location combinations with an
  `if path.is_file(): ... else: expand_to_all_scenarios(<india/rice file>.assign(value=0), ...)`
  pattern, i.e. they read the **India/rice** files as a schema template. `results/india/rice/`
  must exist before any other combination can be built.

Path ordering is inconsistent between stages: `0400` writes
`results/<vehicle>/<location>/`, while `0500` and `5000` write `results/<location>/<vehicle>/`.
Easy to get backwards.

## Shared library: `src/lsff_utils/`

The only real Python package at the top level (installed via `pip install -e .`):

- `config_utils.py` — expands `0050_config/` into the pipeline fan-out
- `data_processing.py` — wealth-quintile recoding (DHS `poorest…richest` → 1–5, extraction
  sheet `Lowest…Highest` → 1–5) and reindexing disparity series onto GBD age groups
- `hemoglobin_distribution.py` — the hemoglobin ensemble distribution (40% gamma / 60%
  mirrored Gumbel, `XMAX = 220`), used by both `0400` notebooks. Contains documented
  workarounds for two upstream `risk_distributions` bugs: a reversed MirroredGumbel CDF
  ([#62](https://github.com/ihmeuw/risk_distributions/issues/62)) and an x_min/x_max
  override ([#61](https://github.com/ihmeuw/risk_distributions/issues/61)). Do not "fix"
  the `1 - cdf` as if it were a typo.
- `results.py` — scenario aggregation helpers
- `snakemake_utils.py` — papermill parameter formatting; currently unused

Note `config_utils` resolves `0050_config/` relative to `__file__`, so it is the one part of
the codebase that works regardless of cwd.

## Code style

`black` with `line-length = 94` and `isort` with `profile = black` (configured in
`pyproject.toml` and each sub-sim's `pyproject.toml`). CI enforces linting.

The documented fix-up procedure, which matters because linting otherwise invalidates the
Snakemake DAG:

1. Make sure Snakemake is fully up to date and all changes are committed.
2. `isort . --gitignore --profile black` (slow), then `black .`
3. `snakemake --config <same config as your last run> --touch` so the formatting-only
   changes do not trigger reruns.

## Tests: the regression harness

`tests/` holds a regression harness that answers one question: **did the pipeline's output
change in a way nobody intended?** It does not validate the science — it detects change.

The suite runs in **either** environment and skips what that environment cannot do,
because the two halves need incompatible dependencies:

```bash
source .test_venv/bin/activate && pytest tests/ --runslow -q   # 302 passed, 3 skipped
source .venv/bin/activate      && pytest tests/ -q             # 170 passed, 135 skipped
```

`.test_venv` has the fuzzy checker but no GBD access; `.venv` has GBD access but cannot
host `vivarium-testing-utils`. Run both to cover everything. Note `--runslow` only exists
in `.test_venv`, since that flag comes from the plugin.

Three layers:

- **`test_deterministic_results.py`** — every tracked result CSV outside the
  microsimulations must match the committed baseline **exactly**. That is possible because
  those 150 files regenerate byte-identically (verified 2026-07-30). Reads the reference
  straight out of git, so there is no second copy to drift; override the comparison point
  with `LSFF_BASELINE_REF=<tag>` during a migration.
- **`test_stochastic_results.py`** — simulation output can't match exactly, so this uses
  `FuzzyChecker` from `vivarium-testing-utils`. It compares count-based proportions against
  the 95% Jeffreys interval implied by the reference counts, failing only on decisive
  Bayes-factor evidence. Measured sensitivity at ~124k samples: detects a 2% relative shift,
  warns "not conclusive" at 1%, passes below that. At 200 seeds the threshold tightens ~4.5×.

- **`test_gbd_assumptions.py`** — the other two layers detect changed *output*; this one
  detects a changed *input contract*, where GBD moves something underneath code that
  hardcodes it. All three checks guard failures that are otherwise **silent**:
  - GBD age bins still nest inside the DHS disparity bins `[0, 5, 15, 30, 50, 125]`, so
    `data_processing.reindex_series_onto_df_by_age_groups` cannot quietly drop rows.
  - The 30 hardcoded LBWSG categories are still exactly GBD's sub-2500g set. This parses
    the birth-weight interval out of each category's description rather than just checking
    the name exists, which is what makes it catch a renumbering.
  - The `0400` anemia responsiveness lists still account for every anemia sequela GBD
    exposes. A removed sequela already fails loudly (`AttributeError`); an *added* one is
    silent, and this is what makes it loud.

  Each reads the project's assumption from its real source of truth — the notebook or
  constants module that owns it — so the test follows the code if someone edits it. All
  three were verified to fire by deliberately violating them.

- **`test_simulation_plausibility.py`** — asserts transitions that must fire actually do,
  in every scenario, and land inside a wide sanity band. **Needs no baseline**, which is the
  point: the other layers compare against a reference run and so cannot help on a branch
  whose output is legitimately expected to differ — exactly the migration case. Written after
  maternal hemorrhage incidence came out zero on the migration branch, and verified to catch
  a full zero, a single zeroed scenario, and a near-zero (0.04% against an expected 8.4%).

  `ParturitionSelectionTransition.compute_transition_proportion` seeds an all-zero series
  and only fills rows matching `pregnancy == 'parturition'`, so any failure of that filter
  yields zeros with no error. `EXPECTED_ZERO_TRANSITIONS` records
  `postpartum_to_not_pregnant` as zero *by design* — `UntrackNotPregnant` untracks simulants
  on time-step cleanup as soon as they reach `not_pregnant`, and observers filter on
  `tracked` — so nobody "fixes" it by moving it into `MUST_FIRE`.

- **`test_artifact_sanity.py`** — compares two artifacts directly, before any simulation
  runs. The cheapest place to catch a data problem: it localises to a single key in seconds,
  where a pipeline run would show only "the DALYs moved", smeared across two microsims and
  mixed with Monte Carlo noise. Three checks — no key gains `inf`/`NaN`, no key newly goes
  all-zero, and no key's scale moves more than `RATIO_THRESHOLD` (3×) — all framed as
  *regressions against a reference artifact* rather than against an allowlist, because
  whether zero is legitimate is context-dependent (Nigeria has no baseline rice fortification
  programme, so `0.0` is correct there, but bouillon is ~0.52).

  ```bash
  LSFF_ARTIFACT=new.hdf LSFF_REFERENCE_ARTIFACT=known-good.hdf pytest tests/test_artifact_sanity.py
  ```

  Run against a GBD-2023 artifact vs the verified GBD-2021 one it flags four keys, which is
  what it was written for — see "GBD 2023 artifact review" below.

Supporting pieces: `tests/baseline.py` (git-backed reference loading, and the
`STOCHASTIC_RESULTS` classification — anything unlisted is checked exactly, so a new output
file fails loudly until classified) and `tests/reference_proportions.py`.

**Open research question recorded in code:** `KNOWN_UNCOVERED_ANEMIA_SEQUELAE` in
`test_gbd_assumptions.py` lists 26 genetic and endocrine anemias (G6PD deficiency,
hemoglobin H disease, hemoglobin E beta thalassemia, beta thalassemia major, thyroid-related)
that are in `gbd_mapping` but in neither `0400` bucket, as of GBD 2021. They look like they
belong in the non-iron-responsive bucket; omitting them excludes those people from the
population rather than counting them as non-responsive, which biases the responsive
fraction. Needs a decision from whoever owns the anemia model.

**`tests/reference/sim_proportions.csv` is the committed baseline for the stochastic layer**
and is deliberately not gitignored. The raw simulation parquet is gitignored and the
April-2025 run's copies no longer exist, so the proportions had to be snapshotted from a
verified run. Regenerate with `python -m tests.reference_proportions` — but only from a run
you trust, and review the diff, because every future comparison is judged against it.

Gotchas:

- `--runslow` and the `slow`/`cluster` markers come from the `vivarium-testing-utils` pytest
  plugin, not from anything in this repo. That plugin imports `pytest_mock` without declaring
  it, so **`pytest-mock` must be installed or the plugin is silently skipped and `--runslow`
  disappears** — which is why the template README's `pytest --runslow` never worked.
- `vivarium-testing-utils` installs into the modern `vivarium.*` namespace. Do not install it
  into `.venv`, whose old-generation `vivarium` is a regular package, not a namespace package.
  Hence the separate `.test_venv`.
- Importing `vivarium.testing_utils` sets `numpy.seterr(all="raise")`, so latent float
  warnings become errors inside tests.
- The old `assert True` stubs (`tests/test_placeholder.py`,
  `0200_pregnancy_sim/tests/test_sample_0200.py`, `0300_child_sim/tests/test_sample_0300.py`)
  are now redundant and can be deleted.

## Gotchas

- `rule results_plots` (`5000_analyze_results/Snakefile:141`) declares only a `log:` and no
  `output:`, yet `rule all` depends on `5000_analyze_results/executed/results_plots.ipynb`.
  Snakemake 8.16 does resolve this — it schedules `results_plots` when that path is
  requested (verified with `snakemake -n`) — but the rule has no declared output, so don't
  expect normal output-staleness handling from it.
- Snakemake auto-loads `profiles/default` (it prints "Using workflow specific profile
  profiles/default"), which sets `rerun-incomplete: true`. Use `--profile profiles/debug`
  for the debug config.
- Simulation rules do `rm -rf <dir> || true; sleep 5; rm -rf <dir>` — a deliberate
  workaround for NFS delete latency. Don't "simplify" it.
- **Sub-sims must be run in-tree via `PYTHONPATH`, never installed.** The Snakefile
  installs them non-editable and then `pip uninstall`s them, keeping only their
  dependencies, and every rule does `export PYTHONPATH=./src` and invokes
  `python src/.../tools/cli.py` directly. The reason: `constants/paths.py` defines
  `DATA_PREP_RESULTS_ROOT = BASE_DIR/"../../.."/0100_data_prep/results`, which only
  resolves correctly from the in-tree `src/`. A real site-packages install points it inside
  the venv and every CSV load breaks. (Both sub-sims also register a console script named
  `make_artifacts`, so installing both into one env silently shadows one.)
- **Current working directory is load-bearing.** Beyond the relative `-o` paths, `0200`'s
  loader creates a joblib cache at `./.cachedir` and `0300`'s reads `./lbwsg_pafs/...`.
  Rules `cd` into the right place first; replicate that when running anything by hand.
- `0200/constants/data_values.py` reads a CSV **at import time**, so a path problem there
  surfaces as an import failure in unrelated modules.
- **Known latent bugs in the Snakefiles**, all of which currently "work" only because
  tracked files already exist:
  - `0400_non_pregnant_anemia_model`'s rules `mkdir -p ../executed/...` but papermill writes
    to `./executed/...`, so they rely on the committed `executed/` directory and create a
    stray `executed/` at the repo root.
  - `calculate_effective_coverage_ethiopia` in `0100_data_prep/Snakefile` omits the
    `{vehicle}` level from its `mkdir` even though its papermill output path includes it.
    (`0500`'s equivalent rule gets it right — copy that one.)
  - `child_results.ipynb` reads `person_time.parquet`, but `child_results_of_interest` in
    `5000_analyze_results/Snakefile:26` lists only `deaths`/`ylds`/`ylls` — an undeclared
    dependency, so Snakemake won't rebuild when it goes stale.
  - `dalys_by_scenario.ipynb`'s NTD fallback branch reads
    `0500_.../results/india/rice/intervention/ylls_by_scenario.csv`, an old scenario-nested
    layout that `model.ipynb` no longer writes. The stale directory is still in the tree, so
    this silently returns **outdated numbers** rather than failing.
- Ethiopia's folate-only path needs `ruleorder: non_pregnant_anemia_ethiopia_folate >
  non_pregnant_anemia`, and its inputs are derived by string-replacing `iron` → `folate`
  and `.ipynb` → `_folate.ipynb` in the iron input list — fragile if you rename anything.
  Fortificant is baked into notebook filenames and hardcoded output paths rather than
  parameterized.
- **Location coverage is asymmetric on purpose.** Ethiopia has no maternal-mortality DHS
  notebook. India/rice gets special "program rolled out after the baseline estimate year"
  zeroing in three separate places (`non_pregnant_anemia.ipynb`,
  `non_pregnant_anemia_folate.ipynb`, `0500/model.ipynb`). Nigeria alone gets consumption
  interpolation/extrapolation in `prep_extracted.ipynb`. Don't "regularize" these.
- `hces/01_extract_hces.ipynb` writes two CSVs into its own directory
  (`india_proportion_government_rice.csv`, `india_rice_fortifiability_disparities.csv`,
  both tracked) as a hand-off to `prep_extracted.ipynb` — a declared exception to the
  `results/` convention.
- The old project name `vivarium_gates_lsff_by_wealth_quintile` is still hardcoded in
  `archive_last_run.sh`'s destination path and the `Snakefile`'s `pip uninstall` line.
  Renaming packages requires updating both.
- `lsff_utils/snakemake_utils.py` is dead code — nothing imports `dict_to_papermill`. It is
  worth keeping only for the comment explaining the papermill-over-Snakemake decision.
- The three `calculate_effective_coverage_<location>` rules are copy-pasted rather than
  looped because of [snakemake#2178](https://github.com/snakemake/snakemake/issues/2178).
- Sub-simulation *directories* (`0200_pregnancy_sim`) and *package* names
  (`vivarium_gates_lsff_by_wealth_quintile`) do not match, and neither matches the repo
  name. Each sub-sim also has its own boilerplate `README.rst` from an older
  model-template describing a workflow that no longer applies — and describing the wrong
  supported locations ("Paksitan", "only Ethiopia"). Treat both as noise.
- **The sub-sims carry a lot of dead code, and it is not dormant-but-working.**
  `0300/components/wasting.py` is commented out in its entirety; `risk.py` and
  `distribution.py` are commented out of `components/__init__.py`; most of `0300`'s
  `model_spec.yaml` components and `data_keys.py` key groups are commented out;
  `0300/data/loader.py` and `data/utilities.py` reference `paths` attributes that no longer
  exist, and `results_processing/process_results.py` imports a `constants.results` module
  that was never there. Uncommenting a component also requires uncommenting its artifact key
  group, or the sim fails at setup with a missing-key error. Don't assume commented code is
  a feature waiting to be switched on.
- Hardcoded IHME absolute paths are scattered through `constants/paths.py`,
  `0300/data/lbwsg_paf.yaml`, and `0300/model_spec.yaml` (including a personal
  `/ihme/homes/zmbc/...` path). Snakemake overrides the ones that matter with `-i`/`-o`.
- `metadata.CLUSTER_PROJECT` disagrees between the two sims (`proj_simscience_prod` vs
  `proj_simscience`) and is unused — the Snakefiles hardcode `-P proj_simscience`.
- `git-lfs` is not configured, despite `0200_pregnancy_sim/README.rst` describing an
  LFS-based artifact workflow.
- `.github/workflows/update_readme.yml` auto-commits `README.rst` on every push (it
  rewrites the supported-Python-versions line from `python_versions.json`). CI is otherwise
  Jenkins, via the shared `vivarium_build_utils` pipeline in `Jenkinsfile`.

## Reproduction status (verified 2026-07-30, on branch `abie/reproduce-2024-results`)

The April-2025 baseline **was reproduced end-to-end**: `snakemake` ran all 52 jobs to
completion (`results_spreadsheet.xlsx` and `results_plots.ipynb` both produced) at default
(small, 10-seed) scale, after the fixes below. Findings:

- **150 of the 165 tracked result CSVs are byte-identical to the committed baseline.** That
  covers all of `0100_data_prep`, all of `0500_neural_tube_defects_model`, and all of
  Ethiopia's stage-5000 outputs — i.e. the DHS/HCES extraction, coverage calculations, and
  the entire folate pathway through to final results are fully deterministic and still
  reproduce exactly. GBD 2021 (release_id 9), DHS, and forecasted-population access all
  still work.
- **The 15 that differ are exactly the ones downstream of the microsimulations**, and they
  differ only by Monte Carlo noise from running 10 seeds instead of the baseline's 200:
  median relative difference 0.001%–1.2%, max 11.3%. Aggregate DALYs per scenario agree to
  0.25%. The headline DALYs-averted figures agree to 0.00% (india/rice
  baseline→intervention, which is folate-driven and therefore deterministic), 0.23%
  (nigeria/bouillon), 0.83% (india/rice zero→baseline) and 2.59% (nigeria/rice). The few
  cells above 10% are all rare-event `maternal_disorders` DALYs in a single wealth quintile.
  A `--config full_scale=yes` run should tighten these further.
- **The dependency pins have not drifted.** `pip_lock.txt` is byte-identical to the version
  used for the April-2025 run (scipy 1.14.0, numpy 1.26.4, pandas 1.5.3), and all six
  git-pinned vivarium commits are still fetchable from GitHub.
- **`0200_pregnancy_sim` cannot run on `main` at all** — but not because of a bad refactor.
  Commit `82549a7`, unhelpfully labelled "Lint", is *legitimate and correct* migration work
  toward the modern suite: 9 of its 10 rewritten imports resolve cleanly against
  `vivarium-engine` 5.5.3 / `vivarium-public-health` 6.4.7 (verified in a throwaway venv).
  It breaks only because the lockfiles still pin the **old** generation, where
  `vivarium.engine.*` and `vivarium.public_health.*` do not exist. It is also incomplete —
  applied to 2 files, and to 17 of ~36 requirement kwargs.
  **`0200`'s source was restored to `5ab6730` (pre-migration) purely to reproduce the old
  results. That is the opposite direction from the roadmap — do not treat the restore as the
  intended end state.** See "Modernization" below.
- **The pregnancy artifact has never been buildable from scratch.** A cold build hits
  `AttributeError: 'float' object has no attribute 'copy'` in
  `lsff_utils/hemoglobin_distribution.py`'s `pdf`, because `scipy.integrate.quad` calls the
  integrand with a Python float (`loader.py:678`). This was masked because
  `rule pregnancy_artifacts` runs `rm -f artifacts/{vehicle}/{location}.hdf` — a path that
  does not exist — while writing to `mean_draw_artifacts/...` with `-a/--append`, so a
  pre-existing artifact was always topped up rather than rebuilt. Fixed here with an
  `np.atleast_1d` coercion, verified numerically identical on the array path.
  **`hemoglobin_cdf_from_mean_sd` has the same latent fragility**, currently unexercised
  because the `0400` notebooks only pass arrays.
- **The shared GBD cache races under parallelism.** `~/vivarium.yaml` points
  `intermediary_data_cache_path` at `/mnt/team/simulation_science/costeffectiveness/vivarium_cache`.
  Entries there had gone stale (dating to 2024), so joblib invalidated and rewrote them on
  first use; with `--cores 4` concurrent artifact builds collided, producing
  `FileNotFoundError: .../func_code.py`. Warm the cache with a single-process run, or build
  artifacts with `--cores 1`.
- **The India/rice schema-template coupling is a hard blocker, now confirmed.** Ethiopia is
  folate-only and needs no microsimulation, yet `cases_by_scenario` for ethiopia/salt fails
  with `FileNotFoundError: results/rescaled_pregnancy_results/rice/india/person_time_anemia.parquet`.
  The zero-fill fallback reads the India/rice file as a schema template, so **no location's
  stage-5000 results can be produced until India/rice's pregnancy simulation has run**, even
  for locations whose models are entirely independent of it.
- **A failed run deletes committed baseline CSVs.** Snakemake removed the six tracked
  `5000_analyze_results/results/ethiopia/salt/*.csv` baselines when it planned to rerun them,
  and could not regenerate them. Restore with
  `git checkout -- 5000_analyze_results/results/`. Commit or stash before any pipeline run.
- **The DRMAA error from `psimulate` is cosmetic.** `drmaa.errors.InternalException:
  slurm_terminate_job error` surfaces from `vivarium_cluster_tools` 1.6.1 / `drmaa` 0.7.9
  during teardown, but the Slurm array job runs and its results are collected correctly
  (verified: the LBWSG PAF output it produced holds plausible values, 0.89–0.93). Ignore it.
  Note `DRMAA_LIBRARY_PATH` is unset and no `libdrmaa.so` is installed, yet submission works
  — `psimulate` uses `sbatch`/`squeue` for the real work.
- **No archived artifacts exist for the baseline.** The newest directory under
  `/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_by_wealth_quintile/` is
  `2024_08_16`, and `*.hdf`/`*.parquet` are gitignored, so the inputs behind the April-2025
  numbers are not preserved anywhere.
- Following the documented setup breaks the environment: see the `pip install -e .` note in
  the environments section.

## GBD 2023 artifact review (2026-08-03)

Diffed Jim's GBD-2023 maternal artifact
(`/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/artifacts/legacy/maternal/nigeria.hdf`,
read-only — copy before opening, `Artifact` can write) against the verified GBD-2021
`mean_draw_artifacts/rice/nigeria.hdf`. Reproduce with `tests/test_artifact_sanity.py`.

Confirmed good:

- **Maternal hemorrhage incidence is restored.** `cause.maternal_hemorrhage.incident_probability`
  mean 0.0139 with 45 non-zero rows, against 0.0182 and the same 45 rows in GBD 2021. The
  fix in PR #3's `02158e1` works.
- **Data-prep-derived keys are numerically identical** across vintages
  (`vehicle_consumption.*`, fortification coverages, effect sizes) — exactly as they should
  be, since those come from CSVs with no GBD coupling. Only GBD-derived keys moved.
- The GBD 2023 covariate rename landed (`stillbirth_to_live_birth_ratio` →
  `stillbirth_28_weeks_to_live_birth_ratio`).
- **Not a bug:** five `iron_fortification.baseline_*` keys are all-zero, but they are
  all-zero in *both* vintages, and `0100_data_prep/results/iron/rice/baseline_fortification/any_coverage/nigeria.csv`
  is genuinely `0.0` — Nigeria has no existing rice fortification programme. Bouillon is ~0.52.

Open problems, most impactful first:

1. **`cause.maternal_disorders.ylds` is ~187× larger** over childbearing ages (sum 0.000786 →
   0.147; median of finite non-zero rows 332×). Not a plausible revision, and it feeds one of
   the four DALY streams directly, so it would dominate final results.
2. **`risk_factor.hemoglobin.standard_deviation` roughly doubled** (max 16.9 → 36.1 g/L). A
   population hemoglobin SD of 36 is not credible. Because severe anemia is a far-tail
   quantity the error amplifies downstream: `pregnant_proportion_below_70_gL` up 22× to 0.58
   in the worst stratum, and `hemoglobin_on_maternal_hemorrhage.paf` up 11×. Note the SD's own
   median movement is *below* the 3× threshold so it is not itself flagged — it is the likely
   upstream cause of two keys that are. Produced by `get_hemoglobin_data` from me_ids
   10487/10488, one of the six `.fillna(0)` loaders.
3. **`cause.maternal_disorders.ylds` carries 8 `inf` values in both vintages**, from dividing
   by a zero maternal-disorders incidence at ages 60+. `.fillna(0)` catches NaN, not `inf`.
   Harmless while the sim runs ages 10–54, but latent.
4. `cause.maternal_abortion_and_miscarriage.raw_incidence_rate` moved 4.8× — flagged for
   review, less obviously wrong than the above.

Every other key moved within 0.47×–2.7×, an ordinary GBD-revision range. That contrast is
what makes the ratio check informative.

## Modernization: modern Vivarium + GBD 2023

**Upgrading the suite and moving to GBD 2023 are the same task.** The pinned
`vivarium_gbd_access` 4.0.6 hardcodes `release_id=RELEASE_IDS.GBD_2021` in eight-plus places
and its `RELEASE_IDS` has no `GBD_2023` member; the modern `vivarium-gbd-access` 6.0.2 sets
`CURRENT_RELEASE_ID = GBD_2023` (release 16). Verified 2026-07-30: the modern stack installs
here in ~85s and a live GBD 2023 query works.

Namespace map for the modern suite (all verified by import):

| old | new |
|---|---|
| `vivarium.framework.X` | `vivarium.engine.framework.X` |
| `from vivarium import Component` | `from vivarium.engine import Component` |
| `vivarium_public_health.X` | `vivarium.public_health.X` |
| `vivarium.framework.artifact` | `vivarium.artifact` |
| `gbd_mapping` | `vivarium.gbd_mapping` |
| `risk_distributions` | `vivarium.risk_distributions` |

**Watch out:** both `main` and `albrja/mic-7325/framework-updates-pt1` use
`requires_attributes`, but released `vivarium-engine` 5.5.3 takes **`required_resources`** on
`register_value_producer`/`register_value_modifier`, and `Component` no longer has
`columns_created`, `columns_required`, or `initialization_requirements` at all (64 usages
across the two sims). Reconcile against 5.5.3 before doing more migration work, or it gets
done twice. `vivarium.public_health.utilities.get_lookup_columns` is also gone — the branch
adds a local shim built on `LookupTable.lookup_attributes`.

Three GBD-2023 risks that fail *silently* rather than loudly:

1. `0400_non_pregnant_anemia_model/non_pregnant_anemia.ipynb` splits ~198 named
   `gbd_mapping.sequelae` into iron-responsive (138) and non-responsive (60). A renamed or
   removed sequela raises `AttributeError`; an **added** one is silently omitted from both
   buckets and shifts the responsiveness split.
2. `src/lsff_utils/data_processing.py` notes "Depends on a GBD age group always fitting into
   a disparity age group." If GBD 2023 age bins straddle a DHS bin edge
   (`[0, 5, 15, 30, 50, 125]`), the disparity join drops rows without erroring.
3. `0300_child_sim/.../constants/data_values.py` hardcodes 30 LBWSG `catNN` strings; LBWSG
   category numbering is not stable across rounds.

Also: `auxiliary_data/` only goes up to `GBD_2021`, so the anemia disability weights the
`0400` notebooks read have no 2023 equivalent on disk; and constants are duplicated across
files and must move together (hemoglobin me_ids 10487/10488 in 3 places, Ethiopia folate
intake in 2, `fortification_mcg_to_dfe` in 2).

**Defuse before migrating, not during:** `0300_child_sim/.../constants/metadata.py` defines
`GBD_2021_ROUND_ID = 7` and passes it as a `gbd_release_id`, but release 7 is `GBD_2019_IT`
(GBD 2021 is 9). It is currently harmless — `reshape_gbd_2019_data_as_gbd_2021_data` has no
callers and the `use_2019_data_keys` routing is fully commented out — but it is a trap for
anyone re-enabling those keys. The child sim already bridges two GBD rounds; going to 2023
makes three, so decide whether to extend or delete that machinery.

Genuinely clean, needs no round work: `0100_data_prep/coverage_calculation/`,
`extraction/prep_*.ipynb` (no GBD coupling at all), and the `5000_analyze_results` notebooks
plus `0100_rescale_results/*` (they call `vivarium_inputs` without pinning a round, so they
follow the library default).

## Filesystem safety (IHME)

This repo lives on IHME shared storage (`/mnt/share` and `/ihme` are the same mount).
Writes under `/mnt/share/homes` / `/ihme/homes` are fine. Everything else under
`/mnt/share`, `/ihme`, `/home/j`, `/snfs1` — including the
`/mnt/team/simulation_science/pub/models/` archive target — is read-only by default:
never delete, move, overwrite, or rename there. Copy to a local working directory instead.
