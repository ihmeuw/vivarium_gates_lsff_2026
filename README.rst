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

There are exactly two environments -- one ``simulation`` and one ``artifact`` --
and each contains **both** simulation packages, so the same environment serves
the maternal and child models.

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
for their arguments. ``make build-env`` also accepts ``p=<maternal|child>`` to
install only one of the two simulation packages.

Supported Python versions: 3.11, 3.12

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

Stages 3 and 4 exist because the child model needs a custom population attributable
fraction for low birth weight and short gestation. It is calculated by running a
small, separate simulation, which needs an artifact of its own -- one holding a
different key set from the full child artifact, since it omits the very PAF the
calculation produces. Stages 3-4 do not depend on the maternal model and can run
at the same time as stages 1-2.

Where the pipeline writes
~~~~~~~~~~~~~~~~~~~~~~~~~

The pipeline writes **inside the repository**, beside the package that produces
each thing::

    0200_pregnancy_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
    0200_pregnancy_sim/sim_results/<vehicle>/<location>/<run>/
    0300_child_sim/mean_draw_artifacts/<vehicle>/<location>.hdf
    0300_child_sim/sim_results/<vehicle>/<location>/<run>/
    0300_child_sim/lbwsg_paf_mean_draw_artifacts/<location>.hdf
    0300_child_sim/lbwsg_pafs/<location>/<run>/

All six are defined in ``src/lsff_utils/paths.py``, which both simulation
packages, every Snakemake rule and every notebook read from -- nothing hardcodes
these locations. All six are gitignored: they hold large binaries and
``psimulate``'s per-run metadata, none of which belongs in version control.

Artifacts sit one level below their root, in a directory per fortification
vehicle: the same location is built once per vehicle, and the artifacts would
otherwise collide on a single filename.

Simulation output is never flattened or overwritten. ``psimulate`` names each run
for the artifact it ran against and the moment it was launched, so a rerun adds
``<location>/<run>/`` alongside the previous runs rather than replacing them, and
the run a validated set of results was built from stays where it was. Code that
reads results resolves the run to use through ``lsff_utils.paths.latest_run``.

Nothing in these paths carries a model iteration number. The repository holds the
run you are working on; the archive holds the versioned record.

Where a finished run goes
~~~~~~~~~~~~~~~~~~~~~~~~~

