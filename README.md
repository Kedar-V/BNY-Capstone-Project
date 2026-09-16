# BNY Corporate-Actions Capstone — Public Document EDA

Exploratory analysis of **public SEC EDGAR tender-offer filings** against the **BNY client-notification schema**.

## Question

How well can public corporate-action documents populate the fields required in a real BNY client notification?

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build public corpus from SEC EFTS (requires network + descriptive User-Agent)
python scripts/build_corpus.py --start 2020-01-01 --end 2025-12-31 --sample-per-form 6

# Run analyses and write outputs/
python scripts/run_eda.py

# Open the notebook
jupyter notebook notebooks/eda.ipynb
```

## Deliverables

| Path | Description |
|------|-------------|
| `notebooks/eda.ipynb` | Main EDA notebook |
| `src/eda/` | Reusable analysis functions + BNY schema |
| `outputs/schema_coverage.csv` | Field coverage matrix |
| `outputs/event_type_coverage.csv` | corporate_action_type × field coverage |
| `outputs/data_quality_report.csv` | Quality / missingness / leakage |
| `EDA_SUMMARY.md` | Concise findings + **Implications for MVP Design** |

## Evidence discipline

- **Observed** vs **inferred** vs **internal** are labeled in all coverage tables
- Missing values are not fabricated
- `notification_type` is kept separate from `corporate_action_type`
- Splits must be at **event_id** (SEC file number), never document-level
