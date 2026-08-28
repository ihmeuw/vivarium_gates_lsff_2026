"""
========
GBD Data
========

Shared helpers for pulling GBD data into the analysis notebooks.

This is the fetch-and-normalize layer that sits between the notebooks and
``vivarium_gbd_access`` / ``vivarium_inputs``; :mod:`lsff_utils.data_processing`
handles reshaping once the data is in hand. The two 0400 notebooks previously
carried verbatim copies of everything here, which is how they drifted apart.

.. warning::

   This module imports ``vivarium_gbd_access``, ``vivarium_inputs`` and
   ``joblib``, none of which exist in the *simulation* environment -- only in
   the *artifact* environment. That is safe because ``lsff_utils/__init__.py``
   is empty, so the simulation packages' ``from lsff_utils import paths`` (and
   friends) never load this module. Do not add a re-export of anything here to
   ``__init__.py``: it would break every simulation import.
"""

import collections
import importlib
import sys
import warnings
from contextlib import contextmanager
from enum import IntEnum
from functools import cache

import loguru
from joblib import Memory
from vivarium_gbd_access import gbd
import vivarium_gbd_access.utilities as vgu
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import utilities as vi_utils
from vivarium_inputs import utility_data

class Verbosity(IntEnum):
    """How much of a GBD pull's own output to let through.

    The two things a pull emits are not the same kind of thing, so they get
    separate treatment rather than a single on/off:

    - *bookkeeping* -- ``vivarium_gbd_access`` config dumps and cache-hit
      notices, plus joblib's cache banners. Pure volume; nothing is ever lost
      by dropping it, and it is dropped at every level below ``ALL``.
    - *data quality* -- ``vivarium_inputs`` warnings about missing age groups,
      unexpected columns, absent disability weights and the like. These can
      matter, especially across a GBD round change, so they are recorded even
      when they are not displayed.
    """

    QUIET = 0
    """Suppress everything and say nothing."""

    SUMMARY = 1
    """Suppress, then report the distinct data-quality warnings on exit."""

    WARNINGS = 2
    """Let data-quality warnings print as they happen; bookkeeping stays off."""

    ALL = 3
    """Suppress nothing."""


DEFAULT_VERBOSITY = Verbosity.SUMMARY
"""Used by :func:`quiet_gbd_logs` when no verbosity is passed. Set this once at
the top of a notebook to change every pull below it."""

# Bookkeeping-only loguru trees: 26 info + 3 debug records, no warnings or
# errors anywhere in the package, so disabling loses no information.
BOOKKEEPING_LOGGERS = ["vivarium_gbd_access"]

# Modules whose loguru warnings are data quality, not bookkeeping. Their
# module-level ``logger`` is swapped for a collector rather than disabled --
# loguru's disable() drops records before any sink sees them, so a disabled
# logger cannot be recorded. Every one of these does `from loguru import
# logger` at module scope, which is what makes the swap possible.
WARNING_SOURCE_MODULES = [
    "vivarium_inputs.validation.raw",
    "vivarium_inputs.validation.shared",
    "vivarium_inputs.core",
]

# Python warnings dropped by :func:`quiet_gbd_logs`, matched as substrings and
# counted so the summary can report them. Kept narrow on purpose -- this matches
# on message text, not category, so a broad entry would hide unrelated warnings.
SUPPRESSED_WARNINGS = ["No version_id was specified"]

# Nesting depth for quiet_gbd_logs; only the outermost block installs/restores.
_quiet_depth = 0

# The draw set every pull in this project is reduced to -- 250 columns in GBD
# 2023. Modelable entities return 1,000 raw draws while vivarium_inputs measures
# return 250, and the two get combined (e.g. non-iron-responsive prevalence is
# divided by GBD anemia prevalence), so they must agree on the same labels.
# Defined here rather than per-notebook so there is one place to change it --
# reassigning gbd_data.DRAWS takes effect everywhere, since the pull functions
# resolve it at call time.
DRAWS = vi_globals.DRAW_COLUMNS


