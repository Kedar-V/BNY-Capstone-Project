# Get the January–September 2026 SEC merger dataset

This guide builds a **merger-candidate filing dataset** from public SEC EDGAR documents. The project uses EdgarTools to search SEC filings and downloads the selected documents from their `sec.gov` URLs. It then screens the downloaded text for language about a merger agreement being signed, completed, or terminated. A match is **not** a verified merger, a unique deal, or proof that the deal closed.

The existing local `data/mergers/sec_2026/` collection contains 2,787 downloaded filings dated January 1–September 30, 2026. Screening selected 691 candidates (572 high-priority and 119 medium-priority) with filing dates January 5–September 30. These counts describe that particular partial download; a new SEC search can return different counts. January–March each have 100 downloaded filings in the local collection, so it is not a complete census. All rows currently have blank human review labels.

## Requirements

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r dataloader/requirements-merger-download.txt
export EDGAR_IDENTITY="Your Name your.email@example.com"
```

Use your own name and email for `EDGAR_IDENTITY`; do not put them in Git. Follow the [SEC fair-access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions). These commands require internet access and enough disk space for the downloaded HTML, parsed JSON, and ZIP.

## Build a new 2026 collection

For a small test, replace `--all` below with `--per-month 3`. The default is also only **three filings per month**, so use `--all` when you want every eligible search result rather than a small sample.

```bash
python dataloader/collect_merger_candidates.py \
  --start 2026-01-01 --end 2026-09-30 --all \
  --out data/mergers/sec_2026_rebuild
```

The search term is `merger`. The default forms are 8-K, 8-K/A, 6-K, 6-K/A, DEFM14A, and DEFS14A. The collector selects one primary or EX-99 document per filing accession, saves its original HTML under `raw/`, and writes parsed text under `documents/`. The output also has `manifest.csv`, `failures.csv`, `summary.json`, and `candidate_documents.zip`. Inspect `failures.csv` and the monthly counts before analysis. Search and downloads can take substantial time; rerunning with the same options and output directory reuses completed work.

## Screen and separate the candidate filings

Create the review queue, then export only filings whose saved text matched a merger-event pattern:

```bash
python merger_research/scripts/build_mergers_only.py screen \
  --archive data/mergers/sec_2026_rebuild/candidate_documents.zip \
  --manifest data/mergers/sec_2026_rebuild/manifest.csv \
  --queue data/mergers/sec_2026_rebuild/review_queue.csv

python dataloader/export_screened_merger_candidates.py \
  --archive data/mergers/sec_2026_rebuild/candidate_documents.zip \
  --manifest data/mergers/sec_2026_rebuild/manifest.csv \
  --queue data/mergers/sec_2026_rebuild/review_queue.csv \
  --output data/mergers/sec_2026_rebuild/screened_merger_candidates.zip
```

The result is `screened_merger_candidates.zip`, `screened_merger_candidates.manifest.csv`, and `screened_merger_candidates.summary.json`. The ZIP contains the selected filing JSON files and an internal `screened_manifest.csv`. Each manifest row includes an SEC source URL, filing date, form, screening evidence, and document hash. The exporter checks that the queue matches the source manifest and that the saved text hashes have not changed.

If you already have this project's local 2026 archive and review queue, run `python dataloader/export_screened_merger_candidates.py` with no arguments. Its default output is `data/mergers/sec_2026/screened_merger_candidates_2026_Jan_Sep.zip`, with a companion `.manifest.csv` and `.summary.json`.

## Obtain confirmed merger filings

The screened set may include announcements of proposed, terminated, historical, or third-party mergers; it can also miss mergers. To build a validated filing-level set, review the source text for each candidate and record `review_label`, `reviewer`, `reviewed_at`, and an exact `confirmed_evidence` quote in the review queue. Follow [the reviewed merger workflow](../merger_research/README.md#build-a-reviewed-mergers-only-filing-set). The `export` command there includes only rows explicitly labeled `merger` and checks the quote against the archived text. Multiple filings may still describe the same deal, so deduplicate and link deals before using this as a deal-level dataset.

The local `data/` directory is gitignored: GitHub contains the code and this guide, **not** the SEC filing ZIPs. Anyone cloning the repository must run the collection commands or obtain the archives separately.
