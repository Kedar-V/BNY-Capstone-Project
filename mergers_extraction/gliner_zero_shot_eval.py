#!/usr/bin/env python3
"""Zero-shot GLiNER (no training) on the merger fields, scored field by field.

Runs the off-the-shelf model on the span fields and the summary fields in common.py, in two window modes:
  pipeline : keyword-anchored windows from src/merger_gliner.py (how the merger pipeline runs today)
  oracle   : the ground-truth record's own supporting quotes (best case for window selection)
Regex, rule and metadata fields (ticker, cusip, isin, consideration_type, ...) are not run through GLiNER.
The ground truth is LLM-generated and unverified, so scores are agreement with it, not accuracy.

    python mergers_extraction/gliner_zero_shot_eval.py                       # 10-filing sample
    python mergers_extraction/gliner_zero_shot_eval.py --split holdout       # held-out deals of mergers.csv
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

import common


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", type=Path, help="ground-truth CSV (default: the 10-filing sample, or mergers.csv with --split)")
    ap.add_argument("--split", choices=["all", "holdout"], default="all",
                    help="holdout: only the held-out deals from build_training_data.py")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--model", default=common.BASE_MODEL)
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--max-windows", type=int, default=12)
    ap.add_argument("--limit", type=int, help="first N filings only")
    args = ap.parse_args()

    default_gt = common.GT_PATH if args.split == "holdout" else common.DATA / "mergers_sample.csv"
    gt = common.load_ground_truth(args.gt or default_gt)
    if args.split == "holdout":
        gt = gt[gt["accession_number"].isin(common.holdout_accessions())]
    accessions = list(dict.fromkeys(gt["accession_number"]))[: args.limit]
    gt = gt[gt["accession_number"].isin(accessions)]
    out = args.out or common.OUTPUTS / ("gliner_zero_shot_holdout" if args.split == "holdout" else "gliner_zero_shot_sample")

    from gliner import GLiNER
    model = GLiNER.from_pretrained(args.model)
    started = time.time()
    fields = {**common.SPAN_FIELDS, **common.SUMMARY_FIELDS}
    per_field, micro, details = common.evaluate(model, gt, fields, threshold=args.threshold, max_windows=args.max_windows)
    common.write_results(out, per_field, micro, details, {
        "gt": str(args.gt or default_gt), "split": args.split, "filings": len(accessions), "records": len(gt),
        "model": args.model, "threshold": args.threshold, "max_windows": args.max_windows,
        "seconds": round(time.time() - started)})
    pd.set_option("display.width", 250)
    print(per_field.to_string(index=False))
    print({mode: round(m["f1"], 3) if m["f1"] is not None else None for mode, m in micro.items()}, "micro-F1 ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
