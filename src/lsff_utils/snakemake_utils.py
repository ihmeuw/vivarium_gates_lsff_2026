from shlex import quote


# We use papermill to run the notebooks, instead of the built-in Snakemake integration,
# because it does not generate incremental output, nor output notebooks when there is
# an error. See https://github.com/snakemake/snakemake/pull/2857
def dict_to_papermill(d):
    return " ".join([f"-p {quote(str(k))} {quote(str(v))}" for k, v in d.items()])


def tolerant_psimulate_restart(cluster_args):
    """Bash to retry incomplete simulation tasks, tolerating "nothing to retry".

    Both simulation rules follow `psimulate run` with an unconditional
    `psimulate restart *` to pick up any tasks the first run left incomplete.
    Under the old suite a fully successful run made that a no-op. Modern
    vivarium-cluster-tools drives psimulate through jobmon, which raises
    `WorkflowAlreadyComplete` instead of exiting 0 when every task is already
    done -- so with bash strict mode a *successful* run failed the rule, and
    Snakemake then deleted the good results as possibly corrupted.

    Tolerate exactly that one error and nothing else: a restart that fails for
    any other reason still fails the rule. The log goes to a node-local temp
    file rather than the results directory, which `psimulate restart *` globs.

    The `PIPESTATUS` braces are doubled because Snakemake runs `str.format` over
    the assembled shell command to resolve `{{wildcards.x}}`, so a single brace
    here is read as a format field and raises NameError.
    """
    return f"""
        restart_log=$(mktemp)
        set +e
        psimulate restart * {cluster_args} 2>&1 | tee "$restart_log"
        restart_status=${{{{PIPESTATUS[0]}}}}
        set -e
        if [ "$restart_status" -ne 0 ] && ! grep -q WorkflowAlreadyComplete "$restart_log"; then
            exit "$restart_status"
        fi
    """.strip()
