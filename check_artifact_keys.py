"""
Compare an artifact's keys against the keys this version of the code asks for.

A simulation run against an artifact built by an older version of the project
fails on the first key the code wants and the artifact does not have::

    ArtifactException: covariate.stillbirth_28_weeks_to_live_birth_ratio.estimate
    should be in .../mean_draw_artifacts/rice/nigeria.hdf

That surfaces one mismatch per cluster run, which is a slow way to find out
there are several. This reports all of them at once, before anything is
submitted, and pairs each missing key with the similarly-named key the artifact
does have -- which is what a rename looks like from the outside.

Usage::

    python check_artifact_keys.py <artifact.hdf> -p maternal
    python check_artifact_keys.py <artifact.hdf> -p child --for-lbwsg-pafs
    python check_artifact_keys.py <new.hdf> --against <old.hdf>

Exits 0 when nothing the code needs is missing, 1 otherwise, so it can gate a
run. Reading the keyspace needs no GBD access and works in either environment.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent

# What fraction of the shorter name's words the two names must share to call
# them a rename. See rename_score.
SIMILARITY_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Reading the artifact
# ---------------------------------------------------------------------------


def read_artifact_keys(path: Path) -> set[str]:
    """Every key present in an artifact.

    Three strategies, cheapest last. The vivarium Artifact class is the
    authority, but importing it drags in the whole framework, which is not
    available in every environment this might be run from. Vivarium artifacts
    also record their own key list at ``metadata.keyspace``, which pandas can
    read on its own -- that is the fallback that matters. Walking the HDF nodes
    is the last resort, for an artifact whose keyspace is somehow absent.
    """
    if not path.is_file():
        raise SystemExit(f"ERROR: no artifact at {path}")

    try:
        from vivarium.artifact import Artifact

        return {str(key) for key in Artifact(str(path)).keys}
    except Exception:
        pass

    try:
        import pandas as pd

        keyspace = pd.read_hdf(str(path), "/metadata/keyspace")
        return {str(key) for key in keyspace}
    except Exception:
        pass

    try:
        import tables

        keys: set[str] = set()
        with tables.open_file(str(path)) as hdf:
            for node in hdf.walk_nodes("/", "Group"):
                # Artifact keys are 'type.name.measure' or 'type.measure',
                # stored as nested groups. A group holding the data itself has
                # array children ('table', 'index', 'values', ...); a group that
                # is only part of the path does not.
                if any(not isinstance(child, tables.Group) for child in node):
                    parts = node._v_pathname.strip("/").split("/")
                    if parts and parts[0]:
                        keys.add(".".join(parts))
        if keys:
            return keys
    except Exception as err:  # pragma: no cover - diagnostic path
        raise SystemExit(f"ERROR: could not read keys from {path}: {err}")

    raise SystemExit(f"ERROR: found no keys in {path}. Is it a vivarium artifact?")


# ---------------------------------------------------------------------------
# Reading what the code wants
# ---------------------------------------------------------------------------


def import_data_keys(package: str):
    """The data_keys module of one simulation package.

    Added to sys.path explicitly rather than relying on the package being
    installed, so this works from a bare checkout.
    """
    src = {
        "maternal": REPO_ROOT / "0200_pregnancy_sim" / "src",
        "child": REPO_ROOT / "0300_child_sim" / "src",
    }[package]
    module = {
        "maternal": "vivarium_gates_lsff_2026_maternal.constants.data_keys",
        "child": "vivarium_gates_lsff_2026_child.constants.data_keys",
    }[package]

    sys.path.insert(0, str(src))
    try:
        import importlib

        return importlib.import_module(module)
    except ImportError as err:
        raise SystemExit(
            f"ERROR: could not import {module}: {err}\n"
            "Activate an environment first: source environment.sh"
        )


def expected_keys(package: str, for_lbwsg_pafs: bool) -> set[str]:
    """The keys a build of this package would write.

    Mirrors the loop in tools/make_artifacts.py, including its skips. Iterating
    a key group yields the NamedTuple's field values -- the key strings -- and
    not its 'name'/'log_name' properties, which is why the build loop can do the
    same thing.
    """
    data_keys = import_data_keys(package)

    keys: set[str] = set()
    for key_group in data_keys.MAKE_ARTIFACT_KEY_GROUPS:
        if package == "child":
            # The PAF artifact holds a different key set from the full child
            # artifact: it adds diarrhea, and omits the four keys that depend on
            # the maternal run or on the PAF this build is about to produce.
            if key_group == data_keys.DIARRHEA and not for_lbwsg_pafs:
                continue
        for key in key_group:
            if package == "child" and for_lbwsg_pafs and key in (
                data_keys.LBWSG.PAF,
                data_keys.POPULATION.FERTILITY_DATA,
                data_keys.LBWSG.BIRTH_WEIGHT_WEALTH_DISPARITIES,
                data_keys.IRON_FORTIFICATION.BIRTH_WEIGHT_EFFECT_SIZE,
            ):
                continue
            keys.add(str(key))

    return keys


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _split(key: str) -> tuple[str, str, str]:
    """A key as (type, entity, measure), e.g. covariate.<entity>.estimate."""
    parts = key.split(".")
    if len(parts) < 2:
        return key, "", ""
    return parts[0], ".".join(parts[1:-1]), parts[-1]


def rename_score(wanted: str, present: str) -> float:
    """How likely two keys are the two ends of one rename.

    Character similarity on whole keys is too blunt. 'cause.all_causes.
    cause_specific_mortality_rate' and 'cause.maternal_disorders.
    cause_specific_mortality_rate' are 84% alike as text while naming entirely
    different quantities, because they share a long type and measure.

    Scoping to the differing component helps but is still fooled by a shared
    suffix: 'other_neonatal_disorders' and 'maternal_disorders' are 76% alike
    on the strength of '_disorders' alone.

    So compare words rather than characters, and ask what fraction of the
    shorter name's words appear in the longer. A rename typically keeps the
    original words and qualifies them, which scores 1.0; unrelated entities
    sharing a category word score at most 0.5. The stillbirth rename --
    'stillbirth_to_live_birth_ratio' to 'stillbirth_28_weeks_to_live_birth_
    ratio' -- scores 1.0, against 0.5 for the neonatal/maternal pair and 0.0
    for all_causes/maternal_disorders.

    Known gap: a measure renamed to an unrelated word, say 'mean' to 'average',
    shares no words and will not be paired. It is still reported, as one missing
    key and one unused key -- unlinked, but not hidden.
    """
    wanted_type, wanted_entity, wanted_measure = _split(wanted)
    present_type, present_entity, present_measure = _split(present)

    if wanted_type != present_type:
        return 0.0

    # At most one of entity and measure may differ. If both do, these are two
    # different keys rather than one key under two names.
    if wanted_entity == present_entity and wanted_measure == present_measure:
        return 1.0
    if wanted_entity == present_entity:
        return _word_containment(wanted_measure, present_measure)
    if wanted_measure == present_measure:
        return _word_containment(wanted_entity, present_entity)

    return 0.0


def _word_containment(a: str, b: str) -> float:
    """Fraction of the shorter name's words that also appear in the longer."""
    a_words = set(a.split("_"))
    b_words = set(b.split("_"))
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / min(len(a_words), len(b_words))


