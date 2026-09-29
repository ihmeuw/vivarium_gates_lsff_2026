===============================
vivarium_gates_lsff_2026
===============================

Vivarium model for large-scale food fortification: data prep, a maternal
simulation, a child simulation, and results processing. Snakemake runs every
stage in order and skips the ones that are already up to date.

It only runs inside the IHME network.

.. contents::
   :depth: 1

Setup
-----

::

  git clone https://github.com/ihmeuw/vivarium_gates_lsff_2026.git
  cd vivarium_gates_lsff_2026
  source environment.sh -t artifact    # build the artifact environment
  source environment.sh                # build the simulation environment and activate it
  snakemake --version                  # check it works

* Add ``-f`` to rebuild an environment, for example ``source environment.sh -f``.
* On the cluster, add ``-s`` to both commands to use the shared environment.
* Always run Snakemake from the simulation environment. It switches to the artifact
  environment by itself when a stage needs it.

Running the model
-----------------

1. Set ``MODEL_NUMBER`` in ``src/lsff_utils/paths.py``. This is the label the run is
   archived under in step 6.
2. Delete what you want rebuilt (see the table below).
3. Start ``tmux`` and an ``srun``. Request enough time for the whole run, because
   the simulations stop early without an error if the ``srun`` runs out of time.
4. Dry run, and check the job table::

     snakemake -n --quiet rules -c1 --config full_scale=true skip_data_prep=true

5. Real run::

     snakemake -c1 -k --config full_scale=true skip_data_prep=true

6. Archive the results to the team drive::

     ./archive_last_run.sh -n    # show what would be copied
     ./archive_last_run.sh

What to delete
~~~~~~~~~~~~~~

Snakemake only rebuilds what is missing, so deleting output is how you ask for
a stage to be redone.

========================================  =======================================================
To redo                                   Delete
========================================  =======================================================
Both simulations (usual rerun)            ``0200_pregnancy_sim/sim_results``
                                          ``0300_child_sim/sim_results``
                                          ``0300_child_sim/mean_draw_artifacts``
                                          ``0400_non_pregnant_anemia_model/results``
Maternal artifact                         ``0200_pregnancy_sim/mean_draw_artifacts``
(GBD data or maternal loader changed)
LBWSG PAFs (takes hours; rarely needed)   ``0300_child_sim/lbwsg_paf*``
Hemoglobin PAF cache                      ``.cachedir``
(hemoglobin PAF loader changed)
Analysis only                             Nothing. Add ``--forcerun dalys_by_scenario cases_by_scenario``
========================================  =======================================================

* Always delete the two ``sim_results`` directories together. If they don't
  match, the child results come out empty with no error.
* Archive the last run before deleting it, because these directories are the only
  copy.
* In the dry run, ``lbwsg_pafs`` and ``pregnancy_artifacts`` should appear only if
  you deleted their outputs.

Snakemake flags
~~~~~~~~~~~~~~~

Put ``--config`` settings last. Everything after ``--config`` is read as a setting.

==============================================  ==========================================================
Flag                                            Effect
==============================================  ==========================================================
``--config full_scale=true``                    Real run with 200 seeds. Without it you get 10 seeds.
``--config skip_data_prep=true``                Use the committed data prep CSVs as they are. Leave it off
                                                only if you changed the extraction sheet or a data prep
                                                notebook.
``--config debug=true``                         One draw and one seed, in the foreground, with a debugger.
``-c1`` (short for ``--cores 1``)               Run one Snakemake job at a time. Include it in every command.
                                                The simulations still run in parallel on the cluster through
                                                ``psimulate``.
``-n``                                          Dry run: show what would run.
``--quiet rules``                               Only print the job table (use with ``-n``).
``-k``                                          Keep going when one job fails.
``--rerun-triggers mtime``                      Decide what to rerun from file timestamps only. Use it when
                                                the dry run lists data prep jobs, such as
                                                ``calculate_effective_coverage_*``, after a combination was
                                                added to the config.
``--forcerun <rule>``                           Redo one stage, e.g. ``--forcerun dalys_by_scenario``.
``--forceall``                                  Redo everything, data prep included.
``--until <rule>``                              Stop after one stage, e.g. ``--until pregnancy_simulations``.
``<file path>``                                 Build one output and what it needs, e.g.
                                                ``0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf``.
``--unlock``                                    Clear the lock left by a crashed or killed run.
==============================================  ==========================================================

``true`` can also be written ``t``, ``yes`` or ``y``. ``full_scale=1`` gives you the
small run.

Example commands
~~~~~~~~~~~~~~~~

When you are ready to run, do a dry run first. It prints a table of how many jobs
each stage will run, and nothing is run::

  snakemake -n --quiet rules -c1 --config full_scale=true skip_data_prep=true

Check that the stages you deleted appear in the table and that nothing you meant to
keep does. If the table looks right, run the same command without ``-n --quiet
rules``::

  snakemake -c1 -k --config full_scale=true skip_data_prep=true

To test one arm before a full run, give the file you want built, for example::

  snakemake -c1 --config skip_data_prep=true -- 0200_pregnancy_sim/mean_draw_artifacts/wheat/nigeria.hdf

If something goes wrong
-----------------------

* **A stage failed.** Read the log path Snakemake prints, fix the problem, and run
  the same command again. Finished stages are not redone.
* **Some simulation jobs failed.** Run ``psimulate restart <run directory>``. The
  run directory is the timestamped one under ``sim_results/``.
* **Checking a simulation run finished.** Run
  ``grep -hE "Workflow finished with status|failed job" <run directory>/logs/*/main.log``.
  A full-scale run should report 600 of 600 jobs.
* **Results are empty or all zero.** The maternal and child runs don't match.
  Delete both ``sim_results`` directories and rerun.
* **"Directory is locked".** Run ``snakemake --unlock``, then your command again.
* **It wants to rerun something you expected it to keep.** Add
  ``--config skip_data_prep=true``. If the dry run still lists data prep jobs, also
  add ``--rerun-triggers mtime``. If that doesn't fix it, ask an engineer before
  starting a long run.

Tests
-----

::

  pytest --runslow

Run them in both environments if you change shared code.

Supported Python versions: 3.11, 3.12
