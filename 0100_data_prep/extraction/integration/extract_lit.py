"""Step 1b: hand extractions (LSFF_effect_sizes.xlsx) -> lit_long.csv, in our terms.

Built to survive the source workbook being edited and reformatted:

* Sheets are recognised by their headers, not their names or positions: any sheet with a
  'Value' column and a 'Data need' column is read. Sheets named in IGNORE_SHEETS, or whose
  name starts with 'OLD', are skipped.
* Columns are found by header name (case/space-insensitive, with a few synonyms), so
  columns can be added, removed or reordered.
* Labels are normalised to our vocabulary (common.py): countries, vehicles, fortificants,
  quintiles, data needs (with typo fixes), data point names.
* Units are converted to the workbook's: % values stored as 0-100 become fractions,
  ppm becomes mcg/g, g/dL becomes g/L.
* Every row gets a ``lit_id``. If the sheet has an 'ID' column, that is used (prefixed
  'lit:'); otherwise a hash of the row's normalised key and data source, which changes when
  those fields are edited. decisions.csv refers to rows by this ID.
* The workbook lives on SharePoint, not in the repo. Pass its path with --lit; the
  file's date and SHA-256 are recorded in sources.csv next to the snapshot.

* An optional 'Use in model' column holds the extractor's recommendation when there are several
  candidate values for the same thing: yes / no / blank (also y, n, true, false, 1, 0, x).
  When candidates disagree, build_extraction uses it to pick the literature default ('no'
  candidates are ignored; if any are 'yes', only those count), and shows it in review.csv
  and comparison.csv.

Rows that can't be mapped onto one of our data needs are kept, with status
'needs_attention' and the reason, so nothing disappears silently.
"""

import argparse
import math
import pathlib

import openpyxl
import pandas as pd

from common import (
    CVF, SCEN, COUNTRIES, FORTIFICANTS, LIT_FILE, LIT_LONG, NEEDS, QUINTILE_LABELS, VEHICLES,
    canonical, fix_typos, need_alias, norm, record_source, stable_id,
)

IGNORE_SHEETS = {"sheet1"}  # Sheet1 is a copy of our own Vehicle Extraction tab

# our column -> header names accepted in the source (normalised)
COLUMN_SYNONYMS = {
    "id": ["id", "lit id", "row id"],
    "country": ["country"],
    "vehicle": ["vehicle"],
    "fortificant": ["fortificant", "nutrient"],
    "scenario": ["scenario"],
    "quintile": ["quintile", "wealth quintile"],
    "population": ["population"],
    "data_need": ["data need"],
    "data_point_name": ["data point name", "measure"],
    "units": ["units", "unit"],
    "value": ["value"],
    "ci": ["ci", "95% ci", "uncertainty"],
    "se": ["se"],
    "year": ["year"],
    "data_source": ["data source", "data source author"],
    "data_source_title": ["data source title"],
    "url": ["url"],
    "gf_input": ["gf input?", "current gf input?"],
    "use_in_model": ["use in model", "use in model?", "use_in_model", "use in the model"],
    "limitations": ["limitations"],
    "notes": ["notes"],
    "term": ["term"],
}

POINT_NAMES = {
    "percentage": "percentage", "mean": "mean", "standard deviation": "standard deviation",
    "sd": "standard deviation", "concentration": "concentration", "mean difference": "Mean difference",
}

USE_IN_MODEL = {
    "yes": "yes", "y": "yes", "true": "yes", "1": "yes", "x": "yes",
    "no": "no", "n": "no", "false": "no", "0": "no",
}

# population label -> (age group, sex)
POPULATIONS = {
    "non-pregnant wra": ("wra", "Female"),
    "wra": ("wra", "Female"),
    "pregnant women": ("pregnant", "Female"),
    "all": ("all", None),
    "children u5": ("u5", "Total"),
    "children u5 - male": ("u5", "Male"),
    "children u5 - female": ("u5", "Female"),
}


def find_columns(ws):
    headers = {norm(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1) if ws.cell(1, c).value}
    return {ours: headers[s] for ours, syns in COLUMN_SYNONYMS.items() for s in syns if s in headers}


def convert_units(value, units):
    """Return (value, units, issue) in the workbook's units.

    Converted values are rounded to 12 significant digits, so that e.g. 33.3% becomes 0.333
    rather than 0.33299999999999996 (floating-point noise that would otherwise end up in the
    generated tables).
    """
    u = norm(units)
    if u == "%":
        issue = "percentage below 1 on a 0-100 scale; check it isn't already a fraction" if 0 < value < 1 else ""
        return float(f"{value / 100:.12g}"), "%", issue
    if u == "ppm":
        return value, "mcg/g", ""
    if u == "g/dl":
        return float(f"{value * 10:.12g}"), "g/L", "converted from g/dL; check the source really is g/dL"
    return value, units, ""


def read_sheet(ws):
    cols = find_columns(ws)
    if "value" not in cols or "data_need" not in cols:
        return []
    out = []
    for r in range(2, ws.max_row + 1):
        raw = {k: ws.cell(r, c).value for k, c in cols.items()}
        if all(v is None for v in raw.values()):
            continue
        out.append((r, raw))
    return out


