#!/usr/bin/env python3
"""Import existing tender eval/train artifacts into MLflow.

Sources:
  - outputs/tender_eval/experiments/ledger.csv (+ runs/*/meta.json, summary.json)
  - models/*/train_meta.json

Idempotent by run name: skips if an MLflow run with the same name already exists
in the target experiment (unless --force).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.mlflow_tracking import (
    EXPERIMENT_EVAL,
    EXPERIMENT_TRAIN,
    configure,
    eval_metrics_from_result,
    start_run,
    tracking_uri,
)


def _existing_run_names(experiment: str) -> set[str]:
    import mlflow
    from mlflow.tracking import MlflowClient

    configure(experiment=experiment)
    client = MlflowClient()
    exp = client.get_experiment_by_name(experiment)
    if exp is None:
        return set()
    names: set[str] = set()
    for run in client.search_runs([exp.experiment_id], max_results=5000):
        name = run.data.tags.get("mlflow.runName") or run.info.run_name
        if name:
            names.add(name)
    return names


def backfill_eval(eval_root: Path, *, force: bool) -> dict:
    ledger = eval_root / "experiments" / "ledger.csv"
    runs_dir = eval_root / "experiments" / "runs"
    existing = set() if force else _existing_run_names(EXPERIMENT_EVAL)
    n_ok = n_skip = n_fail = 0

    rows: list[dict] = []
    if ledger.exists():
        with ledger.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    # Also pick up run dirs not in ledger (e.g. nested --out mistakes).
    known = {r.get("run_id") for r in rows}
    if runs_dir.exists():
        for d in sorted(runs_dir.iterdir()):
            if not d.is_dir() or d.name in known:
                continue
            meta_path = d / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                rows.append(
                    {
                        "run_id": meta.get("run_id") or d.name,
                        "change_summary": meta.get("change_summary") or d.name,
                        "parent_run_id": meta.get("parent_run_id") or "",
                        "keep": meta.get("keep"),
                        "git_commit": meta.get("git_commit") or "",
                        **(meta.get("config") or {}),
                    }
                )

    for row in rows:
        run_id = (row.get("run_id") or "").strip()
        if not run_id:
            continue
        if run_id in existing and not force:
            n_skip += 1
            continue

        run_dir = runs_dir / run_id
        if run_id.startswith("baseline"):
            run_dir = eval_root / "experiments" / "baseline"

        summary: dict = {}
        meta: dict = {}
        if (run_dir / "summary.json").exists():
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        if (run_dir / "meta.json").exists():
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

        # Prefer summary; fall back to ledger micro_* columns.
        if not summary.get("micro"):
            summary = {
                "micro": {
                    "f1": row.get("micro_f1"),
                    "precision": row.get("micro_precision"),
                    "recall": row.get("micro_recall"),
                    "accuracy": row.get("micro_accuracy"),
                    "accuracy_when_gt": row.get("micro_accuracy_when_gt"),
                },
                "per_field": {},
                "n_gt_accessions": row.get("n_accessions"),
            }
            for f in (
                "offer_price",
                "bidder",
                "subject_company",
                "security_description",
                "expiration_date",
            ):
                v = row.get(f"f1_{f}")
                if v not in (None, ""):
                    summary["per_field"][f] = {"f1": v}

        config = meta.get("config") or {
            "gliner_threshold": row.get("gliner_threshold"),
            "gliner_model": row.get("gliner_model"),
            "label_set": row.get("label_set"),
            "max_windows": row.get("max_windows"),
            "fields": row.get("fields"),
            "scope": row.get("scope"),
            "n_accessions": row.get("n_accessions"),
        }
        deltas = meta.get("deltas") or {}
        for k in list(row.keys()):
            if k.startswith("delta_") and row.get(k) not in (None, ""):
                deltas.setdefault(k.removeprefix("delta_"), row.get(k))

        try:
            with start_run(
                experiment=EXPERIMENT_EVAL,
                run_name=run_id,
                params=config,
                tags={
                    "stage": "eval",
                    "run_id": run_id,
                    "parent_run_id": row.get("parent_run_id") or meta.get("parent_run_id") or "",
                    "change_summary": row.get("change_summary") or meta.get("change_summary") or "",
                    "keep": row.get("keep") if row.get("keep") is not None else meta.get("keep"),
                    "git_commit": row.get("git_commit") or meta.get("git_commit") or "",
                    "source": "backfill",
                },
                description=row.get("change_summary") or run_id,
            ) as run:
                metrics = eval_metrics_from_result(summary)
                for k, v in deltas.items():
                    try:
                        metrics[f"delta.{k}"] = float(v)
                    except (TypeError, ValueError):
                        pass
                run.log_metrics(metrics)
                if run_dir.exists():
                    for name in (
                        "summary.json",
                        "meta.json",
                        "per_field.csv",
                        "pipeline_predictions.csv",
                        "pipeline_vs_gt.csv",
                    ):
                        path = run_dir / name
                        if path.exists():
                            run.log_artifact(path)
            existing.add(run_id)
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL eval {run_id}: {exc}", file=sys.stderr)
            n_fail += 1

    return {"eval_ok": n_ok, "eval_skip": n_skip, "eval_fail": n_fail}


def backfill_train(models_root: Path, *, force: bool) -> dict:
    existing = set() if force else _existing_run_names(EXPERIMENT_TRAIN)
    n_ok = n_skip = n_fail = 0
    if not models_root.exists():
        return {"train_ok": 0, "train_skip": 0, "train_fail": 0}

    for meta_path in sorted(models_root.glob("*/train_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        run_name = meta.get("mlflow_run_name") or f"{meta_path.parent.name}_backfill"
        if run_name in existing and not force:
            n_skip += 1
            continue
        try:
            with start_run(
                experiment=EXPERIMENT_TRAIN,
                run_name=run_name,
                params={k: v for k, v in meta.items() if k not in {"mlflow_run_id"}},
                tags={"stage": "train", "source": "backfill", "out_dir": str(meta_path.parent)},
                description=f"Backfill {meta_path.parent.name}",
            ) as run:
                metrics = {
                    k: v
                    for k, v in meta.items()
                    if isinstance(v, (int, float)) and k not in {"n_train", "n_eval"}
                }
                # always log counts as metrics too
                for k in ("n_train", "n_eval", "n_train_spans", "n_eval_spans", "max_steps", "train_runtime_sec", "training_loss"):
                    if k in meta and meta[k] is not None:
                        try:
                            metrics[k] = float(meta[k])
                        except (TypeError, ValueError):
                            pass
                run.log_metrics(metrics)
                run.log_artifact(meta_path)
                final = meta_path.parent / "final"
                if final.exists():
                    run.log_artifact(final, artifact_path="model_final")
            existing.add(run_name)
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL train {run_name}: {exc}", file=sys.stderr)
            n_fail += 1
    return {"train_ok": n_ok, "train_skip": n_skip, "train_fail": n_fail}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill MLflow from ledger + train_meta")
    p.add_argument("--eval-root", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--models-root", type=Path, default=ROOT / "models")
    p.add_argument("--force", action="store_true", help="Re-log even if run name exists")
    p.add_argument("--eval-only", action="store_true")
    p.add_argument("--train-only", action="store_true")
    args = p.parse_args(argv)

    configure()
    print(json.dumps({"tracking_uri": tracking_uri()}, indent=2))
    out: dict = {}
    if not args.train_only:
        out.update(backfill_eval(args.eval_root, force=args.force))
    if not args.eval_only:
        out.update(backfill_train(args.models_root, force=args.force))
    print(json.dumps(out, indent=2))
    return 0 if out.get("eval_fail", 0) == 0 and out.get("train_fail", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
