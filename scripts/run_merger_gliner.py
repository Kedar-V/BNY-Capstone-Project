#!/usr/bin/env python3
"""Extract reviewable merger field spans with GLiNER from saved SEC filing text."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.merger_gliner import export_spans_csv, read_csv, reference_coverage, run, run_reference_texts  # noqa: E402
from src.preprocess.backends.base import GlinerBackend  # noqa: E402


SOURCE = ROOT / "data/mergers/sec_2026"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=SOURCE / "screened_merger_candidates_2026_Jan_Sep.zip")
    parser.add_argument("--manifest", type=Path, default=SOURCE / "screened_merger_candidates_2026_Jan_Sep.manifest.csv")
    parser.add_argument("--reference", type=Path, help="Evaluation-branch mergers.csv (coverage only; unverified labels)")
    parser.add_argument("--text-dir", type=Path, help="Optional Evaluation input_text/ folder, one <accession>.txt per filing")
    parser.add_argument("--output", type=Path, default=SOURCE / "gliner_merger_candidates_2026_Jan_Sep.jsonl")
    parser.add_argument("--model", default="urchade/gliner_medium-v2.1")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--max-windows", type=int, default=12)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--coverage-only", action="store_true", help="Check reference overlap without loading GLiNER")
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_windows < 1:
        parser.error("--max-windows must be positive")
    if args.coverage_only:
        if not args.reference:
            parser.error("--coverage-only requires --reference")
        inventory = read_csv(args.manifest)
        selected = inventory[:args.limit] if args.limit else inventory
        print(json.dumps(reference_coverage(args.reference, inventory, {r["accession_number"] for r in selected}), indent=2))
        return 0

    if args.text_dir and not args.reference:
        parser.error("--text-dir requires --reference")

    backend = GlinerBackend(model_id=args.model, threshold=args.threshold, max_windows=8)
    if not backend.available:
        parser.error(f"GLiNER model unavailable: {backend._load_error}. Install requirements.txt and check model access")
    if args.text_dir:
        result = run_reference_texts(args.reference, args.text_dir, args.output, backend,
                                     limit=args.limit, max_windows=args.max_windows)
    else:
        result = run(args.archive, args.manifest, args.output, backend,
                     reference_path=args.reference, limit=args.limit, max_windows=args.max_windows)
    result.update(export_spans_csv(args.output))
    args.output.with_suffix(".summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
