# LSFF consumption & fortification data scan — September 2026

Scan of what has changed since the April 2025 report, mapped against the inputs currently
used in `0100_data_prep`. Second revision; see "Corrections to the first version" at the
bottom for what changed and why.

**Confidence conventions used below:** *verified* = read from the primary source;
*reported* = from a secondary source I could reach but did not confirm at source;
*unverified* = could not reach the source from this environment.

---

## 🚩 India — the rice fortification programme has been paused

**In late February 2026 the Government of India temporarily discontinued rice fortification
under PMGKAY and allied schemes.** *(verified — Drishti IAS 2 Mar 2026 summary of the
Business Standard report)*

- Triggered by an IIT Kharagpur shelf-life study of Fortified Rice Kernels and fortified
  rice across agro-climatic zones: moisture, storage temperature, humidity and packaging
  materially degrade micronutrient content. Central pool rice is often stored 2–3 years.
- Entitlements unchanged; PDS, ICDS and PM POSHAN continue — without fortified rice.
- For KMS 2025–26 and pending KMS 2024–25 receipts, states/UTs may supply fortified *or*
  non-fortified rice at their discretion.
- Framed as a pause "until a more robust nutrient delivery mechanism is operationalised."
  This reverses the Oct 2024 Cabinet approval of fortified rice supply through Dec 2028.

**Implication.** The India *baseline* scenario (80% coverage of government-distributed rice
at current standards) no longer describes the current situation. This is a
scenario-definition question rather than a data-prep one, and probably needs raising with
the Gates Foundation before the India inputs are rebuilt. It also raises a new modellable
question: retention losses between the FRK standard and what reaches the plate.

In the code this lands on one line — `GOVERNMENT_BASELINE_COVERAGE = 0.8` in
`hces/01_extract_hces.ipynb`, flagged inline there.

### India data inputs

| Current input | Status |
|---|---|
| HCES 2022–23 microdata (rice consumption, wealth index via PCA) | **Superseded.** HCES 2023–24 (Aug 2023–Jul 2024, 261,953 households) factsheet released Dec 2024; unit-level data on microdata.gov.in (catalog 237) and IHSN (catalog 12934). Same FDQ/CSQ/DGQ questionnaire structure, so the wealth-index PCA should port. No 2024–25 round found. |
| DHS/NFHS 2015–16 (hemoglobin disparities), NFHS 2019–21 (birth disparities) | **Superseded, with a caveat.** NFHS-6 fieldwork ran May 2023–Dec 2024 (~679,000 households, 715 districts). India/State fact sheets released 29 May 2026; district fact sheets Aug 2026. *Unit-level recode availability through the DHS Program is unconfirmed* — fact sheets alone will not support quintile-level hemoglobin tabulation. |
| Folate intake from a Delhi cross-sectional study | Still the weakest link. Nothing better surfaced. HCES food-item data could support a crude alternative estimate. |

---

## Nigeria

### NFCMS 2021 microdata does not appear to be publicly obtainable

Confirmed as far as can be confirmed negatively. Everything reachable is report-level: the
IITA final report PDF, the preliminary report, a key-findings deck, CGSpace items, the
UNICEF landing page. No data files anywhere. *(The GHDx record page is JavaScript-rendered
and could not be read from this environment — unverified.)* A GHDx record existing does not
imply a download; GHDx routinely catalogs surveys with metadata only.

Corroborating evidence from within the project: the 2025 report used an **unpublished**
Intake analysis of NFCMS microdata for rice coverage by quintile. If the microdata were
obtainable, we would presumably have tabulated it ourselves.

**Realistic route:** a formal data request to IITA, the Federal Ministry of Health, or
Intake / FHI 360 — not a download. Worth doing, since NFCMS remains the only Nigerian source
that carries 24-hour recall, biomarkers, and brand-level bouillon detail together.

### NLSS 2023 — the most promising new candidate

Nigerian Living Standard Survey 2023 (`NGA-NBS-NLSS-2023`), NBS, LSMS-type. NBS microdata
catalog 168; free registration required to download. *(verified — catalog metadata read
directly; created Aug 2025, last modified Feb 2026, ~2,200 downloads.)*