def normalise(sheet_name, r, raw):
    issues = []
    rec = {"source_sheet": sheet_name, "source_row": r}

    for field, mapping in [("country", COUNTRIES), ("vehicle", VEHICLES), ("fortificant", FORTIFICANTS)]:
        value, text = canonical(mapping, raw.get(field))
        rec[field] = value or (text or None)
        if raw.get(field) is not None and value is None and field == "country":
            issues.append(f"unknown country '{text}'")

    quintile, qtext = canonical(QUINTILE_LABELS, raw.get("quintile"))
    rec["quintile"] = quintile or (qtext or None)

    population = norm(raw.get("population"))
    age_group, sex = POPULATIONS.get(population, (None, None))
    if population and population not in POPULATIONS:
        issues.append(f"unknown population '{raw.get('population')}' (known: {', '.join(POPULATIONS)})")
    rec["population"] = raw.get("population")

    alias = need_alias(raw.get("data_need"))
    rec["need"] = alias
    rec["data_need"] = NEEDS[alias][1] if alias else raw.get("data_need")
    rec["table"] = NEEDS[alias][0] if alias else None
    no_target = []  # fine as data, but nothing in our workbook to put it in
    if alias is None:
        no_target.append("data need is not one of ours")
    elif rec["table"] in (CVF, SCEN) and rec["fortificant"] not in FORTIFICANTS.values():
        issues.append(f"unknown fortificant '{rec['fortificant']}'")

    # A WRA-labelled need measured in children (or vice versa) is a labelling mistake
    if alias in ("any", "amount") and age_group == "u5":
        issues.append("population is children U5 but the data need is for WRA")
    if alias in ("u5_any", "u5_amount") and age_group in ("wra", "pregnant"):
        issues.append("population is women but the data need is for U5")
    if age_group == "pregnant":
        no_target.append("pregnant women: the workbook has no pregnant-specific rows")
    if alias in ("any", "amount"):
        rec["sex"] = "Female"  # WRA rows in our workbook are all Sex = Female
    elif alias in ("u5_any", "u5_amount"):
        rec["sex"] = sex or "Total"
    else:
        rec["sex"] = None

    scenario = raw.get("scenario")
    rec["scenario"] = scenario
    if alias and alias.startswith("intervention") and norm(scenario) not in ("", "intervention") and \
            not norm(scenario).startswith("intervention"):
        issues.append(f"scenario '{scenario}' is not an intervention scenario")

    point = POINT_NAMES.get(norm(raw.get("data_point_name")))
    rec["data_point_name"] = point or raw.get("data_point_name")

    value = raw.get("value")
    rec["raw_value"], rec["raw_units"] = value, raw.get("units")
    if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
        rec["value"], rec["units"], unit_issue = convert_units(float(value), raw.get("units"))
        if unit_issue:
            issues.append(unit_issue)
    else:
        rec["value"], rec["units"] = None, raw.get("units")
        if value is not None:
            issues.append(f"non-numeric value '{value}'")

    for field in ["ci", "se", "year", "data_source", "data_source_title", "url", "gf_input",
                  "limitations", "notes", "term"]:
        rec[field] = raw.get(field)

    use = raw.get("use_in_model")
    rec["use_in_model"] = USE_IN_MODEL.get(norm(use)) if norm(use) else None
    if norm(use) and rec["use_in_model"] is None:
        issues.append(f"'Use in model' should be yes, no or blank, not '{use}'")

    explicit = " ".join(str(raw.get("id") or "").split())
    rec["_explicit_id"] = bool(explicit)
    rec["lit_id"] = (explicit if explicit.startswith("lit:") else f"lit:{explicit}") if explicit else stable_id(
        "lit", rec["country"], rec["vehicle"], rec["fortificant"], rec["scenario"], rec["quintile"],
        rec["population"], rec["need"] or rec["data_need"], rec["data_point_name"], rec["data_source"],
        rec["term"],
    )
    if rec["value"] is None:
        rec["status"] = "no_value"
    elif issues:
        rec["status"] = "needs_attention"
    elif no_target:
        rec["status"] = "no_target"
    else:
        rec["status"] = "ok"
    rec["issues"] = "; ".join(issues + no_target)
    return rec


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lit", type=pathlib.Path, default=LIT_FILE)
    parser.add_argument("--output", type=pathlib.Path, default=LIT_LONG)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.lit, data_only=True)
    records = []
    for ws in wb:
        if norm(ws.title) in IGNORE_SHEETS or norm(ws.title).startswith("old"):
            print(f"skipping sheet '{ws.title}'")
            continue
        rows = read_sheet(ws)
        if not rows:
            print(f"skipping sheet '{ws.title}' (no 'Value' and 'Data need' columns)")
            continue
        records += [normalise(ws.title, r, raw) for r, raw in rows]

    df = pd.DataFrame(records)
    explicit = df[df.pop("_explicit_id")]
    if explicit.lit_id.duplicated().any():
        dups = explicit[explicit.lit_id.duplicated(keep=False)]
        raise SystemExit("Duplicate IDs in the literature workbook: " + "; ".join(
            f"{r.lit_id} ({r.source_sheet} row {r.source_row})" for r in dups.itertuples()))
    # Identical keys (e.g. two 'Assumption' rows) would share an ID; make them unique
    dup = df.groupby("lit_id").cumcount()
    df.loc[dup > 0, "lit_id"] = df.loc[dup > 0, "lit_id"] + "-" + dup[dup > 0].astype(str)

    first = ["lit_id", "status", "issues", "table", "need", "country", "vehicle", "fortificant",
             "scenario", "quintile", "sex", "population", "data_point_name", "value", "units", "use_in_model"]
    df = df[first + [c for c in df.columns if c not in first]]
    df.to_csv(args.output, index=False, lineterminator="\n")
    if args.output.resolve() == LIT_LONG.resolve():
        record_source(args.output, args.lit)
    print(f"Wrote {args.output.name}: {len(df)} rows; " + ", ".join(f"{k}: {v}" for k, v in df.status.value_counts().items()))
    attention = df[df.status == "needs_attention"]
    for _, row in attention.iterrows():
        print(f"  needs attention: {row.source_sheet} row {row.source_row}: {row.issues}")


if __name__ == "__main__":
    main()