``./archive_last_run.sh`` publishes what is in the repository to the team drive,
filed under ``MODEL_NUMBER``::

    /mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/
    |-- artifacts/<MODEL_NUMBER>/{maternal,child}/<vehicle>/<location>.hdf
    |-- data/<MODEL_NUMBER>/{lbwsg_paf_artifacts,lbwsg_pafs}/
    `-- results/<MODEL_NUMBER>/{maternal,child}/<vehicle>/<location>/<run>/

The repository groups outputs by the package that produced them; the archive
groups them by kind and iteration, so ``lsff_utils.paths.ARCHIVE_DESTINATIONS``
declares the mapping between the two. This is what makes a run visible
to anyone but you, and what lets two iterations be compared: every model number
sits alongside the others, so reading two of them is two paths rather than two
checkouts.

Simulation output is archived one run at a time -- the run each
``latest_run.txt`` names, which is the run Snakemake considers current and the
one the downstream stages consumed. Whole run directories are copied, not just
the parquet: they carry ``psimulate``'s ``model_specification.yaml``,
``branches.yaml``, ``keyspace.yaml`` and ``requirements.txt``, plus the
``git_commit.txt`` the simulation rules write.

The archive is **append-only**. ``rsync --ignore-existing`` means an already
published run or artifact is never overwritten, because a previous iteration's
results may depend on it. Re-archiving after a rerun adds the new timestamped run
beside the old one; to replace something already published, bump ``MODEL_NUMBER``
or remove the destination by hand, deliberately.

``-n`` shows what would be copied without changing anything.

Knowing what produced a run
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two files make an archived run traceable back to the code that produced it.

``git_commit.txt``, written into the run directory by the simulation rules at the
moment the run succeeds, records the commit, the branch, and -- when the tree was
dirty -- the diff. It has to be written then rather than at archive time: HEAD
moves, and the archive would otherwise record the commit it was published from
instead of the one that produced the results. Nothing stops Snakemake running
against a dirty tree, so the diff is what makes such a run reproducible at all.

``model_specification.yaml`` records the artifact the run used. In the repository
that is a path inside your working tree, which is meaningless to anyone else and
gone once the repo is cleared for the next iteration, so the archive repoints the
archived copy at the archived artifact and keeps the original value as a comment
above it. Only that line is rewritten; the rest of the file is untouched. The
copy in your working tree is left exactly as ``psimulate`` wrote it.

Running the Pipeline
--------------------

There are two ways to run this, and they do the same thing:

**By hand, a stage at a time.** The six stages below, in order. Each names what
it does, what it reads, what it writes, and the command to run it. This is the
right route when you are working on one stage, or want to run a single location
without touching anything else.

**All at once, with Snakemake.** ``snakemake`` runs exactly these six stages plus
the data prep before them and the analysis after them, in order, skipping
whatever is already built. See "Running Everything at Once with Snakemake" after
stage 6.

Neither route is privileged: they issue the same commands and write to the same
places, because both read their paths from ``src/lsff_utils/paths.py``. You can
run some stages by hand and let Snakemake pick up from there -- it decides what
to do by looking at what is on the shared drive, not by remembering what it ran.
Each stage below names the Snakemake rule that corresponds to it.

Stages 1-2 and 3-4 are independent of one another and can run at the same time;
stage 5 needs both.

Two environments are used, and each stage says which. Activate with
``source environment.sh -t artifact`` for artifact builds and
``source environment.sh`` for simulations, adding ``-s`` for the shared cluster
environment. One artifact environment serves both packages. Snakemake activates
these for you; by hand, you activate them yourself.

Artifact builds are only possible on the IHME network. Without it you are limited
to running simulations against pre-made artifacts.

The examples use Nigeria; substitute any location the project supports.

Stage 1 -- Maternal artifact
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assembles every input the maternal simulation needs for one location: pregnancy
incidence, hemoglobin distributions, maternal disorder rates, and baseline
fortification coverage.

:Reads: ``0100_data_prep/results/`` CSVs, plus GBD via ``vivarium_inputs``
:Writes: ``0200_pregnancy_sim/mean_draw_artifacts/<vehicle>/<location>.hdf``
:Environment: artifact
:Snakemake rule: ``pregnancy_artifacts``

::

  (artifact) :~$ make_artifacts -p maternal -l nigeria --vehicle rice --mean -vvv

Stage 2 -- Maternal simulation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Simulates pregnancies and their outcomes. Its central output for the rest of the
pipeline is ``births``: one line-list record per pregnancy, carrying the
characteristics the child model needs to create a simulant.

:Reads: the stage 1 artifact
:Writes: ``0200_pregnancy_sim/sim_results/<vehicle>/<location>/<run>/results/`` -- ``births``,
         ``deaths``, ``ylds``, ``ylls``, ``person_time_*``, transition counts
:Environment: simulation
:Snakemake rule: ``pregnancy_simulations``

::

  (simulation) :~$ psimulate run \
      0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/model_spec.yaml \
      0200_pregnancy_sim/src/vivarium_gates_lsff_2026_maternal/model_specifications/branches/scenarios_small.yaml \
      -o 0200_pregnancy_sim/sim_results/rice \
      -P proj_simscience -m 2 -r 01:00:00 -q all.q -v

Stage 3 -- LBWSG PAF artifact
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A cut-down artifact feeding the PAF calculation in stage 4. It holds a different
key set from the full child artifact -- it omits the PAF, which is the thing
stage 4 produces -- so the two must never share a path.

:Reads: GBD via ``vivarium_inputs``
:Writes: ``0300_child_sim/lbwsg_paf_mean_draw_artifacts/<location>.hdf``
:Environment: artifact
:Snakemake rule: ``artifact_for_lbwsg_pafs``

::

  (artifact) :~$ make_artifacts -p child -l nigeria --for-lbwsg-pafs --national --mean -vvv

Stage 4 -- LBWSG PAF calculation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A small, short simulation that computes the population attributable fraction of
diarrheal disease mortality due to low birth weight and short gestation. It
exists because GBD does not publish this PAF; the child model needs it.

:Reads: the stage 3 artifact
:Writes: ``0300_child_sim/lbwsg_pafs/<location>/<run>/``
:Environment: simulation
:Snakemake rule: ``lbwsg_pafs``

::

  (simulation) :~$ psimulate run \
      0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf.yaml \
      0300_child_sim/src/vivarium_gates_lsff_2026_child/data/lbwsg_paf_branches.yaml \
      -o 0300_child_sim/lbwsg_pafs \
      -P proj_simscience -m 2 -r 01:00:00 -q all.q -v

Stage 5 -- Child artifact
~~~~~~~~~~~~~~~~~~~~~~~~~

The one stage with upstream dependencies on both branches of the pipeline. It
assembles the child model's inputs, folding in the maternal birth records as the
fertility key and the PAF computed in stage 4.

Name the maternal run explicitly so the artifact records which run produced it.
The PAF results are found automatically under ``0300_child_sim/lbwsg_pafs/``;
the build logs which run it used and takes the most recent, so check that line
when more than one is present.

:Reads: maternal ``births`` (stage 2), PAF results (stage 4),
        ``0100_data_prep/results/`` CSVs, GBD
:Writes: ``0300_child_sim/mean_draw_artifacts/<vehicle>/<location>.hdf``
:Environment: artifact
:Snakemake rule: ``child_artifacts``

::

  (artifact) :~$ make_artifacts -p child -l nigeria --vehicle rice --national --mean -vvv \
      --fertility-data-path 0200_pregnancy_sim/sim_results/rice/nigeria/<run>/results/births

Stage 6 -- Child simulation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Simulates the under-five cohort, creating one simulant per maternal birth record
and following it to age five or death.

:Reads: the stage 5 artifact
:Writes: ``0300_child_sim/sim_results/<vehicle>/<location>/<run>/results/`` -- ``person_time``,
         ``deaths``, ``ylds``, ``ylls``, ``live_births``, ``birth_weight_sum``
:Environment: simulation
:Snakemake rule: ``child_simulations``

::

  (simulation) :~$ psimulate run \
      0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/model_spec.yaml \
      0300_child_sim/src/vivarium_gates_lsff_2026_child/model_specifications/branches/scenarios_small.yaml \
      -o 0300_child_sim/sim_results/rice \
      -P proj_simscience -m 2 -r 01:00:00 -q all.q -v

Running Everything at Once with Snakemake
-----------------------------------------

Snakemake runs the whole thing for you. It reads the rules in ``Snakefile`` and
the six ``Snakefile`` files under the numbered directories, works out which
stages are missing or out of date by looking at what is already on the shared
drive, and runs only those -- in dependency order, activating the right
environment for each one. Every path it uses comes from
``src/lsff_utils/paths.py``, so it writes to the same places the by-hand commands
above do.

How the two environments are handled
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each rule's recipe is its own subshell, and it begins by activating the
environment that stage needs::

  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate vivarium_gates_lsff_2026_artifact
  ...the stage's commands...

So the environment Snakemake is *launched* from is never inherited by a stage,
and no environment has to be active before you invoke ``snakemake``. Of the 24
rules, the three that call ``psimulate`` -- ``pregnancy_simulations``,
``child_simulations`` and ``lbwsg_pafs`` -- use the simulation environment; the
other 21 read GBD or read results, and use the artifact environment. Each stage
in the walkthrough above names which.

Setup
~~~~~

Just the two environments from "Installation". Snakemake is a dependency of the
simulation environment, so ``environment.sh`` installs it::

  :~$ source environment.sh -t artifact   # build the artifact environment
  :~$ source environment.sh               # build the simulation environment, with snakemake

Snakemake needs nothing of its own. It imports only ``lsff_utils``, to resolve
paths and read ``0050_config/``, and ``environment.sh`` installs this repository
editable, so that is already there.

Running it
~~~~~~~~~~

Run it from the simulation environment. Which environment you are in does not
affect what the stages run in, per the section above; it only has to be one that
has ``snakemake``::

  (simulation) :~$ snakemake -n          # dry run: what would run, and why
  (simulation) :~$ snakemake -c1         # build everything end to end

**Always dry-run first.** ``-n`` prints the stages it would run without running
any of them, which is the cheapest way to confirm it agrees with you about what
is already done -- in particular that the expensive PAF stages are not about to
be scheduled again. See "Starting a New Model Iteration" for what does and does
not trigger a rebuild.

Build one thing, and only its prerequisites, by naming the file you want::

  (simulation) :~$ snakemake -c1 -n \
      0200_pregnancy_sim/mean_draw_artifacts/rice/nigeria.hdf

That is the way to test one location end to end: name the output you want and
Snakemake stops as soon as it has it. Name the *file*, not the rule -- most of
these rules carry ``{location}`` and ``{vehicle}`` wildcards, and Snakemake
cannot tell which location you meant from a rule name alone.

Rule names are for going the other way: stopping the pipeline at a stage, for
every location at once. ``--until`` takes a rule name and runs everything up to
and including it, which is how you work outward one stage at a time::

  (simulation) :~$ snakemake -c1 -n --until pregnancy_simulations

Rule names are also what you will see in dry-run output and in the message when
something fails, which is why each stage above lists its own.

``--profile profiles/debug`` runs serially with ``simulate`` in place of
``psimulate`` and drops into a debugger on failure.

Run it somewhere it can submit jobs and somewhere it can survive losing your
connection -- the simulation stages submit their own cluster jobs through
``psimulate`` and wait on them, so a full run is measured in hours. A ``tmux`` or
``screen`` session on a submit host is the usual answer.

If a rule fails, its stage stops and so does everything downstream of it;
finished stages are left alone, so fixing the problem and re-running picks up
where it stopped rather than starting over.

Skipping data prep
~~~~~~~~~~~~~~~~~~

``0100_data_prep``'s outputs are CSVs committed to the repository, so unlike
everything else in the pipeline they are usually already correct and rarely need
rebuilding. Their timestamps, though, come from whenever git last wrote them --
so a fresh clone, a branch switch, or a rebase can leave a notebook looking newer
than the CSVs it produced. Snakemake then schedules that stage, and because the
rest of the pipeline reads those CSVs, everything downstream follows it.

To take the committed CSVs as given::

  (simulation) :~$ snakemake -c1 --config skip_data_prep=true

This suppresses staleness, not the work: a data prep output that is genuinely
missing is still built. It only stops the stage rerunning over a timestamp.

Dry-run both ways when you are unsure which you want. The difference is easy to
read off the job counts -- if the two agree, data prep was not going to run
anyway and the flag changes nothing.

Leave it off when you have actually changed a data prep notebook or the
extraction workbook, since that is exactly the case it would hide.

Overriding the environments
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rules default to the two environments ``environment.sh`` builds, named
``vivarium_gates_lsff_2026_artifact`` and ``vivarium_gates_lsff_2026_simulation``.
Point a run at different ones with ``--config``, which must come after any target
you name::

  (simulation) :~$ snakemake --config simulation_env=my_other_env
  (simulation) :~$ snakemake --config simulation_env=.venv/vivarium_gates_lsff_2026_simulation

A value containing a ``/`` is treated as a venv to source rather than a conda
environment to activate, which is what ``source environment.sh -s`` builds. For
anything neither form expresses, replace the activation shell outright::

  (simulation) :~$ snakemake --config artifact_env_setup='module load python && source /some/env/bin/activate'

Snakemake activates environments but never builds them; a missing one fails that
rule immediately rather than running the stage against the wrong interpreter.
There is no lockfile and no Snakemake-managed environment: ``environment.sh`` and
``pyproject.toml`` are the only description of what gets installed.

Editing a rule: recipes are not f-strings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every ``shell:`` body in the workflow is a plain string, and Snakemake does the
interpolation. **Do not make one an f-string**, however convenient it looks.

Snakemake parses a Snakefile by tokenizing it and re-emitting Python. On Python
3.12+ an f-string is no longer a single token, and Snakemake 8.16+ loses the
literal pieces that span a newline: in a multi-line f-string, *every line
containing no* ``{...}`` *is silently dropped from the recipe*. No error, no
warning -- the rule just runs a shorter script than the one in the file. This
deleted the ``cd 0300_child_sim`` and ``rm -f dump.rdb`` lines from both
simulation rules, leaving ``psimulate`` to fail from the wrong directory.

So a rule gets what it needs three ways:

* Values computed in Python are named at the top of the Snakefile and referenced
  as ``{name}``. Snakemake's formatter resolves module globals, attribute access
  (``{paths.CHILD_RESULTS_ROOT}``) and ``{config[key]}``.
* Wildcards are ``{wildcards.location}``, and a rule's own output is ``{output}``.
  A bare ``{location}`` is *not* the wildcard -- it resolves against the workflow
  globals, where it picks up the loop variables ``0100_data_prep/Snakefile``
  leaves at module scope.
* Anything derived from the wildcards goes in the rule's ``params``, as a lambda
  over ``wildcards``. That is the only interpolation Snakemake resolves per job:
  a ``{name}`` whose *value* contains ``{wildcards.location}`` will not be
  expanded, because Snakemake does not re-scan what it substitutes.

Single-line f-strings are unaffected, which is why the ``input``, ``output`` and
``log`` path lists still use them. ``snakemake -n -p`` prints the recipe a rule
will actually run, and is the fastest way to confirm an edit renders.

Building Artifacts: Details
---------------------------

Artifacts are built with ``make_artifacts``, whose ``-p/--package`` flag selects
which model to build for.

To add a location, add it to the ``LOCATIONS`` constant in that project's
``constants/metadata.py``. The two projects do not model the same set: the child
model runs for Ethiopia, India, and Nigeria, while the maternal model runs for
India and Nigeria only. Ethiopia has no maternal disorders incidence disparities
extract, and its only fortification vehicle is folate-on-salt, so there is no
iron vehicle for the maternal intervention to act through.

With no ``-o``, each build writes to the right root for the current
``MODEL_NUMBER``, so ``-o`` is only needed to write somewhere else.

Passing ``-l all`` builds every location for that project at once. On a cluster
node each location is submitted as an independent Jobmon task and they build
concurrently; off-cluster they are built serially in a single process. The
command logs a monitoring URL for the workflow, and raises naming the unfinished
locations if any task fails, so a partial build is never mistaken for a complete
one. Note that ``-l all`` writes to the same paths a single-location build would,
so point ``-o`` somewhere disposable when testing.

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

Running Simulations: Details
----------------------------

Each simulation is described by a model specification, a `YAML
<https://en.wikipedia.org/wiki/YAML>`__ file you can edit to change what runs.
See
https://vivarium-engine.readthedocs.io/en/latest/concepts/model_specification/index.html

