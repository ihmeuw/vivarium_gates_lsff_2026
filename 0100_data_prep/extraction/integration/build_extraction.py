"""Step 2: build the extraction workbook from GF data, literature data and decisions.

Inputs (all in this directory unless noted):
    gf_long.csv      from extract_gf.py
    lit_long.csv     from extract_lit.py
    arms.csv         which arms take GF values, and how to read GF's g/cap for each
    decisions.csv    hand-made choices that override GF defaults (see README.md)
    ../Data Extraction Sheet.xlsx   the base workbook (never modified)

Phases, each of which can override the one before:
    1. GF defaults   for arms with apply_gf = yes (the mapping in GF_DATA_MAPPING.md)
    2. decisions     rows of decisions.csv with status = active
    3. derived       placeholder SDs / U5 amounts for arms with derive_sd_u5_from,
                     only where neither GF nor a decision supplied a value
    4. checks        the constraints the pipeline relies on (fails the build)

Outputs:
    ../Data Extraction Sheet (integrated).xlsx   recalculated with LibreOffice and verified
    changelog.csv    every planned row: old -> new, origin, reference, what it overrode
    review.csv       things a person should look at: GF/literature conflicts, literature
                     values not used, proposed decisions and their effect, placeholders left

Usage:
    python extract_gf.py && python extract_lit.py && python build_extraction.py
"""

import argparse
import math
import pathlib
import sys

import numpy as np
import openpyxl
import pandas as pd

from common import (
    ALL_SAME, ARMS_FILE, CV, CVF, DECISIONS_FILE, EXTRACTION_DIR, EXTRACTION_FILE, GF_LONG, HERE,
    LIT_LONG, NEEDS, QUINTILES, SCEN, VEH, Workbook, consumer_moments, mixture_sd, need_alias, norm,
    recalculate, round2, verify,
)

DEFAULT_OUTPUT = EXTRACTION_DIR / "Data Extraction Sheet (integrated).xlsx"
CHANGELOG = HERE / "changelog.csv"
REVIEW = HERE / "review.csv"
COMPARISON = HERE / "comparison.csv"
COMPARISON_XLSX = HERE / "comparison.xlsx"

TARGET_YEAR = "2035"
TOTALS_RTOL = 0.1  # check_totals_reasonable in prep_extracted.ipynb
AGREE_RTOL = 0.01  # literature and workbook values closer than this "agree"

SOURCE_LABELS = {
    "gf": "GF Nutrition PST Background Data (updated 30 Sep 2026)",
    "derived": "DERIVED (MIC-7549)",
    "decision": "decision",  # replaced per decision with a specific label
}


def blank(x):
    return x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip() == ""


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


class GF:
    """Lookups into gf_long.csv."""

    def __init__(self, path):
        self.df = pd.read_csv(path, dtype={"year": str})

    def _rows(self, **criteria):
        d = self.df
        for k, v in criteria.items():
            d = d[d[k].astype(str).str.lower() == str(v).lower()]
        return d

    @staticmethod
    def _out(row):
        value = None if pd.isna(row.value) else float(row.value)
        return value, f"GF '{row.source_sheet}'!{row.source_cell}", row.raw

    def national(self, country, vehicle, metric):
        d = self._rows(source_sheet="Burden x Vehicle Matrix", country=country, vehicle=vehicle, metric=metric)
        if len(d) != 1:
            return None, f"GF: no national {metric} for {country} {vehicle}", None
        return self._out(d.iloc[0])

    def by_quintile(self, country, vehicle, metric):
        d = self._rows(country=country, vehicle=vehicle, metric=metric, stratum_type="wealth_quintile")
        out = {q: (None, f"GF: no {metric} for {q}") for q in QUINTILES}
        for _, row in d.iterrows():
            value, ref, _ = self._out(row)
            out[row.stratum] = (value, ref)
        return out

    def target(self, country, vehicle, metric, year=TARGET_YEAR):
        d = self._rows(source_sheet="Coverage Over Time", country=country, vehicle=vehicle, metric=metric,
                       year=year)
        if len(d) != 1:
            return None, f"GF: no {year} {metric} for {country} {vehicle}", None
        return self._out(d.iloc[0])


def read_arms(path):
    arms = pd.read_csv(path, dtype=str).fillna("")
    out = []
    for _, a in arms.iterrows():
        out.append({
            "country": a.country, "vehicle": a.vehicle,
            "fortificants": [f.strip() for f in a.fortificants.split(";") if f.strip()],
            "apply_gf": norm(a.apply_gf) == "yes",
            "gcap_basis": norm(a.gcap_basis) or None,
            "derive_from": a.derive_sd_u5_from or None,
        })
    return out


# --------------------------------------------------------------------------------------
# Phase 1: GF defaults (the mapping documented in GF_DATA_MAPPING.md)
# --------------------------------------------------------------------------------------


