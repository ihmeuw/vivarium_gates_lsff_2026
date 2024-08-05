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

Activate your environment with `conda activate ./.conda_env`, then you can
run `snakemake` to reproduce the results.

One caveat is the raw input data
from surveys, which isn't included in the repository.
If you are on the IHME cluster this will be loaded from J:\Data; otherwise,
you'll need to download this data yourself, and update the corresponding notebooks.