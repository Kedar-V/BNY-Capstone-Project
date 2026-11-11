# Merger GLiNER tuning experiment

The canonical merger GLiNER extraction remains `data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl` (691 filings). `scripts/tune_merger_gliner.py` tests a top-1 acquirer reranker on the saved candidate spans. It does not alter extraction or the canonical output.

Run from the repository root:

```bash
python3 scripts/tune_merger_gliner.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --out-dir data/mergers/sec_2026/evaluation/tuning_consensus
```

The experiment filters spans at confidence 0.4. For acquirer only, it groups identical normalized values and ranks each group by maximum span confidence plus `0.07 * log1p(mention_count)`. Other fields retain the highest-confidence span. Repeated overlapping windows can inflate mention count, so this is an experimental heuristic.

The script uses a reproducible SHA-256 accession split: 19 development filings and 16 comparison filings among the 35 reference-overlapping filings. Provisional relaxed-match micro F1 was 0.2091 to 0.2045 on development, 0.1321 to 0.1549 on comparison, and 0.1706 to 0.1797 across all overlap. Since the comparison set was inspected during tuning, it is **not an untouched test set**. The reference rows are unverified candidates, 20 overlapping filings have multiple deal rows, and one filing-level prediction is scored against each row. These numbers are reference agreement, not validated extraction accuracy.

We also reran GLiNER on the same 35 filings with 12 windows (instead of 6) and threshold 0.35 (instead of 0.4). It produced 2,693 spans versus 1,393 original spans, but development F1 fell to 0.1677. The rerun used a different installed GLiNER version, so it does not isolate the window and threshold effects. The expanded run was not promoted.

Before adopting a tuning change, manually review accession- and deal-aligned labels, score on separate unseen filings, and report field-level precision and recall. `scripts/eval_merger_reviewed.py` provides a reviewed-label workflow.
