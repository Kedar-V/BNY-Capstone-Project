# Dataloader

Scripts that pull public SEC filings into `data/samples/` for pattern hunting.

| Script / notebook | What it does |
|-------------------|----------------|
| `download_samples.py` | Diverse TO / 14D9 / OTP / 8-K (+ exhibits) → PDF + HTML under `data/samples/` |
| `collect_merger_candidates.py` | All-filer SEC merger-keyword search → local source HTML, parsed text, manifest, ZIP |
| `fetch_company_8k.py` | One company’s 8-K items and detected press releases via EdgarTools |
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

The January–September 2026 merger-candidate download is stored separately at `data/mergers/sec_2026/`. This sampler reads `data/processed/documents.parquet`, which currently covers 2020–2025, so running it does not add 2026 filings.

## January–September 2026 merger-candidate sample

The general `download_samples.py` command still uses the 2020–2025 corpus. To make a separate date-matched sample from the 2026 merger review queue, run from the repo root:

```bash
python dataloader/download_merger_samples_2026.py --start 2026-01-01 --end 2026-09-30 --per-month 3
```

This saved 27 original SEC HTML files and PDFs under `data/samples/mergers_2026/`, with three filing dates in each month. The index is `data/samples/manifest_2026_mergers.csv`; `data/samples/mergers_2026/merger_screen.csv` records a preliminary phrase check. These are merger candidates, not independently confirmed merger events. The older `data/samples/manifest.csv` remains the 2020–2025 general sample.

## Rebuild the merger-candidate dataset

The GitHub-ready collection entry point is [`collect_merger_candidates.py`](collect_merger_candidates.py). It does not require a pre-existing local manifest. Install `requirements-merger-download.txt`, set your own `EDGAR_IDENTITY`, and follow [`docs/merger-data-download.md`](../docs/merger-data-download.md) for a bounded run, full run, outputs, and review-queue creation. Downloaded data remains gitignored.

For a specific company’s 8-K source evidence, run:

```bash
python dataloader/fetch_company_8k.py --company AAPL --start 2025-01-01 --end 2025-12-31 --out data/company_8k/apple_2025
```

Set `EDGAR_IDENTITY` to your own name and contact email first. This fetcher saves item text, detected press-release text, an inventory, and retrieval summary; it does not classify corporate actions.
