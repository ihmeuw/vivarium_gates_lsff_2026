"""Shared vocabulary and helpers for the GF + literature integration scripts.

Everything that encodes *our* terminology lives here, so the extract scripts and the
build script agree on it: data-need names (with short aliases), workbook sheet names,
quintile/vehicle/country/fortificant spellings, unit conversions, and the code that
edits, recalculates and verifies the extraction workbook.
"""

import hashlib
import math
import pathlib
import shutil
import subprocess
import tempfile

import numpy as np
import openpyxl

HERE = pathlib.Path(__file__).resolve().parent
EXTRACTION_DIR = HERE.parent

GF_FILE = EXTRACTION_DIR / "Nutrition PST Background Data.xlsx"
LIT_FILE = EXTRACTION_DIR / "LSFF_effect_sizes.xlsx"
EXTRACTION_FILE = EXTRACTION_DIR / "Data Extraction Sheet.xlsx"

GF_LONG = HERE / "gf_long.csv"
LIT_LONG = HERE / "lit_long.csv"
ARMS_FILE = HERE / "arms.csv"
DECISIONS_FILE = HERE / "decisions.csv"

# --------------------------------------------------------------------------------------
# Our workbook's sheets and data needs
# --------------------------------------------------------------------------------------

CV = "Country-Vehicle Extraction"
CVF = "Country-Vehicle-Fort Extraction"
SCEN = "Scenario Definition Extraction"
VEH = "Vehicle Extraction"
SHEET_ALIASES = {"cv": CV, "cvf": CVF, "scen": SCEN, "veh": VEH}

# alias -> (workbook sheet, full data-need text as it appears in our workbook)
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
# Editing the extraction workbook
# --------------------------------------------------------------------------------------

# Build step that planned a value -> label in changelog.csv's "step" column
STEP_LABELS = {"gf": "GF default", "decision": "decision", "derived": "derived placeholder"}
DEFAULT_SOURCE = {"gf": "GF", "decision": "decision", "derived": "derived"}


class Workbook:
    """Read access to the extraction workbook (cached values) plus a write plan.

    Nothing is written until ``save``. ``plan`` maps (sheet, row) to the planned entry,
    so later phases (decisions, derived values) can supersede earlier ones and the
    change log can show what was overridden.
    """

    def __init__(self, path):
        self.path = path
        self.wb = openpyxl.load_workbook(path)
        self.values = openpyxl.load_workbook(path, data_only=True)
        self.plan = {}
        self._headers = {}

    def header(self, sheet):
        if sheet not in self._headers:
            ws = self.values[sheet]
            self._headers[sheet] = {
                norm(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1) if ws.cell(1, c).value
            }
        return self._headers[sheet]

    def get(self, sheet, row, column):
        col = self.header(sheet).get(norm(column))
        return None if col is None else self.values[sheet].cell(row, col).value

    def rows(self, sheet):
        return range(2, self.values[sheet].max_row + 1)

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
        """Planned value if any, else the workbook's existing value."""
        entry = self.plan.get((sheet, row))
        if entry is not None and entry["action"] == "set":
            return entry["value"]
        return self.get(sheet, row, "value")

    def propose(self, sheet, row, value, *, origin, ref, method, formula=None, decision_id=None,
                source_label=None, source=None):
        """Plan a value. A later proposal replaces an earlier one (recorded as superseded).

        origin is the build step that set it (gf, decision, derived); source is where the
        number came from (GF, literature, typed value, derived from ...).
        """
        previous = self.plan.get((sheet, row))
        self.plan[(sheet, row)] = {
            "action": "set", "value": value, "formula": formula, "origin": origin, "ref": ref,
            "method": method, "decision_id": decision_id, "source_label": source_label,
            "source": source or DEFAULT_SOURCE[origin], "superseded": previous,
        }

    def keep(self, sheet, row, *, origin, ref, method, decision_id=None):
        """Plan to leave a row alone (e.g. a decision rejecting a GF default)."""
        previous = self.plan.get((sheet, row))
        self.plan[(sheet, row)] = {
            "action": "keep", "value": None, "formula": None, "origin": origin, "ref": ref,
            "method": method, "decision_id": decision_id, "source": "existing extraction sheet",
            "superseded": previous,
        }

    def changelog(self, source_labels):
        """One record per planned row, plus the expected post-recalc values for verify."""
        records, expected = [], {}
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
            elif isinstance(old, (int, float)) and np.isclose(old, entry["value"], rtol=1e-9, atol=1e-12):
                record["status"] = "unchanged"
            else:
                record["status"] = "changed"
                rel = (entry["value"] - old) / old if isinstance(old, (int, float)) and old else None
                record["relative_change"] = rel
                header = self.header(sheet)
                ws = self.wb[sheet]
                value_cell = ws.cell(row, header["value"])
                value_cell.value = entry["formula"] if entry["formula"] is not None else entry["value"]
                expected[(sheet, value_cell.coordinate)] = entry["value"]
                provenance = {
                    "data source": entry.get("source_label") or source_labels[entry["origin"]],
                    "notes": f"{entry['ref']}; {entry['method']}"
                    + (f" [decision {entry['decision_id']}]" if entry["decision_id"] else "")
                    + f" (was {old!r} from {self.get(sheet, row, 'data source')!r})",
                }
                if rel is None or abs(rel) > 0.01:  # old CI/SE no longer describe the value
                    provenance.update({"ci": None, "se": None})
                for col, new in provenance.items():
                    if col in header:
                        cell = ws.cell(row, header[col])
                        cell.value = new
                        expected[(sheet, cell.coordinate)] = new
            records.append(record)
        return records, expected


def recalculate(path):
    """Recalculate formulas with LibreOffice so pandas can read their results."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
            check=True, capture_output=True,
        )
        shutil.move(str(pathlib.Path(tmp) / path.name), path)
    return True


def verify(original, updated, expected):
    """Every cell matches the original except the ones we meant to change.

    Returns (problems, recomputed); recomputed lists untouched formula cells whose
    result changed because an input did.
    """
    old = openpyxl.load_workbook(original, data_only=True)
    old_formulas = openpyxl.load_workbook(original)
    new = openpyxl.load_workbook(updated, data_only=True)
    problems, recomputed = [], []
    for ws_old in old:
        ws_new, ws_formula = new[ws_old.title], old_formulas[ws_old.title]
        for row in range(1, max(ws_old.max_row, ws_new.max_row) + 1):
            for col in range(1, max(ws_old.max_column, ws_new.max_column) + 1):
                coord = ws_old.cell(row, col).coordinate
                want = expected.get((ws_old.title, coord), ws_old.cell(row, col).value)
                got = ws_new.cell(row, col).value
                if isinstance(want, (int, float)) and isinstance(got, (int, float)):
                    ok = np.isclose(want, got, rtol=1e-9, atol=1e-12)
                else:
                    ok = (want in (None, "") and got in (None, "")) or want == got
                if ok:
                    continue
                original_cell = ws_formula.cell(row, col).value
                if (isinstance(original_cell, str) and original_cell.startswith("=")
                        and (ws_old.title, coord) not in expected and got is not None):
                    recomputed.append((ws_old.title, coord, original_cell, want, got))
                else:
                    problems.append((ws_old.title, coord, want, got))
    return problems, recomputed
