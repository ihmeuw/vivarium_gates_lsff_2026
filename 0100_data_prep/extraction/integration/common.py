"""Shared vocabulary and helpers for the GF + literature integration scripts.

Everything that encodes *our* terminology lives here, so the extract scripts and the
build script agree on it: data-need names (with short aliases), table names,
quintile/vehicle/country/fortificant spellings, unit conversions, and the code that
reads the base extraction tables and writes the generated ones.
"""

import datetime
import hashlib
import math
import pathlib

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
EXTRACTION_DIR = HERE.parent

# Hand-maintained extraction tables (the base layer) and the build's output, which is
# what the data prep notebooks read. See ../README.md.
BASE_DIR = EXTRACTION_DIR / "data"
GENERATED_DIR = EXTRACTION_DIR / "generated"

# The source workbooks live outside the repo (SharePoint). Their extracts are committed
# as gf_long.csv and lit_long.csv, and sources.csv records which file each came from.
GF_FILE = EXTRACTION_DIR / "Nutrition PST Background Data.xlsx"
LIT_FILE = EXTRACTION_DIR / "LSFF_effect_sizes.xlsx"

GF_LONG = HERE / "gf_long.csv"
LIT_LONG = HERE / "lit_long.csv"
SOURCES = HERE / "sources.csv"
ARMS_FILE = HERE / "arms.csv"
DECISIONS_FILE = HERE / "decisions.csv"

# --------------------------------------------------------------------------------------
# Our extraction tables and data needs
# --------------------------------------------------------------------------------------

# The tables the build manages (file stems in data/ and generated/). The other tables in
# data/ (country, universal, data_sources, progress) are read as they are.
CV = "country_vehicle"
CVF = "country_vehicle_fortificant"
SCEN = "scenario_definition"
VEH = "vehicle"
TABLES = [CV, CVF, SCEN, VEH]

# alias -> (table, full data-need text as it appears in the table)
NEEDS = {
    "any": (CV, "Vehicle consumption by WRA -- any"),
    "amount": (CV, "Vehicle consumption by WRA -- amount"),
    "u5_any": (CV, "Vehicle consumption by U5 children -- any"),
    "u5_amount": (CV, "Vehicle consumption by U5 children -- amount"),
    "fortifiability": (CV, 'Vehicle "fortifiability" (essentially amount industrially produced)'),
    "baseline_any": (CVF, "Vehicle fortification at baseline -- any"),
    "baseline_concentration": (CVF, "Vehicle fortification at baseline -- amount among fortified"),
    "baseline_effectiveness": (CVF, "Baseline effective % of fortified"),
    "intervention_coverage": (SCEN, "Intervention coverage % of fortifiable"),
    "intervention_effectiveness": (SCEN, "Intervention effective % of fortified"),
    "intervention_concentration": (SCEN, "Vehicle fortification in intervention -- amount among fortified"),
    "hb_effect": (VEH, "Iron fortification/consumption effect on hemoglobin"),
    "bw_effect": (VEH, "Iron fortification/consumption effect on birthweight"),
}

QUINTILES = ["Lowest", "Second", "Middle", "Fourth", "Highest"]
ALL_SAME = "All (assumed same)"


