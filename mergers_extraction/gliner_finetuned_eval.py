#!/usr/bin/env python3
"""Fine-tuned GLiNER versus zero-shot GLiNER on the held-out deals, field by field.

Both models are scored on the same held-out filings with the same windows and scorer (common.evaluate), on the
span fields they were trained for. Uses the ground-truth snapshot that build_training_data.py trained from.

    python mergers_extraction/gliner_finetuned_eval.py --name medium_500steps
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

import common


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="medium_500steps", help="folder under models/merger_gliner/")
    ap.add_argument("--gt", type=Path, default=common.TRAINING_DATA / "ground_truth_snapshot.csv")
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--max-windows", type=int, default=12)
    ap.add_argument("--skip-zero-shot", action="store_true")
    ap.add_argument("--windows", choices=["pipeline", "learned"], default="pipeline",
                    help="pipeline: the original keyword windows of src/merger_gliner.py; learned: window_selection.py selector")
    ap.add_argument("--per-field", type=int, default=5, help="learned windows per field (budget = 10 x this)")
    ap.add_argument("--split", choices=["holdout", "validation"], default="holdout",
                    help="validation: the deals carved out of training for choosing checkpoints and methods")
    ap.add_argument("--no-oracle", action="store_true", help="skip the ground-truth-passage scoring (faster)")
    ap.add_argument("--limit", type=int, help="first N filings only (for a quick test)")
    args = ap.parse_args()

    gt = common.load_ground_truth(args.gt)
    wanted = common.holdout_accessions() if args.split == "holdout" else common.validation_accessions()
    gt = gt[gt["accession_number"].isin(wanted[: args.limit])]
    from gliner import GLiNER

    finetuned = common.MODELS / args.name / "final"
    if not finetuned.exists():
        raise SystemExit(f"{finetuned} not found: train it first with train_gliner.py --name {args.name}")
    models = {"finetuned": str(finetuned)}
    if not args.skip_zero_shot and args.split == "holdout":
        models["zero_shot"] = common.BASE_MODEL
    out = common.OUTPUTS / f"gliner_finetuned_{args.name}_{args.split}" / f"{args.windows}_windows"
    window_fn = None
    if args.windows == "learned":
        from window_selection import Selector
        selector = Selector.load()
        window_fn = lambda text: selector.select(text, per_field=args.per_field, max_windows=10 * args.per_field)  # noqa: E731
    table = []
    for tag, path in models.items():
        started = time.time()
        per_field, micro, details = common.evaluate(GLiNER.from_pretrained(path), gt, common.SPAN_FIELDS,
                                                    threshold=args.threshold, max_windows=args.max_windows,
                                                    window_fn=window_fn, window_name=args.windows, oracle=not args.no_oracle)
        common.write_results(out / tag, per_field, micro, details, {
            "gt": str(args.gt), "split": args.split, "filings": int(gt["accession_number"].nunique()),
            "records": len(gt), "model": path, "threshold": args.threshold, "max_windows": args.max_windows,
            "windows": args.windows, "seconds": round(time.time() - started)})
        cols = [c for c in (f"{args.windows}_f1", "oracle_f1") if c in per_field]
        fields = per_field.set_index("field")[cols]
        overall = pd.DataFrame({c: [micro[c[:-3]]["f1"]] for c in cols}, index=["MICRO"])
        table.append(pd.concat([fields, overall]).add_prefix(f"{tag}_"))
    combined = pd.concat(table, axis=1).astype(float).round(3)
    combined.to_csv(out / "comparison.csv")
    print(combined.to_string())
    print("->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