Each specification names the artifact it runs against in its ``input_data``
section, already pointed at the current iteration's artifact, so ``-i`` is only
needed to run against a different one.

The stage commands above use ``psimulate``, which runs draws, seeds, and
scenarios in parallel across cluster nodes. To run a single simulation instead --
one draw, one seed, one scenario -- drop the branches file and the cluster flags
and use ``simulate run``::

  (simulation) :~$ simulate run <model_spec.yaml> -o <output_dir> -vvv

Add ``--pdb`` to drop into the debugger on failure. ``-vvv`` logs every time step.
Do a single run first when testing a change; it is far cheaper to find a crash on
one job than on thirty.

Stages 2 and 6 each have a full-size and a small branches file, both in
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

If some tasks fail, ``psimulate restart <run_dir>`` reruns only those. Run it by
hand when that happens -- the Snakemake rules deliberately do not. jobmon retries
each task itself and refuses to resume a finished workflow
(``WorkflowAlreadyComplete``), so an unconditional restart fails every run that
succeeded.

Note that stages 2 and 6 sweep the same three maternal scenarios, and the child
model filters birth records by scenario and seed. A child job whose
``(scenario, random_seed)`` pair is missing from the maternal results initializes
an empty population and writes empty results *without failing*, so confirm that
every task produced non-empty output rather than relying on the job count.

