# GBD 2023 migration findings

Drafts for GitHub issues, kept here so the evidence and the measurements behind each
one survive independently of whether the issue gets posted, edited, or closed. They
are **drafts, not a record of posted issues** — cross-references still read
`#<ISSUE-B>` and `#<ISSUE-C>` and need the real numbers filling in.

| file | what it reports | status |
|---|---|---|
| `issue_a_maternal_disorder_saturation.md` | `maternal_disorders.incident_probability` pinned at its `.clip(upper=1)` bound (27 of 45 Nigeria rows), and GBD-2023 revisions diverging by country. **Also carries the retraction of an earlier severe-anemia report.** | open |
| `issue_b_draw_alignment.md` | `maternal_disorders.ylds` divided by the draw count in every `--mean` artifact. Pre-existing, affects published results, bounded under 0.2% of DALYs. | open |
| `issue_c_anemia_responsiveness.md` | `0400` treats unclassified anemia sequelae as iron-*responsive*, because the responsive group is a residual. ~1% of anemia, up to ~3.9%. | needs a research decision |

## Read the retraction in issue A even if you skip the rest

An earlier version of issue A reported that severe anemia jumped 38x under GBD 2023
and called it a genuine round effect. It was our own bug: the `1 - cdf` MirroredGumbel
workaround in `lsff_utils.hemoglobin_distribution`, still applied against a library
that had fixed the upstream bug it was written for. Corrected, the move is ~1.5x.

Three things there are worth more than the number:

- **Reproducibility across builds distinguishes nothing when the builds share a code
  path.** "It reproduces in two independently built artifacts" was treated as evidence
  of a data effect; both builds carried the same inverted CDF.
- **Re-test upstream-bug workarounds individually on a library upgrade.**
  risk_distributions#62 became actively harmful; its sibling #61 is still required.
- **The `0400` notebook's own consistency assertion caught this**, not any of the five
  regression-harness layers. Read self-checks when they fire rather than widening the
  tolerance.

## Provenance

Everything in these drafts was measured, not inferred, against the verified GBD-2021
reference artifacts and a full GBD-2023 pipeline run at 10 seeds. Where a number is an
estimate or rests on a proxy, the draft says so. Figures superseded during the work are
kept as explicit corrections rather than quietly replaced, because in more than one
case the reasoning error was the more useful finding.

See CLAUDE.md — "The severe-anemia finding was a code bug" and "Full pipeline under
GBD 2023" — for how these fit into the migration as a whole.
