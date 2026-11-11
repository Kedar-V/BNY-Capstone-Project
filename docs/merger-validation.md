# Reviewed merger extraction validation

This pipeline compares GLiNER's extracted merger fields with **human-verified, deal-aligned** SEC values. It is separate from the [provisional reference-agreement experiments](eval-merger.md). The Evaluation branch's `mergers.csv` is a useful review starting point, but its current rows are marked `candidate_not_verified`; copying them straight into gold would not validate extraction.

## 1. Prepare a review cohort

From the project root:

```bash
python scripts/eval_merger_reviewed.py prepare \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --gliner data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --out-dir data/mergers/sec_2026/evaluation/reviewed_pipeline
```

This writes `gold_review.csv`, `model_predictions.csv`, and `prepare_summary.json`. The current overlap contains 35 filings and 1,258 field cells from 74 reference records. The gold table contains **blank** `gold_value` columns; its `reference_candidate` and `reference_quote` columns are only leads for the reviewer. GLiNER predictions are in a separate file so gold can be checked against SEC sources without seeing model output. Source hashes and input file hashes support later audits. Preparation refuses to overwrite existing review files unless `--force` is supplied.

For each reference row, assign a stable `deal_id` identifying the transaction or security record being evaluated. If one filing has multiple records, give them distinct IDs and align the corresponding model prediction rows by filling `deal_id` in `model_predictions.csv`. A single filing-level top-1 span cannot be scored against several deals without this step. Keep related amendments and counterparties together when making train/test splits.

For each gold field, inspect the SEC filing and any relevant exhibits. Enter `gold_state=present`, `absent`, or `unknown`. For `present`, fill `gold_value` with a canonical value and `gold_evidence` with an exact supporting passage. For `absent`, leave `gold_value` blank. Set `review_status=verified` or `adjudicated` and record `reviewer`; leave uncertain cells as `unknown`. The reference's `candidate_not_verified` label does not count as review. A second reviewer should adjudicate disputed deals and critical terms before final reporting.

## 2. Score reviewed fields

```bash
python scripts/eval_merger_reviewed.py score \
  --gold data/mergers/sec_2026/evaluation/reviewed_pipeline/gold_review.csv \
  --predictions data/mergers/sec_2026/evaluation/reviewed_pipeline/model_predictions.csv \
  --out-dir data/mergers/sec_2026/evaluation/reviewed_pipeline
```

The scorer produces `score_summary.json`, `per_field.csv`, and `score_details.csv`. Its field metrics count a correct present value as TP, a missing present value as FN, a spurious value for a verified-absent field as FP, and a wrong present value as both FP and FN. Verified absent with no prediction is TN. Precision, recall, F1, and cell accuracy are reported by field and micro-averaged. Unknown/unreviewed cells never enter the denominator. The summary reports exclusions and review coverage.

Identifier and category fields use strict normalized equality. Dates accept ISO or English calendar dates; cash amounts compare exact decimal values. Names, ratios, and narrative terms that differ in wording require explicit comparison review. For an equivalent alias or a confirmed mismatch, set `comparison_override=match` or `mismatch` with `comparison_reviewer` and `comparison_note`. Unresolved comparisons stay out of metrics; the detail table flags them. The script does not infer a deal ID from reference wording.

**Current state:** Running `score` on the untouched template returns `accuracy_status=not_scorable`, because no cells have been reviewed. This is the correct result. The older top-1 and quote-agreement reports are provisional diagnostics, not ground-truth accuracy. Detection precision/recall also requires reviewed non-merger filings and is outside this field-extraction score.