Starting a New Model Iteration
------------------------------

One number, and it labels the archive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``MODEL_NUMBER`` in ``src/lsff_utils/paths.py`` names the iteration. It appears
only in the archive path -- the in-repo roots do not carry it, so bumping it does
not move anything the pipeline writes.

That is a deliberate change from the older layout, where three numbers keyed
three sets of shared-drive roots and bumping one *was* how you forced a rebuild:
the outputs were repointed at a directory that did not exist yet, so everything
beneath it ran again. Nothing works that way now.

**Snakemake decides what to rerun, which is what it is for.** A stage reruns when
its output is missing, when an input is newer, or when its recipe code changed --
the default ``--rerun-triggers``. The two LBWSG PAF rules additionally mark their
inputs ``ancient()``, so editing the child package does not drag the most
expensive stage in the pipeline along with it.

The consequence to remember: **bumping ``MODEL_NUMBER`` alone rebuilds nothing.**
Last iteration's outputs are still sitting at the same in-repo paths, and
Snakemake will consider them up to date.

Step 1: archive what you have
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

  :~$ ./archive_last_run.sh -n     # check what would be published
  :~$ ./archive_last_run.sh

Publishes the current outputs to the team drive under the *current*
``MODEL_NUMBER``. Do this before bumping, or the run you just finished gets filed
under the next iteration's name.