The NLSS food module asks households to recall the **total quantity** of each of **99
prespecified food items** over 7 days *(reported, for the 2018/19 round)*. Quantities rather
than frequency is what makes this usable, and it is the same shape of input we already
exploit for India — so the existing machinery largely transfers:

- Household rice quantity → the existing meals-based within-household allocation
- Asset, housing, water and sanitation variables → the DHS-emulating PCA wealth index
  already implemented in `hces/01_extract_hces.ipynb`
- Large sample, so quintile × age × sex cells should hold up

**The question that decides its value: whether bouillon/seasoning is one of the 99 items.**
Not confirmed — the item code list was not reachable. Given ~90–100% household penetration of
bouillon in Nigeria it would be surprising to omit, but that is not confirmation. First thing
to check after logging in.

**What NLSS will not give us**, that NFCMS did: no biomarkers, no 24-hour recall (hence no
folate intake), and no brand or fortification questions — so the "branded bouillon =
fortifiable" basis for the fortifiability split would need another source.

### GHS-Panel Wave 5 — useful as a cross-check, not a primary source

Nigeria General Household Survey-Panel Wave 5, 2023/24. ~5,000 households, panel design,
post-planting (Jul–Sep) and post-harvest (Jan–Mar) visits. World Bank catalog 6410
(DOI `10.48529/zd5s-tj25`); NBS catalog 82.

Wave 5 covers Food Consumption and Expenditure, Aggregate Food Consumption, and Dietary
Diversity, and the data dictionary does contain quantity and unit variables in the food
consumption sections *(verified — data dictionary read directly)*. But the dietary diversity
module records *days consumed per food group in the last 7 days* — frequency, not amount
*(reported)* — and ~5k households is thin once stratified by quintile, age and sex.

Its distinctive value is **seasonality**: two visits per year is the only handle we would have
on within-year variation in vehicle consumption.

### Other Nigeria inputs

| Current input | Status |
|---|---|
| DHS 2018 (hemoglobin, birthweight, maternal mortality disparities) | Still newest standard DHS. NDHS 2023–24 exists but is COVID-era, which the 2025 report excluded on. Worth revisiting that exclusion rule as 2030 approaches. |
| NG Food Fortification Regulations 2021 (rice concentrations) | Unchanged as far as found. |
| Bouillon concentrations (Gates-specified) | **Changed context.** Nigeria adopted a *voluntary* multiple-micronutrient bouillon standard in Sept 2024 (iron, zinc, folic acid, B12), informed by the CoMIT trial. Through 2026 there is an active push — and organised opposition (CAPPA) — around making it mandatory. The model's assumption of zero effective baseline coverage may need revisiting if voluntary uptake has begun. |

---

## Ethiopia

### The new national survey exists; the results release is the bottleneck

The PubMed link is the **study protocol**, not results: Woldeyohannes et al., *BMJ Open*
2023, "Ethiopia National Food and Nutrition Survey to inform the Ethiopian National Food and
Nutrition Strategy" — PMID 37185190, [DOI](https://doi.org/10.1136/bmjopen-2022-067641).
*(verified via PubMed.)* 16,596 households, 639 enumeration areas, two-stage stratified
cluster sampling; outcomes include dietary intake, micronutrient status, intervention
coverage and soil nutrients.

Its value is twofold. It confirms this is **the same survey behind the 2022 FNS baseline we
already cite** — so "is there a new Ethiopian food consumption survey?" resolves to: yes, it
exists, it was fielded (Jul 2021–Dec 2023), and it is large. And it gives us a citable
sampling design while we wait. It contains no results and no data.

That makes chasing EPHI for the FNS baseline final report the highest-value Ethiopia action.

### A vintage question in our own citations