def gf_consumption_any(gf, wb, arm):
    c, v = arm["country"], arm["vehicle"]
    national, nat_ref, _ = gf.national(c, v, "coverage")
    by_q = gf.by_quintile(c, v, "coverage")
    method = "GF Coverage (% using the vehicle)"
    if all(val is not None for val, _ in by_q.values()):
        for q, (value, ref) in by_q.items():
            wb.propose(CV, wb.one(CV, country=c, vehicle=v, need="any", quintile=q), value,
                       origin="gf", ref=ref, method=method)
        wb.propose(CV, wb.one(CV, country=c, vehicle=v, need="any", quintile="Total"), national,
                   origin="gf", ref=nat_ref, method=method + "; Total only sanity-checks the quintiles")
        u5_rows = wb.find(CV, country=c, vehicle=v, need="u5_any")
        if v == "Wheat" and u5_rows:  # unused by the pipeline; keep wheat's mirror of WRA tidy
            for row in u5_rows:
                q = wb.get(CV, row, "quintile")
                value, ref = by_q[q] if q in by_q else (national, nat_ref)
                wb.propose(CV, row, value, origin="gf", ref=ref, method=method + "; U5 row mirrors WRA")
    elif national is not None:
        wb.propose(CV, wb.one(CV, country=c, vehicle=v, need="any", quintile=ALL_SAME), national,
                   origin="gf", ref=nat_ref, method=method + "; national, no quintile breakdown in GF")


def gf_consumption_amount(gf, wb, arm):
    c, v, basis = arm["country"], arm["vehicle"], arm["gcap_basis"]
    letter = openpyxl.utils.get_column_letter(wb.header(CV)["value"])
    national, nat_ref, _ = gf.national(c, v, "g_per_capita")
    by_q = gf.by_quintile(c, v, "g_per_capita")
    means = {}
    for q, (gcap, ref) in by_q.items():
        if gcap is None:
            return
        row = wb.one(CV, country=c, vehicle=v, need="amount", data_point_name="mean", quintile=q)
        if basis == "among_consumers":
            any_row = wb.one(CV, country=c, vehicle=v, need="any", quintile=q)
            value = gcap * wb.current(CV, any_row)
            wb.propose(CV, row, value, origin="gf", ref=ref, formula=f"={gcap}*{letter}{any_row}",
                       method="GF g/cap is among consumers, multiplied by WRA coverage")
        else:
            value = gcap
            wb.propose(CV, row, value, origin="gf", ref=ref, method="GF g/cap used as the mean over all WRA")
        means[q] = value
    row = wb.one(CV, country=c, vehicle=v, need="amount", data_point_name="mean", quintile="Total")
    formula = None
    if basis == "among_consumers":
        any_row = wb.one(CV, country=c, vehicle=v, need="any", quintile="Total")
        total, formula = national * wb.current(CV, any_row), f"={national}*{letter}{any_row}"
    else:
        total = national
    if np.isclose(np.mean(list(means.values())), total, rtol=TOTALS_RTOL, atol=0):
        wb.propose(CV, row, total, origin="gf", ref=nat_ref, formula=formula,
                   method="GF national g/cap (converted as for the quintiles); only sanity-checks them")
    else:
        wb.keep(CV, row, origin="gf", ref=nat_ref,
                method=f"GF national converts to {total:.3g} but the quintile mean is "
                       f"{np.mean(list(means.values())):.3g} (GF national is from M4N, strata from NFCMS); "
                       "kept the existing Total so the pipeline's totals check passes")


def gf_fortifiability(gf, wb, arm):
    c, v = arm["country"], arm["vehicle"]
    value, ref, raw = gf.target(c, v, "consolidation")
    rows = wb.find(CV, country=c, vehicle=v, need="fortifiability")
    if arm["gcap_basis"] == "hces":
        for row in rows:
            wb.keep(CV, row, origin="gf", ref=ref,
                    method=f"GF {TARGET_YEAR} consolidation {raw} is market-wide; ours applies only to purchased "
                           "non-PDS rice. Needs a decision")
        return
    if value is None:
        return
    for row in rows:
        wb.propose(CV, row, value, origin="gf", ref=ref,
                   method=f"GF {TARGET_YEAR} consolidation; national, applied to every quintile")


def gf_baseline(gf, wb, arm, fortificant):
    c, v = arm["country"], arm["vehicle"]
    any_rows = wb.find(CVF, country=c, vehicle=v, fortificant=fortificant, need="baseline_any")
    eff_rows = wb.find(CVF, country=c, vehicle=v, fortificant=fortificant, need="baseline_effectiveness")
    cons, cons_ref, _ = gf.national(c, v, "consolidation")
    compl, compl_ref, _ = gf.national(c, v, "compliance")
    if arm["gcap_basis"] == "hces":
        for row in eff_rows:
            wb.keep(CVF, row, origin="gf", ref=compl_ref,
                    method="India baseline coverage comes from HCES; GF's market-wide numbers don't map onto it")
        return
    if cons is None or compl is None or len(any_rows) != 1:
        return  # GF n/a (or quintile-specific rows we don't overwrite with a national number)
    split = round2(math.sqrt(compl))
    coverage = cons * split
    wb.propose(CVF, any_rows[0], coverage, origin="gf", ref=f"{cons_ref} x {compl_ref}",
               method=f"consolidation x sqrt(compliance) = {cons} x {split}")
    if coverage > 0 and len(eff_rows) == 1:
        wb.propose(CVF, eff_rows[0], split, origin="gf", ref=compl_ref,
                   method=f"sqrt(current compliance {compl}), 2 d.p.")


