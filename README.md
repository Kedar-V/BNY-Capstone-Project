# BNY Corporate-Actions Capstone — Public Document EDA

Exploratory analysis of **public SEC filings** against the **BNY client-notification schema**, focused on:

**Tender offers · Exchange offers · Rights issues · Mergers · Conversions**

## Repo map

| Path | Role |
|------|------|
| `dataloader/` | Sample SEC downloads → `data/samples/` ([README](dataloader/README.md)) |
| `preprocess/` | GLiNER-on-samples demo notebook ([README](preprocess/README.md)) |
| `scripts/` | Corpus build, EDA run, preprocess CLI, DB init |
| `src/eda/` | EFTS client, corpus, coverage / MVP analysis |
| `src/preprocess/` | TO Concise Rep pipeline (inventory → download → …) |
| `notebooks/` | EDA / inspect notebooks (analysis, not download) |
| `docs/` | Schema, preprocess LLD, ROI notes |
| `data/` | Local artifacts (**gitignored**) |
| `db/` | Postgres schema |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build public corpus from SEC EFTS
python scripts/build_corpus.py --start 2020-01-01 --end 2025-12-31 --sample-per-form 6

# Pattern-hunting sample PDFs + HTML (TO / 14D9 / OTP / 8-K + exhibits)
python dataloader/download_samples.py

# Run analyses → outputs/ + MVP figures
python scripts/run_eda.py

# Open an analysis notebook
jupyter notebook notebooks/tender_offer_eda.ipynb
```

SEC User-Agent is auto-generated per run (see [`dataloader/README.md`](dataloader/README.md)).

## 2025 SEC merger candidate data

A local 8,638-document SEC merger-candidate archive, manifest, and 28-filer sample are stored under the gitignored `data/mergers/sec_2025/`. See [`merger_research/README.md`](merger_research/README.md) for the offline importer, output, and validation limits.

The [mergers-only review workflow](merger_research/README.md#build-a-reviewed-mergers-only-filing-set) screens all archived documents and exports only filings confirmed by review.


The partial January–September 2026 merger-candidate archive is in `data/mergers/sec_2026/` (2,787 downloaded filing documents). Its `coverage_summary.json` gives monthly counts; `review_queue.csv` contains unreviewed evidence-ranked candidates. This archive is separate from `dataloader/download_samples.py`, whose source corpus currently ends in 2025.

## Rebuild SEC merger-candidate data

Use [`dataloader/collect_merger_candidates.py`](dataloader/collect_merger_candidates.py) to search EDGAR by filing date and save source HTML, parsed text, a manifest, and a portable ZIP under gitignored `data/`. Start with the [download and review guide](docs/merger-data-download.md); results are unreviewed candidates, not confirmed merger deals.

## Postgres event datastore

```bash
docker compose up -d
python scripts/init_db.py
```

See [`db/README.md`](db/README.md).

## Preprocess pipeline (TO-first Concise Rep)

Design: [`docs/lld-preprocess-pipeline.md`](docs/lld-preprocess-pipeline.md)

```bash
python scripts/run_preprocess.py --path tender --stage inventory --limit 20
python scripts/run_preprocess.py --path tender --stage all --cohort gold --limit 3 --skip-db --viz
```

Inspect: [`notebooks/preprocess_stage_inspect.ipynb`](notebooks/preprocess_stage_inspect.ipynb).

## Deliverables

| Path | Description |
|------|-------------|
| `notebooks/tender_offer_eda.ipynb` | MVP-oriented EDA |
| `src/eda/event_taxonomy.py` | Five event types + SEC form map + gaps |
| `outputs/` | Coverage CSVs + MVP figures |
| `EDA_SUMMARY.md` | Findings + MVP implications |

## Evidence discipline

- **Observed** vs **inferred** vs **internal** vs **corpus gap** are labeled
- Missing values are not fabricated for uncollected event types
- `notification_type` is kept separate from `corporate_action_type`
- Splits must be at **event_id**, never document-level
