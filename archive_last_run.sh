#!/bin/bash
#
# Publish the current in-repo pipeline output to the team drive under MODEL_NUMBER.
#
# The pipeline writes inside the repository (see lsff_utils.paths); this is what
# makes a run visible to everyone else and keeps it as the versioned record. What
# gets copied:
#
#   0200_pregnancy_sim/mean_draw_artifacts/         -> artifacts/<M>/maternal/
#   0300_child_sim/mean_draw_artifacts/             -> artifacts/<M>/child/
#   0300_child_sim/lbwsg_paf_mean_draw_artifacts/   -> data/<M>/lbwsg_paf_artifacts/
#   0300_child_sim/lbwsg_pafs/<..>/<run>/           -> data/<M>/lbwsg_pafs/<..>/<run>/
#   0200_pregnancy_sim/sim_results/<..>/<run>/      -> results/<M>/maternal/<..>/<run>/
#   0300_child_sim/sim_results/<..>/<run>/          -> results/<M>/child/<..>/<run>/
#
# -- relative to the repository on the left and to TEAM_ARCHIVE_ROOT on the
# right, with <M> standing in for MODEL_NUMBER. The mapping is not derived from
# the path: the repository groups outputs by producing package, the archive by
# kind and iteration, so paths.ARCHIVE_DESTINATIONS declares it and this script
# reads it from there.
#
# Simulation output is copied one run at a time: only the run each latest_run.txt
# names, which is the run Snakemake considers current and the one the downstream
# stages consumed. Whole run directories are copied, not just the parquet -- they
# carry psimulate's model_specification.yaml, branches.yaml, keyspace.yaml and
# requirements.txt, plus the git_commit.txt the simulation rules write.
#
# The archive is append-only: rsync runs with --ignore-existing, so an already
# archived run or artifact is never overwritten. Re-archiving after a rerun adds
# the new timestamped run alongside the old one. To replace something already
# published, bump MODEL_NUMBER -- or remove the destination by hand, deliberately.
#
# Usage: ./archive_last_run.sh [-n]
#          -n   dry run; show what would be copied and change nothing

set -euo pipefail

dry_run=""
while getopts ":n" opt; do
    case $opt in
        n) dry_run="--dry-run" ;;
        \?) echo "usage: $0 [-n]" >&2; exit 2 ;;
    esac
done

# Read the layout from lsff_utils.paths so the repo and the archive cannot drift.
if ! read -r MODEL_NUMBER REPO_ROOT TEAM_ROOT MARKER_NAME < <(python - <<'PY'
from lsff_utils import paths

print(
    paths.MODEL_NUMBER,
    paths.REPO_ROOT,
    paths.TEAM_ARCHIVE_ROOT,
    paths.RUN_MARKER_NAME,
)
PY
); then
    echo "ERROR: could not import lsff_utils.paths. Activate an environment first." >&2
    exit 1
fi

# Escape hatch for testing and for archiving somewhere other than the team drive.
TEAM_ROOT=${ARCHIVE_ROOT:-$TEAM_ROOT}

echo "model number : $MODEL_NUMBER"
echo "from         : $REPO_ROOT"
echo "to           : $TEAM_ROOT"
[ -n "$dry_run" ] && echo "mode         : DRY RUN"
echo

copied=0
skipped=0

# rsync -a preserves times so a re-archive can tell old files from new;
# --ignore-existing is what makes the archive append-only.
copy_dir() {
    local src=$1 dest=$2
    local out
    out=$(rsync -a --ignore-existing --itemize-changes $dry_run "$src/" "$dest/")
    local n
    n=$(grep -c '^>' <<<"$out" || true)
    if [ "$n" -gt 0 ]; then
        echo "  + $n file(s)  ->  ${dest#"$TEAM_ROOT"/}"
        copied=$((copied + n))
    else
        echo "  = already archived  ->  ${dest#"$TEAM_ROOT"/}"
        skipped=$((skipped + 1))
    fi
}

