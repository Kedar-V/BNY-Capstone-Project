#!/usr/bin/env python3
"""CLI for modular TO-first preprocess pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess import PATH_NAMES, STAGE_NAMES
from src.preprocess.metrics import write_metrics_csv
from src.preprocess.orchestrator import PIPELINE_ORDER, run_pipeline, run_stage
from src.preprocess.progress import progress_enabled
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT
from src.preprocess.viz import run_viz


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BNY preprocess: inventory → Concise Rep → DB")
    p.add_argument("--path", default="tender", choices=list(PATH_NAMES))
    p.add_argument("--stage", default="all", help=f"one of {list(STAGE_NAMES)} or all")
    p.add_argument(
        "--from-stage",
        default=None,
        choices=list(STAGE_NAMES),
        help="When --stage all, start at this stage (skip earlier ones)",
    )
    p.add_argument("--event-id", action="append", dest="event_ids", default=None)
    p.add_argument("--cohort", default=None, choices=["gold", "needs_otp_resolve", "incomplete"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="Reprocess even if stage artifacts exist")
    p.add_argument(
        "--pending-only",
        action="store_true",
        help="Only events missing Concise Rep (assemble); skip fully processed",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-db", action="store_true", help="Skip load_db stage")
    p.add_argument("--fake-gliner", action="store_true", help="Use FakeSpanBackend (tests/demo)")
    p.add_argument("--gliner-model", default=None)
    p.add_argument("--preprocess-root", type=Path, default=DEFAULT_PREPROCESS_ROOT)
    p.add_argument("--viz", action="store_true")
    p.add_argument("--viz-only", action="store_true")
    p.add_argument("--inspect-limit", type=int, default=5)
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("--progress", action="store_true", help="Force tqdm even if not a TTY")
    args = p.parse_args(argv)

    # Default: show tqdm unless explicitly disabled (important for redirected/CI logs too when --progress)
    show_progress = True
    if args.no_progress:
        show_progress = False
    elif args.progress:
        show_progress = True
    else:
        show_progress = progress_enabled(True)

    extra = {}
    if args.fake_gliner:
        extra["span_backend"] = "fake"
    if args.gliner_model:
        extra["gliner_model"] = args.gliner_model
    if args.skip_db:
        extra["skip_db"] = True
    if args.pending_only:
        extra["pending_only"] = True

    if args.viz_only:
        out = run_viz(
            path_name=args.path,
            event_ids=args.event_ids,
            inspect_limit=args.inspect_limit,
            root=args.preprocess_root,
            show_progress=show_progress,
        )
        print(json.dumps(out, indent=2))
        return 0

    common = dict(
        path_name=args.path,
        preprocess_root=args.preprocess_root,
        event_ids=args.event_ids,
        cohort=args.cohort,
        limit=args.limit,
        force=args.force,
        dry_run=args.dry_run,
        show_progress=show_progress,
        extra=extra,
    )

    results = []
    if args.stage == "all":
        order = list(PIPELINE_ORDER)
        if args.from_stage:
            if args.from_stage not in order:
                print(f"unknown --from-stage {args.from_stage}", file=sys.stderr)
                return 2
            order = order[order.index(args.from_stage) :]
        results = run_pipeline(skip_db=args.skip_db, stages=order, **common)
    else:
        results = [run_stage(args.stage, **common)]

    for r in results:
        print(
            f"[{r.stage}] status={r.status} ok={r.n_success} fail={r.n_failed} skip={r.n_skipped} metrics={r.metrics}"
        )
        if r.errors:
            print(f"  errors({len(r.errors)}): {r.errors[:3]}")

    metrics_path = write_metrics_csv(args.path, args.preprocess_root)
    print(f"metrics -> {metrics_path}")

    if args.viz:
        viz_out = run_viz(
            path_name=args.path,
            event_ids=args.event_ids,
            inspect_limit=args.inspect_limit,
            root=args.preprocess_root,
            show_progress=show_progress,
        )
        print(f"viz -> {json.dumps(viz_out)}")

    failed = [r for r in results if r.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
