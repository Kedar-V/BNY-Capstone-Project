# Dataloader

Scripts that pull public SEC filings into `data/samples/` for pattern hunting.

| Script / notebook | What it does |
|-------------------|----------------|
| `download_samples.py` | Diverse TO / 14D9 / OTP / 8-K (+ exhibits) → PDF + HTML under `data/samples/` |
| `inspect_samples.ipynb` | Quick inventory charts + browse one folder |

Related (not in this folder): full EFTS corpus build is `scripts/build_corpus.py`; preprocess HTML is `scripts/run_preprocess.py --stage download`.

## Quick start

```bash
# from repo root, with venv active
# needs data/processed/documents.parquet first:
python scripts/build_corpus.py --tracks tender,conversion --skip-sample

python dataloader/download_samples.py
# optional:
python dataloader/download_samples.py --n 30 --force

jupyter notebook dataloader/inspect_samples.ipynb
```

Requires **Google Chrome** (headless HTML→PDF) on macOS at the default app path.

`SecClient` auto-generates a random User-Agent each run (no personal identity in the repo). It also pauses between requests; if you hit HTTP 429, wait and retry.

## Output layout

```text
data/samples/
  manifest.csv
  schedule_to/   *.pdf  + html/
  to_t/          *.pdf  + html/
  to_i/          *.pdf  + html/
  14d9/          *.pdf  + html/
  amendments/    *.pdf  + html/
  offer_to_purchase/  *.pdf  + html/
  8k/            *.pdf  + html/          # primary current report
  8k_exhibits/   *.pdf  + html/          # EX-* for those 8-K accessions
```

`data/` is gitignored — samples stay local.
