"""Human-readable outputs: review.csv with everything spelled out, and STATUS.md.

The build works with IDs (decision IDs, literature IDs, sheet rows). These functions
resolve them, so nobody has to look things up across several files.
"""

import math
import re

import pandas as pd

from common import ALL_SAME, NEEDS, VEH, need_alias, norm

# Plain names for our data needs
NEED_LABELS = {
    "any": "WRA consumption: share eating the vehicle",
    "amount": "WRA consumption: g/day",
    "u5_any": "U5 consumption: share eating the vehicle",
    "u5_amount": "U5 consumption: g/day",
    "fortifiability": "fortifiability (consolidation)",
    "baseline_any": "baseline: share fortified",
    "baseline_concentration": "baseline: concentration (mcg/g)",
    "baseline_effectiveness": "baseline: effective share of fortified",
    "intervention_coverage": "intervention: coverage of fortifiable",
    "intervention_effectiveness": "intervention: effective share of fortified",
    "intervention_concentration": "intervention: concentration (mcg/g)",
    "hb_effect": "hemoglobin effect (g/L)",
    "bw_effect": "birthweight effect (g per mg/day)",
}

ISSUE_ORDER = [
    "placeholder remains",
    "GF national inconsistent with GF quintiles",
    "recommended literature value differs from output",
    "literature could replace placeholder",
    "literature disagrees with output",
    "several literature candidates",
    "conflicting literature recommendations",
    "proposed decision (not applied)",
    "proposed decision is invalid",
    "literature row needs attention",
    "literature value has no row in the extraction sheet",
]

WHAT_TO_DO = {
    "GF national inconsistent with GF quintiles": "The existing Total was kept; rescale with method:scale_to_gf_total, or record a 'keep' decision",
    "placeholder remains": "Needs a real value, or a 'keep' decision if the placeholder is deliberate",
    "recommended literature value differs from output": "Adopt it with a lit: decision, or record why not",
    "literature could replace placeholder": "Usually adopt it with a lit: decision",
    "literature disagrees with output": "Decide which is right; a 'gf' or 'keep' decision records that the output is",
    "several literature candidates": "Pick one (decision), or ask Juhi to mark 'Use in model'",
    "conflicting literature recommendations": "Ask Juhi which one she means",
    "proposed decision (not applied)": "Set its status to active or rejected",
    "proposed decision is invalid": "Fix the decision (see detail)",
    "literature row needs attention": "Fix the row in Juhi's sheet",
    "literature value has no row in the extraction sheet": "Nothing to do unless the sheet should gain a row",
}


def blank(x):
    return x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip() == ""


def fmt(v):
    if blank(v):
        return ""
    if isinstance(v, (int, float)):
        return f"{v:.4g}"
    return str(v)


def describe_row(wb, tab, row):
    """(arm, item, stratum) for a row of the extraction sheet."""
    d = wb.describe(tab, row)
    alias = need_alias(d["data_need"])
    arm = " ".join(str(d[k]) for k in ["country", "vehicle", "fortificant"] if not blank(d[k]))
    item = NEED_LABELS.get(alias, d["data_need"])
    if alias in ("amount", "u5_amount") and not blank(d["data_point_name"]):
        item += " " + ("SD" if norm(d["data_point_name"]) == "standard deviation" else "mean")
    parts = [d[k] for k in ["scenario", "quintile", "sex"] if not blank(d[k]) and d[k] != ALL_SAME]
    if alias in ("any", "amount"):
        parts = [p for p in parts if p != "Female"]  # every WRA row is Female
    parts = list(dict.fromkeys(str(p) for p in parts))
    if len(parts) > 1 and "Total" in parts:  # e.g. U5 rows: quintile Total, sex Female -> Female
        parts.remove("Total")
    return arm, item, ", ".join(parts)


