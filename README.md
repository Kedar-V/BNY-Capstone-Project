# BNY Corporate-Actions Capstone — Public Document EDA

Exploratory analysis of **public SEC filings** against the **BNY client-notification schema**, focused on:

**Tender offers · Exchange offers · Rights issues · Mergers · Conversions**

Current downloaded corpus is **tender-centric** (Schedule TO + SC 14D9). Other types are defined in `src/eda/event_taxonomy.py` with explicit corpus-gap tracking.

## Question

How well can public corporate-action documents populate the fields required in a real BNY client notification — enough to power a **versioned event datastore → notification draft** MVP?

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build public corpus from SEC EFTS (requires network + descriptive User-Agent)
python scripts/build_corpus.py --start 2020-01-01 --end 2025-12-31 --sample-per-form 6

# Run analyses and write outputs/ + MVP figures
python scripts/run_eda.py

# Open the notebook
jupyter notebook notebooks/tender_offer_eda.ipynb
```

## Postgres event datastore

```bash
docker compose up -d
pip install -r requirements.txt
python scripts/init_db.py
```

See [`db/README.md`](db/README.md) for schema (`events`, `documents`, `event_versions`, `event_field_values`, path-specific `*_concise_*` Concise Rep tables).

## Preprocess pipeline (TO-first Concise Rep)

Design: [`docs/lld-preprocess-pipeline.md`](docs/lld-preprocess-pipeline.md) · Example I/O: [`docs/preprocess-stage-io-example.md`](docs/preprocess-stage-io-example.md)

```bash
# Inventory preferred TO events into cohorts (gold / needs_otp_resolve / incomplete)
python scripts/run_preprocess.py --path tender --stage inventory --limit 20

# Full pipe on gold cohort (real GLiNER; skip DB load if Postgres not up)
python scripts/run_preprocess.py --path tender --stage all --cohort gold --limit 3 \
  --skip-db --viz

# Single event / stage
python scripts/run_preprocess.py --path tender --stage gliner --event-id 005-02933
```

Inspect outputs in [`notebooks/preprocess_stage_inspect.ipynb`](notebooks/preprocess_stage_inspect.ipynb).

Stages are independent (`--stage inventory|download|cleanup|segment|gliner|assemble|load_db`).

## Deliverables

| Path | Description |
|------|-------------|
| `notebooks/tender_offer_eda.ipynb` | MVP-oriented EDA (datastore → notification) |
| `src/eda/event_taxonomy.py` | Five event types + SEC form map + gaps |
| `outputs/mvp_corpus_gaps.csv` | Which types are collected vs missing |
| `outputs/datastore_field_catalog.csv` | Field roles for the event store |
| `outputs/mvp_events.csv` | Tender v1 MVP event pool |
| `outputs/schema_coverage.csv` | Field coverage matrix |
| `EDA_SUMMARY.md` | Findings + Implications for MVP Design |
| `outputs/figures/mvp_*.png` | Decision-relevant plots only |

## Evidence discipline

- **Observed** vs **inferred** vs **internal** vs **corpus gap** are labeled
- Missing values are not fabricated for uncollected event types
- `notification_type` is kept separate from `corporate_action_type`
- Splits must be at **event_id**, never document-level
