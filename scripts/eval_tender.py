#!/usr/bin/env python3
"""Evaluate tender Concise Reps against tender_offers.csv ground truth.

Supports experiment ledger (--run-id / --experiment-note), core field scoring,
GLiNER threshold, and holdout accessions.

When ``--run-id`` is set, metrics are also logged to MLflow experiment
``tender_eval`` (see docs/mlflow.md). Open the UI with ``python scripts/mlflow_ui.py``.

Examples:
  python scripts/eval_tender.py --snapshot-baseline
  python scripts/eval_tender.py --fields core --holdout --reset-eval \\
      --run-id core_labels --experiment-note "shrink labels to core-14" \\
      --parent-run-id baseline_2026-10-12
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import (
    ensure_holdout,
    record_experiment,
    snapshot_baseline,
)
from src.evaluation.run_tracker import RunTracker, git_commit, sha256_file
from src.evaluation.tender import (
    CORE_GT_FIELDS,
    GT_VALUE_FIELDS,
    evaluate_tender,
    field_coverage,
    gt_event_ids_from_corpus,
    load_gt,
    load_preds,
    write_report,
)
from src.preprocess.parallel import configure_torch_threads, default_workers, pick_torch_device
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tender pipeline vs GT evaluation")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--preprocess-root", type=Path, default=DEFAULT_PREPROCESS_ROOT)
    p.add_argument(
        "--documents-parquet",
        type=Path,
        default=ROOT / "data/processed/documents.parquet",
    )
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--holdout", action="store_true", help="Score fixed 20-accession holdout")
    p.add_argument("--run-preprocess", action="store_true")
    p.add_argument("--skip-db", action="store_true", default=True)
    p.add_argument("--fake-gliner", action="store_true")
    p.add_argument("--force", action="store_true", help="Re-run preprocess even if artifacts exist")
    p.add_argument("--reset-eval", action="store_true", help="Delete eval checkpoint before scoring")
    p.add_argument("--coverage-only", action="store_true")
    p.add_argument("--snapshot-baseline", action="store_true")
    p.add_argument("--fields", choices=["all", "core"], default="core")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--device", default="auto")
    p.add_argument("--gliner-batch-size", type=int, default=8)
    p.add_argument("--gliner-threshold", type=float, default=0.35)
    p.add_argument("--gliner-max-windows", type=int, default=8)
    p.add_argument("--gliner-model", default=None)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--experiment-note", default="")
    p.add_argument("--parent-run-id", default=None)
    p.add_argument("--skip-missing-pred", action="store_true",
                   help="Exclude GT rows whose accession/event has no prediction (instead of counting them as misses)")
    p.add_argument("--heartbeat-every", type=int, default=10, help="rows between progress.jsonl heartbeats")
    p.add_argument("--keep", choices=["auto", "true", "false"], default="auto")
    args = p.parse_args(argv)

    workers = default_workers(args.workers)
    device = pick_torch_device(args.device)
    configure_torch_threads(workers)
    show_progress = not args.no_progress
    score_fields = CORE_GT_FIELDS if args.fields == "core" else GT_VALUE_FIELDS

    if args.snapshot_baseline:
        dest = snapshot_baseline(args.out)
        print(json.dumps({"baseline": str(dest)}, indent=2))
        return 0

    print(
        json.dumps(
            {
                "workers": workers,
                "device": device,
                "gliner_batch_size": args.gliner_batch_size,
                "gliner_threshold": args.gliner_threshold,
                "fields": args.fields,
                "n_score_fields": len(score_fields),
            },
            indent=2,
        )
    )

    cov = field_coverage()
    print(json.dumps({"coverage_ok": cov["ok"], "n_gt_value_fields": len(GT_VALUE_FIELDS)}, indent=2))
    if args.fields == "all" and not cov["ok"]:
        print("ERROR: pipeline missing GT field extractors", cov, file=sys.stderr)
        return 1
    if args.coverage_only:
        return 0

    if not args.gt.exists():
        print(f"ERROR: GT not found: {args.gt}", file=sys.stderr)
        return 1

    gt_rows = load_gt(args.gt)
    tracker = RunTracker(
        args.out,
        {
            "gt_path": str(args.gt),
            "gt_sha256": sha256_file(args.gt),
            "git_commit": git_commit(ROOT),
            "fields": args.fields,
            "gliner_threshold": args.gliner_threshold,
            "gliner_model": args.gliner_model,
            "run_preprocess": args.run_preprocess,
            "force": args.force,
            "holdout": args.holdout,
            "limit": args.limit,
            "run_id": args.run_id,
        },
        every=args.heartbeat_every,
    )
    tracker.note(
        n_gt_rows_loaded=len(gt_rows),
        n_currency_undecided=sum(1 for r in gt_rows if r.get("_currency_undecided")),
    )
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )

    acc_to_eid: dict[str, str] = {}
    if args.documents_parquet.exists():
        acc_to_eid = gt_event_ids_from_corpus(set(accessions), args.documents_parquet)

    if args.holdout:
        accessions = ensure_holdout(args.out, accessions, n=20)
        acc_set = set(accessions)
        gt_rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in acc_set]
        acc_to_eid = {a: e for a, e in acc_to_eid.items() if a in acc_set}
        print(f"holdout accessions: {len(accessions)}")
    elif args.limit is not None:
        preds_acc, preds_eid = load_preds(args.preprocess_root)

        def has_pred(a: str) -> bool:
            return a in preds_acc or acc_to_eid.get(a, "") in preds_eid

        ranked = [a for a in accessions if has_pred(a)] + [a for a in accessions if not has_pred(a)]
        accessions = ranked[: args.limit]
        acc_set = set(accessions)
        gt_rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in acc_set]
        acc_to_eid = {a: e for a, e in acc_to_eid.items() if a in acc_set}

    if args.run_preprocess:
        if not args.documents_parquet.exists():
            print(f"ERROR: corpus missing: {args.documents_parquet}", file=sys.stderr)
            return 1
        if not acc_to_eid:
            acc_to_eid = gt_event_ids_from_corpus(set(accessions), args.documents_parquet)
        missing = [a for a in accessions if a not in acc_to_eid]
        if missing:
            print(f"WARN: {len(missing)} GT accessions not in corpus (e.g. {missing[:3]})")
        event_ids = sorted(set(acc_to_eid.values()))
        if not event_ids:
            print("ERROR: no event_ids resolved from GT accessions", file=sys.stderr)
            return 1
        # Prefer GT accession docs when inventoring each event
        preferred = {eid: acc for acc, eid in acc_to_eid.items()}
        print(f"Running preprocess for {len(event_ids)} events…")
        extra: dict = {
            "workers": workers,
            "gliner_device": device,
            "gliner_batch_size": args.gliner_batch_size,
            "gliner_threshold": args.gliner_threshold,
            "gliner_max_windows": args.gliner_max_windows,
            "preferred_accessions": preferred,
            "pending_only": not args.force,
        }
        if args.gliner_model:
            extra["gliner_model"] = args.gliner_model
        if args.fake_gliner:
            extra["span_backend"] = "fake"
        from src.preprocess.orchestrator import PIPELINE_ORDER, run_stage

        results = []
        for stage_name in PIPELINE_ORDER:
            if stage_name == "load_db" and args.skip_db:
                continue
            print(f"[stage] {stage_name} ({len(event_ids)} events)", flush=True)
            with tracker.stage(f"preprocess:{stage_name}", n_events=len(event_ids)) as rec:
                r = run_stage(
                    stage_name,
                    path_name="tender",
                    preprocess_root=args.preprocess_root,
                    event_ids=event_ids,
                    force=args.force,
                    show_progress=show_progress,
                    extra={**extra, **({"skip_db": True} if args.skip_db else {})},
                )
                rec["status"] = getattr(r, "status", "ok") or "ok"
                rec["metrics"] = getattr(r, "metrics", None)
            results.append(r)
        print(json.dumps({r.stage: {"status": r.status, **(r.metrics or {})} for r in results}, indent=2))

    if args.reset_eval:
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
                print(f"reset {path}")

    preds_acc, preds_eid = load_preds(args.preprocess_root)
    print(
        f"Loaded predictions for {len(preds_acc)} accessions / {len(preds_eid)} events; "
        f"scoring {len(gt_rows)} GT rows / {len(accessions)} accessions ({args.fields})"
    )
    if args.skip_missing_pred:
        def _has_pred(r: dict) -> bool:
            a = (r.get("accession_number") or "").strip()
            return a in preds_acc or acc_to_eid.get(a, "") in preds_eid

        n_before = len(gt_rows)
        gt_rows = [r for r in gt_rows if _has_pred(r)]
        accessions = sorted({(r.get("accession_number") or "").strip() for r in gt_rows})
        print(f"--skip-missing-pred: excluded {n_before - len(gt_rows)} rows without predictions; scoring {len(gt_rows)}")
        tracker.note(n_rows_excluded_no_prediction=n_before - len(gt_rows))
    tracker.note(n_pred_accessions=len(preds_acc), n_pred_events=len(preds_eid))
    with tracker.stage("eval", n_rows=len(gt_rows), n_accessions=len(accessions)) as rec:
        result = evaluate_tender(
            gt_rows,
            preds_acc,
            accession_to_event_id=acc_to_eid,
            preds_by_event_id=preds_eid,
            out_dir=args.out,
            resume=not args.reset_eval,
            show_progress=show_progress,
            score_fields=score_fields,
            on_row=tracker.on_row,
            on_resume=tracker.eval_started,
        )
        rec["micro"] = result["micro"]
    with tracker.stage("report"):
        write_report(result, args.out, gt_rows=gt_rows)
    tracker.finish(
        "ok",
        micro=result["micro"],
        n_gt_rows=result.get("n_gt_rows"),
        n_accessions_missing_prediction=result["n_accessions_missing_prediction"],
    )

    keep = None if args.keep == "auto" else args.keep == "true"
    if args.run_id:
        meta = record_experiment(
            args.out,
            run_id=args.run_id,
            change_summary=args.experiment_note or args.run_id,
            parent_run_id=args.parent_run_id,
            result=result,
            config={
                "gliner_threshold": args.gliner_threshold,
                "gliner_model": args.gliner_model or "urchade/gliner_medium-v2.1",
                "label_set": "core" if args.fields == "core" else "all",
                "max_windows": args.gliner_max_windows,
                "fields": args.fields,
                "scope": "holdout" if args.holdout else ("limit" if args.limit else "full"),
                "n_accessions": result.get("n_gt_accessions"),
                "n_gt_rows": result.get("n_gt_rows"),
            },
            keep=keep,
            repo=ROOT,
        )
        print(json.dumps({"experiment": meta}, indent=2, default=str))

    print(
        json.dumps(
            {
                "out": str(args.out),
                "fields": args.fields,
                "n_gt_rows": result.get("n_gt_rows"),
                "n_gt_accessions": result["n_gt_accessions"],
                "n_accessions_scored": result["n_accessions_scored"],
                "n_accessions_missing_prediction": result["n_accessions_missing_prediction"],
                "n_accessions_joined_via_event_id": result["n_accessions_joined_via_event_id"],
                "micro": result["micro"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
