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

import warnings
from contextlib import contextmanager
from functools import cache

import loguru
from joblib import Memory
from vivarium_gbd_access import gbd
import vivarium_gbd_access.utilities as vgu
from vivarium_inputs import globals as vi_globals
from vivarium_inputs import utilities as vi_utils
from vivarium_inputs import utility_data

# Loggers that emit once (or many times) per cached GBD call. Disabled together
# by :func:`quiet_gbd_logs`.
NOISY_LOGGERS = ["vivarium_inputs.validation.raw", "vivarium_gbd_access"]

# Warnings dropped by :func:`quiet_gbd_logs`, matched as substrings. Kept narrow
# on purpose -- this suppresses by message text, not by category, so a broad
# entry here would hide unrelated warnings.
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
def quiet_gbd_logs():
    """Silence the per-call chatter from a bulk GBD pull.

    A single ``get_measure`` call emits roughly 161 lines of log. At 66 sequelae
    per :func:`pull_sequelae_prevalence` call that buries the notebook, so this
    turns off four separate sources at once:

    - ``vivarium_gbd_access`` re-emits a multi-line config dump on *every*
      cached call, plus an INFO line per cache hit.
    - ``vivarium_inputs.validation.raw`` warns about data we knowingly tolerate.
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

    Everything is restored in a ``finally``, so an exception part-way through a
    pull cannot leave logging off for the rest of the session.

    Re-entrant: only the outermost block installs and restores. That matters
    because ``loguru.logger.enable()`` re-enables unconditionally rather than
    restoring the previous state, so a naive nested use would switch logging
    back on for the remainder of the enclosing block.
    """
    global _quiet_depth

    if _quiet_depth:
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

    for name in NOISY_LOGGERS:
        loguru.logger.disable(name)
    vgu.get_memory = _quiet_get_memory
    _quiet_depth += 1
    try:
        # catch_warnings saves and restores showwarning along with the filters.
        with warnings.catch_warnings():
            shown = warnings.showwarning

            def _drop_suppressed(message, category, filename, lineno, file=None, line=None):
                if any(text in str(message) for text in SUPPRESSED_WARNINGS):
                    return
                shown(message, category, filename, lineno, file, line)

            warnings.showwarning = _drop_suppressed
            yield
    finally:
        _quiet_depth -= 1
        vgu.get_memory = original_get_memory
        for name in NOISY_LOGGERS:
            loguru.logger.enable(name)


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
    """Normalize a raw GBD draw frame to the Vivarium index convention."""
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
