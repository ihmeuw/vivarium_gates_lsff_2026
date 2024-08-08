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
- Run `snakemake` to reproduce the results.

This will only work on the IHME cluster, since it loads GBD and GHDx data.