def gf_intervention(gf, wb, arm, fortificant):
    c, v = arm["country"], arm["vehicle"]
    compl, ref, raw = gf.target(c, v, "compliance")
    if compl is None:
        return
    split = round2(math.sqrt(compl))
    for need in ["intervention_coverage", "intervention_effectiveness"]:
        for row in wb.find(SCEN, country=c, vehicle=v, fortificant=fortificant, need=need):
            wb.propose(SCEN, row, split, origin="gf", ref=ref,
                       method=f"sqrt({TARGET_YEAR} compliance {compl}), 2 d.p. (equal split, KB 9/9)")


def apply_gf_defaults(gf, wb, arms):
    for arm in arms:
        if not arm["apply_gf"]:
            continue
        if arm["gcap_basis"] != "hces":
            gf_consumption_any(gf, wb, arm)
            gf_consumption_amount(gf, wb, arm)
        gf_fortifiability(gf, wb, arm)
        for fortificant in arm["fortificants"]:
            gf_baseline(gf, wb, arm, fortificant)
            gf_intervention(gf, wb, arm, fortificant)


# --------------------------------------------------------------------------------------
# Phase 2: decisions
# --------------------------------------------------------------------------------------

DECISION_KEYS = ["country", "vehicle", "fortificant", "scenario", "quintile", "sex", "data_point_name"]


def decision_rows(wb, d):
    alias = need_alias(d["need"])
    if alias is None:
        raise ValueError(f"decision {d['decision_id']}: unknown need '{d['need']}'")
    sheet = NEEDS[alias][0]
    criteria = {k: d.get(k) for k in DECISION_KEYS if not blank(d.get(k))}
    if sheet == VEH:
        criteria = {k: v for k, v in criteria.items() if k in ("vehicle", "data_point_name")}
    return sheet, wb.find(sheet, need=alias, **criteria)


def resolve_decision(wb, lit, d):
    """What a decision would do: list of (sheet, row, action, value, ref, method, label)."""
    sheet, rows = decision_rows(wb, d)
    if not rows:
        raise ValueError(f"decision {d['decision_id']} matches no rows in the extraction sheet")
    source, transform = str(d["source"]).strip(), norm(d.get("transform"))
    out = []
    for row in rows:
        if source == "keep":
            out.append((sheet, row, "keep", None, "decision: keep existing value", d["rationale"], None))
            continue
        if source == "gf":
            out.append((sheet, row, "accept", None, "decision: accept GF default", d["rationale"], None))
            continue
        if source.startswith("lit:"):
            match = lit[lit.lit_id == source]
            if len(match) != 1:
                raise ValueError(f"decision {d['decision_id']}: literature row {source} not found "
                                 "(did the source row change? see lit_long.csv)")
            m = match.iloc[0]
            if pd.isna(m.value):
                raise ValueError(f"decision {d['decision_id']}: {source} has no value")
            value = float(m.value)
            ref = f"{source} ({m.source_sheet} row {m.source_row}: {m.data_source})"
            label = f"Literature extraction: {m.data_source}"
            kind = "literature"
        elif source.startswith("value:"):
            value = float(source.split(":", 1)[1])
            ref, label = f"value typed in decision {d['decision_id']}", f"Decision {d['decision_id']}"
            kind = "typed value"
        else:
            raise ValueError(f"decision {d['decision_id']}: unknown source '{source}'")
        method = d["rationale"]
        if transform == "sqrt":
            value = round2(math.sqrt(value))
            method = f"sqrt, 2 d.p.; {method}"
        elif transform == "times_coverage":
            q = wb.get(sheet, row, "quintile")
            any_row = wb.one(CV, country=wb.get(sheet, row, "country"), vehicle=wb.get(sheet, row, "vehicle"),
                             need="any", quintile=q)
            value = value * wb.current(CV, any_row)
            method = f"x WRA coverage; {method}"
        elif transform:
            raise ValueError(f"decision {d['decision_id']}: unknown transform '{transform}'")
        out.append((sheet, row, "set", value, ref, method, (label, kind)))
    return out


