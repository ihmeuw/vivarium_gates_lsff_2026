===============================
vivarium_gates_lsff_2026
===============================

Vivarium simulation model for the vivarium_gates_lsff_2026 project: a maternal
simulation and a child simulation, with data prep before them and results
processing after them.

One command runs the whole thing. **Snakemake** works out which pieces are
missing or out of date, runs only those in the right order, and activates the
right environment for each one. You do not run the stages yourself.

**Note: this can only be run inside the IHME network**, because the input data
are only accessible there.

.. contents::
   :depth: 1

Setup
-----

Clone the repository::

  :~$ git clone https://github.com/ihmeuw/vivarium_gates_lsff_2026.git
  :~$ cd vivarium_gates_lsff_2026

You need ``conda``; we recommend `Miniforge
<https://github.com/conda-forge/miniforge>`_.

There are two environments and you need **both**. ``artifact`` is used by every
stage that reads GBD; ``simulation`` is used by the stages that run the
simulations. Snakemake switches between them for you -- you just have to have
built them once.

``source environment.sh`` builds an environment if it does not exist yet, then
activates it::

  :~$ source environment.sh -t artifact   # build the artifact environment
  :~$ source environment.sh               # build the simulation environment

On the cluster, add ``-s`` to both commands to layer a small virtual environment
on top of the nightly shared environment instead of building your own copy::

  :~$ source environment.sh -s -t artifact
  :~$ source environment.sh -s

Deactivate with ``conda deactivate`` (or ``deactivate`` if you used ``-s``).
Local conda environments rebuild themselves automatically once they are more
than a week old; ``-f`` forces a rebuild sooner.

Run Snakemake from the simulation environment, and check that it is there before
you start::

  (simulation) :~$ snakemake --version

If that errors, rebuild the environment with ``source environment.sh -f``.

What the pipeline does
----------------------

The maternal model simulates pregnancies and writes one birth record per
pregnancy. The child model turns those birth records into its own population,
one simulant per birth -- so the child model cannot run until the maternal model
has finished. Six stages, in order::

    0100_data_prep notebooks
             |  (CSVs in 0100_data_prep/results/)
             v
    1. maternal artifact  ---------->  0200_pregnancy_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
             |
             v
    2. maternal simulation  -------->  0200_pregnancy_sim/sim_results/<vehicle>/<location>/<run>/
             |                             (births, deaths, ylds, ...)
             |
             |    3. LBWSG PAF artifact  -->  0300_child_sim/lbwsg_paf_mean_draw_artifacts/<location>.hdf
             |               |
             |               v
             |    4. LBWSG PAF simulation ->  0300_child_sim/lbwsg_pafs/<location>/<run>/
             |               |
             v               v
    5. child artifact  ------------->  0300_child_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
             |
             v
    6. child simulation  ----------->  0300_child_sim/sim_results/<vehicle>/<location>/<run>/

Then ``5000_analyze_results`` rescales and combines everything into
``5000_analyze_results/results_spreadsheet.xlsx`` and the plots in
``5000_analyze_results/executed/results_plots.ipynb``. Those two files are what
the pipeline is for; asking for them is what pulls every stage in behind them.

Stages 3 and 4 compute a population attributable fraction the child model needs
and GBD does not publish. **They are the most expensive part of the pipeline**,
they do not depend on the maternal model, and they rarely need redoing -- so
leave their output alone unless the PAFs themselves changed.

Everything is written inside the repository, next to the package that produced
it, at the paths in the diagram above. None of it is committed to git.

Running a model iteration
-------------------------

Five steps. Steps 1-3 take a minute; step 4 takes hours.

Step 1: bump the model number
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit ``MODEL_NUMBER`` in ``src/lsff_utils/paths.py``, e.g. from ``model1.2.1`` to
``model1.3``. That is the only edit, and it labels the results this iteration
will publish in step 5.

Bump it **before** you run anything. Nothing in the repository carries the
number, so bumping it does not move or rebuild anything by itself -- it just
decides where step 5 files the results.

Step 2: delete what should be rebuilt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Snakemake only rebuilds what is missing or out of date, so deleting a directory
is how you say "redo this". For a full rerun of both simulations::

  :~$ rm -rf 0200_pregnancy_sim/sim_results 0300_child_sim/sim_results
  :~$ rm -rf 0300_child_sim/mean_draw_artifacts
  :~$ rm -rf 0400_non_pregnant_anemia_model/results

Add these only when they apply:

``rm -rf 0200_pregnancy_sim/mean_draw_artifacts``
  Rebuilds the maternal artifact. Needed if GBD data or the maternal
  ``data/loader.py`` changed.
``rm -rf 0300_child_sim/lbwsg_paf*``
  Recomputes the LBWSG PAFs (stages 3 and 4). Hours of work -- only if the PAFs
  themselves must change.
``rm -rf .cachedir``
  Clears a cache the maternal artifact build keeps. Needed if the hemoglobin PAF
  loader changed, because editing it does not invalidate the cache.

Two things to know here:

* **Delete both ``sim_results`` directories together**, not just the child's. The
  child model matches its population to the maternal results by scenario and
  seed; if the two runs were made at different scales, the mismatched child jobs
  quietly produce empty results instead of failing.
