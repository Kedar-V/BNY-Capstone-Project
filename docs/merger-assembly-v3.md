# Merger extraction assembly experiment (11 November 2026)

This experiment uses the saved January–September 2026 SEC text and GLiNER spans. It does **not** retrain GLiNER or replace the existing 691-filing JSONL. The selector chooses a provisional value per filing and field; a separate source-evidence queue supports later deal-level human review.

## Measured result

The reference comparison has **35 overlapping filings and 74 unverified reference rows**. The same accession split used in earlier experiments has 19 development and 16 comparison filings. The comparison half has already been inspected during tuning, so it is not a clean held-out test.

| Cohort | Original top-1 micro F1 | Previous acquirer-only micro F1 | Combined assembly micro F1 |
|---|---:|---:|---:|
| Development | 0.209 | 0.232 | **0.264** |
| Comparison | 0.132 | 0.178 | **0.197** |
| All overlap | 0.171 | 0.205 | **0.230** |

| Field | Original top-1 F1 | Combined assembly F1 |
|---|---:|---:|
| Acquirer | 0.444 | **0.653** |
| Target | 0.360 | **0.446** |
| Cash consideration | 0.040 | **0.110** |
| Stock exchange ratio | 0.168 | 0.168 |
| Effective date | 0.063 | 0.063 |
| Security description | 0.063 | 0.063 |
| Shareholder vote date | 0 | 0 |
| Ticker | 0 | 0 |

CUSIP and ISIN have no scored values in the overlap. These F1 values are **provisional agreement with `candidate_not_verified` reference rows**, not validated accuracy. One filing-level selection is scored against every reference deal row for that filing. The relaxed matcher can accept a generic label such as “Parent” or miss a valid company alias. Do not compare these F1 values with the tender-offer pipeline's 0.535.

## What changed

- `scripts/tune_merger_gliner_v3.py` retains the role-aware acquirer selection from v2. For target, it favors repeated, full company names over short generic role labels. For cash consideration, it selects only a dollar-denominated amount without “million” or “billion” in the span, and abstains otherwise. This rejects descriptive labels such as “Per Share Merger Consideration” and obvious total transaction amounts. It does not prove that every remaining amount is per-share. It uses GLiNER candidates and source quotes only; reference values are used after selection for scoring.
- `scripts/build_merger_review_clusters.py` groups candidate spans by source window and creates a separate queue of passages about conditional effective times and formula-based exchange ratios. It reads the saved SEC text, records exact source substrings, and leaves `deal_id` and `review_status` blank. **A window is not necessarily a deal.** The 691 filings generated 3,457 window-review rows and 419 flagged term passages (291 effective-time contexts, 128 exchange-ratio contexts). These are review leads, not new validated field predictions; no F1 is claimed for them.
- The original `gliner_merger_candidates_2026_Jan_Sep.jsonl` remains unchanged. The new selection is in `data/mergers/sec_2026/evaluation/assembly_v3/ranked_top1.csv` with source quotes.

## Reproduce

From the project root:

```bash
python3 scripts/tune_merger_gliner_v3.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --out-dir data/mergers/sec_2026/evaluation/assembly_v3

python3 scripts/build_merger_review_clusters.py \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --archive data/mergers/sec_2026/screened_merger_candidates_2026_Jan_Sep.zip \
  --out-dir data/mergers/sec_2026/evaluation/assembly_v3

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/merger -q
```

The current run passed **19 merger tests**. `summary.json` records input hashes, split membership, and field-level counts. `window_review_queue.csv` and `conditional_term_review_queue.csv` are for human review; retain SEC source evidence and assign deal IDs before using them as gold.

## Next decision

The measured gain comes from better **candidate selection**, mainly party names. Date, ratio, security, and ticker failures remain. The next credible accuracy test requires adjudicated, deal-aligned values from filings not used in these tuning experiments. Use `scripts/eval_merger_reviewed.py` for that review and keep multi-deal filings together when splitting data. The new queues can help reviewers find conditional language, but they cannot decide the transaction identity or final value automatically.
