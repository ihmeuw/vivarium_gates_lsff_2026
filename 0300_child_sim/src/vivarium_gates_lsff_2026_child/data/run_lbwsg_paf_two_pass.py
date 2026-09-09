"""Run the LBWSG PAF simulation twice, so the late neonatal PAF is computed on the
frame the main simulation actually produces.

The PAF simulation's mortality needs a ``(1 - PAF)`` deflation to kill at realistic
rates, but the PAF is what the simulation exists to compute. This mirrors how the
MNCNH project resolves that circularity (``vivarium_gates_mncnh``'s
``run_paf_sim.py``), reduced to LSFF's layout:

1. **Pass 1**: run the spec with no calibration (``rate x RR``, no deflation). The
   early neonatal PAF observed on the first time step is exact -- nobody has died
   yet -- but its late neonatal PAF is computed on a cohort whose high-RR categories
   were over-depleted by roughly ``E[RR]``-times-too-high mortality.
2. Extract the per-sex early neonatal PAF from pass 1 and write it as a calibration
   file.
3. **Pass 2**: run the same spec with ``lbwsg_paf_calibration.enn_paf_path`` pointing
   at that file. Early neonatal mortality is now deflated to the level the main
   simulation applies, so the second time step observes the late neonatal PAF on the
   true early-neonatal-survivor frame. Pass 2's output is the deliverable: its early
   neonatal PAF reproduces pass 1 exactly (mortality still precedes no observation),
   and its late neonatal PAF is the corrected one.

Pass 1's run directory and the generated calibration file and spec live under
``<output-root>/pass1/``, which the loader's run resolution (rooted at
``<output-root>/<location>/``) never scans, so they cannot be mistaken for results.
"""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

from vivarium_gates_lsff_2026_child.constants import paths as child_paths

# Matches the artifact PAF key's demographic frame; the component validates against
# this exact set before building its calibration lookup.
CALIBRATION_COLUMNS = ["sex", "age_start", "age_end", "year_start", "year_end", "value"]


def run_simulation(
    simulate_command: str, spec: Path, branches: str, artifact: Path, output: Path, extra: str
) -> None:
    """Invoke one simulation run exactly as the Snakefile recipe used to."""
    command = [
        *shlex.split(simulate_command),
        str(spec),
        *([branches] if branches else []),
        "-i",
        str(artifact),
        "-o",
        str(output),
        *shlex.split(extra),
    ]
    print(f"Running: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def find_paf_output(root: Path, exclude: Path | None = None) -> Path:
    """The newest PAF measure output under ``root``, whatever produced it.

    ``psimulate`` writes ``<location>/<timestamp>/results/<measure>/*.parquet`` and
    ``simulate run`` writes ``.../<measure>.parquet``; globbing for the measure name
    and taking the newest tolerates both.
    """
    candidates = [
        p
        for p in root.rglob(child_paths.LBWSG_PAF_MEASURE_NAME + "*")
        if exclude is None or exclude.resolve() not in p.resolve().parents
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No '{child_paths.LBWSG_PAF_MEASURE_NAME}' output found under '{root}'."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_paf(path: Path) -> pd.Series:
    """Mean PAF by (age_group, sex) from one run's measure output."""
    df = pd.read_parquet(path)
    return df.groupby(["age_group", "sex"])["value"].mean()


def build_calibration_frame(paf: pd.Series) -> pd.DataFrame:
    """The per-sex early neonatal PAF, shaped for the calibration lookup table.

    One value per sex, applied at every age: only mortality that precedes an
    observation can affect output, and the only such mortality is early neonatal
    (the late neonatal observation is taken before any late neonatal death is
    drawn), so the value carried beyond early neonatal ages is inert.
    """
    enn = paf.loc["early_neonatal"]
    if not ((enn > 0) & (enn < 1)).all():
        raise ValueError(f"Implausible early neonatal PAF from pass 1:\n{enn}")
    frame = enn.reset_index().rename(columns={"value": "value"})
    frame["age_start"] = 0.0
    frame["age_end"] = 5.0
    frame["year_start"] = 2021
    frame["year_end"] = 2023
    return frame[CALIBRATION_COLUMNS]


def write_pass2_spec(spec: Path, calibration_path: Path, out: Path) -> None:
    """Copy the spec with the calibration path filled in."""
    model_spec = yaml.safe_load(spec.read_text())
    model_spec["configuration"]["lbwsg_paf_calibration"] = {
        "enn_paf_path": str(calibration_path.resolve())
    }
    out.write_text(yaml.safe_dump(model_spec, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="lbwsg_paf.yaml")
    parser.add_argument("--branches", default="", help="branches yaml, or '' for none")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--simulate-command", default="psimulate run")
    parser.add_argument("--extra-args", default="", help="cluster/debug arguments")
    args = parser.parse_args()

    pass1_root = args.output_root / "pass1"
    pass1_root.mkdir(parents=True, exist_ok=True)

    print("=== Pass 1: uncalibrated run (early neonatal PAF only) ===", flush=True)
    run_simulation(
        args.simulate_command, args.spec, args.branches, args.artifact, pass1_root, args.extra_args
    )
    pass1_paf = read_paf(find_paf_output(pass1_root))
    print(f"Pass 1 PAFs:\n{pass1_paf}", flush=True)

    calibration_path = pass1_root / f"{args.location}_enn_paf_calibration.parquet"
    build_calibration_frame(pass1_paf).to_parquet(calibration_path, index=False)
    pass2_spec = pass1_root / f"{args.location}_lbwsg_paf_pass2.yaml"
    write_pass2_spec(args.spec, calibration_path, pass2_spec)

    print("=== Pass 2: calibrated run (both PAFs) ===", flush=True)
    run_simulation(
        args.simulate_command,
        pass2_spec,
        args.branches,
        args.artifact,
        args.output_root,
        args.extra_args,
    )
    pass2_paf = read_paf(find_paf_output(args.output_root, exclude=pass1_root))
    print(f"Pass 2 PAFs:\n{pass2_paf}", flush=True)

    # Mortality precedes no early neonatal observation, so calibration cannot move it:
    # a mismatch means the passes diverged some other way (spec drift, wrong artifact).
    if not pass1_paf.loc["early_neonatal"].round(6).equals(
        pass2_paf.loc["early_neonatal"].round(6)
    ):
        sys.exit("Pass 2 early neonatal PAF does not reproduce pass 1; investigate.")
    if not (pass2_paf.loc["late_neonatal"] < pass2_paf.loc["early_neonatal"]).all():
        sys.exit("Late neonatal PAF should be below early neonatal; investigate.")
    print("Two-pass LBWSG PAF run complete.", flush=True)


if __name__ == "__main__":
    main()
