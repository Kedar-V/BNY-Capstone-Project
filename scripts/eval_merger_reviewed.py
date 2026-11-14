#!/usr/bin/env python3
"""Prepare blinded merger reviews and score only adjudicated deal-level fields."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = (
    "acquirer", "target", "consideration_type", "cash_consideration",
    "stock_exchange_ratio", "shareholder_vote_date", "closing_conditions",
    "event_status", "mandatory_voluntary_indicator", "security_description",
    "ticker", "cusip", "isin", "effective_date", "available_options",
    "default_option", "election_deadline",
)
REVIEWED = {"verified", "adjudicated", "manually_reviewed"}
STATES = {"present", "absent", "unknown"}
EXACT_FIELDS = {"ticker", "cusip", "isin", "consideration_type", "mandatory_voluntary_indicator"}
DATE_FIELDS = {"shareholder_vote_date", "effective_date", "election_deadline"}
NARRATIVE_FIELDS = {"closing_conditions", "event_status", "security_description", "available_options", "default_option", "stock_exchange_ratio"}
GOLD_COLUMNS = (
    "reference_row_id", "accession_number", "deal_id", "field", "reference_candidate",
    "reference_quote", "sec_source_url", "reference_input_hash", "gliner_text_sha256",
    "gold_state", "gold_value",
    "gold_evidence", "review_status", "reviewer", "review_note",
    "comparison_override", "comparison_reviewer", "comparison_note",
)
PRED_COLUMNS = (
    "accession_number", "deal_id", "field", "predicted_value", "score",
    "source_quote", "source_start", "source_end", "text_sha256",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_predictions(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    result = {row["accession_number"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate GLiNER accession")
    return result


def prepare(reference_path: Path, gliner_path: Path) -> tuple[list[dict], list[dict], dict]:
    """Keep proposed reference values separate from blank human gold columns."""
    references = read_csv(reference_path)
    predictions = load_predictions(gliner_path)
    if not references or not set(FIELDS).issubset(references[0]):
        raise ValueError("Reference CSV lacks merger fields")
    gold_rows = []
    overlap = set()
    for index, row in enumerate(references, start=2):
        accession = row["accession_number"].strip()
        if accession not in predictions:
            continue
        overlap.add(accession)
        try:
            passages = json.loads(row.get("passages") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid passages JSON on reference CSV line {index}") from exc
        for field in FIELDS:
            quotes = passages.get(field, []) if isinstance(passages, dict) else []
            quote = next((item.get("quote", "") for item in quotes if isinstance(item, dict) and item.get("quote")), "")
            gold_rows.append({
                "reference_row_id": f"csv-line-{index}", "accession_number": accession,
                "deal_id": "", "field": field,
                "reference_candidate": row.get(field, ""), "reference_quote": quote,
                "sec_source_url": row.get("filing_index_url", ""),
                "reference_input_hash": row.get("input_hash", ""),
                "gliner_text_sha256": predictions[accession].get("text_sha256", ""),
                "gold_state": "unknown", "gold_value": "", "gold_evidence": "",
                "review_status": "unreviewed", "reviewer": "", "review_note": "",
                "comparison_override": "", "comparison_reviewer": "", "comparison_note": "",
            })
    pred_rows = []
    for accession in sorted(overlap):
        record = predictions[accession]
        for field in FIELDS:
            candidates = record.get("candidates", {}).get(field, [])
            top = max(candidates, key=lambda item: float(item.get("score") or 0), default=None)
            pred_rows.append({
                "accession_number": accession, "deal_id": "", "field": field,
                "predicted_value": top.get("value", "") if top else "",
                "score": top.get("score", "") if top else "",
                "source_quote": top.get("source_quote", "") if top else "",
                "source_start": top.get("start", "") if top else "",
                "source_end": top.get("end", "") if top else "",
                "text_sha256": record.get("text_sha256", ""),
            })
    return gold_rows, pred_rows, {
        "reference_rows": len(references), "prediction_filings": len(predictions),
        "overlap_filings": len(overlap), "review_cells": len(gold_rows),
        "reference_csv_sha256": sha256_file(reference_path),
        "gliner_jsonl_sha256": sha256_file(gliner_path),
        "reference_statuses": dict(Counter(r.get("relevance", "") for r in references)),
    }


def canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def date_value(value: str) -> str | None:
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    return None


def cash_value(value: str) -> Decimal | None:
    amounts = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", value)
    if not amounts:
        amounts = re.findall(r"(?<![A-Za-z\d])([\d,]+(?:\.\d+)?)(?![A-Za-z\d])", value)
    if len(amounts) != 1:
        return None
    try:
        return Decimal(amounts[0].replace(",", ""))
    except InvalidOperation:
        return None


def compare(field: str, predicted: str, gold: str, override: str = "") -> str:
    """Return match/mismatch/needs_review; never silently equate narratives."""
    if override:
        if override not in {"match", "mismatch"}:
            raise ValueError(f"Invalid comparison_override: {override}")
        return override
    if canonical(predicted) == canonical(gold):
        return "match"
    if field in EXACT_FIELDS:
        return "mismatch"
    if field in DATE_FIELDS:
        pred_date, gold_date = date_value(predicted), date_value(gold)
        return "match" if pred_date and gold_date and pred_date == gold_date else "needs_review"
    if field == "cash_consideration":
        pred_cash, gold_cash = cash_value(predicted), cash_value(gold)
        return "match" if pred_cash is not None and gold_cash is not None and pred_cash == gold_cash else "needs_review"
    return "needs_review"


def score(gold_path: Path, prediction_path: Path) -> tuple[dict, list[dict]]:
    gold_rows, predictions = read_csv(gold_path), read_csv(prediction_path)
    if not gold_rows or not set(GOLD_COLUMNS).issubset(gold_rows[0]):
        raise ValueError("Gold review CSV lacks required columns")
    if not predictions or not set(PRED_COLUMNS).issubset(predictions[0]):
        raise ValueError("Prediction CSV lacks required columns")
    reference_counts = Counter(accession for accession, _ in {
        (r["accession_number"], r["reference_row_id"]) for r in gold_rows
    })
    pred_by_key = {}
    for row in predictions:
        key = (row["accession_number"], row["deal_id"].strip(), row["field"])
        if key in pred_by_key:
            raise ValueError(f"Duplicate prediction key: {key}")
        pred_by_key[key] = row
    counts = defaultdict(Counter)
    exclusions = Counter()
    details = []
    seen_gold = set()
    for row in gold_rows:
        accession, deal_id, field = (row[key].strip() for key in ("accession_number", "deal_id", "field"))
        key = (accession, deal_id, field)
        if field not in FIELDS:
            raise ValueError(f"Unknown field: {field}")
        if key in seen_gold and deal_id:
            raise ValueError(f"Duplicate gold deal-field key: {key}")
        seen_gold.add(key)
        if row["review_status"].strip().casefold() not in REVIEWED:
            exclusions["not_reviewed"] += 1
            continue
        state = row["gold_state"].strip().casefold()
        if state not in STATES:
            raise ValueError(f"Invalid gold_state for {key}: {state}")
        if state == "unknown":
            exclusions["unknown_gold"] += 1
            continue
        if not deal_id:
            exclusions["missing_deal_id"] += 1
            continue
        if reference_counts[accession] > 1 and (accession, deal_id, field) not in pred_by_key:
            exclusions["multi_deal_unaligned"] += 1
            continue
        if state == "present" and (not row["gold_value"].strip() or not row["gold_evidence"].strip()):
            raise ValueError(f"Present gold needs value and verified evidence: {key}")
        if state == "absent" and row["gold_value"].strip():
            raise ValueError(f"Absent gold has a value: {key}")
        if not row["reviewer"].strip():
            raise ValueError(f"Reviewed gold lacks reviewer: {key}")
        pred = pred_by_key.get(key)
        if pred is None and reference_counts[accession] == 1:
            pred = pred_by_key.get((accession, "", field))
        predicted = pred["predicted_value"].strip() if pred else ""
        gold_value = row["gold_value"].strip()
        if state == "absent" and not predicted:
            outcome = "tn"
        elif state == "absent":
            outcome = "fp"
        elif not predicted:
            outcome = "fn"
        else:
            override = row["comparison_override"].strip().casefold()
            if override and (not row["comparison_reviewer"].strip() or not row["comparison_note"].strip()):
                raise ValueError(f"Comparison override needs reviewer and note: {key}")
            result = compare(field, predicted, gold_value, override)
            outcome = {"match": "tp", "mismatch": "mismatch", "needs_review": "needs_comparison_review"}[result]
        if outcome == "needs_comparison_review":
            exclusions[outcome] += 1
        else:
            counts[field][outcome] += 1
        details.append({"accession_number": accession, "deal_id": deal_id, "field": field,
                        "gold_state": state, "gold_value": gold_value,
                        "predicted_value": predicted, "outcome": outcome,
                        "reviewer": row["reviewer"]})
    def summarize(counter: Counter) -> dict:
        tp, fp, fn, tn, mismatch = (counter[key] for key in ("tp", "fp", "fn", "tn", "mismatch"))
        fp += mismatch
        fn += mismatch
        denominator_p, denominator_r = tp + fp, tp + fn
        precision = tp / denominator_p if denominator_p else None
        recall = tp / denominator_r if denominator_r else None
        f1 = (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if precision is not None and recall is not None else None
        cells = tp + tn + counter["fp"] + counter["fn"] + mismatch
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "mismatches": mismatch,
                "scored_cells": cells, "precision": precision, "recall": recall,
                "f1": f1, "cell_accuracy": (tp + tn) / cells if cells else None}
    total = Counter()
    for counter in counts.values():
        total.update(counter)
    summary = {"metric_type": "reviewed_deal_field_extraction", "gold_cells": len(gold_rows),
               "gold_review_csv_sha256": sha256_file(gold_path),
               "model_predictions_csv_sha256": sha256_file(prediction_path),
               "reviewed_cells": sum(r["review_status"].strip().casefold() in REVIEWED for r in gold_rows),
               "excluded_cells": dict(exclusions), "micro": summarize(total),
               "per_field": {field: summarize(counts[field]) for field in FIELDS},
               "accuracy_status": "scored" if summarize(total)["scored_cells"] else "not_scorable",
               "note": "Only reviewed, deal-aligned cells with resolved comparisons enter metrics. This scores extraction, not merger discovery."}
    return summary, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Create separate blinded gold and model prediction tables")
    prep.add_argument("--reference", type=Path, required=True)
    prep.add_argument("--gliner", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True)
    prep.add_argument("--force", action="store_true", help="Overwrite existing review files")
    run = sub.add_parser("score", help="Score reviewed deal-level fields")
    run.add_argument("--gold", type=Path, required=True)
    run.add_argument("--predictions", type=Path, required=True)
    run.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        existing = [args.out_dir / name for name in ("gold_review.csv", "model_predictions.csv") if (args.out_dir / name).exists()]
        if existing and not args.force:
            parser.error(f"Refusing to overwrite review files: {existing}. Use a new --out-dir or --force.")
        gold, predictions, summary = prepare(args.reference, args.gliner)
        write_csv(args.out_dir / "gold_review.csv", GOLD_COLUMNS, gold)
        write_csv(args.out_dir / "model_predictions.csv", PRED_COLUMNS, predictions)
        destination = args.out_dir / "prepare_summary.json"
    else:
        summary, details = score(args.gold, args.predictions)
        write_csv(args.out_dir / "score_details.csv", ("accession_number", "deal_id", "field", "gold_state", "gold_value", "predicted_value", "outcome", "reviewer"), details)
        write_csv(args.out_dir / "per_field.csv", ("field", "tp", "fp", "fn", "tn", "mismatches", "scored_cells", "precision", "recall", "f1", "cell_accuracy"),
                  [{"field": field, **metrics} for field, metrics in summary["per_field"].items()])
        destination = args.out_dir / "score_summary.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
