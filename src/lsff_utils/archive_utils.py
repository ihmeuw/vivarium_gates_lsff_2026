"""Helpers for ``archive_last_run.sh``.

psimulate records the artifact it ran against in each run's
``model_specification.yaml``, and under the in-repo layout that is a path inside
whoever's working tree produced the run. Once the run is archived that path is
useless to everyone else, and gone entirely once the repo is cleared for the next
iteration. The archived copy is therefore repointed at the archived artifact, so
the specification keeps doing its job: saying what was run, and where to find the
inputs it ran on.

The rewrite touches the ``artifact_path`` line and nothing else -- the rest of
psimulate's file is left byte-for-byte alone rather than round-tripped through a
YAML dumper.
"""

import re
from pathlib import Path

from lsff_utils import paths

# Deliberately line-oriented. `artifact_path` appears once, as a leaf under
# `input_data`, and matching the line keeps the surrounding file untouched.
_ARTIFACT_PATH_LINE = re.compile(
    r"^(?P<indent>\s*)artifact_path:\s*(?P<quote>['\"]?)(?P<path>.+?)(?P=quote)\s*$"
)


def archived_artifact_path(
    recorded: Path | str,
    repo_root: Path | str,
    team_root: Path | str,
    model_number: str,
) -> Path | None:
    """Where an in-repo artifact ends up in the archive.

    Mirrors the copy the script performs, via ``paths.ARCHIVE_DESTINATIONS``: the
    repository groups outputs by producing package, the archive by kind and
    iteration. Returns ``None`` when the recorded path is under no known root --
    a run made against an artifact elsewhere already names a path that outlives
    the run, and must be left alone.
    """
    recorded = Path(recorded)
    repo_root = Path(repo_root)

    for root, (kind, subpath) in paths.ARCHIVE_DESTINATIONS.items():
        # Compare relative to the given repo_root so tests can point at a
        # different tree than the one lsff_utils happens to be installed in.
        root = repo_root / Path(root).relative_to(paths.REPO_ROOT)
        try:
            rel = recorded.relative_to(root)
        except ValueError:
            continue
        return Path(team_root, kind, model_number, subpath, *rel.parts)

    return None


def rewrite_spec_artifact_path(
    spec_path: Path | str,
    repo_root: Path | str,
    team_root: Path | str,
    model_number: str,
) -> Path | None:
    """Repoint an archived run's specification at the archived artifact.

    Returns the new path, or ``None`` if the file has no ``artifact_path`` or the
    recorded one is not in the repository. The original value is preserved as a
    comment above the line, so the rewrite does not erase what actually ran.
    """
    spec_path = Path(spec_path)
    lines = spec_path.read_text().splitlines(keepends=True)

    for i, line in enumerate(lines):
        match = _ARTIFACT_PATH_LINE.match(line.rstrip("\n"))
        if not match:
            continue

        recorded = match.group("path")
        archived = archived_artifact_path(recorded, repo_root, team_root, model_number)
        if archived is None:
            return None

        indent = match.group("indent")
        newline = "\n" if line.endswith("\n") else ""
        lines[i : i + 1] = [
            f"{indent}# archived: this run used {recorded}\n",
            f"{indent}artifact_path: {archived}{newline}",
        ]
        spec_path.write_text("".join(lines))
        return archived

    return None
