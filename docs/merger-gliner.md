# Merger GLiNER extraction

This pipeline reads the saved SEC filing **text** in the January–September 2026 merger-candidate ZIP and uses GLiNER to propose evidence-linked field spans. It does not use the Evaluation CSV's values or quotations as model input. The labels are aligned to the fields in [`Evaluation/notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv`](https://github.com/Kedar-V/BNY-Capstone-Project/blob/Evaluation/notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv).

The Evaluation branch calls its results *unverified*; all 118 rows in the current CSV say `candidate_not_verified`. They are model-generated reference candidates, **not adjudicated ground truth**. The file contains 71 distinct accession numbers, of which only 3 are in our current 691-document screened archive. Consequently, the pipeline reports overlap, but it does not calculate accuracy from that CSV.

## Setup

From the project root, install the GLiNER dependencies from `requirements.txt` (or install `torch` and `gliner` in an existing environment). The first real run downloads the model weights for `urchade/gliner_medium-v2.1`. The SEC source ZIP and manifest must already be in `data/mergers/sec_2026/`; see [the collection guide](README-mergers-2026.md).

To copy the Evaluation CSV into the local, gitignored data directory after fetching that branch:

```bash
git fetch origin Evaluation
mkdir -p data/mergers/reference
git show origin/Evaluation:notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv \
  > data/mergers/reference/mergers_evaluation_2026_Jan_Sep.csv
```

Check accession overlap without loading GLiNER:

```bash
python scripts/run_merger_gliner.py --coverage-only \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep.csv
```

## Run extraction

Start with a small smoke run, then omit `--limit` for all 691 screened filings:

```bash
python scripts/run_merger_gliner.py --limit 5 \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep.csv \
  --output data/mergers/sec_2026/gliner_merger_smoke.jsonl

python scripts/run_merger_gliner.py \
  --max-windows 6 \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep.csv
```

The default output is `data/mergers/sec_2026/gliner_merger_candidates_2026_Jan_Sep.jsonl`, plus a `.summary.json` and a flat `.spans.csv` for spreadsheet review. Each JSONL record contains the SEC accession, source URL, saved-text hash, model ID, windows scored, and **all** proposed spans by field. Every span has its exact source-text offsets, score, surrounding quote, and `method=gliner`. `canonical_fields` stay null pending review; a high GLiNER score is not proof that a proposed value is correct for the transaction.

The Evaluation branch does not commit its `input_text/` filing bodies. If your teammate supplies that folder, or you generate it with the Evaluation branch's filing loader, you can run directly on its 71 unique accessions:

```bash
python scripts/run_merger_gliner.py \
  --reference data/mergers/reference/mergers_evaluation_2026_Jan_Sep.csv \
  --text-dir /path/to/merger_2026-01-01_2026-09-30/input_text \
  --output data/mergers/sec_2026/gliner_evaluation_inputs.jsonl
```

The text mode expects `<accession_number>.txt` and checks each file against the reference CSV's `input_hash`. Missing text files are reported in the summary. Multiple reference records for one filing produce one GLiNER extraction, because a filing may describe more than one deal or security. Ground-truth values remain separate from model input.

The extractor scans the filing opening and bounded windows near merger, consideration, vote, closing, election, and identifier language. Windows are selected from the SEC text alone, never from reference answers. This limits runtime on long filings but can miss terms outside the selected windows. `--max-windows` changes the cap; `--model` and `--threshold` can be used for documented experiments. Keep those settings fixed for a held-out evaluation.

The local October 28, 2026 run used `gliner==0.2.29`, `urchade/gliner_medium-v2.1`, threshold `0.4`, and six windows per filing. It processed all 691 screened filings and produced 20,292 source-linked candidate spans. This is a **candidate count**, not an accuracy measure; repeated party mentions create many spans. A basic post-filter removes malformed tickers/CUSIPs/ISINs and cash candidates adjacent to par-value wording, but other false positives remain.

GLiNER proposes spans for acquirer, target, cash consideration, stock ratio, vote/effective/election dates, conditions, status wording, security description, identifiers, and options. It does **not** reliably resolve relationships, conditional formulas, deal-level identity, or mandatory/voluntary status. `consideration_type` and `mandatory_voluntary_indicator` remain null, as do all canonical fields. Review the filing and its exhibits before turning spans into final values.

## Evaluate later

The current archive has only 3 matching reference accessions, and the Evaluation CSV has multiple rows per filing. Align by accession **and deal/security**, not by CSV row number. Obtain the missing filing texts or a larger common cohort, and have the reference fields and evidence reviewed by people. Then compare field values and evidence on held-out deals; include non-merger filings to assess detection. The current 691-file screen and this GLiNER extractor should never be scored against their own outputs as if they were ground truth.

This is a separate merger-specific entry point. `scripts/run_preprocess.py --path merger` remains a stub because the older modular preprocess stages are tender-offer-specific.
