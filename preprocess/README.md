# Preprocess demos

Notebooks that show how extraction (GLiNER) works on the **sample docs** from `dataloader/`.

| Notebook | What it does |
|----------|----------------|
| `run_gliner_on_samples.ipynb` | Load HTML from `data/samples/`, run GLiNER, tune folder/labels/threshold for different use cases |

## Tuning (in the notebook)

Open `run_gliner_on_samples.ipynb` and use the **Tuning guide** section:

1. **`FOLDER` / filters** — which sample type (OTP, 14D9, 8-K, exhibits, …)
2. **`USE_CASE` / `LABELS`** — tender full vs cover vs 8-K vs custom zero-shot labels
3. **`THRESHOLD` / `MAX_WINDOWS` / `MAX_CHARS`** — precision vs recall vs how deep into the doc

Full production pipeline (inventory → download → cleanup → segment → gliner → assemble):

```bash
python scripts/run_preprocess.py --path tender --stage gliner --cohort gold --limit 3
```

Design: [`docs/lld-preprocess-pipeline.md`](../docs/lld-preprocess-pipeline.md) · walkthrough: [`notebooks/preprocess_stage_inspect.ipynb`](../notebooks/preprocess_stage_inspect.ipynb)

## Quick start

```bash
# samples must exist
python dataloader/download_samples.py

jupyter notebook preprocess/run_gliner_on_samples.ipynb
```

First run downloads `urchade/gliner_medium-v2.1` (needs `torch` + `gliner` from `requirements.txt`).
