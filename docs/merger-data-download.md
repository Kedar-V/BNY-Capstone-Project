# Rebuild SEC merger-candidate data

This repository publishes the collection and review code. Downloaded SEC documents stay under the gitignored `data/` directory. The collector uses EdgarTools to search SEC EDGAR and the project's SEC client to save the original source HTML and extracted text. A filing date is **not** necessarily the date a merger was announced or completed. Keyword hits are candidates, not confirmed merger events or distinct deals.

From the repository root, create a Python environment and install the small download dependency set:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r dataloader/requirements-merger-download.txt
export EDGAR_IDENTITY="Your Name your.email@example.com"
```

Set `EDGAR_IDENTITY` to your own contact information. Do not commit it to the repository. The SEC requires an identifying User-Agent and limits automated access; the collector and EdgarTools apply request controls. [SEC fair-access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions).

Start with a bounded January–September 2026 run:

```bash
python dataloader/collect_merger_candidates.py \
  --start 2026-01-01 --end 2026-09-30 \
  --per-month 3 --out data/mergers/sec_2026_rebuild
```

`--per-month` caps selected filing documents **per calendar month**, after a merger-keyword search of 8-K, 8-K/A, 6-K, 6-K/A, DEFM14A, and DEFS14A. Search results are ranked by SEC relevance score and one primary or EX-99 document is selected per filing accession. This is a reproducible screening sample, not a random or complete census. Use `--all` only when you intend to download every eligible result; it can take substantial time and disk space. Override the form list with `--forms`, for example `--forms 8-K,DEFM14A,S-4,425`.

The chosen output directory contains:

| File | Meaning |
| --- | --- |
| `search_YYYY-MM.json` | Resumable monthly search hits |
| `raw/*.html` | Original SEC response bytes |
| `documents/*.json` | Metadata, direct SEC URL, parsed text, and preliminary evidence |
| `manifest.csv` | One row per successfully saved filing document |
| `failures.csv` | Retrieval failures to retry or inspect |
| `candidate_documents.zip` | Parsed JSON files and manifests for portable analysis |
| `summary.json` | Search and download counts |

The collector can be rerun with the same arguments and output directory. Completed monthly searches and successful document downloads are reused. If the search forms or query scope change, use a new output directory so cached search results are not mixed.

To generate a review queue from the ZIP, run:

```bash
python merger_research/scripts/build_mergers_only.py screen \
  --archive data/mergers/sec_2026_rebuild/candidate_documents.zip \
  --manifest data/mergers/sec_2026_rebuild/manifest.csv \
  --queue data/mergers/sec_2026_rebuild/review_queue.csv
```

The queue ranks evidence for human review. Its high-priority rows are **not** confirmed mergers. A mergers-only export requires reviewed labels and an exact supporting quote; see [the review workflow](../merger_research/README.md#build-a-reviewed-mergers-only-filing-set).

To package only the filings that matched merger-event language in the existing January–September 2026 review queue, run:

```bash
python dataloader/export_screened_merger_candidates.py
```

This writes `data/mergers/sec_2026/screened_merger_candidates_2026_Jan_Sep.zip`, a standalone `.manifest.csv`, and a `.summary.json`. The ZIP contains the selected source JSON files and its own manifest. The current local run selected 691 of 2,787 downloaded filings (572 high priority, 119 medium). **This is a screened candidate dataset, not a confirmed mergers-only dataset**: merger language can describe proposed, terminated, historical, or third-party transactions, and a filing can mention more than one deal. It also does not recover mergers missed by the original keyword search or screening rules. Review and label the filings before using them as ground truth.

The existing `dataloader/download_samples.py` uses a separate 2020–2025 corpus. After generating the 2026 review queue, `dataloader/download_merger_samples_2026.py --queue data/mergers/sec_2026_rebuild/review_queue.csv` can save a small HTML/PDF browsing sample. It requires Google Chrome for PDF rendering.

## What to commit to GitHub

Commit the collector, its dependency file, this guide, and the merger-research code and reports that its README links to. The root `.gitignore` keeps downloaded filings, PDFs, generated review queues, and other large local caches out of the repository. The command below also stages the research notebook, presentations, and small results; omit those paths if they are not part of the intended public project.

```bash
git add .gitignore README.md dataloader/README.md \
  dataloader/collect_merger_candidates.py \
  dataloader/requirements-merger-download.txt \
  dataloader/download_merger_samples_2026.py \
  dataloader/fetch_company_8k.py \
  dataloader/export_screened_merger_candidates.py \
  dataloader/download_samples.py \
  docs/merger-data-download.md \
  merger_research/
git diff --cached --stat
```

This stages the reproducible pipeline and documentation, not the local SEC archive. Review `git diff --cached` before committing. The 2026 sampler is optional for users who only need parsed text; it uses Google Chrome to create PDFs.

The screenshot’s `run_bny_merger_pilot.py` is superseded by `merger_research/scripts/import_sec_merger_2025.py`, which has project-relative defaults and evidence-offset checks. The Apple-specific `export_actions.py` asserts exactly nine records and is not a general merger collector. The reusable part is `dataloader/fetch_company_8k.py`. The small 2025 filer sample and its limitations are ready to stage under `merger_research/examples/`.
