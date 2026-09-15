"""Compare two vivarium artifacts key by key.

TEMPORARY (MIC-7476): a throwaway check that the shared-function migration did not
move any artifact values. Delete once the migration is validated.

Usage::

    python compare_artifacts.py <old.hdf> <new.hdf>
"""

import sys

import numpy as np
import pandas as pd
from vivarium.artifact import Artifact

# Loose enough to ignore float-path noise from a different aggregation order,
# tight enough that a real change in the data still shows up.
RTOL = 1e-9


def main(old_path: str, new_path: str) -> None:
    old, new = Artifact(old_path), Artifact(new_path)
    old_keys, new_keys = set(old.keys), set(new.keys)
    identical, changed, errors = [], [], []

    for key in sorted(old_keys & new_keys):
        try:
            a, b = old.load(key), new.load(key)
        except Exception as exc:
            errors.append((key, f"load failed: {type(exc).__name__}: {exc}"))
            continue

        if isinstance(a, pd.Series):
            a = a.to_frame()
        if isinstance(b, pd.Series):
            b = b.to_frame()

        if not (isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame)):
            (identical if a == b else changed).append((key, f"{a!r} -> {b!r}"))
            continue

        if list(a.index.names) != list(b.index.names):
            changed.append(
                (key, f"index levels {list(a.index.names)} -> {list(b.index.names)}")
            )
            continue
        if a.shape != b.shape:
            changed.append((key, f"shape {a.shape} -> {b.shape}"))
            continue

        # Sort first: a different row order is not a difference in the data.
        a, b = a.sort_index(), b.sort_index()
        if not a.index.equals(b.index):
            changed.append((key, "same shape but different index values"))
            continue

        try:
            av, bv = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
        except (TypeError, ValueError):
            (identical if a.equals(b) else changed).append((key, "non-numeric values differ"))
            continue

        if np.allclose(av, bv, rtol=RTOL, equal_nan=True):
            identical.append((key, ""))
            continue

        absdiff = np.abs(av - bv)
        with np.errstate(divide="ignore", invalid="ignore"):
            reldiff = np.where(av != 0, absdiff / np.abs(av), np.nan)
        nan_delta = int(np.isnan(bv).sum() - np.isnan(av).sum())
        note = f"max abs {np.nanmax(absdiff):.6g}, max rel {np.nanmax(reldiff):.3%}"
        if nan_delta:
            note += f", NaN count {nan_delta:+d}"
        changed.append((key, note))

    print(f"\nIDENTICAL: {len(identical)} keys")

    print(f"\nCHANGED: {len(changed)} keys")
    for key, note in changed:
        print(f"  {key}\n      {note}")

    if errors:
        print(f"\nERRORS: {len(errors)} keys")
        for key, note in errors:
            print(f"  {key}\n      {note}")

    only_old = sorted(old_keys - new_keys)
    only_new = sorted(new_keys - old_keys)
    if only_old:
        print(f"\nONLY IN OLD ({len(only_old)}) -- expect the 4 MIC-7476 skips here:")
        for key in only_old:
            print(f"  {key}")
    if only_new:
        print(f"\nONLY IN NEW ({len(only_new)}):")
        for key in only_new:
            print(f"  {key}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
