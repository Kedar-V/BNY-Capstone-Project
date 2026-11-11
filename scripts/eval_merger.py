#!/usr/bin/env python3
"""Evaluate merger GLiNER output against reference rows.

Top-1 mode mirrors the Evaluation branch's tender scorer and reports provisional
agreement with unverified reference candidates. Reviewed mode only scores
adjudicated, single-deal canonical values.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


FIELDS = (
    "acquirer", "target", "consideration_type", "cash_consideration",
    "stock_exchange_ratio", "shareholder_vote_date", "closing_conditions",
    "event_status", "mandatory_voluntary_indicator", "security_description",
    "ticker", "cusip", "isin", "effective_date", "available_options",
    "default_option", "election_deadline",
)
REVIEWED = {"manually_reviewed", "adjudicated", "verified"}
CORE_FIELDS = (
    "acquirer", "target", "cash_consideration", "stock_exchange_ratio",
    "shareholder_vote_date", "effective_date", "security_description",
    "ticker", "cusip", "isin",
)
MISSING = {"", "n/a", "na", "none", "null", "-", "—"}


def normalized(value: object) -> str:
    if value is None:
        return ""
    result = re.sub(r"\s+", " ", str(value).strip().casefold())
    return "" if result in MISSING else result


def soft_match(predicted: str, gold: str) -> bool:
    """Tender-style relaxed text match; only a reference-agreement heuristic."""
    p, g = normalized(predicted), normalized(gold)
    if not p or not g:
        return False
    if p == g or (len(p) >= 5 and p in g) or (len(g) >= 5 and g in p):
        return True
    # Tender evaluator permits numeric comparisons. For merger consideration,
    # require exact number tokens to avoid matching a par value to the price.
    p_numbers = set(re.findall(r"\d+(?:\.\d+)?", p))
    g_numbers = set(re.findall(r"\d+(?:\.\d+)?", g))
    if p_numbers and g_numbers and ("$" in p or "$" in g or "per share" in p or "per share" in g):
        return bool(p_numbers & g_numbers)
    return False


def evaluate_top1(
    reference_path: Path,
    predictions_path: Path,
    *,
    fields: tuple[str, ...] = CORE_FIELDS,
    scope: str = "overlap",
) -> tuple[dict, list[dict]]:
    """Score one highest-confidence span per field and reference CSV row.

    This follows tender's top-1/row-wise TP, FP and FN accounting, while
    explicitly reporting that the reference labels are unverified.
    """
    if scope not in {"overlap", "all"}:
        raise ValueError("scope must be overlap or all")
    with reference_path.open(newline="", encoding="utf-8-sig") as stream:
        gold = list(csv.DictReader(stream))
    with predictions_path.open(encoding="utf-8") as stream:
        predictions = [json.loads(line) for line in stream if line.strip()]
    if not gold or not set(fields).issubset(gold[0]):
        raise ValueError("Reference CSV is empty or lacks scored merger fields")
    by_accession = {p["accession_number"]: p for p in predictions}
    if len(by_accession) != len(predictions):
        raise ValueError("Prediction JSONL has duplicate accessions")
    reference_accessions = {r["accession_number"].strip() for r in gold}
    overlap = reference_accessions & by_accession.keys()
    selected = [r for r in gold if scope == "all" or r["accession_number"].strip() in overlap]
    counts: dict[str, Counter] = {field: Counter() for field in fields}
    details = []
    for index, row in enumerate(selected):
        accession = row["accession_number"].strip()
        prediction = by_accession.get(accession, {})
        for field in fields:
            values = prediction.get("candidates", {}).get(field, [])
            top = max(values, key=lambda v: float(v.get("score") or 0), default=None)
            pred_value = str(top["value"]) if top else ""
            gold_value = row.get(field, "")
            p, g = normalized(pred_value), normalized(gold_value)
            if not p and not g:
                outcome = "both_blank"
                continue
            if p and g and soft_match(pred_value, gold_value):
                outcome = "tp"
                counts[field]["tp"] += 1
            elif p and g:
                outcome = "mismatch"
                counts[field]["fp"] += 1
                counts[field]["fn"] += 1
            elif p:
                outcome = "fp_no_reference"
                counts[field]["fp"] += 1
            else:
                outcome = "fn_missing_prediction"
                counts[field]["fn"] += 1
            counts[field]["scored"] += 1
            details.append({
                "reference_row": index, "accession_number": accession,
                "event_id": row.get("event_id", ""), "field": field,
                "reference_value": gold_value, "predicted_top1": pred_value,
                "predicted_score": top.get("score", "") if top else "",
                "outcome": outcome, "reference_status": row.get("relevance", ""),
            })
    def finalize(count: Counter) -> dict:
        tp, fp, fn = (count[key] for key in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if precision is not None and recall is not None else None
        return {"tp": tp, "fp": fp, "fn": fn, "scored": count["scored"],
                "precision": precision, "recall": recall, "f1": f1,
                "agreement_accuracy": tp / count["scored"] if count["scored"] else None}
    micro = Counter()
    for count in counts.values():
        micro.update(count)
    summary = {
        "metric_type": "provisional_top1_reference_agreement",
        "scope": scope, "fields": list(fields),
        "reference_rows": len(gold), "reference_accessions": len(reference_accessions),
        "prediction_accessions": len(by_accession), "overlap_accessions": len(overlap),
        "rows_scored": len(selected),
        "reference_statuses": dict(Counter(r.get("relevance", "") for r in selected)),
        "micro": finalize(micro),
        "per_field": {field: finalize(count) for field, count in counts.items()},
        "verified_accuracy": None,
        "limitations": "Reference values are unverified; top-1 GLiNER spans are not canonical deal values. Multiple reference rows for a filing reuse the same prediction. Relaxed string matching can over- or under-count agreement. These are provisional comparison metrics, not validated extraction accuracy.",
    }
    return summary, details


def evaluate(reference_path: Path, predictions_path: Path) -> tuple[dict, list[dict]]:
    with reference_path.open(newline="", encoding="utf-8-sig") as stream:
        gold = list(csv.DictReader(stream))
    with predictions_path.open(encoding="utf-8") as stream:
        predictions = [json.loads(line) for line in stream if line.strip()]
    if not gold:
        raise ValueError("Reference CSV is empty")
    if not set(FIELDS).issubset(gold[0]):
        raise ValueError("Reference CSV lacks merger fields")
    if len({p["accession_number"] for p in predictions}) != len(predictions):
        raise ValueError("Prediction JSONL has duplicate accessions")
    by_accession = {p["accession_number"]: p for p in predictions}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in gold:
        grouped[row["accession_number"].strip()].append(row)
    overlap = set(grouped) & by_accession.keys()
    status = Counter(r.get("review_status") or r.get("relevance") or "" for r in gold)
    details = []
    counts: dict[str, Counter] = defaultdict(Counter)
    excluded = Counter()
    for accession in sorted(overlap):
        rows = grouped[accession]
        # One accession can contain multiple deals/security records. Span-only
        # GLiNER output has no deal ID, so such rows cannot be scored fairly.
        if len(rows) != 1:
            excluded["multiple_reference_rows_per_filing"] += 1
            continue
        row = rows[0]
        review = row.get("review_status") or row.get("relevance") or ""
        if review.strip().casefold() not in REVIEWED:
            excluded["reference_not_reviewed"] += 1
            continue
        canonical = by_accession[accession].get("canonical_fields") or {}
        if not any(normalized(canonical.get(field)) for field in FIELDS):
            excluded["canonical_prediction_missing"] += 1
            continue
        for field in FIELDS:
            expected = normalized(row[field])
            actual = normalized(canonical.get(field))
            if not expected and not actual:
                outcome = "true_negative"
            elif expected and actual and expected == actual:
                outcome = "correct"
                counts[field]["tp"] += 1
            elif expected and actual:
                outcome = "wrong_value"
                counts[field]["fp"] += 1
                counts[field]["fn"] += 1
            elif actual:
                outcome = "spurious"
                counts[field]["fp"] += 1
            else:
                outcome = "missed"
                counts[field]["fn"] += 1
            details.append({"accession_number": accession, "field": field,
                            "gold_value": row[field], "predicted_value": canonical.get(field),
                            "outcome": outcome})
    metrics = {}
    for field, c in counts.items():
        tp, fp, fn = (c[k] for k in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if precision is not None and recall is not None else None
        metrics[field] = {"tp": tp, "fp": fp, "fn": fn,
                          "precision": precision, "recall": recall, "f1": f1}
    scored = len({d["accession_number"] for d in details})
    summary = {"reference_rows": len(gold), "reference_accessions": len(grouped),
               "prediction_accessions": len(by_accession), "overlap_accessions": len(overlap),
               "reference_statuses": dict(status), "scored_filings": scored,
               "excluded_overlap_filings": dict(excluded), "field_metrics": metrics,
               "accuracy_status": "scored" if scored else "not_scorable",
               "note": "Scores require reviewed single-deal reference rows and non-null canonical predictions; GLiNER span candidates alone are not canonical predictions."}
    return summary, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", "--gt", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-prefix", "--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("top1", "reviewed"), default="top1")
    parser.add_argument("--fields", choices=("core", "all"), default="core")
    parser.add_argument("--scope", choices=("overlap", "all"), default="overlap")
    args = parser.parse_args()
    summary, details = (evaluate_top1(args.reference, args.predictions,
                                      fields=CORE_FIELDS if args.fields == "core" else FIELDS,
                                      scope=args.scope)
                        if args.mode == "top1" else evaluate(args.reference, args.predictions))
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with args.output_prefix.with_suffix(".details.csv").open("w", newline="", encoding="utf-8") as stream:
        fieldnames = (("reference_row", "accession_number", "event_id", "field", "reference_value",
                       "predicted_top1", "predicted_score", "outcome", "reference_status")
                      if args.mode == "top1" else
                      ("accession_number", "field", "gold_value", "predicted_value", "outcome"))
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(details)
    if args.mode == "top1":
        with args.output_prefix.with_suffix(".per_field.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("field", "tp", "fp", "fn", "scored", "precision", "recall", "f1", "agreement_accuracy"))
            writer.writeheader()
            writer.writerows({"field": field, **metrics} for field, metrics in summary["per_field"].items())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