def norm(x):
    """Case/space-insensitive comparison key ('' for missing)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    return " ".join(str(x).split()).lower()


# Spelling fixes seen in hand extractions. Add to these rather than editing source sheets.
TYPO_FIXES = {
    "nigera": "nigeria",
    "fortication": "fortification",
}


def fix_typos(text):
    out = norm(text)
    for wrong, right in TYPO_FIXES.items():
        out = out.replace(wrong, right)
    return out


COUNTRIES = {"nigeria": "Nigeria", "ethiopia": "Ethiopia", "india": "India"}
VEHICLES = {
    "wheat": "Wheat", "wheat flour": "Wheat", "rice": "Rice", "salt": "Salt", "salt (dfs)": "Salt",
    "salt/dfs": "Salt", "bouillon": "Bouillon", "edible oil": "Oil", "oil": "Oil",
    "maize flour": "Maize", "maize": "Maize",
}
FORTIFICANTS = {"iron": "Iron", "folate": "Folate", "folic acid": "Folate", "fa": "Folate"}
QUINTILE_LABELS = {
    "lowest": "Lowest", "poorest": "Lowest", "second": "Second", "2nd": "Second",
    "middle": "Middle", "third": "Middle", "3rd": "Middle", "fourth": "Fourth", "4th": "Fourth",
    "highest": "Highest", "wealthiest": "Highest", "richest": "Highest",
    "total": "Total", "all": "Total", "national": "Total", "all (assumed same)": ALL_SAME,
}


def canonical(mapping, value):
    """Map a raw label to our spelling; returns (canonical or None, raw stripped)."""
    key = fix_typos(value)
    return mapping.get(key), " ".join(str(value).split()) if value is not None else ""


def need_alias(text):
    """Alias for a data need given an alias or full text (typo-tolerant); None if unknown."""
    key = fix_typos(text)
    if key in NEEDS:
        return key
    for alias, (_, full) in NEEDS.items():
        if norm(full) == key:
            return alias
    return None


def stable_id(prefix, *parts):
    digest = hashlib.sha1("|".join(norm(p) for p in parts).encode()).hexdigest()[:8]
    return f"{prefix}:{digest}"


def round2(x):
    """Round half up to 2 d.p., the precision of the existing intervention rows."""
    return math.floor(x * 100 + 0.5) / 100


def consumer_moments(p, mean, sd):
    """Invert the pregnancy sim's zero-inflated normal (intervention.py).

    Workbook mean/SD describe all women: a point mass at 0 (prob 1 - p) mixed with a
    normal over consumers. Returns the consumers' mean and variance; the variance must
    be positive or the sim draws NaNs.
    """
    mean_a = mean / p
    return mean_a, sd**2 / p - mean_a**2 * (1 - p)


def mixture_sd(p, mean, consumer_cv):
    """SD over all women, given the consumers' CV (inverse of consumer_moments)."""
    mean_a = mean / p
    return math.sqrt(p * (consumer_cv * mean_a) ** 2 + mean_a**2 * p * (1 - p))


# --------------------------------------------------------------------------------------
# Source snapshots (sources.csv)
# --------------------------------------------------------------------------------------


def record_source(snapshot, source_file):
    """Record in sources.csv which source workbook a committed snapshot was made from."""
    source_file = pathlib.Path(source_file)
    digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
    modified = None
    try:
        import openpyxl
        modified = openpyxl.load_workbook(source_file, read_only=True).properties.modified
    except Exception:
        pass
    if modified is None:
        modified = datetime.datetime.fromtimestamp(source_file.stat().st_mtime)
    row = {"snapshot": pathlib.Path(snapshot).name, "source_file": source_file.name,
           "source_modified": modified.strftime("%Y-%m-%d %H:%M"), "sha256": digest,
           "extracted_on": datetime.date.today().isoformat()}
    table = pd.read_csv(SOURCES, dtype=str).fillna("") if SOURCES.exists() else pd.DataFrame(columns=list(row))
    table = table[table.snapshot != row["snapshot"]]
    table = pd.concat([table, pd.DataFrame([row])]).sort_values("snapshot")
    table.to_csv(SOURCES, index=False, lineterminator="\n")


# --------------------------------------------------------------------------------------
# Reading the base tables and writing the generated ones
# --------------------------------------------------------------------------------------

# Build step that planned a value -> label in changelog.csv's "step" column
STEP_LABELS = {"lit": "literature default", "gf": "GF default", "decision": "decision",
               "derived": "derived placeholder"}
DEFAULT_SOURCE = {"lit": "literature", "gf": "GF", "decision": "decision", "derived": "derived"}


