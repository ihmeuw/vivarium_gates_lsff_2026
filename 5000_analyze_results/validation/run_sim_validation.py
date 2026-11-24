"""Run the simulation V&V notebooks once per arm, through papermill.

The source notebooks in ``pregnancy_model_NO/`` and ``child_model/`` are kept
without outputs. Each arm's execution, with its outputs, is written to

    {folder}/executed/{location}/{vehicle}/{notebook}.ipynb

i.e. an ``executed/`` folder inside each of ``pregnancy_model_NO/`` and
``child_model/``.

Arms are discovered from what the data source actually holds, the way the
``non_simulation/`` notebooks do it -- not from 0050_config, which describes the
working tree and can disagree with an archived iteration. A pregnancy notebook
runs for every arm with a run under the maternal results, a child notebook for
every arm with a run under the child results.

The data source is ``lsff_utils.paths.MODEL_NUMBER`` unless ``--data-source``
names another iteration (or ``local`` for this working tree). It is passed to
each notebook explicitly, so the arms found here and the run the notebook reads
always come from the same place. Archive before validating.

Examples::

    python run_sim_validation.py                            # MODEL_NUMBER
    python run_sim_validation.py --data-source model2.6.2   # a previous iteration
"""

import argparse
import logging
import sys
import traceback
from pathlib import Path

import papermill

from lsff_utils import paths

HERE = Path(__file__).resolve().parent

# Each folder's notebooks read one simulation's results; that is where its arms
# are discovered.
FOLDERS = {
    "pregnancy_model_NO": (
        paths.MATERNAL_RESULTS_ROOT,
        ["mat_dis_anemia.ipynb", "preg_states.ipynb"],
    ),
    "child_model": (
        paths.CHILD_RESULTS_ROOT,
        ["child_lbwsg.ipynb", "child_lbwsg_gbd.ipynb", "child_mortality.ipynb"],
    ),
}


def _drop_data_source_warnings(record: logging.LogRecord) -> bool:
    """Hide papermill's two warnings about ``data_source``; it is still injected.

    papermill lists a notebook's parameters by parsing the `parameters` cell, and
    it cannot parse ``data_source``'s default (a function call). It warns about
    that line, then warns again that ``data_source`` is "unknown" when it is
    passed -- but it injects every passed parameter regardless. Any other
    papermill warning still shows.
    """
    message = record.getMessage()
    return not (
        message.startswith("Unable to parse line") and "data_source =" in message
        or message == "Passed unknown parameter: data_source"
    )


# A logger's filter does not apply to its children, and the parse warning is
# logged by papermill.translators, not papermill.
for _name in ("papermill", "papermill.translators"):
    logging.getLogger(_name).addFilter(_drop_data_source_warnings)


def discover_arms(results_root: Path) -> list[tuple[str, str]]:
    """(location, vehicle) pairs with at least one run under ``results_root``.

    Results are laid out ``{vehicle}/{location}/{timestamped run}/``.
    """
    return sorted(
        (location_dir.name, location_dir.parent.name)
        for location_dir in results_root.glob("*/*")
        if paths.run_dirs(location_dir)
    )


def executed_path(notebook: Path, location: str, vehicle: str) -> Path:
    return notebook.parent / "executed" / location / vehicle / notebook.name


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data-source",
        default=paths.MODEL_NUMBER,
        help=f"A model number, or 'local' for this working tree. Default: {paths.MODEL_NUMBER}.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop at the first failing notebook instead of running the rest.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data_source = args.data_source

    # (location, vehicle, notebook) jobs.
    jobs = []
    for folder, (results_root, notebook_names) in FOLDERS.items():
        root = paths.source_root(results_root, data_source)
        found = discover_arms(root)
        print(f"{data_source} {folder}: {root}")
        print(f"  arms: {', '.join(f'{l}/{v}' for l, v in found) or '(none)'}")

        for name in notebook_names:
            notebook = HERE / folder / name
            jobs += [(location, vehicle, notebook) for location, vehicle in found]

    if not jobs:
        sys.exit("Nothing to run.")

    failures = []
    for location, vehicle, notebook in jobs:
        output = executed_path(notebook, location, vehicle)
        output.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {location}/{vehicle}: {notebook.relative_to(HERE)}", flush=True)
        print(f"    -> {output.relative_to(HERE)}", flush=True)
        try:
            papermill.execute_notebook(
                str(notebook),
                str(output),
                parameters={"location": location, "vehicle": vehicle, "data_source": data_source},
                kernel_name="python3",
                # Run from the notebook's own folder, so any relative paths in it
                # resolve the same as when it is run by hand.
                cwd=str(notebook.parent),
            )
        except Exception:
            # papermill has still written the partial notebook to `output`, with
            # the traceback in the failing cell.
            traceback.print_exc()
            failures.append((location, vehicle, notebook, output))
            if args.stop_on_error:
                break

    if failures:
        print(f"\n{len(failures)} notebook(s) failed:", file=sys.stderr)
        for location, vehicle, notebook, output in failures:
            print(f"  {location}/{vehicle} {notebook.name}  (see {output})", file=sys.stderr)
        sys.exit(1)
    print(f"\nAll {len(jobs)} notebooks ran.")


if __name__ == "__main__":
    main()
