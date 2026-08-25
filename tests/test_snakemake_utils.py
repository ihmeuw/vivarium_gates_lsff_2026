"""Unit tests for ``lsff_utils.snakemake_utils``.

``tolerant_psimulate_restart`` generates the bash that both simulation rules use to
retry incomplete tasks. It is worth testing out of proportion to its five lines,
because getting it wrong has already destroyed good results once: modern
vivarium-cluster-tools raises ``WorkflowAlreadyComplete`` rather than exiting 0 when
a run left nothing to retry, so under bash strict mode a *successful* simulation
failed its rule, and Snakemake then deleted the output as possibly corrupted.

Two things here are easy to "simplify" into breakage, and both are covered:

  - The doubled ``PIPESTATUS`` braces. Snakemake runs ``str.format`` over the
    assembled shell command to resolve ``{wildcards.x}``, so a single brace is read
    as a format field and raises NameError at DAG construction. Tested by actually
    calling ``str.format`` on the result.
  - The tolerate-one-error-only logic. Tested by *running* the generated bash
    against a stub ``psimulate`` on PATH, which needs no cluster: a real success, the
    tolerated already-complete case, and a genuine failure must exit 0, 0 and
    non-zero respectively.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from lsff_utils.snakemake_utils import dict_to_papermill, tolerant_psimulate_restart

CLUSTER_ARGS = "-P proj_simscience -m 2 -r 01:00:00 -q all.q"


def write_stub_psimulate(directory: Path, message: str, exit_code: int) -> None:
    """A fake ``psimulate`` that prints ``message`` and exits ``exit_code``."""
    stub = directory / "psimulate"
    stub.write_text(f'#!/bin/bash\necho "{message}"\nexit {exit_code}\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def run_snippet(snippet: str, stub_directory: Path, working_directory: Path) -> int:
    """Run the generated bash under strict mode, as the Snakefiles do.

    ``.format()`` first, because the raw snippet is deliberately *not* valid bash:
    ``${{PIPESTATUS[0]}}`` becomes a real parameter expansion only after Snakemake's
    format pass. Running it unformatted gives "bad substitution", so this call is
    part of reproducing the real execution path rather than a convenience.
    """
    environment = dict(os.environ, PATH=f"{stub_directory}:{os.environ['PATH']}")
    completed = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", snippet.format()],
        cwd=working_directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return completed.returncode


def test_snippet_survives_snakemakes_format_pass() -> None:
    """Snakemake calls ``str.format`` on the shell command before running it.

    The doubled braces exist for exactly this reason, so the test applies the same
    transformation and checks a single-brace ``${PIPESTATUS[0]}`` comes out. A
    single brace in the source would raise here, which is what happens at DAG
    construction time.
    """
    snippet = tolerant_psimulate_restart(CLUSTER_ARGS)

    formatted = snippet.format()

    assert "${PIPESTATUS[0]}" in formatted, (
        "after Snakemake's str.format pass the snippet no longer contains "
        f"${{PIPESTATUS[0]}}:\n{formatted}"
    )
    assert "{" not in formatted.replace("${PIPESTATUS[0]}", ""), (
        "unresolved braces survive the format pass, which means a literal brace is "
        "being read as a format field"
    )


def test_snippet_tolerates_only_the_already_complete_error() -> None:
    """The set of tolerated failures is exactly one, checked by name."""
    snippet = tolerant_psimulate_restart(CLUSTER_ARGS)

    assert "WorkflowAlreadyComplete" in snippet, (
        "the tolerated error is no longer named; if the library renamed it, update "
        "this and the docstring, but do not broaden the check to any failure"
    )
    assert 'exit "$restart_status"' in snippet or "exit $restart_status" in snippet, (
        "the snippet no longer re-raises the original exit status, so a genuine "
        "restart failure would be swallowed and the rule would report success"
    )


def test_snippet_logs_outside_the_globbed_results_directory() -> None:
    """``psimulate restart *`` globs the working directory, so the log must not land
    there or the restart would try to treat its own log as a run directory."""
    snippet = tolerant_psimulate_restart(CLUSTER_ARGS)

    assert "mktemp" in snippet, "restart log is no longer written to a temp file"


def test_snippet_passes_cluster_arguments_through() -> None:
    snippet = tolerant_psimulate_restart(CLUSTER_ARGS)

    assert CLUSTER_ARGS in snippet, f"cluster args missing from:\n{snippet}"


def test_successful_restart_exits_zero(tmp_path: Path) -> None:
    """The ordinary case: there were incomplete tasks and the restart handled them."""
    stub_directory = tmp_path / "bin"
    stub_directory.mkdir()
    write_stub_psimulate(stub_directory, "restarted 3 tasks", 0)

    status = run_snippet(tolerant_psimulate_restart(CLUSTER_ARGS), stub_directory, tmp_path)

    assert status == 0, f"a successful restart should exit 0, got {status}"


def test_already_complete_restart_exits_zero(tmp_path: Path) -> None:
    """The regression this function exists for.

    A fully successful first run leaves nothing to retry, jobmon raises
    ``WorkflowAlreadyComplete`` and psimulate exits non-zero. Before this helper,
    bash strict mode turned that into a rule failure and Snakemake deleted the
    perfectly good simulation output.
    """
    stub_directory = tmp_path / "bin"
    stub_directory.mkdir()
    write_stub_psimulate(
        stub_directory, "jobmon.exceptions.WorkflowAlreadyComplete: nothing to do", 1
    )

    status = run_snippet(tolerant_psimulate_restart(CLUSTER_ARGS), stub_directory, tmp_path)

    assert status == 0, (
        f"WorkflowAlreadyComplete should be tolerated but the snippet exited {status}. "
        "Under Snakemake this deletes the completed simulation output."
    )


def test_genuine_restart_failure_still_fails(tmp_path: Path) -> None:
    """The other half of the contract: everything except that one error must fail.

    Without this the helper would hide real breakage, which is worse than the
    problem it was written to solve.
    """
    stub_directory = tmp_path / "bin"
    stub_directory.mkdir()
    write_stub_psimulate(stub_directory, "RuntimeError: could not reach the cluster", 17)

    status = run_snippet(tolerant_psimulate_restart(CLUSTER_ARGS), stub_directory, tmp_path)

    assert status == 17, (
        f"a genuine restart failure should propagate its exit status, got {status}. "
        "Tolerating it would let a broken simulation look like a successful one."
    )


@pytest.mark.parametrize(
    "mapping,expected",
    [
        ({"location": "india"}, "-p location india"),
        ({"location": "india", "vehicle": "rice"}, "-p location india -p vehicle rice"),
        ({"vehicle": "bouillon cube"}, "-p vehicle 'bouillon cube'"),
        ({"draws": 10}, "-p draws 10"),
    ],
)
def test_dict_to_papermill_quotes_its_arguments(mapping: dict, expected: str) -> None:
    """Currently unused -- kept for the comment explaining the papermill-over-Snakemake
    decision -- but tested because the whole point of it over an f-string is the
    shell quoting, and a value with a space is exactly what a caller would get wrong.
    """
    assert dict_to_papermill(mapping) == expected
