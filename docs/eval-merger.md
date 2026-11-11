# Evaluating merger extraction

For a defensible accuracy evaluation, use the [reviewed merger validation workflow](merger-validation.md). The comparisons below are exploratory scores against unverified reference candidates.

## Tender-style top-1 comparison

The `Evaluation` branch's `scripts/eval_tender.py` scores one top-ranked value per field for each reference row, then reports TP/FP/FN, precision, recall, F1, accuracy, and per-field details. The merger adaptation uses the saved GLiNER JSONL in place of tender Concise Reps:

```bash
python scripts/eval_merger.py \
  --gt data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --mode top1 --fields core --scope overlap \
  --out data/mergers/sec_2026/evaluation/merger_gliner_top1_core
```

Outputs are `.summary.json`, `.per_field.csv`, and `.details.csv`. `--scope overlap` isolates filings present in both datasets; `--scope all` additionally counts reference filings absent from the 691-document GLiNER archive as missing predictions, mixing discovery coverage with extraction performance. `--fields all` includes longer narrative fields that a span detector is not designed to resolve.

This reproduces the tender scorer's **top-1, row-wise comparison style**, but every merger reference row is marked `candidate_not_verified`. Multiple reference deals for one accession reuse the same filing-level GLiNER prediction, and relaxed text matching is not semantic adjudication. Report these numbers as **provisional reference agreement**. The November 5, 2026 local core/overlap run scored 74 rows from 35 overlapping filings and had micro F1 `0.1706`; this is not validated extraction F1.

## Provisional score available now

The current unverified Evaluation CSV has field-specific supporting quotes. Score how often distinct GLiNER span values appear literally in a quote for the same field:

```bash
python scripts/eval_merger_evidence.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --output-prefix data/mergers/sec_2026/evaluation/merger_gliner_evidence_agreement
```

`quote_support_fraction` is supported distinct candidate values divided by all distinct candidate values in reference-covered filing-fields. `field_coverage_fraction` is reference accession-fields with at least one supported candidate divided by all reference accession-fields with a quote. Repeated mentions of the same value in one filing count once. Results are pooled by accession and field, so multi-deal filings can cross-match. Quotes may omit correct values or include incorrect text. These scores are **reference-evidence agreement**, not extraction precision, recall, F1, or accuracy. The `.details.csv` shows supported and unsupported values for manual inspection.

## Reviewed accuracy score

Run the merger scorer from the project root:

```bash
python scripts/eval_merger.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --output-prefix data/mergers/sec_2026/evaluation/merger_gliner_scoring
```

The current run reports `accuracy_status: not_scorable`. The Evaluation CSV contains unverified LLM-generated candidate values. The GLiNER JSONL contains repeated candidate spans and leaves every `canonical_fields` value null. Some filings also have several reference rows for distinct deals or securities. The scorer does not turn these into ground truth or silently pick a span as a final value.

For field scores, a reference row needs `review_status=manually_reviewed`, `adjudicated`, or `verified`, with its values checked against SEC evidence. The prediction JSONL needs final values in `canonical_fields`. The current scorer accepts only filings with one reference row and one prediction record; multi-deal filings require deal IDs on both sides and deal-level alignment first. Missing and wrong values count as false negatives; spurious and wrong values count as false positives. Exact values are compared case-insensitively with whitespace normalized. This deliberately does not equate different names, date formats, formulas, or paraphrases; add field-specific normalization only after its rules are reviewed and frozen.

The output `.summary.json` contains per-field true positives, false positives, false negatives, precision, recall, and F1 when filings are scorable. The `.details.csv` records each field comparison. It does not measure merger detection or discovery recall; those need reviewed positive **and negative** filings. Keep the unverified overlap diagnostics separate from accuracy results.