def apply_decisions(wb, lit, decisions):
    decided = {}  # (sheet, row) -> decision_id, for silencing conflicts
    active = decisions[decisions.status.str.lower() == "active"]
    # times_coverage decisions depend on coverage, which other decisions may set first
    ordered = pd.concat([active[active["transform"].str.lower() != "times_coverage"],
                         active[active["transform"].str.lower() == "times_coverage"]])
    for _, d in ordered.iterrows():
        for sheet, row, action, value, ref, method, label in resolve_decision(wb, lit, d):
            decided[(sheet, row)] = d.decision_id
            if action == "set":
                wb.propose(sheet, row, value, origin="decision", ref=ref, method=method,
                           decision_id=d.decision_id, source_label=label[0], source=label[1])
            elif action == "keep":
                wb.keep(sheet, row, origin="decision", ref=ref, method=method, decision_id=d.decision_id)
    return decided


# --------------------------------------------------------------------------------------
# Phase 3: derived placeholders
# --------------------------------------------------------------------------------------


def derive_sd_and_u5(wb, arm, decided):
    """Placeholder SDs and U5 amounts from another vehicle (see GF_DATA_MAPPING.md)."""
    c, v, base = arm["country"], arm["vehicle"], arm["derive_from"]

    def value(vehicle, need, point, **kw):
        return wb.current(CV, wb.one(CV, country=c, vehicle=vehicle, need=need, data_point_name=point, **kw))

    def coverage(vehicle, q):
        return wb.current(CV, wb.one(CV, country=c, vehicle=vehicle, need="any", quintile=q))

    for q in QUINTILES + ["Total"]:
        row = wb.one(CV, country=c, vehicle=v, need="amount", data_point_name="standard deviation", quintile=q)
        if (CV, row) in decided:
            continue
        mean_a, var_a = consumer_moments(coverage(base, q), value(base, "amount", "mean", quintile=q),
                                         value(base, "amount", "standard deviation", quintile=q))
        cv = math.sqrt(var_a) / mean_a
        p = coverage(v, q)
        wb.propose(CV, row, mixture_sd(p, value(v, "amount", "mean", quintile=q), cv), origin="derived",
                   source=f"derived from {base}", ref=f"(no SD source) {base} consumer CV", method=f"DERIVED: {base} consumer CV {cv:.3f}, "
                   f"converted to an SD over all women with coverage {p}")

    ratio = (np.mean([value(v, "amount", "mean", quintile=q) for q in QUINTILES])
             / np.mean([value(base, "amount", "mean", quintile=q) for q in QUINTILES]))
    p_base, p = coverage(base, "Total"), coverage(v, "Total")
    for sex in ["Total", "Female", "Male"]:
        mean_row = wb.one(CV, country=c, vehicle=v, need="u5_amount", data_point_name="mean", sex=sex)
        if (CV, mean_row) not in decided:
            wb.propose(CV, mean_row, value(base, "u5_amount", "mean", sex=sex) * ratio, origin="derived",
                       source=f"derived from {base}", ref=f"(no U5 source) {base} U5 x {ratio:.4f}",
                       method=f"DERIVED: {base} U5 mean x {ratio:.4f} (ratio of mean WRA quintile means)")
        sd_row = wb.one(CV, country=c, vehicle=v, need="u5_amount", data_point_name="standard deviation", sex=sex)
        if (CV, sd_row) not in decided:
            mean_a, var_a = consumer_moments(p_base, value(base, "u5_amount", "mean", sex=sex),
                                             value(base, "u5_amount", "standard deviation", sex=sex))
            cv = math.sqrt(var_a) / mean_a
            wb.propose(CV, sd_row, mixture_sd(p, wb.current(CV, mean_row), cv), origin="derived",
                       source=f"derived from {base}", ref=f"(no U5 SD source) {base} U5 consumer CV",
                       method=f"DERIVED: {base} U5 consumer CV {cv:.3f} at national coverage {p}")


# --------------------------------------------------------------------------------------
# Phase 4: checks
# --------------------------------------------------------------------------------------