def describe_lit(lit, lit_id):
    """'value units (source; Juhi's sheet <tab> row <n>)' for a literature row."""
    if blank(lit_id) or not str(lit_id).startswith("lit:"):
        return ""
    m = lit[lit.lit_id == lit_id]
    if len(m) != 1:
        return f"{lit_id} (not found)"
    r = m.iloc[0]
    value = f"{r.raw_value} {r.raw_units or ''}".strip() if not blank(r.raw_value) else "(no value)"
    pick = {"yes": "; Juhi recommends it", "no": "; Juhi does not recommend it"}.get(r.use_in_model, "")
    return f"{value} from {r.data_source} (Juhi's sheet '{r.source_sheet}' row {r.source_row}{pick})"


def describe_lit_target(lit, lit_id):
    m = lit[lit.lit_id == lit_id]
    if len(m) != 1:
        return "", "", ""
    r = m.iloc[0]
    arm = " ".join(str(x) for x in [r.country, r.vehicle, r.fortificant] if not blank(x))
    item = NEED_LABELS.get(r.need, r.data_need) if not blank(r.need) else str(r.data_need)
    stratum = ", ".join(str(x) for x in [r.scenario, r.quintile, r.population] if not blank(x))
    return arm, item, stratum


def candidates_text(detail, lit):
    """Each candidate in a 'several literature candidates' item, spelled out."""
    ids = re.findall(r"lit:[0-9a-f]{8}(?:-\d+)?", detail)
    return " OR ".join(describe_lit(lit, i) for i in ids) if ids else detail


def source_text(lit, source):
    source = str(source).strip()
    if source.startswith("lit:"):
        return describe_lit(lit, source)
    if source == "gf":
        return "GF"
    if source == "keep":
        return "existing extraction sheet"
    if source.startswith("method:"):
        return f"computed ({source.split(':', 1)[1]})"
    if source.startswith("value:"):
        return "typed value"
    return source


def describe_decision(decisions, decision_id):
    if blank(decision_id):
        return ""
    d = decisions[decisions.decision_id == decision_id]
    if len(d) != 1:
        return str(decision_id)
    d = d.iloc[0]
    return f"{decision_id} ({d.status}): {d.rationale}"


def enrich_review(review, wb, lit, decisions):
    """Add plain-language columns so each review row stands on its own."""
    if review.empty:
        return review
    out = []
    for _, r in review.iterrows():
        tab, row = r.get("tab"), r.get("row")
        if not blank(tab) and not blank(row):
            arm, item, stratum = describe_row(wb, tab, int(row))
        elif not blank(r.get("lit_id")):
            arm, item, stratum = describe_lit_target(lit, r.get("lit_id"))
        else:
            arm, item, stratum = "", "", ""
        if not arm and not blank(r.get("decision_id")):
            d = decisions[decisions.decision_id == r.get("decision_id")]
            if len(d):
                d = d.iloc[0]
                arm = " ".join(str(x) for x in [d.country, d.vehicle, d.fortificant] if not blank(x))
                item = NEED_LABELS.get(need_alias(d.need), d.need)
        if tab == VEH:
            arm = f"(all countries) {arm}"
        out.append({
            "arm": arm, "item": item, "where": stratum, "issue": r["issue"],
            "what_to_do": WHAT_TO_DO.get(r["issue"], ""),
            "output_value": fmt(r.get("output_value")),
            "literature": (candidates_text(r["detail"], lit) if r["issue"] == "several literature candidates"
                           else describe_lit(lit, r.get("lit_id"))),
            "decision": describe_decision(decisions, r.get("decision_id")),
            "detail": r["detail"],
            "lit_id": r.get("lit_id"), "decision_id": r.get("decision_id"),
            "tab": tab, "row": row,
        })
    df = pd.DataFrame(out)
    df["_issue"] = df.issue.map({k: i for i, k in enumerate(ISSUE_ORDER)}).fillna(99)
    return df.sort_values(["arm", "_issue", "item", "where"]).drop(columns="_issue")


