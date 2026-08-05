"""
=====
Paths
=====

Shared filesystem locations for the LSFF modeling pipeline.

Data too large to live in the repository lives on the team's shared drive, laid
out first by kind -- ``data`` for pipeline inputs and intermediates, ``artifacts``
for the artifacts simulations run against, ``results`` for simulation output --
and then by model iteration::

    /mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026/
    |-- artifacts/<MODEL_NUMBER>/
    |   |-- maternal/
    |   `-- child/
    |-- data/<MODEL_NUMBER>/
    |   |-- lbwsg_paf_artifacts/
    |   `-- lbwsg_pafs/
    `-- results/<MODEL_NUMBER>/
        |-- maternal/
        `-- child/

Starting a new model iteration means bumping :data:`MODEL_NUMBER` here. That
moves every root below at once; see the "Starting a New Model Iteration" section
of the repository README for the two other places that need updating.

These constants live in ``lsff_utils`` rather than in either simulation package
because the two packages have to agree on them. The child model's population
comes from the maternal model's birth records, so the child artifact build reads
out of the same iteration's ``results/`` directory that the maternal simulation
wrote to. Defining the roots twice invites the two halves of the pipeline to
disagree about which iteration they are part of.
"""

import os
from pathlib import Path

DEFAULT_MODEL_ROOT = Path(
    "/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026"
)

# `LSFF_MODEL_ROOT` relocates every root below at once. Unset -- the default -- gives
# exactly the shared-drive layout described above, so this changes nothing for anyone
# working against the team directory.
#
# It exists because that directory is shared, and a pipeline run writes artifacts and
# results into it: a Snakemake run would overwrite whatever a colleague's run put
# there, and IHME policy treats these paths as read-only. Pointing this at a writable
# directory lets the pipeline run end to end without touching shared state.
#
# This is also the seam where the orchestration and the packages currently disagree.
# The Snakefiles keep intermediates in-tree, while these constants expect them on the
# shared drive; `LBWSG_PAF_RESULTS_ROOT` is the one the child artifact build reads with
# no command-line override, so it is the one that actually blocks a run. Reconciling
# the two properly -- deciding where intermediates belong and updating the Snakefiles
# to match -- is still open.
MODEL_ROOT = Path(os.environ.get("LSFF_MODEL_ROOT") or DEFAULT_MODEL_ROOT)

# Bump this to start a new model iteration. See the module docstring.
MODEL_NUMBER = "legacy"

ARTIFACT_ROOT = MODEL_ROOT / "artifacts" / MODEL_NUMBER
DATA_ROOT = MODEL_ROOT / "data" / MODEL_NUMBER
RESULTS_ROOT = MODEL_ROOT / "results" / MODEL_NUMBER

MATERNAL_ARTIFACT_ROOT = ARTIFACT_ROOT / "maternal"
CHILD_ARTIFACT_ROOT = ARTIFACT_ROOT / "child"

MATERNAL_RESULTS_ROOT = RESULTS_ROOT / "maternal"
CHILD_RESULTS_ROOT = RESULTS_ROOT / "child"

# Intermediates of the LBWSG PAF calculation, which runs as its own simulation
# between the two artifact builds. The cut-down artifact that feeds it holds a
# different key set from the full child artifact -- it omits the PAF, which is
# what the calculation produces -- so the two must never share a path.
LBWSG_PAF_ARTIFACT_ROOT = DATA_ROOT / "lbwsg_paf_artifacts"
LBWSG_PAF_RESULTS_ROOT = DATA_ROOT / "lbwsg_pafs"