def pair_renames(
    missing: Iterable[str], orphaned: Iterable[str]
) -> tuple[list[tuple[str, str]], set[str], set[str]]:
    """Match each missing key to the orphaned key it most resembles.

    Greedy, best-first, and one-to-one: the highest-scoring pair in the whole
    grid is taken first, so a strong match is never lost to a weaker one that
    happened to be considered earlier, and each orphan is claimed once.
    """
    remaining_missing = set(missing)
    remaining_orphans = set(orphaned)
    pairs: list[tuple[str, str]] = []

    while remaining_missing and remaining_orphans:
        best = max(
            (
                (rename_score(wanted, present), wanted, present)
                for wanted in remaining_missing
                for present in remaining_orphans
            ),
            key=lambda scored: (scored[0], scored[1], scored[2]),
        )
        score, wanted, present = best
        if score < SIMILARITY_THRESHOLD:
            break
        pairs.append((wanted, present))
        remaining_missing.discard(wanted)
        remaining_orphans.discard(present)

    pairs.sort()
    return pairs, remaining_missing, remaining_orphans


def report(
    artifact: Path,
    present: set[str],
    wanted: set[str],
    label: str,
) -> int:
    missing = wanted - present
    orphaned = present - wanted
    pairs, unmatched_missing, unmatched_orphans = pair_renames(missing, orphaned)

    print()
    print(f"  artifact  {artifact}")
    print(f"  compared  {label}")
    print(f"  keys      {len(present)} in artifact, {len(wanted)} wanted")
    print()

    if not missing:
        print("  Nothing the code asks for is missing.")
        if orphaned:
            print(f"  ({len(orphaned)} key(s) in the artifact are unused; harmless.)")
        print()
        return 0

    if pairs:
        print(f"  LIKELY RENAMES ({len(pairs)}) -- same data, different key:")
        print()
        for wanted_key, present_key in pairs:
            print(f"    wanted by code : {wanted_key}")
            print(f"    in artifact    : {present_key}")
            print()

    if unmatched_missing:
        print(f"  MISSING, NO CLOSE MATCH ({len(unmatched_missing)}) -- new data,")
        print("  not a rename. The artifact cannot supply these at all:")
        print()
        for key in sorted(unmatched_missing):
            print(f"    {key}")
        print()

    if unmatched_orphans:
        print(f"  UNUSED BY THIS CODE ({len(unmatched_orphans)}):")
        print()
        for key in sorted(unmatched_orphans):
            print(f"    {key}")
        print()

    print("  A pairing here is a hypothesis from the key names alone. Confirm the two")
    print("  keys mean the same thing before treating a rename as safe to relabel --")
    print("  a key can be renamed because the underlying quantity changed.")
    print()

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diff an artifact's keys against what this code expects.",
    )
    parser.add_argument("artifact", type=Path, help="Artifact to check.")
    parser.add_argument(
        "-p",
        "--package",
        choices=["maternal", "child"],
        help="Which package's key set to compare against.",
    )
    parser.add_argument(
        "--for-lbwsg-pafs",
        action="store_true",
        help="(child only) Compare against the cut-down LBWSG PAF key set.",
    )
    parser.add_argument(
        "--against",
        type=Path,
        default=None,
        help="Compare against another artifact's keys instead of the code's.",
    )
    args = parser.parse_args()

    present = read_artifact_keys(args.artifact)

    if args.against is not None:
        wanted = read_artifact_keys(args.against)
        label = f"keys of {args.against}"
    else:
        if args.package is None:
            parser.error("one of -p/--package or --against is required")
        wanted = expected_keys(args.package, args.for_lbwsg_pafs)
        label = f"{args.package} package" + (
            " (--for-lbwsg-pafs key set)" if args.for_lbwsg_pafs else ""
        )

    return report(args.artifact, present, wanted, label)


if __name__ == "__main__":
    raise SystemExit(main())
