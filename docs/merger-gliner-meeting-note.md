# Merger GLiNER extraction: experiments and discussion note

**Prepared:** 5 November 2026  
**Scope:** January–September 2026 SEC merger-candidate filings in BNY-Capstone-Project  
**Status:** exploratory; no validated merger extraction F1 yet

## What we built and ran

1. **SEC candidate collection and screening.** The saved collection contains 2,787 downloaded filings. Text screening selected 691 merger-related candidates (572 high-priority, 119 medium-priority). Screening is a keyword/pattern filter, so a candidate is not a verified merger or a unique deal. The collection is partial, particularly in early months.
2. **Merger GLiNER extraction.** `scripts/run_merger_gliner.py` reads the saved filing text and `src/merger_gliner.py` selects bounded windows around merger-related phrases. The October 28 run used `urchade/gliner_medium-v2.1`, threshold 0.40, and up to six windows per filing. It processed 691 filings and produced 20,292 source-linked *candidate spans*. Each span has a score, source quote, and text offsets; canonical deal fields remain null. The model was not trained on the Evaluation reference values.
3. **Reference comparison.** The latest local Evaluation reference has 860 rows across 562 accessions, all labeled `candidate_not_verified`. Only 35 accessions overlap the saved GLiNER output, giving 74 reference rows. Twenty of those 35 filings have multiple reference rows. `scripts/eval_merger.py` scores the highest-confidence candidate per field against each row using relaxed text matching. Baseline micro precision was 0.203, recall 0.147, F1 0.171. This is *provisional reference agreement*, not accuracy against reviewed ground truth.
4. **Reviewed-label evaluation framework.** `scripts/eval_merger_reviewed.py` prepared 1,258 field cells across the overlapping rows. None has been human reviewed yet. Its score is therefore null, which is the correct state. This framework requires deal IDs and verified source evidence before a validated F1 can be reported.
5. **Tuning experiment A: more filing coverage.** We reran the same 35 overlapping filings with up to 12 windows and threshold 0.35. Spans increased from 1,393 to 2,693. Development F1 fell from 0.209 to 0.168; the comparison subset rose only from 0.132 to 0.143. The runtime had a different GLiNER package version, so this experiment does not isolate window count from other effects. We did not promote this output.
6. **Tuning experiment B: acquirer consensus reranker.** `scripts/tune_merger_gliner.py` groups repeated normalized acquirer spans and ranks each group by its best confidence plus `0.07 × log1p(mention count)`; all other fields retain max-score selection. On the 19-filing development split, micro F1 changed 0.209 → 0.205. On the 16-filing comparison split, it changed 0.132 → 0.155. Across all 35 overlapping filings, micro F1 changed 0.171 → 0.180; acquirer F1 changed 0.444 → 0.500. Because we inspected the comparison split during tuning, it is no longer an untouched test set. The reranker remains experimental and has not replaced the canonical GLiNER output.

## Field-level findings from the 35-filing comparison

| Field | Provisional F1 before → after reranker | Observed failure pattern |
|---|---:|---|
| Acquirer | 0.444 → 0.500 | Often a ranking/name-resolution error: another candidate matched the reference in all 38 baseline top-1 mismatch rows under the relaxed scorer. |
| Target | 0.360 → 0.360 | Wrong party or abbreviation selected; 18 of 46 misses had another matching candidate, 28 had none. |
| Stock exchange ratio | 0.168 → 0.168 | Many reference values are formulas or conditional terms, not one fixed numeric span; 25 rows had no candidate. |
| Effective date | 0.063 → 0.063 | Nearby historical dates are selected when the reference describes conditional timing; 16 rows had no candidate. |
| Security description | 0.063 → 0.063 | Long share-class descriptions and exclusions are missed; 48 rows had no candidate. |
| Cash consideration | 0.040 → 0.040 | Model sometimes selects a label rather than an amount; reference cells may include conditions as well as price. |
| Shareholder vote date | 0 → 0 | Wrong contextual date or no candidate; no missed reference value matched another candidate under current scoring. |
| Ticker | 0 → 0 | 69 of 73 populated reference rows had no ticker candidate; inspect model proposals and the strict ticker filter separately. |

CUSIP and ISIN had no scored values in the overlapping reference rows and are excluded from the chart. Counts above describe disagreements with unverified reference cells. They are not confirmed model-error counts.

## Why the numbers need care

The reference is not adjudicated ground truth. One filing-level prediction is reused against multiple deal/security rows, and the relaxed scorer can reject aliases or accept weak substring/number matches. The 0.535 F1 discussed previously belongs to a **different tender-offer experiment**, with a different cohort and scoring setup; it is not a merger score. The chart titled “Merger reranking lifts provisional micro F1 to 0.18” shows our merger experiment, not that tender result.

## Decisions to discuss

- **Evaluation unit:** define one deal/security record and stable `deal_id` per reference row; align predictions to that unit before scoring.
- **Gold review:** verify a manageable sample against SEC text, including evidence quotes, absent/conditional states, and a second reviewer for disputed values. Keep all model predictions out of gold labeling.
- **New held-out set:** reserve filings (and related amendments/counterparties) that have not been used in these tuning experiments.
- **Next engineering target:** prioritize ticker detection and date-context classification, then deal-level party resolution and formula-valued consideration. Evaluate each change by field-level precision/recall and source-evidence review.
- **Reporting:** keep provisional reference-agreement charts separate from validated accuracy and from merger detection metrics.

## Files to bring to the meeting

- `data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl` — 691 filing-level GLiNER records.
- `data/mergers/sec_2026/evaluation/merger_gliner_top1_core.summary.json` and `.details.csv` — baseline field scores and mismatches.
- `data/mergers/sec_2026/evaluation/tuning_consensus/summary.json` — split-level reranking comparison.
- `data/mergers/sec_2026/evaluation/merger_gliner_tuned_per_field.png` — meeting chart.
- `data/mergers/sec_2026/evaluation/reviewed_pipeline/gold_review.csv` — blank review template; not yet ground truth.
- `scripts/run_merger_gliner.py`, `src/merger_gliner.py`, `scripts/eval_merger.py`, `scripts/eval_merger_reviewed.py`, `scripts/tune_merger_gliner.py` — pipeline and scoring code.

The project contains older documentation and Evaluation-branch snapshots with earlier reference counts. For this discussion, use the artifact paths and counts above from the current local run.
