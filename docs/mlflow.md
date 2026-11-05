# MLflow experiment tracking

Local store (default): SQLite at `outputs/mlflow.db`, artifacts under `outputs/mlartifacts/`.

Experiments:

| Experiment | What |
|---|---|
| `tender_gliner_train` | Fine-tunes (`scripts/train_tender_gliner.py`) |
| `tender_eval` | Pipeline vs GT (`scripts/eval_tender.py --run-id …`) |

## Quick start

```bash
# install (once)
.venv/bin/pip install 'mlflow>=2.14'

# import past ledger / train_meta runs
.venv/bin/python scripts/mlflow_backfill.py

# UI
.venv/bin/python scripts/mlflow_ui.py
# → http://127.0.0.1:5000
```

## Automatic logging

**Train** — every `train_tender_gliner.py` run logs params (model, steps, lr, span counts), metrics (`training_loss`, runtime), and artifacts (`train_meta.json`, `model_final/`).

```bash
.venv/bin/python scripts/train_tender_gliner.py \
  --base-model urchade/gliner_small-v2.1 \
  --out models/tender_gliner_small \
  --run-name small_passage_500 \
  --note "passage spans, MPS"
```

**Eval** — `record_experiment()` (triggered by `--run-id`) mirrors the CSV ledger into MLflow and attaches `summary.json`, `per_field.csv`, prediction CSVs.

```bash
.venv/bin/python scripts/eval_tender.py --fields core --holdout \
  --run-preprocess --force --reset-eval \
  --gliner-model models/tender_gliner_small/final \
  --run-id small_passage_holdout \
  --experiment-note "passage-FT small holdout" \
  --parent-run-id finetune_holdout_200
```

## Config

| Env | Default | Meaning |
|---|---|---|
| `MLFLOW_TRACKING_URI` | `sqlite:///…/outputs/mlflow.db` | Store / server URI |
| `MLFLOW_ARTIFACT_ROOT` | `outputs/mlartifacts` | Local artifact directory |
| `MLFLOW_ENABLED` | `1` | Set `0` to disable logging |

Point at a remote server later without code changes:

```bash
export MLFLOW_TRACKING_URI=http://mlflow.example:5000
```

## API (for notebooks / new scripts)

```python
from src.evaluation.mlflow_tracking import EXPERIMENT_TRAIN, start_run

with start_run(
    experiment=EXPERIMENT_TRAIN,
    run_name="my_probe",
    params={"threshold": 0.35},
    tags={"note": "adhoc"},
) as run:
    run.log_metrics({"micro_f1": 0.42})
    run.log_artifact("outputs/tender_eval/summary.json")
```

## Backfill again

```bash
.venv/bin/python scripts/mlflow_backfill.py          # skip existing names
.venv/bin/python scripts/mlflow_backfill.py --force # re-log everything
```