class _WarningCollector:
    """Stands in for a module's ``loguru.logger``, recording warnings instead of
    emitting them. Anything other than ``warning`` falls through to the real
    logger, so a module that also logs at another level is unaffected."""

    def __init__(self, real):
        self._real = real
        self.messages = []

    def warning(self, message, *args, **kwargs):
        text = str(message)
        if args or kwargs:
            try:
                text = text.format(*args, **kwargs)
            except (IndexError, KeyError):
                pass
        self.messages.append(text)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _import_or_none(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _report_suppressed(collectors, warning_counts):
    """Print what a SUMMARY-level block swallowed, deduplicated."""
    messages = collections.Counter()
    for collector in collectors.values():
        messages.update(collector.messages)
    if not messages and not warning_counts:
        return

    lines = []
    if messages:
        lines.append(
            f"{sum(messages.values())} data-quality warning(s) from vivarium_inputs, "
            f"{len(messages)} distinct:"
        )
        lines += [f"    {n}x  {text}" for text, n in messages.most_common()]
    lines += [f"{n}x  {pattern!r}" for pattern, n in warning_counts.items()]
    lines.append(
        "Set gbd_data.DEFAULT_VERBOSITY = gbd_data.Verbosity.WARNINGS to see these live, "
        "or Verbosity.QUIET to stop reporting them."
    )
    print("quiet_gbd_logs: " + "\n  ".join(lines), file=sys.stderr)


# Columns dropped from a modelable-entity pull -- present in the raw GBD frame,
# meaningless once it is reshaped to the Vivarium convention.
_ME_METADATA_LEVELS = [
    "year_start",
    "year_end",
    "measure_id",
    "metric_id",
    "model_version_id",
    "modelable_entity_id",
]


@contextmanager
def quiet_gbd_logs(verbosity=None):
    """Silence the per-call chatter from a bulk GBD pull.

    A single ``get_measure`` call emits roughly 161 lines of log. At 66 sequelae
    per :func:`pull_sequelae_prevalence` call that buries the notebook, so this
    turns off several sources at once:

    - ``vivarium_gbd_access`` re-emits a multi-line config dump on *every*
      cached call, plus an INFO line per cache hit.
    - ``vivarium_gbd_access.utilities.get_memory`` hardcodes
      ``joblib.Memory(verbose=1)``, so it is swapped for one that builds the
      same cache in the same location, quietly. It has to be replaced rather
      than mutated: ``Memory.cache()`` reads the private ``_verbose``, so
      setting ``memory.verbose = 0`` after construction silently does nothing.
    - ``get_draws`` warns once per call that we did not pin a ``version_id``.
      This one cannot be handled with ``filterwarnings``:
      ``vivarium_gbd_access.gbd.base_data.get_draws`` calls
      ``warnings.filterwarnings("default", module="get_draws")`` on *every*
      call, and ``filterwarnings`` prepends, so an "ignore" filter installed
      here is immediately outranked. Overriding ``showwarning`` works because
      filters decide whether a warning is emitted, while ``showwarning``
      decides how it is displayed -- and nothing upstream touches that.
    - ``vivarium_inputs`` data-quality warnings, which are *recorded* rather
      than dropped -- see :class:`Verbosity`.

    Parameters
    ----------
    verbosity
        A :class:`Verbosity`. Defaults to :data:`DEFAULT_VERBOSITY`.

    Everything is restored in a ``finally``, so an exception part-way through a
    pull cannot leave logging off for the rest of the session.

    Re-entrant: only the outermost block installs and restores, and only it
    reports. That matters because ``loguru.logger.enable()`` re-enables
    unconditionally rather than restoring the previous state, so a naive nested
    use would switch logging back on for the remainder of the enclosing block.
    A nested block's ``verbosity`` is ignored; the outermost one governs.
    """
    global _quiet_depth

    verbosity = Verbosity(DEFAULT_VERBOSITY if verbosity is None else verbosity)

    if verbosity is Verbosity.ALL or _quiet_depth:
        _quiet_depth += 1
        try:
            yield
        finally:
            _quiet_depth -= 1
        return

    original_get_memory = vgu.get_memory

    def _quiet_get_memory():
        config = vgu.get_input_config()
        if not config.input_data.cache_data:
            return original_get_memory()
        return Memory(location=vgu.get_cache_directory(config), verbose=0)

    # Data-quality warnings are collected only when they are not being shown.
    collectors = {}
    if verbosity <= Verbosity.SUMMARY:
        for name in WARNING_SOURCE_MODULES:
            module = _import_or_none(name)
            if module is None:
                continue
            collectors[name] = _WarningCollector(module.logger)
            module.logger = collectors[name]

    warning_counts = collections.Counter()
    for name in BOOKKEEPING_LOGGERS:
        loguru.logger.disable(name)
    vgu.get_memory = _quiet_get_memory
    _quiet_depth += 1
    try:
        # catch_warnings saves and restores showwarning along with the filters.
        with warnings.catch_warnings():
            shown = warnings.showwarning

            def _drop_suppressed(message, category, filename, lineno, file=None, line=None):
                text = str(message)
                for pattern in SUPPRESSED_WARNINGS:
                    if pattern in text:
                        warning_counts[pattern] += 1
                        return
                shown(message, category, filename, lineno, file, line)

            warnings.showwarning = _drop_suppressed
            yield
    finally:
        _quiet_depth -= 1
        vgu.get_memory = original_get_memory
        for name in BOOKKEEPING_LOGGERS:
            loguru.logger.enable(name)
        for name, collector in collectors.items():
            _import_or_none(name).logger = collector._real
        if verbosity is Verbosity.SUMMARY:
            _report_suppressed(collectors, warning_counts)


@cache
def most_recent_year() -> int:
    """The most recent estimation year in the current GBD release.

    2023 for release 16. Note that 2021 is *not* a GBD 2023 estimation year --
    the full set is 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2022, 2023, 2024.

    A function rather than a module-level constant, because resolving it is
    itself a cached GBD call: doing it at import time would make ``import
    gbd_data`` reach for the database and emit three lines of log before any
    caller has a chance to silence them. Memoized, so repeat calls are free.
    """
    with quiet_gbd_logs():
        return utility_data.get_most_recent_year()


def patch_population_validation_ceiling(ceiling: int = 1_000_000_000) -> int:
    """Raise ``vivarium_inputs``' hardcoded upper bound on a population value.

    ``vivarium_inputs.validation.raw.MAX_POP`` is ``695_000_000``, commented
    "Number pulled from GBD global population largest 5 year age bin". It was
    calibrated on an earlier round and GBD 2023 has outgrown it, so
    ``get_population_structure("Global")`` raises ``DataAbnormalError``.

    Exactly one row of 75 trips it -- the *both sexes* 5-to-9 bin, at
    700,543,600 -- and ``get_population_structure`` discards that row on its own,
    so the guard fires on data that never reaches the analysis. Per-country
    pulls are nowhere near the limit; this is only needed for ``"Global"``.

    Returns the previous value.

    TODO: Remove once vivarium_inputs raises MAX_POP for GBD 2023.
    """
    from vivarium_inputs.validation import raw as vi_raw

    previous = vi_raw.MAX_POP
    vi_raw.MAX_POP = ceiling
    return previous


def reshape_to_vivarium_format(df, location):
    """Normalize a raw GBD draw frame to the Vivarium index convention.

    Quiet despite doing no fetching of its own: ``scrub_gbd_conventions`` looks
    up location IDs and age bins, each a cached GBD call worth several lines of
    log. Nesting is harmless -- :func:`quiet_gbd_logs` is re-entrant, so the
    call from :func:`pull_modelable_entity_draws` is a no-op.
    """
    with quiet_gbd_logs():
        df = vi_utils.reshape(df, value_cols=[c for c in df.columns if "draw_" in c])
        df = vi_utils.scrub_gbd_conventions(df, location)
        df = vi_utils.split_interval(df, interval_column="age", split_column_prefix="age")
        df = vi_utils.split_interval(df, interval_column="year", split_column_prefix="year")
        df = vi_utils.sort_hierarchical_data(df)
        df.index = df.index.droplevel("location")
        return df


def pull_modelable_entity_draws(me_id, location, year=None, draws=None):
    """Pull draws for a modelable entity, reshaped to the Vivarium convention.

    Named to match :func:`pull_sequelae_prevalence` rather than the
    ``vivarium_gbd_access`` function it wraps -- the two take different
    arguments and return different shapes, so sharing a name invites misreading
    at the call site.

    Parameters
    ----------
    me_id
        GBD modelable entity ID.
    location
        Location name; case is normalized before resolution.
    year
        Estimation year. Defaults to :func:`most_recent_year`.
    draws
        Draw columns to keep. Defaults to the module-level :data:`DRAWS`,
        resolved at call time so reassigning it takes effect here. Modelable
        entities return 1,000 raw draws, so this truncates to the first 250 --
        matching what ``vivarium_inputs`` returns for the measures these get
        combined with.
    """
    with quiet_gbd_logs():
        # NOTE: resolved inside the context manager -- get_most_recent_year is itself
        # a cached GBD call, so defaulting it outside leaks its logs.
        if year is None:
            year = most_recent_year()
        if draws is None:
            draws = DRAWS

        location_id = utility_data.resolve_location(location.title())
        result = gbd.get_modelable_entity_draws(
            me_id=me_id, location_id=location_id, year_id=year, data_type="draws"
        )
        return (
            reshape_to_vivarium_format(result, location.title())
            .droplevel(_ME_METADATA_LEVELS)[draws]
            .copy()
        )
