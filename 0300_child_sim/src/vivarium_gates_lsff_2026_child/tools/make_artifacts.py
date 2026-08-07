"""Main application functions for building artifacts.

.. admonition::

   Logging in this module should typically be done at the ``info`` level.
   Use your best judgement.

"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple, Union

import click
from loguru import logger
from vivarium import cluster_tools as vct
from vivarium.cluster_tools.core.cluster.interface import NativeSpecification
from vivarium.cluster_tools.core.jobmon.artifact import build_artifacts_in_parallel

from vivarium_gates_lsff_2026_child.constants import data_keys, metadata
from vivarium_gates_lsff_2026_child.tools.app_logging import add_logging_sink
from vivarium_gates_lsff_2026_child.utilities import (
    delete_if_exists,
    len_longest_location,
    sanitize_location,
)


def running_from_cluster() -> bool:
    on_cluster = True

    try:
        vct.get_cluster_name()
    except:
        on_cluster = False
    return on_cluster


def check_for_existing(
    output_dir: Path, location: str, append: bool, replace_keys: Tuple
) -> None:
    existing_artifacts = set(
        [
            item.stem
            for item in output_dir.iterdir()
            if item.is_file() and item.suffix == ".hdf"
        ]
    )
    locations = set([sanitize_location(loc) for loc in metadata.LOCATIONS])
    existing = locations.intersection(existing_artifacts)

    if existing:
        if location != "all":
            existing = [sanitize_location(location)]
        if not append:
            click.confirm(
                f"Existing artifacts found for {existing}. Do you want to delete and rebuild?",
                abort=True,
            )
            for loc in existing:
                path = output_dir / f"{loc}.hdf"
                logger.info(f"Deleting artifact at {str(path)}.")
                path.unlink(missing_ok=True)
        elif replace_keys:
            click.confirm(
                f"Existing artifacts found for {existing}. If the listed keys {replace_keys} "
                "exist, they will be deleted and regenerated. Do you want to delete and regenerate "
                "them?",
                abort=True,
            )


def build_single(
    location: str,
    vehicle: str,
    output_dir: str,
    replace_keys: Tuple,
    mean_draw: bool,
    fertility_data_path: str,
    fetch_subnationals: bool,
    for_lbwsg_pafs: bool,
) -> None:
    path = Path(output_dir) / f"{sanitize_location(location)}.hdf"
    build_single_location_artifact(
        path,
        location,
        vehicle,
        replace_keys,
        mean_draw,
        fertility_data_path,
        fetch_subnationals,
        for_lbwsg_pafs,
    )


def build_artifacts(
    location: str,
    vehicle: str,
    output_dir: str,
    append: bool,
    replace_keys: Tuple,
    verbose: int,
    mean_draw: bool,
    fertility_data_path: str,
    fetch_subnationals: bool,
    for_lbwsg_pafs: bool,
) -> None:
    """Main application function for building artifacts.
    Parameters
    ----------
    location
        The location to build the artifact for.  Must be one of the
        locations specified in the project globals or the string 'all'.
        If the latter, this application will build all artifacts in
        parallel.
    output_dir
        The path where the artifact files will be built. The directory
        will be created if it doesn't exist
    append
        Whether we should append to existing artifacts at the given output
        directory.  Has no effect if artifacts are not found.
    replace_keys
        A list of keys to replace in the artifact. Is ignored if append is
        False or if there is no existing artifact at the output location
    fetch_subnationals
        Whether to fetch subnational data.  If False, only national data.
    verbose
        How noisy the logger should be.
    """

    output_dir = Path(output_dir)
    vct.mkdir(output_dir, parents=True, exists_ok=True)

    check_for_existing(output_dir, location, append, replace_keys)

    if location in metadata.LOCATIONS:
        build_single(
            location,
            vehicle,
            output_dir,
            replace_keys,
            mean_draw,
            fertility_data_path,
            fetch_subnationals,
            for_lbwsg_pafs,
        )
    elif location == "all":
        if running_from_cluster():
            # parallel build when on cluster
            build_all_artifacts(
                output_dir,
                vehicle,
                mean_draw,
                verbose,
                fertility_data_path,
                fetch_subnationals,
                for_lbwsg_pafs,
            )
        else:
            # serial build when not on cluster
            for loc in metadata.LOCATIONS:
                build_single(
                    loc,
                    vehicle,
                    output_dir,
                    replace_keys,
                    mean_draw,
                    fertility_data_path,
                    fetch_subnationals,
                    for_lbwsg_pafs,
                )
    else:
        raise ValueError(
            f'Location must be one of {metadata.LOCATIONS} or the string "all". '
            f"You specified {location}."
        )


def build_all_artifacts(
    output_dir: Path,
    vehicle: str,
    mean_draw: bool,
    verbose: int,
    fertility_data_path: str,
    fetch_subnationals: bool,
    for_lbwsg_pafs: bool,
) -> None:
    """Builds artifacts for all locations in parallel.

    Each location becomes an independent Jobmon task, so they build concurrently.

    Parameters
    ----------
    output_dir
        The directory where the artifacts will be built.
    vehicle
        The fortification vehicle to build for.
    mean_draw
        Whether to collapse draws to their mean.
    verbose
        How noisy the logger should be.
    fertility_data_path
        Location of the maternal simulation's birth records. Ignored when
        building the cut-down LBWSG PAF artifact, which has no fertility key.
    fetch_subnationals
        Whether to pull subnational rather than national data.
    for_lbwsg_pafs
        Whether to build the cut-down artifact that feeds the PAF calculation.

    Note
    ----
        This function should not be called directly.  It is intended to be
        called by the :func:`build_artifacts` function located in the same
        module.
    """
    build_commands = {}
    for location in metadata.LOCATIONS:
        location_cleaned = sanitize_location(location)
        artifact_path = output_dir / f"{location_cleaned}.hdf"
        command = (
            f"{sys.executable} {Path(__file__).resolve()} "
            f'--artifact-path "{artifact_path}" '
            f'--location "{location}" '
            f'--vehicle "{vehicle}"'
        )
        if mean_draw:
            command += " --mean"
        if fetch_subnationals:
            command += " --fetch-subnationals"
        if for_lbwsg_pafs:
            command += " --for-lbwsg-pafs"
        if fertility_data_path:
            command += f' --fertility-data-path "{fertility_data_path}"'
        build_commands[f"{location_cleaned}_artifact"] = command

    native_specification = NativeSpecification(
        job_name="make_artifacts",
        project=metadata.CLUSTER_PROJECT,
        queue=metadata.CLUSTER_QUEUE,
        peak_memory=metadata.MAKE_ARTIFACT_MEM,
        max_runtime=metadata.MAKE_ARTIFACT_RUNTIME,
        hardware=[],
        cores=metadata.MAKE_ARTIFACT_CPU,
        requires_archive_node=True,  # Need J-drive access for data
    )

    # SLURM will not create a missing log directory; it fails the job instead.
    worker_logging_root = output_dir / "logs"
    vct.mkdir(worker_logging_root, parents=True, exists_ok=True)

    # A workflow name is also its resume key, so it must be unique per run:
    # reusing one without resume=True makes Jobmon refuse to start.
    launch_time = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    logger.info(f"Submitting {len(build_commands)} artifact builds to Jobmon.")
    _, monitoring_url = build_artifacts_in_parallel(
        workflow_name=f"build_child_artifacts_{launch_time}",
        build_commands=build_commands,
        native_specification=native_specification,
        worker_logging_root=worker_logging_root,
        env_prefix=sys.prefix,
        max_concurrently_running=len(build_commands),
    )
    if monitoring_url:
        logger.info(f"Monitor the workflow at {monitoring_url}")

    logger.info("**Done**")


def build_single_location_artifact(
    path: Union[str, Path],
    location: str,
    vehicle: str,
    replace_keys: Tuple = (),
    mean_draw: bool = True,
    fertility_data_path: str = None,
    fetch_subnationals: bool = False,
    for_lbwsg_pafs: bool = True,
    log_to_file: bool = False,
) -> None:
    """Builds an artifact for a single location.
    Parameters
    ----------
    path
        The full path to the artifact to build.
    location
        The location to build the artifact for.  Must be one of the locations
        specified in the project globals.
    log_to_file
        Whether we should write the application logs to a file.
    Note
    ----
        This function should not be called directly.  It is intended to be
        called by the :func:`build_artifacts` function located in the same
        module.
    """
    location = location.strip('"')
    path = Path(path)
    if log_to_file:
        log_file = path.parent / "logs" / f"{sanitize_location(location)}.log"
        if log_file.exists():
            log_file.unlink()
        add_logging_sink(log_file, verbose=2)

    # Local import to avoid data dependencies
    from vivarium_gates_lsff_2026_child.data import builder

    logger.info(f"Building artifact for {location} at {str(path)}.")
    artifact = builder.open_artifact(path, location)

    for key_group in data_keys.MAKE_ARTIFACT_KEY_GROUPS:
        if key_group == data_keys.DIARRHEA and not for_lbwsg_pafs:
            continue
        logger.info(f"Loading and writing {key_group.log_name} data")
        for key in key_group:
            if (
                key
                in (
                    data_keys.LBWSG.PAF,
                    data_keys.POPULATION.FERTILITY_DATA,
                    data_keys.LBWSG.BIRTH_WEIGHT_WEALTH_DISPARITIES,
                    data_keys.IRON_FORTIFICATION.BIRTH_WEIGHT_EFFECT_SIZE,
                )
                and for_lbwsg_pafs
            ):
                continue
            logger.info(f"   - Loading and writing {key} data")
            builder.load_and_write_data(
                artifact,
                key,
                location,
                vehicle,
                key in replace_keys,
                mean_draw,
                fertility_data_path,
                fetch_subnationals,
            )

    logger.info(f"**Done building -- {location}**")


if __name__ == "__main__":
    # Entry point for the per-location tasks that build_all_artifacts submits.
    # Named flags rather than positional argv, for two reasons. Booleans passed
    # positionally arrive as strings and every non-empty string is truthy, so
    # 'False' would read as True. And the previous positional call was misaligned
    # against this signature -- mean_draw landed in 'vehicle', fetch_subnationals
    # in 'replace_keys', and for_lbwsg_pafs in 'mean_draw'.
    parser = argparse.ArgumentParser(description="Build the artifact for a single location.")
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--vehicle", default="rice")
    parser.add_argument("--mean", dest="mean_draw", action="store_true")
    parser.add_argument("--fetch-subnationals", action="store_true")
    parser.add_argument("--for-lbwsg-pafs", action="store_true")
    parser.add_argument("--fertility-data-path", default=None)
    args = parser.parse_args()

    build_single_location_artifact(
        args.artifact_path,
        args.location,
        args.vehicle,
        mean_draw=args.mean_draw,
        fertility_data_path=args.fertility_data_path,
        fetch_subnationals=args.fetch_subnationals,
        for_lbwsg_pafs=args.for_lbwsg_pafs,
        log_to_file=True,
    )
