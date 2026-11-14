# Merger date-context and deal-review trial (11 November 2026)

This trial uses the saved SEC filing text and GLiNER output. It is separate from the canonical 691-filing extraction and does not assign verified merger deals.

## Results

The top-1 date gate accepts a GLiNER date only when its nearby source text has the appropriate meeting or merger-effective-time cue and lacks obvious unrelated-date language. It abstains otherwise. Combined with the existing v3 acquirer/target/cash selector:

| Cohort | Current assembly provisional micro F1 | With date gate |
|---|---:|---:|
| Development (19 filings) | 0.264 | **0.285** |
| Comparison (16 filings) | 0.197 | **0.213** |
| All overlap (35 filings) | 0.230 | **0.249** |

The improvement is chiefly **fewer false date selections**, not more correct top-1 dates. Across all overlap, false shareholder-vote-date predictions fell from 42 to 13 but its TP count stayed 0, so its F1 remains 0. Effective-date false predictions fell from 54 to 20; TP stayed 4, and provisional effective-date F1 rose from 0.063 to 0.085. The date gate does not resolve conditional dates or transaction identity.

A separate SEC-text rule finds dates within 80 characters of a “special meeting” phrase and a scheduling connector. It produces **461 distinct filing/date candidates** across 691 filings, including 201 stricter “held/scheduled” candidates. In the 35 overlap filings, GLiNER's shareholder-vote-date spans contained **0** matching dates for the 45 reference rows with parseable dates. The broad rule's candidate set contained a matching date for **45/45** rows; the strict tier covered **44/45**. The broad set still contained 148 distinct filing/date candidates for 23 distinct reference dates; the strict tier contained 80. These counts are candidate coverage against unverified reference text, **not precision, deal-level recall, or validated accuracy**. Many candidates need rejection or assignment to a specific meeting and company.

`meeting_date_candidates.csv` contains ISO date, exact source offsets and quote, broad/strict tier, and nearby GLiNER party mentions. Its `deal_id` and `review_status` are intentionally blank. Nearby mentions are review hints, not a confirmed acquirer/target relationship. The existing `assembly_v3/window_review_queue.csv` can be used alongside it to identify which transaction a meeting belongs to.

## Reproduce

```bash
python3 scripts/trial_merger_dates.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep_cfdb287.csv \
  --predictions data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl \
  --archive data/mergers/sec_2026/screened_merger_candidates_2026_Jan_Sep.zip \
  --out-dir data/mergers/sec_2026/evaluation/date_context_trial

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/merger -q
```

The local run passed **21 merger tests**. `summary.json` records input hashes and field-level counts. The reference rows are all `candidate_not_verified`, several filings have multiple reference deal rows, and the comparison cohort was examined in prior trials. A reviewed, unseen, deal-aligned test set is still required before promoting the date rules or reporting accuracy.