* **If your last iteration has not been archived yet, archive it first** (step 5)
  -- these directories are the only copy until you do.

Step 3: dry run
~~~~~~~~~~~~~~~

Always do this first. ``-n`` shows what would run without running any of it::

  (simulation) :~$ snakemake -n -q -c1 --config full_scale=true skip_data_prep=true

You get a table of rules and how many jobs of each. Read it before committing
hours, and check:

* **The stages you deleted are there.** If something you meant to redo is
  missing, its old output is still on disk.
* **``lbwsg_pafs`` and ``artifact_for_lbwsg_pafs`` are absent**, unless you
  deliberately deleted the PAF directories. If they appear unexpectedly, ask
  before spending the time.
* **``pregnancy_artifacts`` is absent**, if you did not mean to rebuild the
  maternal artifact.

Step 4: run it
~~~~~~~~~~~~~~

Same command without ``-n``::

  :~$ tmux new -s lsff
  :~$ source environment.sh
  (simulation) :~$ snakemake -c1 -k --config full_scale=true skip_data_prep=true

A full-scale run takes hours, and the simulation stages submit their own cluster
jobs and wait on them. So:

* Run it **on a cluster submit host**, from inside ``tmux`` (or ``screen``), so it
  survives losing your connection.
* Do **not** run it inside an ``srun`` or ``salloc`` session. That silently cuts
  the simulations short without reporting an error.

If a stage fails, everything downstream of it stops and the finished stages are
left alone -- fix the problem and run the same command again to pick up where it
stopped.

Step 5: archive the results
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Publishing to the team drive is the last step. Until you do it, the iteration
exists only in your working copy::

  :~$ ./archive_last_run.sh -n     # show what would be published
  :~$ ./archive_last_run.sh

This files everything under the ``MODEL_NUMBER`` from step 1, at
``/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/``. Already
published runs are never overwritten, so re-running it is safe.

Options
-------

Options are added to the same ``snakemake`` command. Put the ``--config`` ones at
the end -- everything after ``--config`` is read as a setting::

  (simulation) :~$ snakemake -c1 -k --config full_scale=true skip_data_prep=true

``--config full_scale=true``
  **Use this for a real run.** Without it you get a small trial run: 10 random
  seeds per simulation instead of 200. Only ``true``, ``t``, ``yes`` and ``y``
  count as true -- ``full_scale=1`` silently gives you the small run.
``--config skip_data_prep=true``
  Take the data prep CSVs in ``0100_data_prep/results/`` as given. Use this
  unless you changed a data prep notebook or the extraction workbook: git can
  make those CSVs look out of date when they are not, which otherwise reruns
  data prep and everything after it. Genuinely missing CSVs are still built.
``--config debug=true``
  Run one simulation at a time in the foreground, one draw and one seed, and
  drop into a debugger if it crashes. For chasing an error, not for results.
``-n``
  Dry run: print what would run and stop. Add ``-q`` for just the summary table.
``-k``
  Keep going after a failure, so one broken location does not stop the others.
``--forcerun dalys_by_scenario cases_by_scenario``
  Redo just the analysis notebooks -- the DALYs and case counts and the
  spreadsheet and plots built from them -- reusing the existing simulation
  results. Useful when only the analysis changed.
``--forceall``
  Redo absolutely everything, data prep included.
``<a file path>``
  Build one thing and only what it needs, e.g.
  ``snakemake -c1 0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf``.
  Good for testing one location.
``--until <rule name>``
  Stop after that stage, for every location. E.g.
  ``--until pregnancy_simulations``.

If something goes wrong
-----------------------

**A stage failed.** Read the log path Snakemake prints, fix it, and re-run the
same command. Finished stages are not redone.

**Some simulation jobs failed but Snakemake moved on.** Run
``psimulate restart <run directory>`` by hand; it reruns only the failed jobs.
The run directory is the timestamped one under ``sim_results/``.

**Results look empty or all zero.** Usually a scale mismatch between the maternal
and child runs -- see step 2. Delete both ``sim_results`` directories and rerun.

**Snakemake says the directory is locked** after a crash or a kill: run
``snakemake --unlock`` once, then re-run your command.

**It wants to rerun something you expected it to keep.** Nothing is broken;
something it reads looks newer than the output. ``--config skip_data_prep=true``
covers the common case. Otherwise ask an engineer before starting a long run.

Tests
-----

::

  (simulation) :~$ pytest --runslow

A different set of tests runs in the artifact and simulation environments, so run
them in both if you are changing shared code.

Repository layout
-----------------

::

    0050_config/       shared configuration (locations, vehicles, scenarios)
    0100_data_prep/    extraction and preparation notebooks; writes results/ CSVs
    0200_pregnancy_sim/ maternal simulation
    0300_child_sim/    child simulation
    0400_non_pregnant_anemia_model/  standalone analysis notebooks
    0500_neural_tube_defects_model/  standalone analysis notebooks
    5000_analyze_results/            results processing, spreadsheet and plots
    Snakefile          the workflow; one more per numbered directory

Supported Python versions: 3.11, 3.12