Step 2: bump the number
~~~~~~~~~~~~~~~~~~~~~~~

Change ``MODEL_NUMBER`` in ``src/lsff_utils/paths.py``. That is the only edit --
the model specifications no longer name an artifact, so nothing else needs
touching. ``tests/test_paths.py`` enforces that.

Step 3: force what should be rebuilt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the step the old layout did for you. Decide what the iteration is
actually changing and force exactly that::

  :~$ snakemake -c1 --forcerun dalys_by_scenario cases_by_scenario
  :~$ snakemake -c1 --forceall        # everything, data prep included

``--forcerun`` is the option to reach for first: the outputs stay put until the
rerun succeeds, so a failure leaves you where you started. Note it only forces
jobs *already in the DAG* -- it will not pull in a stage that Snakemake has
pruned, which is what the next paragraph is about.

Deleting the outputs works too, and is the only way to make a stage rerun that
``--forcerun`` cannot reach::

  :~$ rm -rf 0[23]00_*/sim_results/         # new simulation runs
  :~$ rm -rf 0300_child_sim/mean_draw_artifacts   # ... and a new child artifact
  :~$ rm -rf 0200_pregnancy_sim/mean_draw_artifacts  # only if GBD data or a loader changed
  :~$ rm -rf 0300_child_sim/lbwsg_paf*       # only if the PAFs must be recalculated

