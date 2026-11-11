# Merger extraction improvement experiment (10 November 2026)

## Outcome

A new **role-aware acquirer reranker** improves provisional agreement with the current reference, while preserving the saved 691-filing GLiNER extraction. It changes only the selected acquirer; other fields retain the original highest-confidence span. The experiment is in `scripts/tune_merger_gliner_v2.py` and its outputs are in `data/mergers/sec_2026/evaluation/role_aware_v2/`.

| Cohort | Filings | Baseline micro F1 | Role-aware micro F1 | Baseline acquirer F1 | Role-aware acquirer F1 |
|---|---:|---:|---:|---:|---:|
| Development | 19 | 0.209 | 0.232 | 0.649 | 0.784 |
| Comparison | 16 | 0.132 | 0.178 | 0.229 | 0.514 |
| All overlap | 35 | 0.171 | 0.205 | 0.444 | 0.653 |

The same 35 filings were used in earlier tuning work, including inspection of the comparison half. The comparison results are therefore **not an untouched test**. The reference has 860 rows across 562 accessions; 74 rows from 35 accessions overlap the saved predictions. Every reference row is marked `candidate_not_verified`, and 20 overlapping filings have multiple deal rows. These are relaxed-match *reference-agreement* scores, **not validated extraction accuracy**.

## Method

The baseline selects the highest-confidence GLiNER span for each field. The new acquirer selector groups identical normalized names, then ranks groups using:

`best span confidence + 0.12 × log1p(mention count) + 0.08 for a full organization name − 0.16 for a short/generic role − 0.24 for an advisory-context mention`

Full names are detected with common organization suffixes such as Inc., Corp., LLC, and Ltd. Generic roles include “Parent,” “Company,” and “Merger Sub.” Advisory context is detected from the **source quote**, using terms such as “financial advisor,” “underwriting,” and “fairness opinion.” It does not use reference values, company-specific blacklists, or the accession's gold answer to select a candidate. The 0.40 confidence cutoff is unchanged. Repeated nearby windows may increase mention count; the score is heuristic, not a calibrated probability.

The rule addresses a recurring error: the model often assigns a high acquirer score to a financial adviser, a target, or a generic role word. In the overlap, the selected acquirer changed in 17 filings. Under the current relaxed reference scorer, nine changed filings improved, none worsened, and eight were ties. Some ties remain semantically questionable; for example, “Parent” can match a long reference description without identifying the legal entity. One changed filing with five reference rows can affect the micro score five times.

## Reproduce

From the project root:

```bash
python3 scripts/tune_merger_gliner_v2.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --out-dir data/mergers/sec_2026/evaluation/role_aware_v2

python3 -m pytest tests/merger -q
```

`summary.json` records input SHA-256 hashes, split membership, micro and field-level scores. `ranked_top1.csv` contains one selected candidate per available filing/field, including a source quote, for review. The 691-filing GLiNER JSONL is unchanged. Fourteen merger tests passed locally.

## Next accuracy improvements

1. **Verify deal-aligned gold.** Use `scripts/eval_merger_reviewed.py` to review source evidence and assign `deal_id`. Its current template has 1,258 cells and zero reviewed cells; validated F1 is unavailable. Reserve a new accession/deal holdout that was not inspected during this experiment.
2. **Treat roles separately from mentions.** A filing can mention parent, subsidiary, target, surviving company, and financial advisers. A relation or event-record layer should resolve which organization fills each role rather than choosing a single highest-scoring entity span.
3. **Represent conditional terms.** Many reference “effective dates” have no calendar date, and stock consideration may be a VWAP formula. Use structured states such as `conditional`, `not_stated`, and `fixed_value`, with source evidence, before scoring these fields.
4. **Add ticker evidence rules cautiously.** The SEC 8-K cover page often lists all registered symbols under “Trading Symbol(s),” while long proxy filings may only mention tickers in prose. In one inspected overlap filing, the reference ticker `CHTH` is absent from the saved text; other ticker discrepancies require symbol-format and source review. Extract cover-table and prose ticker candidates with source offsets, then review whether each belongs to the target, acquirer, or registrant. Do not award ticker matches from reference values alone.
5. **Separate dataset quality from field extraction.** The 691 screened filings are merger-language candidates. Assess merger detection with reviewed merger and non-merger filings; assess field extraction only on verified, deal-aligned records.

The earlier 12-window / 0.35-threshold GLiNER rerun produced more spans but lowered development F1. It remains unpromoted. This reranker is experimental pending human review and a genuinely unseen test cohort.
