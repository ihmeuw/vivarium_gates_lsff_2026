import argparse
from time import time
from layered_config_tree import LayeredConfigTree
import pandas as pd

from multiprocessing import Pool

if __name__ == "__main__":
    parser = argparse.ArgumentParser("local_psimulate")
    parser.add_argument("model_spec", type=str)
    parser.add_argument("branches", type=str)
    parser.add_argument("-i", "--input-artifact", type=str)
    parser.add_argument("-o", "--output-directory", type=str)
    args = parser.parse_args()

    from vivarium.framework.engine import SimulationContext

    from pathlib import Path

    from vivarium.framework.configuration import build_model_specification
    from vivarium_cluster_tools.psimulate.branches import Keyspace
    from vivarium_cluster_tools.psimulate import model_specification, COMMANDS

    keyspace = Keyspace.from_branch_configuration(Path(args.branches))

    model_spec = model_specification.parse(
        command=COMMANDS.run,
        input_model_specification_path=Path(args.model_spec),
        artifact_path=Path(args.input_artifact),
        model_specification_path=Path(args.model_spec),
        results_root=Path(args.output_directory),
        keyspace=keyspace,
    )

    base_output_dir = Path(f"{args.output_directory}/{Path(args.input_artifact).stem}/local_psimulate")
    import shutil
    shutil.rmtree(base_output_dir, ignore_errors=True)
    base_output_dir.mkdir(exist_ok=True, parents=True)

    def run(tuple):
        input_draw, random_seed, branch_config = tuple
        configuration = LayeredConfigTree(
            branch_config, layers=["branch_base", "branch_expanded"]
        )

        configuration.update(
            {
                "randomness": {
                    "random_seed": random_seed,
                    "additional_seed": input_draw,
                },
                "input_data": {
                    "input_draw_number": input_draw,
                },
            },
            layer="branch_expanded",
            source="branch_config",
        )
        branch_config.update(configuration.to_dict())
        sim = SimulationContext(
            model_spec, configuration=configuration
        )
        sim.run_simulation()

        results = sim.get_results()  # Dict[measure, results dataframe]

        from vivarium.framework.utilities import collapse_nested_dict
        # https://github.com/ihmeuw/vivarium_cluster_tools/blob/37e611e3d76f622083e5785fa37b5aee95b28fa3/src/vivarium_cluster_tools/psimulate/worker/vivarium_work_horse.py#L213-L224
        for key, val in collapse_nested_dict(branch_config):
            # Exclude the run_configuration values from branch_configuration
            # since they are duplicates. Also do not include the additional_seed
            # value since it is identical to input_draw
            col_name = key.split(".")[-1]
            col_name = "input_draw" if col_name == "input_draw_number" else col_name
            if not (key.startswith("run_configuration") or "additional_seed" in key):
                for df in results.values():
                    # insert the new columns second from the right and use the
                    # last part of the key as the column name
                    df.insert(df.shape[1] - 1, col_name, val)
        
        return results

    with Pool(5) as p:
        all_results = p.map(run, list(keyspace))
    
    all_results_keys = set()
    for results_dict in all_results:
        all_results_keys = all_results_keys | set(results_dict.keys())

    results_dir = base_output_dir / "results"
    results_dir.mkdir(exist_ok=True, parents=True)
    for key in all_results_keys:
        df = pd.concat([
            result_dict[key]
            for result_dict in
            all_results
        ])
        df.to_parquet(results_dir / f"{key}.parquet")