def run_checks(wb, arms):
    problems = []
    for (sheet, row), entry in wb.plan.items():
        if entry["action"] == "set" and norm(wb.get(sheet, row, "units")) == "%" and not 0 <= entry["value"] <= 1:
            problems.append(f"{sheet} row {row}: percentage {entry['value']} outside [0, 1]")

    for arm in arms:
        c, v = arm["country"], arm["vehicle"]
        if arm["gcap_basis"] == "hces" or not wb.find(CV, country=c, vehicle=v, need="amount"):
            continue
        # Pregnancy sim: consumers' variance must be positive (intervention.py)
        for row in wb.find(CV, country=c, vehicle=v, need="amount", data_point_name="mean"):
            q = wb.get(CV, row, "quintile")
            sd_rows = (wb.find(CV, country=c, vehicle=v, need="amount", data_point_name="standard deviation",
                               quintile=q)
                       or wb.find(CV, country=c, vehicle=v, need="amount", data_point_name="standard deviation",
                                  quintile=ALL_SAME))
            any_rows = (wb.find(CV, country=c, vehicle=v, need="any", quintile=q)
                        or wb.find(CV, country=c, vehicle=v, need="any", quintile=ALL_SAME))
            if not sd_rows or not any_rows:
                continue
            _, var_a = consumer_moments(wb.current(CV, any_rows[0]), wb.current(CV, row), wb.current(CV, sd_rows[0]))
            if var_a <= 0:
                problems.append(f"{c} {v} {q}: consumers' variance {var_a:.3g} <= 0 (SD too small for the mean "
                                "and coverage; the pregnancy sim would draw NaN)")
        # prep_extracted: Total within 10% of the unweighted mean of the quintiles
        q_rows = [wb.find(CV, country=c, vehicle=v, need="amount", data_point_name="mean", quintile=q) for q in QUINTILES]
        t_rows = wb.find(CV, country=c, vehicle=v, need="amount", data_point_name="mean", quintile="Total")
        if all(q_rows) and t_rows:
            q_mean = np.mean([wb.current(CV, r[0]) for r in q_rows])
            total = wb.current(CV, t_rows[0])
            if not np.isclose(q_mean, total, rtol=TOTALS_RTOL, atol=0):
                problems.append(f"{c} {v}: amount Total {total:.3g} vs quintile mean {q_mean:.3g} fails the "
                                "prep_extracted totals check")
        # Coverage notebook: intervention target >= baseline coverage
        fort = {wb.get(CV, r, "quintile"): wb.current(CV, r) for r in wb.find(CV, country=c, vehicle=v, need="fortifiability")}
        for f in arm["fortificants"]:
            for row in wb.find(CVF, country=c, vehicle=v, fortificant=f, need="baseline_any"):
                q = wb.get(CVF, row, "quintile")
                fv = fort.get(q, fort.get(ALL_SAME, fort.get("Total")))
                for irow in wb.find(SCEN, country=c, vehicle=v, fortificant=f, need="intervention_coverage"):
                    target = wb.current(SCEN, irow) * fv
                    baseline = wb.current(CVF, row)
                    if target < baseline and not np.isclose(target, baseline):
                        problems.append(f"{c} {v} {f} {q}: intervention target {target:.3g} < baseline {baseline:.3g}")
    return problems


# --------------------------------------------------------------------------------------
# Review report
# --------------------------------------------------------------------------------------


def lit_workbook_rows(wb, r):
    """Workbook rows a literature row speaks to (for comparison only)."""
    if r.need not in NEEDS:
        return []
    sheet = NEEDS[r.need][0]
    criteria = {"need": r.need, "vehicle": r.vehicle, "data_point_name": r.data_point_name}
    if sheet == VEH:
        return wb.find(sheet, **criteria)
    criteria["country"] = r.country
    if sheet in (CVF, SCEN):
        criteria["fortificant"] = r.fortificant
    if sheet == SCEN and norm(r.scenario).startswith("intervention"):
        criteria["scenario"] = r.scenario
    if sheet == CV and not blank(r.sex):
        rows = wb.find(sheet, sex=r.sex, **criteria) or (
            wb.find(sheet, sex=ALL_SAME, **criteria) if r.sex == "Total" else [])
    else:
        rows = wb.find(sheet, **criteria)
    if sheet == SCEN:
        return rows
    q = r.quintile if not blank(r.quintile) else "Total"
    exact = [x for x in rows if norm(wb.get(sheet, x, "quintile")) == norm(q)]
    if exact or q != "Total":
        return exact
    return [x for x in rows if norm(wb.get(sheet, x, "quintile")) == norm(ALL_SAME)]


def recommended_first(lits):
    """Juhi's 'Use in model' = yes candidates first, then unmarked, then 'no'."""
    order = {"yes": 0, "no": 2}
    return sorted(lits, key=lambda x: order.get(x.use_in_model, 1))


def recommendation_tag(x):
    return {"yes": " [recommended]", "no": " [not recommended]"}.get(x.use_in_model, "")