The 2025 *Nutrients* paper on Ethiopian energy and nutrient intake gaps
([DOI](https://doi.org/10.3390/nu17172818)) draws on the older National Food Consumption
Survey, described there as fielded in the **lean season, June–September 2011** (8,254
households, 8,254 WRA, 7,272 children 6–45 months, single 24-hour recall) *(reported)*.

Our report cites Saje et al. as the "2013 Ethiopian National Food Consumption Survey."
Plausibly the same survey under different date conventions — but if so, our baseline folate
intake for Ethiopia comes from **2011 lean-season** data, which should be stated explicitly
given the seasonality implications. Worth confirming which vintage Saje actually used.

### Harvard Dataverse NIPN is a metadata catalog, not a data repository

The NIPN collection holds metadata descriptions, codebooks, questionnaires, reports and
publications; obtaining data means requesting it from the data owner, subject to each
owner's sharing policy *(reported)*. Hosted by EPHI with IFPRI technical assistance. The
dataverse page itself is JavaScript-rendered and could not be enumerated from this
environment — *unverified*, worth clicking through.

So it will not hand over files, but it is a good way to establish which Ethiopian datasets
exist, what variables they contain, and who to ask. That bears directly on the
folate-intake-by-wealth gap.

### Other Ethiopia inputs

| Current input | Status |
|---|---|
| 2022 FNS Baseline Survey, *preliminary* report (salt coverage) | Preliminary report launched Mar 2023; collection ran Jul 2021–Dec 2023. No public final report confirmed. Chase EPHI. |
| Saje et al., median folate intake by wealth | See the vintage question above. |
| Sisay et al., serum folate by wealth tertile | **Relevant new work:** Tesfaye et al., *Maternal & Child Nutrition* 2025 — serum folate concentration corresponding to the RBC folate threshold for elevated NTD risk in Ethiopian WRA. Bears directly on the serum→RBC folate step in the NTD model. |
| Gates Foundation salt consumption tabulation by quintile | No public replacement found. |
| Salt fortification scenario (folic acid at 25%/100% Codex NRV) | **Now a real programme, not hypothetical.** Ethiopia has launched a national iodine + folic acid double-fortified salt programme (MoH / EPHI / Nutrition International, with UC Davis and U Toronto, Gates-funded). Rapid folic-acid test kits reportedly rolling out across regions in 2026. Acceptability confirmed for DFS and TFS (Tesfaye et al. 2025). A 2025 medRxiv paper costs out expanding salt iodization to multiple micronutrients. Actual programme concentrations should replace the assumed NRV-based levels once published. |
| Ethiopia DHS 2016 | Still newest standard DHS. |
| — | New: **Ethiopian Food Composition Table 2025** (EPHI) — useful for any folate intake recalculation. |

---

## Suggested priority order

1. **Resolve the India scenario question** with stakeholders before rebuilding India inputs.
   The pause changes what "baseline" means.
2. **Swap HCES 2022–23 → 2023–24** and re-run the wealth-index PCA. Highest value, lowest
   risk. See `hces/HCES_UPDATE_NOTES.md` for the guardrails added ahead of this.
3. **Register on the NBS catalog and check the NLSS 2023 food item list for bouillon.** One
   lookup that determines whether Nigeria has a usable public consumption source at all.
4. **Chase EPHI** for the FNS baseline final report and any published DFS programme
   concentrations. The protocol paper confirms the data exists.
5. **Request NFCMS 2021 microdata** from IITA / FMoH / Intake. Still the only Nigerian source
   combining recall, biomarkers and brand detail.
6. **Check NFHS-6 recode availability** through the DHS Program; document 2019–21 as fallback
   if unavailable.
7. **Resolve the Saje et al. survey vintage** (2011 vs 2013) and state it in the methods.
8. **Revisit the "no effective baseline coverage" assumption** in Nigeria given the 2024
   voluntary bouillon standard.

---

## Corrections to the first version

Recorded rather than quietly edited, in case the earlier version was circulated.

- **"NFCMS 2021 microdata is now catalogued on GHDx, a possible route to reproducing the
  unpublished Intake tabulations in-house" — withdrawn.** That came from a search-engine
  summary of the GHDx record page, not from the record itself, and the page could not be
  read from this environment. No evidence of obtainable microdata exists; the route is a
  formal data request. The same incorrect claim appeared in the first version of
  `hces/HCES_UPDATE_NOTES.md` and has been corrected there.
- **NLSS 2023 and GHS-Panel Wave 5 were missed entirely** in the first pass, which searched
  for successors to NFCMS rather than for general consumption surveys that happen to carry
  food quantities. NLSS 2023 may be the more practical source despite not being a nutrition
  survey.
- **The Ethiopia FNS baseline and the "new" national food and nutrition survey were treated
  as separate items.** The protocol paper shows they are the same survey.
