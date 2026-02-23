# Impact of large-scale food fortification (LSFF) by wealth

## Setup

First, install conda if you haven't already; we recommend using [Miniforge](https://github.com/conda-forge/miniforge) which can be
installed with:

```
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh
```

Then, make a conda environment for the project with:

```
conda create --prefix .conda_env --file conda_lock.txt
```

**Note: This won't work unless you are on Linux and an x86 processor.**

Then:

- Activate your environment with `conda activate ./.conda_env`.
- Install the utilities with `pip install -e .`.
- Run `snakemake` to approximately reproduce the results, or `snakemake --config full_scale=yes` to reproduce the results at full scale.

This will only work on the IHME cluster, since it loads GBD and GHDx data, and uses Slurm (by default)
to run the microsimulations.
Add `local=yes` to your `--config` to avoid this by running the simulations locally
(will be slow, especially at full scale).

Also, if you are running somewhere (like your IHME home directory) where you can't afford to dump
10s of gigabytes of logs (!), try running `watch 'truncate -s 0 */sim_results/*/*/*/logs/*/*/*'`
in another terminal while you run this.
This may be fixed by more recent Vivarium versions, because the Vivarium version here outputs
many duplicate logs from a `psimulate`.

## Development

This repository enforces code linting. Here are the steps to fix your code if it does not pass:

- Ensure that Snakemake is completely up to date and you have committed all changes.
- `conda activate ./.conda_env` (if you haven't already)
- `source .venv/bin/activate`
- `isort . --gitignore --profile black` (takes some time)
- `black .`
- `snakemake --config <your config from your previous snakemake run> --touch` to tell Snakemake that linting changes don't require reruns 