# psimulate records the artifact a run used, and under the in-repo layout that is
# a path in the working tree that produced it -- unreachable for anyone else, and
# gone once the repo is cleared for the next iteration. Repoint the archived copy
# at the archived artifact so the specification still says where to find what ran.
rewrite_spec() {
    local spec=$1
    [ -f "$spec" ] || return 0
    python - "$spec" "$REPO_ROOT" "$TEAM_ROOT" "$MODEL_NUMBER" <<'PY'
import sys

from lsff_utils import archive_utils

new = archive_utils.rewrite_spec_artifact_path(*sys.argv[1:5])
if new:
    print(f"    artifact_path -> {new}")
PY
}

# The repository groups outputs by producing package, the archive by kind and
# iteration, so the mapping between them is declared in lsff_utils.paths rather
# than derived from the path. One line per root: src, destination, is-run-root.
while IFS=$'\t' read -r src dest is_run; do
    [ -d "$src" ] || { echo "${src#"$REPO_ROOT"/}: nothing built, skipping"; continue; }
    echo "${src#"$REPO_ROOT"/}:"

    if [ "$is_run" = "0" ]; then
        # Artifacts: single files, no run directories. Straight mirror.
        [ -n "$dry_run" ] || mkdir -p "$dest"
        copy_dir "$src" "$dest"
        continue
    fi

    # Simulation output: only the run each marker names.
    found=0
    while IFS= read -r -d '' marker; do
        found=1
        run_root=$(dirname "$marker")
        run=$(tr -d '[:space:]' < "$marker")
        [ -d "$run_root/$run" ] || {
            echo "  ! $MARKER_NAME names '$run', which does not exist under ${run_root#"$REPO_ROOT"/}" >&2
            exit 1
        }
        dest_parent="$dest/${run_root#"$src"/}"
        [ -n "$dry_run" ] || mkdir -p "$dest_parent/$run"
        copy_dir "$run_root/$run" "$dest_parent/$run"
        if [ -z "$dry_run" ]; then
            # Copy the marker too, so paths.latest_run works on the archive.
            cp "$marker" "$dest_parent/$MARKER_NAME"
            rewrite_spec "$dest_parent/$run/model_specification.yaml"
        fi
    done < <(find "$src" -name "$MARKER_NAME" -print0 | sort -z)
    [ "$found" -eq 1 ] || echo "  no $MARKER_NAME found -- no completed runs to archive"
done < <(python - "$TEAM_ROOT" "$MODEL_NUMBER" <<'MAPPING'
import sys

from lsff_utils import paths

team_root, model_number = sys.argv[1], sys.argv[2]
for root, (kind, subpath) in paths.ARCHIVE_DESTINATIONS.items():
    dest = f"{team_root}/{kind}/{model_number}/{subpath}"
    print(f"{root}\t{dest}\t{int(root in paths.RUN_ROOTS)}")
MAPPING
)

echo
if [ "$copied" -eq 0 ]; then
    if [ "$skipped" -gt 0 ]; then
        echo "Nothing new to archive: everything present is already under $MODEL_NUMBER."
        echo "Bump MODEL_NUMBER in src/lsff_utils/paths.py to publish a new iteration."
    else
        echo "ERROR: nothing was archived. Has the pipeline run?" >&2
        exit 1
    fi
    exit 0
fi

# Record the archiving event itself. The commit that produced each run is in that
# run's git_commit.txt; this is who published it, when, and from what tree.
if [ -z "$dry_run" ]; then
    for kind in artifacts data results; do
        dest="$TEAM_ROOT/$kind/$MODEL_NUMBER"
        [ -d "$dest" ] || continue
        {
            echo "archived:  $(date '+%Y-%m-%d %H:%M:%S %z')"
            echo "by:        $(whoami)@$(hostname)"
            echo "from:      $REPO_ROOT"
            echo "commit:    $(git -C "$REPO_ROOT" rev-parse HEAD)"
            git -C "$REPO_ROOT" diff --quiet HEAD \
                && echo "tree:      clean" \
                || echo "tree:      DIRTY (see each run's git_commit.txt for its diff)"
            echo "---"
        } >> "$dest/archive_info.txt"
    done
fi

echo "Archived $copied file(s) under $MODEL_NUMBER."
