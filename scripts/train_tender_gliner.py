#!/usr/bin/env python3
"""Fine-tune GLiNER on tender span JSONL (gate: core F1 < 0.40 after zero-shot).

Reads data/gliner_ft/tender_spans.jsonl; writes models/tender_gliner/.
Logs params/metrics/artifacts to MLflow experiment ``tender_gliner_train``.

Use --train-all to train on every span (for promoting as default).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        rows.append(json.loads(ln))
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fine-tune GLiNER on tender spans")
    p.add_argument("--data", type=Path, default=ROOT / "data/gliner_ft/tender_spans.jsonl")
    p.add_argument("--holdout", type=Path, default=ROOT / "outputs/tender_eval/experiments/holdout_accessions.txt")
    p.add_argument("--base-model", default="urchade/gliner_large-v2.1")
    p.add_argument("--out", type=Path, default=ROOT / "models/tender_gliner")
    p.add_argument("--max-steps", type=int, default=500)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--lr", type=float, default=5e-6)
    p.add_argument("--train-all", action="store_true", help="Train on all spans (no holdout split)")
    p.add_argument("--use-cpu", action="store_true")
    p.add_argument("--run-name", default=None, help="MLflow run name (default: derived from out dir)")
    p.add_argument("--note", default="", help="Free-text note tagged on the MLflow run")
    args = p.parse_args(argv)

    if not args.data.exists():
        print(f"missing spans: {args.data} — run scripts/build_tender_gliner_spans.py first", file=sys.stderr)
        return 1

    rows = load_jsonl(args.data)
    holdout: set[str] = set()
    if args.holdout.exists() and not args.train_all:
        holdout = {ln.strip() for ln in args.holdout.read_text().splitlines() if ln.strip()}

    if args.train_all:
        train_raw = rows
        # small monitor split from end (still in train set for production weights)
        eval_raw = rows[-max(1, len(rows) // 10) :]
    else:
        train_raw = [r for r in rows if (r.get("accession") or "") not in holdout]
        eval_raw = [r for r in rows if (r.get("accession") or "") in holdout]
        if not train_raw:
            train_raw = rows
        if not eval_raw:
            eval_raw = train_raw[: max(1, len(train_raw) // 5)] or train_raw

    def slim(xs: list[dict]) -> list[dict]:
        return [{"tokenized_text": x["tokenized_text"], "ner": x["ner"]} for x in xs]

    train_data = slim(train_raw)
    eval_data = slim(eval_raw)

    n_spans_train = sum(len(x.get("ner") or []) for x in train_raw)
    n_spans_eval = sum(len(x.get("ner") or []) for x in eval_raw)
    run_name = args.run_name or f"{args.out.name}_{args.base_model.split('/')[-1]}_{args.max_steps}steps"

    from src.evaluation.mlflow_tracking import EXPERIMENT_TRAIN, start_run

    params = {
        "base_model": args.base_model,
        "data": str(args.data),
        "out": str(args.out),
        "max_steps": args.max_steps,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "train_all": args.train_all,
        "use_cpu": args.use_cpu,
        "n_train_examples": len(train_data),
        "n_eval_examples": len(eval_data),
        "n_train_spans": n_spans_train,
        "n_eval_spans": n_spans_eval,
        "n_holdout_accessions": len(holdout),
    }
    print(json.dumps({"base": args.base_model, "n_train": len(train_data), "n_eval": len(eval_data),
                      "train_all": args.train_all, "max_steps": args.max_steps, "out": str(args.out),
                      "mlflow_experiment": EXPERIMENT_TRAIN, "mlflow_run_name": run_name}, indent=2))

    from gliner import GLiNER

    t0 = time.time()
    with start_run(
        experiment=EXPERIMENT_TRAIN,
        run_name=run_name,
        params=params,
        tags={
            "stage": "train",
            "note": args.note,
            "out_dir": str(args.out),
        },
        description=args.note or f"Fine-tune {args.base_model}",
    ) as run:
        model = GLiNER.from_pretrained(args.base_model)
        args.out.mkdir(parents=True, exist_ok=True)
        train_out = model.train_model(
            train_dataset=train_data,
            eval_dataset=eval_data,
            output_dir=str(args.out),
            learning_rate=args.lr,
            weight_decay=0.01,
            others_lr=1e-5,
            others_weight_decay=0.01,
            lr_scheduler_type="linear",
            warmup_ratio=0.1,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            focal_loss_alpha=0.75,
            focal_loss_gamma=2,
            max_steps=args.max_steps,
            save_steps=max(100, args.max_steps // 2),
            save_total_limit=2,
            logging_steps=25,
            dataloader_num_workers=0,
            use_cpu=args.use_cpu,
            report_to="none",
        )
        model.save_pretrained(str(args.out / "final"))
        elapsed = time.time() - t0

        metrics: dict = {"train_runtime_sec": elapsed}
        # HuggingFace Trainer returns TrainOutput-like objects
        if train_out is not None:
            for attr in ("global_step", "training_loss"):
                if hasattr(train_out, attr):
                    metrics[attr] = getattr(train_out, attr)
            if isinstance(train_out, dict):
                metrics.update({k: v for k, v in train_out.items() if isinstance(v, (int, float))})

        meta = {
            "base_model": args.base_model,
            "n_train": len(train_data),
            "n_eval": len(eval_data),
            "n_train_spans": n_spans_train,
            "n_eval_spans": n_spans_eval,
            "train_all": args.train_all,
            "max_steps": args.max_steps,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "data": str(args.data),
            "mlflow_run_id": run.run_id,
            "mlflow_run_name": run_name,
            **metrics,
        }
        (args.out / "train_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        run.log_metrics(metrics)
        run.log_artifact(args.out / "train_meta.json")
        run.log_artifact(args.out / "final", artifact_path="model_final")
        print(json.dumps({"saved": str(args.out / "final"), **meta}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