Removing nothing is a valid choice. If the iteration is a code change that
Snakemake can see, it will rerun the affected stages on its own; the numbered
directories on the team drive still keep the iterations apart.

Committed outputs prune stages
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The results under ``0100_data_prep``, ``0400_``, ``0500_`` and
``5000_analyze_results`` are committed to the repository, and a present,
up-to-date target stops Snakemake descending into what produces it. So a run
that looks like a full pipeline can quietly skip data prep and the analysis
notebooks entirely -- they are already there and nothing they depend on is
newer. ``--forceall`` is what actually reruns them.

Commit before you run
^^^^^^^^^^^^^^^^^^^^^

Snakemake does not require a clean tree, and the simulation rules record the
diff in ``git_commit.txt`` so a run made mid-edit stays reproducible. But the
executed notebooks this repository commits carry their cell outputs, so a dirty
tree can make that diff megabytes -- in every run directory, and in every
archived copy. It is capped (see ``MAX_EMBEDDED_DIFF_BYTES`` in
``src/lsff_utils/snakemake_utils.py``), and above the cap the diff body is
dropped and only the summary kept. Committing first is what keeps the
provenance a clean commit hash instead.

Step 4: dry-run before you commit to it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

  (simulation) :~$ snakemake -n

Read the job list before starting the real run, and check two things.

**That the expensive stages you meant to reuse are absent.**
``artifact_for_lbwsg_pafs`` and ``lbwsg_pafs`` should not appear unless you
cleared ``data/``. If they do, something they read looks newer than their output;
find out what before spending the hours.

**That ``pregnancy_artifacts`` is absent, if you meant to reuse the maternal
artifact.** Unlike the PAF rules it is *not* insulated from its inputs: it reads
``loader.py`` and the data prep CSVs normally, so if any of them looks newer,
Snakemake rebuilds the maternal artifact **in place**. Since the in-repo path no
longer carries a number, that overwrites the artifact your last iteration ran
against -- which is why Step 1 comes first. Archive, and the published copy is
safe whatever happens locally.

That rebuild is usually right -- a genuine loader change should propagate rather
than silently produce results from a stale artifact -- but committed CSVs can
schedule one on a timestamp alone. ``--config skip_data_prep=true`` takes them as
given if that is what happened.

What follows automatically, and what does not
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every Snakemake rule, both simulation packages and every notebook build their
paths from ``lsff_utils.paths``, so moving a root is a one-line change and
nothing else needs to know.

``make_artifacts`` resolves ``-o`` from the same constants when you omit it, so a
hand-run build lands where Snakemake would put it -- except for the ``<vehicle>``
directory, which Snakemake appends and a hand-run build does not.

``simulate`` and ``psimulate`` are vivarium's own commands and know nothing about
``lsff_utils.paths``, so their ``-o`` is always whatever you type. The stage
commands above spell the paths out for that reason.

Overriding ``-o`` works everywhere and is the right way to test. Point it at a
scratch directory and a trial run cannot touch anything a validated set of
results depends on::

  (artifact) :~$ make_artifacts -p maternal -l nigeria -o ~/scratch/artifacts -vvv

Prefer archiving and bumping to deleting an archived iteration: it costs disk but
keeps a baseline to compare against, which is what tells you whether a change in
results is real.

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
``tests/``, and ``pyproject.toml``. ``src/`` at the repository root holds two smaller
packages: ``lsff_utils``, shared helpers and the path constants both simulations
read, and ``vivarium_gates_lsff_2026``, which provides the ``make_artifacts``
command and dispatches to whichever project ``-p`` names.