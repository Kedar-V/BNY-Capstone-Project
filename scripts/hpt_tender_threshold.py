#!/usr/bin/env python3
"""Sweep GLiNER confidence threshold on a fixed fine-tuned model (holdout).

Re-runs only ``gliner`` + ``assemble`` per threshold, scores core GT, logs each
trial to MLflow experiment ``tender_eval``.

Example:
  python scripts/hpt_tender_threshold.py \\
      --gliner-model models/tender_gliner_medium/final \\
      --thresholds 0.25,0.30,0.35,0.40,0.45,0.50,0.55
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import ensure_holdout, record_experiment
from src.evaluation.mlflow_tracking import EXPERIMENT_EVAL, start_run, eval_metrics_from_result
from src.evaluation.tender import (
    CORE_GT_FIELDS,
    evaluate_tender,
    gt_event_ids_from_corpus,
    load_gt,
    load_preds,
    write_report,
)
from src.preprocess.orchestrator import run_pipeline
from src.preprocess.parallel import configure_torch_threads, default_workers, pick_torch_device
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="HPT: GLiNER threshold sweep on holdout")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--preprocess-root", type=Path, default=DEFAULT_PREPROCESS_ROOT)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--gliner-model", type=Path, default=ROOT / "models/tender_gliner_medium/final")
    p.add_argument("--thresholds", default="0.25,0.30,0.35,0.40,0.45,0.50,0.55")
    p.add_argument("--device", default="auto")
    p.add_argument("--gliner-batch-size", type=int, default=8)
    p.add_argument("--gliner-max-windows", type=int, default=8)
    p.add_argument("--run-prefix", default="hpt_medium_passage_t")
    p.add_argument("--parent-run-id", default="medium_passage_holdout")
    p.add_argument("--workers", type=int, default=None)
    args = p.parse_args(argv)

    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    workers = default_workers(args.workers)
    device = pick_torch_device(args.device)
    configure_torch_threads(workers)

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    accessions = ensure_holdout(args.out, accessions, n=20)
    acc_set = set(accessions)
    gt_rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in acc_set]
    acc_to_eid = gt_event_ids_from_corpus(acc_set, args.documents_parquet)
    event_ids = sorted(set(acc_to_eid.values()))
    preferred = {eid: acc for acc, eid in acc_to_eid.items()}

    print(
        json.dumps(
            {
                "model": str(args.gliner_model),
                "thresholds": thresholds,
                "n_holdout_accessions": len(accessions),
                "n_events": len(event_ids),
                "device": device,
            },
            indent=2,
        )
    )

    leaderboard: list[dict] = []
    best: dict | None = None

    for t in thresholds:
        run_id = f"{args.run_prefix}{t:.2f}".replace(".", "p")
        print(f"\n=== threshold={t} run_id={run_id} ===")
        extra = {
            "workers": workers,
            "gliner_device": device,
            "gliner_batch_size": args.gliner_batch_size,
            "gliner_threshold": t,
            "gliner_max_windows": args.gliner_max_windows,
            "gliner_model": str(args.gliner_model),
            "preferred_accessions": preferred,
            "pending_only": False,
        }
        results = run_pipeline(
            path_name="tender",
            preprocess_root=args.preprocess_root,
            event_ids=event_ids,
            force=True,
            skip_db=True,
            show_progress=True,
            stages=["gliner", "assemble"],
            extra=extra,
        )
        print(
            json.dumps(
                {r.stage: {"status": r.status, **(r.metrics or {})} for r in results},
                indent=2,
            )
        )

        # fresh eval dir slice under experiments/runs via record_experiment
        for name in (
            "checkpoint.jsonl",
            "live_metrics.json",
            "summary.json",
            "details.jsonl",
            "per_field.csv",
            "pipeline_predictions.csv",
            "pipeline_vs_gt.csv",
        ):
            path = args.out / name
            if path.exists():
                path.unlink()

        preds_acc, preds_eid = load_preds(args.preprocess_root)
        result = evaluate_tender(
            gt_rows,
            preds_acc,
            accession_to_event_id=acc_to_eid,
            preds_by_event_id=preds_eid,
            out_dir=args.out,
            resume=False,
            show_progress=True,
            score_fields=CORE_GT_FIELDS,
        )
        write_report(result, args.out, gt_rows=gt_rows)

        meta = record_experiment(
            args.out,
            run_id=run_id,
            change_summary=f"HPT threshold={t} on {args.gliner_model.name}",
            parent_run_id=args.parent_run_id,
            result=result,
            config={
                "gliner_threshold": t,
                "gliner_model": str(args.gliner_model),
                "label_set": "core",
                "max_windows": args.gliner_max_windows,
                "fields": "core",
                "scope": "holdout",
                "n_accessions": result.get("n_gt_accessions"),
                "n_gt_rows": result.get("n_gt_rows"),
                "hpt": "threshold",
            },
            keep=None,
            repo=ROOT,
        )
        micro = result.get("micro") or {}
        row = {
            "threshold": t,
            "run_id": run_id,
            "micro_f1": micro.get("f1"),
            "micro_precision": micro.get("precision"),
            "micro_recall": micro.get("recall"),
            "mlflow_run_id": meta.get("mlflow_run_id"),
        }
        leaderboard.append(row)
        if best is None or (row["micro_f1"] or 0) > (best["micro_f1"] or 0):
            best = row
        print(json.dumps(row, indent=2))

    # summary parent run
    with start_run(
        experiment=EXPERIMENT_EVAL,
        run_name=f"{args.run_prefix}sweep",
        params={
            "gliner_model": str(args.gliner_model),
            "thresholds": thresholds,
            "hpt": "threshold_sweep",
        },
        tags={"stage": "hpt", "parent_run_id": args.parent_run_id},
        description="GLiNER threshold HPT summary",
    ) as run:
        if best:
            run.log_metrics(
                {
                    "best_micro_f1": best["micro_f1"],
                    "best_threshold": best["threshold"],
                }
            )
            run.log_dict({"leaderboard": leaderboard, "best": best}, "hpt_threshold_leaderboard.json")

    out_path = args.out / "experiments" / "hpt_threshold_leaderboard.json"
    out_path.write_text(json.dumps({"best": best, "leaderboard": leaderboard}, indent=2), encoding="utf-8")
    print(json.dumps({"best": best, "leaderboard": leaderboard, "out": str(out_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
