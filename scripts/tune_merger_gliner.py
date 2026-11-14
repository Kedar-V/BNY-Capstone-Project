#!/usr/bin/env python3
"""Reproducible, provisional top-1 merger GLiNER ranking experiment."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.eval_merger import CORE_FIELDS, normalized, soft_match


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def choose(values: list[dict], *, field: str, consensus: bool,
           threshold: float = 0.4, bonus: float = 0.07) -> dict | None:
    eligible = [x for x in values if float(x.get("score") or 0) >= threshold]
    if not eligible:
        return None
    if not consensus or field != "acquirer":
        return max(eligible, key=lambda x: float(x["score"]))
    groups: dict[str, list[dict]] = {}
    for value in eligible:
        key = normalized(value.get("value", ""))
        if key:
            groups.setdefault(key, []).append(value)
    if not groups:
        return None
    best_group = max(groups.values(), key=lambda group:
                     max(float(v["score"]) for v in group) + bonus * math.log1p(len(group)))
    return max(best_group, key=lambda x: float(x["score"]))


def score(reference: list[dict], predictions: dict[str, dict], cohort: set[str],
          *, consensus: bool, threshold: float, bonus: float) -> dict:
    count = Counter()
    for row in reference:
        accession = row["accession_number"]
        if accession not in cohort:
            continue
        for field in CORE_FIELDS:
            selected = choose(predictions[accession]["candidates"].get(field, []), field=field,
                              consensus=consensus, threshold=threshold, bonus=bonus)
            predicted = selected["value"] if selected else ""
            gold = row.get(field, "")
            if not normalized(predicted) and not normalized(gold):
                continue
            if predicted and gold and soft_match(predicted, gold):
                count["tp"] += 1
            elif predicted and gold:
                count["fp"] += 1
                count["fn"] += 1
            elif predicted:
                count["fp"] += 1
            else:
                count["fn"] += 1
    tp, fp, fn = (count[x] for x in ("tp", "fp", "fn"))
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--acquirer-consensus-bonus", type=float, default=0.07)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1 or args.acquirer_consensus_bonus < 0:
        parser.error("threshold must be 0–1 and bonus nonnegative")
    with args.reference.open(newline="", encoding="utf-8-sig") as stream:
        reference = list(csv.DictReader(stream))
    with args.predictions.open(encoding="utf-8") as stream:
        docs = [json.loads(line) for line in stream if line.strip()]
    predictions = {d["accession_number"]: d for d in docs}
    if len(predictions) != len(docs):
        raise ValueError("Duplicate prediction accession")
    overlap = {r["accession_number"] for r in reference} & predictions.keys()
    dev = {a for a in overlap if int(hashlib.sha256(a.encode()).hexdigest(), 16) % 2 == 0}
    holdout = overlap - dev
    summary = {
        "metric_type": "provisional_reference_agreement_not_verified_accuracy",
        "reference_sha256": file_hash(args.reference),
        "predictions_sha256": file_hash(args.predictions),
        "threshold": args.threshold,
        "acquirer_consensus_bonus": args.acquirer_consensus_bonus,
        "split_rule": "SHA256(accession) mod 2: even=development, odd=holdout",
        "development_accessions": sorted(dev), "holdout_accessions": sorted(holdout),
        "results": {
            cohort_name: {
                "score_only": score(reference, predictions, cohort, consensus=False,
                                    threshold=args.threshold, bonus=args.acquirer_consensus_bonus),
                "acquirer_consensus": score(reference, predictions, cohort, consensus=True,
                                            threshold=args.threshold, bonus=args.acquirer_consensus_bonus),
            }
            for cohort_name, cohort in (("development", dev), ("holdout", holdout), ("all_overlap", overlap))
        },
        "limitations": "Reference rows are unverified. One filing-level prediction is reused for multiple merger rows. The scorer uses relaxed text matching. Do not report these F1 values as validated extraction accuracy.",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "ranked_top1.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("accession_number", "field", "value", "score", "selection_method", "source_quote"))
        writer.writeheader()
        for accession in sorted(predictions):
            for field in CORE_FIELDS:
                selected = choose(predictions[accession]["candidates"].get(field, []), field=field,
                                  consensus=True, threshold=args.threshold, bonus=args.acquirer_consensus_bonus)
                if selected:
                    writer.writerow({"accession_number": accession, "field": field,
                                     "value": selected["value"], "score": selected["score"],
                                     "selection_method": "acquirer_consensus" if field == "acquirer" else "max_score",
                                     "source_quote": selected.get("source_quote", "")})
    print(json.dumps(summary["results"], indent=2))


if __name__ == "__main__":
    main()