def build_review(wb, lit, arms, decisions, decided):
    issues = []
    basis = {(a["country"], a["vehicle"]): a["gcap_basis"] for a in arms}

    def add(kind, detail, **kw):
        issues.append({"issue": kind, "detail": detail, **kw})

    for _, r in lit[lit.status == "needs_attention"].iterrows():
        add("literature row needs attention", r.issues, lit_id=r.lit_id,
            location=f"{r.source_sheet} row {r.source_row}")

    by_target = {}
    for _, r in lit[lit.status == "ok"].iterrows():
        rows = lit_workbook_rows(wb, r)
        if not rows:
            if r.need in NEEDS and NEEDS[r.need][0] != VEH:
                add("literature value has no row in the extraction sheet", f"{r.need} {r.country} {r.vehicle} {r.quintile or ''} "
                    f"{r.data_point_name}: {r.value:g}", lit_id=r.lit_id)
            continue
        for row in rows:
            sheet = NEEDS[r.need][0]
            by_target.setdefault((sheet, row), []).append(r)

    for (sheet, row), lits in sorted(by_target.items()):
        current = wb.current(sheet, row)
        current = float(current) if isinstance(current, (int, float)) else current
        entry = wb.plan.get((sheet, row))
        origin = entry["origin"] if entry and entry["action"] == "set" else "existing"
        source = norm(wb.get(sheet, row, "data source"))
        placeholder = origin == "derived" or (origin == "existing" and source.startswith(("dummy", "derived")))
        desc = wb.describe(sheet, row)
        label = " ".join(str(desc[k]) for k in ["country", "vehicle", "fortificant", "scenario", "quintile", "sex",
                                                "data_point_name"] if not blank(desc[k]))
        label = f"{label} | {NEEDS[need_alias(desc['data_need'])][1] if need_alias(desc['data_need']) else ''}"
        lits = recommended_first(lits)
        values = sorted({round(float(x.value), 9) for x in lits})
        recommended = [x for x in lits if x.use_in_model == "yes"]
        if len(values) > 1:
            add("several literature candidates", f"{label}: " + ", ".join(
                f"{x.lit_id}={x.value:g} ({x.data_source}){recommendation_tag(x)}" for x in lits),
                tab=sheet, row=row, output_value=current, decision_id=decided.get((sheet, row)),
                lit_recommended="; ".join(x.lit_id for x in recommended) or None)
            if len({round(float(x.value), 9) for x in recommended}) > 1:
                add("conflicting literature recommendations", f"{label}: more than one candidate with different "
                    "values is marked 'Use in model' = yes: " + ", ".join(f"{x.lit_id}={x.value:g}" for x in recommended),
                    tab=sheet, row=row, output_value=current)
        for x in lits:
            if x.use_in_model == "no" and recommended:
                continue  # Juhi recommends another candidate for this row; that one is reported instead
            comparable = x.value
            note = ""
            if x.need in ("amount", "u5_amount") and x.data_point_name == "mean" and \
                    basis.get((x.country, x.vehicle)) == "among_consumers":
                q = wb.get(sheet, row, "quintile") if x.need == "amount" else "Total"
                any_row = wb.find(CV, country=x.country, vehicle=x.vehicle, need="any", quintile=q)
                if any_row:
                    comparable = x.value * wb.current(CV, any_row[0])
                    note = " (literature value x coverage, per the arm's among_consumers basis)"
            agree = isinstance(current, (int, float)) and np.isclose(current, comparable, rtol=AGREE_RTOL, atol=1e-9)
            if agree or (sheet, row) in decided:
                continue
            if x.use_in_model == "yes":
                kind = "recommended literature value differs from output"
            elif placeholder:
                kind = "literature could replace placeholder"
            else:
                kind = "literature disagrees with output"
            where = {"existing": "unchanged from extraction sheet", "gf": "GF default",
                     "derived": "derived placeholder", "decision": "decision"}[origin]
            add(kind, f"{label}: output {current!r} ({where}) vs literature {comparable:g}{note} "
                f"[{x.data_source}]{recommendation_tag(x)}", tab=sheet, row=row, output_value=current,
                lit_id=x.lit_id, lit_value=comparable, lit_recommended=x.use_in_model)

    for _, d in decisions[decisions.status.str.lower() == "proposed"].iterrows():
        try:
            effects = resolve_decision(wb, lit, d)
        except ValueError as e:
            add("proposed decision is invalid", str(e), decision_id=d.decision_id)
            continue
        for sheet, row, action, value, ref, method, _ in effects:
            now = wb.current(sheet, row)
            now = float(now) if isinstance(now, (int, float)) else now
            add("proposed decision (not applied)", f"{d.rationale} -> would {action} "
                f"{'' if value is None else f'{value:g} '}(output now {now!r})",
                decision_id=d.decision_id, tab=sheet, row=row, output_value=now,
                lit_id=d.source if str(d.source).startswith("lit:") else None, lit_value=value)

    modeled = {(a["country"], a["vehicle"]) for a in arms}
    for sheet in (CV, CVF, SCEN, VEH):
        for row in wb.rows(sheet):
            entry = wb.plan.get((sheet, row))
            source = norm(wb.get(sheet, row, "data source"))
            is_placeholder = (entry is not None and entry["origin"] == "derived") or (
                (entry is None or entry["action"] == "keep") and source.startswith("dummy"))
            key = (wb.get(sheet, row, "country"), wb.get(sheet, row, "vehicle"))
            if is_placeholder and (sheet == VEH or key in modeled):
                desc = wb.describe(sheet, row)
                add("placeholder remains", " ".join(str(v) for v in desc.values() if not blank(v)),
                    tab=sheet, row=row, output_value=wb.current(sheet, row))
    return pd.DataFrame(issues)


# --------------------------------------------------------------------------------------
# Three-way comparison: existing sheet vs GF vs literature (plus the output)
# --------------------------------------------------------------------------------------


