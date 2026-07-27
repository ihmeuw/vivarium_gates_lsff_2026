from shlex import quote


# We use papermill to run the notebooks, instead of the built-in Snakemake integration,
# because it does not generate incremental output, nor output notebooks when there is
# an error. See https://github.com/snakemake/snakemake/pull/2857
def dict_to_papermill(d):
    return " ".join([f"-p {quote(str(k))} {quote(str(v))}" for k, v in d.items()])