def decision_effects(wb, lit, decisions, resolve, gf_values):
    """Per active/proposed decision: the arm it belongs to and a one-line summary of its effect."""
    out = []
    for _, d in decisions.iterrows():
        if norm(d.status) not in ("active", "proposed"):
            continue
        arm_of_decision = " ".join(str(x) for x in [d.country, d.vehicle] if not blank(x))
        try:
            effects = resolve(wb, lit, d, gf_values)
        except ValueError as e:
            out.append({"d": d, "arm": arm_of_decision, "summary": f"invalid: {e}"})
            continue
        # Group the targeted rows by (arm, item) and list their values compactly
        groups = {}
        for e in effects:
            arm, item, stratum = describe_row(wb, e["sheet"], e["row"])
            if e["sheet"] == VEH:
                arm = f"(all countries) {arm}"
            if e["action"] == "set":
                what = fmt(e["value"])
            elif e["action"] == "accept":
                what = f"{fmt(e['value'])} (GF, accepted)"
            else:
                what = "existing value kept"
            groups.setdefault((arm, item), []).append(f"{stratum} {what}".strip() if stratum else what)
        parts = []
        for (arm, item), values in groups.items():
            parts.append(f"{arm}: {item} → " + "; ".join(values))
        arm = next(iter(groups))[0] if groups else arm_of_decision
        out.append({"d": d, "arm": arm, "summary": " | ".join(parts)})
    return out


def write_status(path, wb, lit, arms, decisions, review, resolve, gf_values):
    """STATUS.md: per arm, the decisions in effect and what is still open."""
    effects = decision_effects(wb, lit, decisions, resolve, gf_values)
    arm_names = [f"{a['country']} {a['vehicle']}" for a in arms if a["apply_gf"]]
    out = ["# Status of the extraction build", "",
           "Generated by `build_extraction.py`; do not edit. For each arm: the decisions in effect, "
           "proposed decisions, and what is still open, with IDs resolved. `review.csv` has the open "
           "items as a filterable table. Arms with apply_gf = no in `arms.csv` are not listed.", ""]

    def section(title, match):
        lines = [f"## {title}", ""]
        mine = [x for x in effects if match(x["arm"])]
        active = [x for x in mine if norm(x["d"].status) == "active"]
        proposed = [x for x in mine if norm(x["d"].status) == "proposed"]
        if active:
            lines += ["**Decisions in effect**", ""]
            for x in active:
                d = x["d"]
                lines.append(f"- **{d.decision_id}** {x['summary']}  ")
                lines.append(f"  Source: {source_text(lit, d.source)}"
                             + (f", then {d['transform']}" if not blank(d['transform']) else "") + f". Why: {d.rationale}")
            lines.append("")
        if proposed:
            lines += ["**Proposed, not applied** (set status to active or rejected)", ""]
            for x in proposed:
                d = x["d"]
                verb = "is" if x["summary"].startswith("invalid") else "would set"
                lines.append(f"- **{d.decision_id}** {verb} {x['summary']}  ")
                lines.append(f"  Source: {source_text(lit, d.source)}. Why: {d.rationale}")
            lines.append("")
        items = review[review.arm.fillna("").apply(match) & ~review.issue.str.startswith("proposed decision")] \
            if len(review) else review
        if len(items):
            lines += ["**Still open**", ""]
            for issue, group in items.groupby("issue", sort=False):
                lines.append(f"*{issue}*: {WHAT_TO_DO.get(issue, '')}")
                lines.append("")
                for _, r in group.iterrows():
                    where = f" [{r['where']}]" if r["where"] else ""
                    bits = [f"output {r.output_value}" if r.output_value else "",
                            f"literature: {r.literature}" if r.literature else ""]
                    bits = "; ".join(b for b in bits if b)
                    problem = f" Problem: {r.detail}." if issue == "literature row needs attention" else ""
                    lines.append(f"- {r.arm}: {r['item']}{where}" + (f". {bits}" if bits else "") + problem)
                lines.append("")
        if len(lines) == 2:
            lines += ["Nothing open.", ""]
        return lines

    for name in arm_names:
        out += section(name, lambda arm, name=name: arm.startswith(name))
    out += section("Effect sizes (all countries)", lambda arm: arm.startswith("(all countries)"))
    path.write_text("\n".join(out))