def gf_only(gf, path, arms):
    """What the GF mapping alone would put in every row, for every arm in arms.csv.

    Unlike the build, this ignores apply_gf, so you can see GF's numbers for arms that
    don't take them yet. Rows the mapping can't place are skipped.
    """
    wb = Workbook(path)
    for arm in arms:
        arm = dict(arm, apply_gf=True)
        steps = [] if arm["gcap_basis"] == "hces" else [gf_consumption_any, gf_consumption_amount]
        for step in steps + [gf_fortifiability]:
            try:
                step(gf, wb, arm)
            except (LookupError, TypeError):
                pass
        for f in arm["fortificants"]:
            for step in (gf_baseline, gf_intervention):
                try:
                    step(gf, wb, arm, f)
                except (LookupError, TypeError):
                    pass
    return wb


def compare(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or pd.isna(a) or pd.isna(b):
        return ""
    if np.isclose(a, b, rtol=AGREE_RTOL, atol=1e-9):
        return "same"
    return f"differs ({(b - a) / a:+.0%})" if a else "differs"


def build_comparison(gf, wb, lit, arms, extraction_path):
    gfw = gf_only(gf, extraction_path, arms)
    basis = {(a["country"], a["vehicle"]): a["gcap_basis"] for a in arms}
    listed = {(a["country"], a["vehicle"]): ("yes" if a["apply_gf"] else "listed, GF off") for a in arms}

    lit_by_row, lit_unplaced = {}, []
    for _, r in lit[lit.status.isin(["ok", "needs_attention"])].iterrows():
        rows = lit_workbook_rows(wb, r)
        if not rows:
            if r.need in NEEDS or r.status == "ok":
                lit_unplaced.append(r)
            continue
        for row in rows:
            lit_by_row.setdefault((NEEDS[r.need][0], row), []).append(r)

    records = []
    for sheet in (CV, CVF, SCEN, VEH):
        for row in wb.rows(sheet):
            alias = need_alias(wb.get(sheet, row, "data need"))
            if alias is None:
                continue
            d = wb.describe(sheet, row)
            existing = wb.get(sheet, row, "value")
            g = gfw.plan.get((sheet, row))
            gf_value = g["value"] if g and g["action"] == "set" else None
            lits = recommended_first(lit_by_row.get((sheet, row), []))
            lit_values, lit_published = [], []
            for x in lits:
                v = x.value
                if x.need in ("amount", "u5_amount") and x.data_point_name == "mean" and \
                        basis.get((x.country, x.vehicle)) == "among_consumers":
                    q = wb.get(sheet, row, "quintile") if x.need == "amount" else "Total"
                    any_row = wb.find(CV, country=x.country, vehicle=x.vehicle, need="any", quintile=q)
                    v = x.value * wb.current(CV, any_row[0]) if any_row else v
                lit_values.append(round(float(v), 9))
                lit_published.append(x.raw_value)
            lit_value = lit_values[0] if len(set(lit_values)) == 1 else None
            rec_values = {v for v, x in zip(lit_values, lits) if x.use_in_model == "yes"}
            rec_ids = [x.lit_id for x in lits if x.use_in_model == "yes"]
            lit_recommended = rec_values.pop() if len(rec_values) == 1 else None
            # Compare against Juhi's pick when she made one, else the single candidate
            lit_compare = lit_recommended if lit_recommended is not None else lit_value
            entry = wb.plan.get((sheet, row))
            out_set = entry is not None and entry["action"] == "set"
            output = entry["value"] if out_set else existing
            records.append({
                "tab": sheet, "row": row, "need": alias,
                **{k: d[k] for k in ["country", "vehicle", "fortificant", "scenario", "quintile", "sex", "data_point_name"]},
                "units": wb.get(sheet, row, "units"),
                "arm_in_arms_csv": listed.get((d["country"], d["vehicle"]), "" if sheet == VEH else "no"),
                "existing_value": existing,
                "existing_source": wb.get(sheet, row, "data source"),
                "gf_value": gf_value,
                "gf_reference": g["ref"] if g else None,
                "lit_value": lit_value if lit_value is not None else ("; ".join(
                    f"{v:g}{'*' if x.use_in_model == 'yes' else ''}" for v, x in zip(lit_values, lits)) or None),
                "lit_recommended_value": lit_recommended,
                "lit_recommended_id": "; ".join(rec_ids) or None,
                "lit_as_published": "; ".join(str(v) for v in lit_published) or None,
                "lit_ids": "; ".join(x.lit_id for x in lits) or None,
                "lit_source": "; ".join(str(x.data_source) for x in lits) or None,
                "gf_vs_existing": compare(existing, gf_value),
                "lit_vs_existing": compare(existing, lit_compare),
                "lit_vs_gf": compare(gf_value, lit_compare),
                "output_value": output,
                "output_source": entry["source"] if entry else "existing extraction sheet",
                "decision_id": entry["decision_id"] if entry else None,
            })
    for x in lit_unplaced:
        records.append({"tab": None, "row": None, "need": x.need, "country": x.country, "vehicle": x.vehicle,
                        "fortificant": x.fortificant, "scenario": x.scenario, "quintile": x.quintile, "sex": x.sex,
                        "data_point_name": x.data_point_name, "units": x.units,
                        "arm_in_arms_csv": listed.get((x.country, x.vehicle), "no"),
                        "lit_value": x.value, "lit_as_published": x.raw_value, "lit_ids": x.lit_id,
                        "lit_source": x.data_source,
                        "output_source": "(no row in the extraction sheet)" if x.status == "ok"
                        else f"(literature row needs attention: {x.issues})"})
    return pd.DataFrame(records)


def write_comparison_xlsx(df, path):
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    df.to_excel(path, index=False, sheet_name="comparison")
    book = openpyxl.load_workbook(path)
    ws = book.active
    ws.freeze_panes = "L2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True)
    cols = {c.value: c.column for c in ws[1]}
    differs, same = PatternFill("solid", fgColor="F8CBAD"), PatternFill("solid", fgColor="C6EFCE")
    for r in range(2, ws.max_row + 1):
        for flag, target in [("gf_vs_existing", "gf_value"), ("lit_vs_existing", "lit_value")]:
            v = ws.cell(r, cols[flag]).value or ""
            fill = differs if v.startswith("differs") else same if v == "same" else None
            if fill:
                ws.cell(r, cols[target]).fill = fill
                ws.cell(r, cols[flag]).fill = fill
        v = ws.cell(r, cols["lit_vs_gf"]).value or ""
        if v:
            ws.cell(r, cols["lit_vs_gf"]).fill = differs if v.startswith("differs") else same
    widths = {"need": 22, "existing_source": 30, "gf_reference": 30, "lit_source": 30, "lit_ids": 16,
              "output_source": 24}
    for name, col in cols.items():
        ws.column_dimensions[get_column_letter(col)].width = widths.get(name, 12)
    book.save(path)


# --------------------------------------------------------------------------------------


def read_decisions(path):
    d = pd.read_csv(path, dtype=str, comment="#").fillna("")
    d.columns = [c.strip() for c in d.columns]
    if d.decision_id.duplicated().any():
        raise ValueError(f"duplicate decision_id: {d.decision_id[d.decision_id.duplicated()].tolist()}")
    return d


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extraction", type=pathlib.Path, default=EXTRACTION_FILE)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--decisions", type=pathlib.Path, default=DECISIONS_FILE)
    parser.add_argument("--arms", type=pathlib.Path, default=ARMS_FILE)
    parser.add_argument("--lit-long", type=pathlib.Path, default=LIT_LONG)
    args = parser.parse_args()
    if args.output.resolve() == args.extraction.resolve():
        sys.exit("Refusing to overwrite the base extraction workbook; choose another --output")

    gf, lit = GF(GF_LONG), pd.read_csv(args.lit_long)
    if "use_in_model" not in lit.columns:
        lit["use_in_model"] = None
    arms, decisions = read_arms(args.arms), read_decisions(args.decisions)
    wb = Workbook(args.extraction)

    apply_gf_defaults(gf, wb, arms)
    decided = apply_decisions(wb, lit, decisions)
    for arm in arms:
        if arm["derive_from"]:
            derive_sd_and_u5(wb, arm, decided)

    review = build_review(wb, lit, arms, decisions, decided)
    review.to_csv(REVIEW, index=False)
    comparison = build_comparison(gf, wb, lit, arms, args.extraction)
    comparison.to_csv(COMPARISON, index=False)
    write_comparison_xlsx(comparison, COMPARISON_XLSX)
    problems = run_checks(wb, arms)
    if problems:
        print("Checks failed; workbook NOT written:")
        for p in problems:
            print("  " + p)
        print(f"See {REVIEW.name} for context.")
        sys.exit(1)

    records, expected = wb.changelog(SOURCE_LABELS)
    pd.DataFrame(records).to_csv(CHANGELOG, index=False)
    wb.wb.calculation.fullCalcOnLoad = True
    wb.wb.save(args.output)

    if recalculate(args.output):
        bad, recomputed = verify(args.extraction, args.output, expected)
        if bad:
            for p in bad[:30]:
                print("MISMATCH", p)
            sys.exit(f"{len(bad)} cells differ from what was intended; do not use {args.output.name}")
        print("Recalculated with LibreOffice; all untouched values match the base workbook.")
        for sheet, coord, formula, before, after in recomputed:
            print(f"  recomputed: {sheet}!{coord} {formula}: {before} -> {after}")
    else:
        print("WARNING: LibreOffice not found; open the output in Excel and save it before use.")

    log = pd.DataFrame(records)
    print(f"\nWrote {args.output.name}, {CHANGELOG.name}, {REVIEW.name}, {COMPARISON_XLSX.name}")
    print(log.groupby(["step", "source", "status"]).size().to_string())
    if len(review):
        print("\nReview items:")
        print(review.groupby("issue").size().to_string())


if __name__ == "__main__":
    main()
