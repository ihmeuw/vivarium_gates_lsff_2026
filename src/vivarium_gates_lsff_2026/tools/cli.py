from typing import Optional, Tuple

import click
from loguru import logger
from vivarium.engine.framework.utilities import handle_exceptions


@click.command()
@click.option(
    "-p",
    "--project",
    required=True,
    type=click.Choice(["maternal", "child"]),
    help="Which model to build artifacts for.",
)
@click.option(
    "-l",
    "--location",
    default="all",
    show_default=True,
    type=str,
    help=(
        "Location for which to make an artifact. Note: prefer building artifacts on the cluster.\n"
        'If you specify location "all" you must be on a cluster node.'
    ),
)
@click.option(
    "-o",
    "--output-dir",
    default=None,
    type=click.Path(),
    help="Specify an output directory. Defaults to the project artifact root if not provided.",
)
@click.option(
    "-a",
    "--append",
    is_flag=True,
    help="Append to the artifact instead of overwriting.",
)
@click.option("-r", "--replace-keys", multiple=True, help="Specify keys to overwrite.")
@click.option("-v", "verbose", count=True, help="Configure logging verbosity.")
@click.option(
    "--mean",
    "mean_draw",
    is_flag=True,
    help="Generate a mean draw artifact.",
)
@click.option(
    "--vehicle",
    "vehicle",
    default="rice",
    show_default=True,
    type=str,
    help="Fortification vehicle.",
)
@click.option(
    "--pdb",
    "with_debugger",
    is_flag=True,
    help="Drop into python debugger if an error occurs.",
)
# Child-only flags
@click.option(
    "--national",
    "build_national",
    is_flag=True,
    help="(child only) Build artifacts at national level instead of subnational.",
)
@click.option(
    "--for-lbwsg-pafs",
    "for_lbwsg_pafs",
    is_flag=True,
    help="(child only) Build artifact for LBWSG PAFs.",
)
@click.option(
    "--fertility-data-path",
    "fertility_data_path",
    default=None,
    type=click.Path(),
    help="(child only) Location of fertility data.",
)
def make_artifacts(
    project: str,
    location: str,
    output_dir: Optional[str],
    append: bool,
    replace_keys: Tuple[str, ...],
    verbose: int,
    mean_draw: bool,
    vehicle: str,
    with_debugger: bool,
    build_national: bool,
    for_lbwsg_pafs: bool,
    fertility_data_path: Optional[str],
) -> None:
    location = location.title()

    if project == "maternal":
        from vivarium_gates_lsff_2026_maternal.constants import paths
        from vivarium_gates_lsff_2026_maternal.tools import (
            build_artifacts,
            configure_logging_to_terminal,
        )

        configure_logging_to_terminal(verbose)
        resolved_output_dir = output_dir or str(paths.ARTIFACT_ROOT)
        main = handle_exceptions(build_artifacts, logger, with_debugger=with_debugger)
        main(
            location,
            resolved_output_dir,
            append or replace_keys,
            replace_keys,
            mean_draw,
            vehicle,
            verbose,
        )
    elif project == "child":
        from vivarium_gates_lsff_2026_child.constants import paths
        from vivarium_gates_lsff_2026_child.tools import (
            build_artifacts,
            configure_logging_to_terminal,
        )

        configure_logging_to_terminal(verbose)
        resolved_output_dir = output_dir or str(paths.ARTIFACT_ROOT)
        fetch_subnationals = not build_national
        main = handle_exceptions(build_artifacts, logger, with_debugger=with_debugger)
        main(
            location,
            vehicle,
            resolved_output_dir,
            append or replace_keys,
            replace_keys,
            verbose,
            mean_draw,
            fertility_data_path,
            fetch_subnationals,
            for_lbwsg_pafs,
        )


if __name__ == "__main__":
    make_artifacts()