def read_table(path):
    """A table as text, exactly as written (blank cells are '')."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], encoding="utf-8-sig")


def table_text(df):
    """The CSV text of a table; read_table(table_text(df)) round-trips byte for byte."""
    return df.to_csv(index=False, lineterminator="\n")


def format_number(x):
    """Shortest round-trip text for a number (integers without '.0')."""
    x = float(x)
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


def _parse_value(text):
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return text


class Workbook:
    """Read access to the base extraction tables plus a write plan.

    Rows are addressed as (table, line), where line is the row's line number in the CSV
    (the header is line 1), as an editor shows it. Nothing is written until ``outputs``.
    ``plan`` maps (table, line) to the planned entry, so later phases (decisions, derived
    values) can supersede earlier ones and the change log can show what was overridden.
    """

    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = pathlib.Path(base_dir)
        self.frames = {t: read_table(self.base_dir / f"{t}.csv") for t in TABLES}
        self.plan = {}
        self._headers = {t: {norm(c): c for c in df.columns} for t, df in self.frames.items()}

    def header(self, sheet):
        return self._headers[sheet]

    def get(self, sheet, row, column):
        """A cell: the Value column as a number where it is one, other columns as text.

        Blank cells are None.
        """
        col = self._headers[sheet].get(norm(column))
        if col is None:
            return None
        text = self.frames[sheet].at[row - 2, col]
        if col == "Value":
            return _parse_value(text)
        return None if text == "" else text

    def rows(self, sheet):
        return range(2, len(self.frames[sheet]) + 2)

    def find(self, sheet, **criteria):
        """Rows matching all criteria. Keys use _ for spaces; 'need' takes an alias.

        A criterion whose value is None or '' is a wildcard.
        """
        out = []
        for row in self.rows(sheet):
            if self.get(sheet, row, "value") is None and self.get(sheet, row, "data need") is None:
                continue
            ok = True
            for key, wanted in criteria.items():
                if wanted is None or wanted == "":
                    continue
                if key == "need":
                    ok = need_alias(self.get(sheet, row, "data need")) == wanted
                else:
                    ok = norm(self.get(sheet, row, key.replace("_", " "))) == norm(wanted)
                if not ok:
                    break
            if ok:
                out.append(row)
        return out

    def one(self, sheet, **criteria):
        rows = self.find(sheet, **criteria)
        if len(rows) != 1:
            raise LookupError(f"Expected 1 row in {sheet} for {criteria}, found {rows}")
        return rows[0]

    def describe(self, sheet, row):
        cols = ["country", "vehicle", "fortificant", "scenario", "quintile", "sex", "data need", "data point name"]
        return {c.replace(" ", "_"): self.get(sheet, row, c) for c in cols}

    def current(self, sheet, row):
        """Planned value if any, else the base value."""
        entry = self.plan.get((sheet, row))
        if entry is not None and entry["action"] == "set":
            return entry["value"]
        return self.get(sheet, row, "value")

    def propose(self, sheet, row, value, *, origin, ref, method, derivation=None, decision_id=None,
                source_label=None, source=None):
        """Plan a value. A later proposal replaces an earlier one (recorded as superseded).

        origin is the build step that set it (lit, gf, decision, derived); source is where
        the number came from (literature, GF, typed value, derived from ...). derivation,
        if given, says how the value was computed (the Derivation column, where there is one).
        """
        previous = self.plan.get((sheet, row))
        self.plan[(sheet, row)] = {
            "action": "set", "value": float(value), "derivation": derivation, "origin": origin, "ref": ref,
            "method": method, "decision_id": decision_id, "source_label": source_label,
            "source": source or DEFAULT_SOURCE[origin], "superseded": previous,
        }

    def keep(self, sheet, row, *, origin, ref, method, decision_id=None):
        """Plan to leave a row at its base value (e.g. a decision rejecting a default)."""
        previous = self.plan.get((sheet, row))
        self.plan[(sheet, row)] = {
            "action": "keep", "value": None, "derivation": None, "origin": origin, "ref": ref,
            "method": method, "decision_id": decision_id, "source": "base extraction table",
            "superseded": previous,
        }

    def outputs(self, source_labels):
        """Apply the plan: (change-log records, {table: generated DataFrame})."""
        frames = {t: df.copy() for t, df in self.frames.items()}
        records = []
        for (sheet, row), entry in sorted(self.plan.items()):
            old = self.get(sheet, row, "value")
            superseded = entry["superseded"]
            record = {
                "tab": sheet, "row": row, **self.describe(sheet, row),
                "old_value": old, "new_value": entry["value"],
                "source": entry["source"], "step": STEP_LABELS[entry["origin"]],
                "decision_id": entry["decision_id"],
                "reference": entry["ref"], "method": entry["method"],
                "overrides": None if superseded is None else
                f"{STEP_LABELS[superseded['origin']]} ({superseded['source']}): {superseded['value']} "
                f"({superseded['ref']})",
            }
            if entry["action"] == "keep":
                record["status"] = "kept"
            elif isinstance(old, float) and np.isclose(old, entry["value"], rtol=1e-9, atol=1e-12):
                record["status"] = "unchanged"
            else:
                record["status"] = "changed"
                rel = (entry["value"] - old) / old if isinstance(old, float) and old else None
                record["relative_change"] = rel
                cols = self._headers[sheet]
                df, i = frames[sheet], row - 2
                df.at[i, "Value"] = format_number(entry["value"])
                df.at[i, cols["data source"]] = entry.get("source_label") or source_labels[entry["origin"]]
                df.at[i, cols["notes"]] = (
                    f"{entry['ref']}; {entry['method']}"
                    + (f" [decision {entry['decision_id']}]" if entry["decision_id"] else "")
                    + f" (base: {old!r} from {self.get(sheet, row, 'data source')!r})")
                if "derivation" in cols:
                    df.at[i, cols["derivation"]] = entry["derivation"] or ""
                if rel is None or abs(rel) > 0.01:  # the base CI/SE no longer describe the value
                    for c in ("ci", "se"):
                        if c in cols:
                            df.at[i, cols[c]] = ""
            records.append(record)
        return records, frames
