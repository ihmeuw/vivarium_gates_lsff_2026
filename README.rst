===============================
vivarium_gates_lsff_2026
===============================

Vivarium simulation model for the vivarium_gates_lsff_2026 project.

**Note: It is not yet possible to run this simulation outside of the IHME network.**
This is because it has not yet been "archived," which means that the input data
necessary are only accessible within IHME.
We usually archive a simulation when development is complete.

.. contents::
   :depth: 1

Installation
------------

Open up your normal shell
(if you're on linux or OSX) or the ``git bash`` shell if you're on Windows.
First, clone this repository::

  :~$ git clone https://github.com/ihmeuw/vivarium_gates_lsff_2026.git
  ...git will copy the repository from github and place it in your home directory...
  :~$ cd vivarium_gates_lsff_2026

You will need ``conda`` to install all of this repository's requirements.
We recommend installing `Miniforge <https://github.com/conda-forge/miniforge>`_.
The platform-specific instructions for installation can be found at that link.
Once you have ``conda`` installed, you are ready to proceed.

Currently, the process of making artifacts and running simulations requires
two distinct environments.
**Note that it will not be possible to create the environment for making artifacts
unless you are on the IHME network.**
We call these the "artifact" and "simulation" environments.

There are two environment options: a **local conda environment** (for personal
machines) or a **shared environment on the cluster** with a lightweight venv wrapper.

To create or update an environment, use ``source environment.sh``. This will
automatically create the environment if it doesn't exist.

**Local conda environment** (default)::

  :~$ source environment.sh
  ...creates/activates the simulation conda environment...
  :~$ source environment.sh -t artifact
  ...creates/activates the artifact conda environment...

Local conda environments are automatically rebuilt if they are stale (older
than a week). To deactivate a local conda environment, run ``conda deactivate``.

**Shared environment on the cluster** (recommended for cluster development)::

  :~$ source environment.sh -s
  ...creates/activates a venv overlay on the shared simulation environment...
  :~$ source environment.sh -s -t artifact
  ...creates/activates a venv overlay on the shared artifact environment...

To deactivate a shared cluster environment, run ``deactivate``.

The shared environments are conda environments built nightly by Jenkins;
``source environment.sh -s`` layers a lightweight virtual environment on top
of one, with this repository installed in editable mode. Note that this
requires the repository to have been added to the Jenkins shared-environment
nightly build; until then (or if the shared environment is otherwise
unavailable), use the local conda environment instead.

Additional options are available; pass the ``-h`` flag to see them
(e.g. ``-f`` to force a rebuild, ``-l`` to install git lfs).
The underlying ``make`` targets can also be run directly: ``make build-env``
and ``make build-shared-env``; see the ``help`` target in the ``Makefile``
for their arguments.

Supported Python versions: 3.10, 3.11, 3.12

The Modeling Pipeline
---------------------

This repository holds two simulations that run in sequence. The maternal model
(``0200_pregnancy_sim``) simulates pregnancies and emits a birth record for each
one; the child model (``0300_child_sim``) turns those birth records into its own
starting population, one simulant per birth. The child model therefore cannot be
built or run until the maternal model has produced results.

Six stages, in order. Each depends on the output of the one before it::

    0100_data_prep notebooks
             |  (CSVs in 0100_data_prep/results/)
             v
    1. maternal artifact  ---------->  artifacts/<n>/maternal/<location>.hdf
             |
             v
    2. maternal simulation  -------->  results/<n>/maternal/<location>/<run>/
             |                             (births, deaths, ylds, ...)
             |
             |    3. LBWSG PAF artifact  -->  data/<n>/lbwsg_paf_artifacts/<location>.hdf
             |               |
             |               v
             |    4. LBWSG PAF simulation ->  data/<n>/lbwsg_pafs/<location>/<run>/
             |               |
             v               v
    5. child artifact  ------------->  artifacts/<n>/child/<location>.hdf
             |
             v
    6. child simulation  ----------->  results/<n>/child/<location>/<run>/

Stages 3 and 4 exist because the child model needs a custom population attributable
fraction for low birth weight and short gestation. It is calculated by running a
small, separate simulation, which needs an artifact of its own -- one holding a
different key set from the full child artifact, since it omits the very PAF the
calculation produces. Stages 3-4 do not depend on the maternal model and can run
at the same time as stages 1-2.

Everything the pipeline reads or writes on the shared drive lives under a single
root, organized by kind and then by model iteration::

    /mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/
    |-- artifacts/<MODEL_NUMBER>/{maternal,child}/
    |-- data/<MODEL_NUMBER>/{lbwsg_paf_artifacts,lbwsg_pafs}/
    `-- results/<MODEL_NUMBER>/{maternal,child}/

``MODEL_NUMBER`` is defined once, in ``src/lsff_utils/paths.py``, and both
simulation packages read it from there. See "Starting a New Model Iteration"
below.

Making Artifacts
----------------

As noted above, it is not possible to make artifacts unless you are on the IHME network.
If you are not on the IHME network, you will be limited to running simulations from pre-made
artifacts; see the next section for how to do this.

Artifacts are built with ``make_artifacts``, which takes a ``-p/--project`` flag
selecting which model to build for. Activate the artifact environment first
(``source environment.sh -t artifact``, plus ``-s`` for a shared environment).
One artifact environment serves both projects.

To add a location, add it to the ``LOCATIONS`` constant in that project's
``constants/metadata.py``.

With no ``-o``, each build writes to the right root for the current
``MODEL_NUMBER``, so ``-o`` is only needed to write somewhere else.

**Stage 1 -- maternal artifact**::

  (artifact) :~$ make_artifacts -p maternal -l nigeria --vehicle rice -vvv

**Stage 3 -- LBWSG PAF artifact** (the cut-down artifact feeding the PAF calculation)::

  (artifact) :~$ make_artifacts -p child -l nigeria --for-lbwsg-pafs --national -vvv

**Stage 5 -- child artifact**. This is the one with upstream dependencies: it
reads the maternal birth records and the PAF results. Name the maternal run
explicitly so the artifact records which run it came from::

  (artifact) :~$ make_artifacts -p child -l nigeria --vehicle rice --national -vvv \
      --fertility-data-path /mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/results/legacy_1.0/maternal/nigeria/<run>/results/births

The PAF results are found automatically under ``data/<n>/lbwsg_pafs/``; the build
logs which run it used, and it takes the most recent, so check that line if more
than one run is present.

Flags worth knowing:

``--national``
  Build national rather than subnational data. The historical pipeline passed
  this for both child artifacts.
``--mean``
  Collapse all draws to their mean in a single ``draw_0`` column. Much faster and
  smaller, but the resulting artifact cannot support a draw sweep.
``-a/--append``
  Keep keys already present instead of rebuilding them. Convenient while
  iterating on one loader, but it silently retains stale data when a
  configuration change (a new GBD release, say) should have invalidated it.
  Prefer a clean build when anything other than a single loader has changed.

Running Simulations
-------------------

Each simulation is described by a model specification, a `YAML
<https://en.wikipedia.org/wiki/YAML>`__ file you can edit to change what runs.
See
https://vivarium-engine.readthedocs.io/en/latest/concepts/model_specification/index.html

Each specification names the artifact it runs against in its ``input_data``
section, already pointed at the current iteration's artifact, so no ``-i`` is
needed unless you want a different one. The specifications are:

Stage 2 -- maternal simulation
  ``0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/model_spec.yaml``

Stage 4 -- LBWSG PAF calculation
  ``0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf.yaml``

Stage 6 -- child simulation
  ``0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/model_spec.yaml``

With the simulation environment active (``source environment.sh``), run a single
simulation -- one draw, one seed, one scenario -- with ``simulate run``::

  (simulation) :~$ simulate run <model_spec.yaml> -o <output_dir> -vvv

Add ``--pdb`` to drop into the debugger on failure. ``-vvv`` logs every time step.

**On the IHME cluster**, run draws, seeds, and scenarios in parallel with
``psimulate`` and a branches file::

  (simulation) :~$ psimulate run <model_spec.yaml> <branches.yaml> -o <output_dir> \
      -P proj_simscience -m 2 -r 01:00:00 -q all.q -v

Stages 2 and 6 each have a full-size and a small branches file, both living in
``model_specifications/branches/`` of their package. Start with the small one:

``scenarios_small.yaml``
  30 jobs -- 1 draw x 10 seeds x 3 maternal scenarios.

``scenarios.yaml``
  600 jobs -- 1 draw x 200 seeds x 3 maternal scenarios.

Stage 4 uses ``data/lbwsg_paf_branches.yaml``, a single draw and seed.

``psimulate`` writes one parquet per task into a directory per metric,
``<run>/results/<metric>/<task_id>.parquet``, injecting ``input_draw``,
``random_seed``, and ``scenario`` as columns. ``pd.read_parquet`` on the metric
directory concatenates them. ``simulate run`` instead writes a single
``<run>/results/<metric>.parquet``. Code that reads results handles both.

If some tasks fail, ``psimulate restart <run_dir>`` reruns only those.

Note that stages 2 and 6 sweep the same three maternal scenarios, and the child
model filters birth records by scenario and seed. A child job whose
``(scenario, random_seed)`` pair is missing from the maternal results initializes
an empty population and writes empty results *without failing*, so confirm that
every task produced non-empty output rather than relying on the job count.

Starting a New Model Iteration
------------------------------

Bump ``MODEL_NUMBER`` in ``src/lsff_utils/paths.py``. That repoints every
artifact, data, and results root at once, so the pipeline writes to fresh
directories and the previous iteration stays intact for comparison.

Three model specifications hardcode their artifact path, because YAML cannot read
the constants. Update the ``artifact_path`` in each:

- ``0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/model_spec.yaml``
- ``0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/model_spec.yaml``
- ``0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf.yaml``

``tests/test_paths.py`` fails if any of these disagrees with
``lsff_utils.paths``, so a forgotten update is caught by the test suite rather
than by a simulation quietly running against the previous iteration's artifact.

Then work through stages 1-6 above. Prefer bumping ``MODEL_NUMBER`` to deleting a
previous iteration: it costs disk but keeps a baseline to compare against, which
is what tells you whether a change in results is real.

Running Tests
-------------

You can run tests with::

  (vivarium_gates_lsff_2026_simulation) :~/vivarium_gates_lsff_2026$ pytest --runslow
  ...pytest will run all tests in the tests directory...

It may be the case that a different set of tests will run, depending on whether you are in the artifact
or simulation environment.
To be safe, it is best to run the tests in both environments.

Repository Layout
-----------------

Work is split into numbered stages, each a directory at the repository root::

    0050_config/       shared configuration (fortificants, intervention scenarios)
    0100_data_prep/    extraction and preparation notebooks; writes results/ CSVs
    0200_pregnancy_sim/ maternal simulation (vivarium_gates_lsff_2026_maternal)
    0300_child_sim/    child simulation (vivarium_gates_lsff_2026_child)
    0400_non_pregnant_anemia_model/  standalone analysis notebooks
    0500_neural_tube_defects_model/  standalone analysis notebooks
    5000_analyze_results/            results processing

The two simulation stages are installable packages, each with its own ``src/``,
``tests/``, and ``setup.py``. ``src/`` at the repository root holds two smaller
packages: ``lsff_utils``, shared helpers and the path constants both simulations
read, and ``vivarium_gates_lsff_2026``, which provides the ``make_artifacts``
command and dispatches to whichever project ``-p`` names.