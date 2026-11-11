#!/usr/bin/env python3
"""Audit merger GLiNER/reference overlap without treating unverified labels as gold."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


FIELDS = (
    "acquirer", "target", "cash_consideration", "stock_exchange_ratio",
    "shareholder_vote_date", "closing_conditions", "event_status",
    "security_description", "ticker", "cusip", "isin", "effective_date",
    "available_options", "default_option", "election_deadline",
)


def audit(reference_path: Path, predictions_path: Path) -> tuple[dict, list[dict]]:
    with reference_path.open(newline="", encoding="utf-8-sig") as source:
        reference = list(csv.DictReader(source))
    with predictions_path.open(encoding="utf-8") as source:
        predictions = [json.loads(line) for line in source if line.strip()]
    if len({row["accession_number"] for row in predictions}) != len(predictions):
        raise ValueError("Duplicate prediction accession")
    by_accession = {row["accession_number"]: row for row in predictions}
    ref_accessions = {row["accession_number"] for row in reference}
    overlapping = ref_accessions & by_accession.keys()
    counts = {field: Counter() for field in FIELDS}
    review_rows = []
    for row in reference:
        accession = row["accession_number"]
        if accession not in overlapping:
            continue
        prediction = by_accession[accession]
        for field in FIELDS:
            value = row.get(field, "").strip()
            candidates = prediction.get("candidates", {}).get(field, [])
            if value:
                counts[field]["reference_rows_with_value"] += 1
                if candidates:
                    counts[field]["rows_with_any_same_field_candidate"] += 1
            review_rows.append({
                "accession_number": accession,
                "event_id": row.get("event_id", ""),
                "field": field,
                "reference_value": value,
                "reference_relevance": row.get("relevance", ""),
                "candidate_count_in_filing": len(candidates),
                "top_candidate": candidates[0]["value"] if candidates else "",
                "top_candidate_score": candidates[0]["score"] if candidates else "",
                "top_candidate_quote": candidates[0]["source_quote"] if candidates else "",
                "match_review": "unreviewed",
            })
    summary = {
        "reference_rows": len(reference),
        "reference_accessions": len(ref_accessions),
        "prediction_accessions": len(by_accession),
        "overlap_accessions": len(overlapping),
        "overlap_reference_rows": sum(r["accession_number"] in overlapping for r in reference),
        "reference_relevance": dict(Counter(r.get("relevance", "") for r in reference)),
        "field_candidate_presence_on_overlap": {field: dict(count) for field, count in counts.items()},
        "accuracy": None,
        "note": "Candidate presence is only a coverage diagnostic. Reference rows are unverified; multiple deals may share one filing; GLiNER spans are not canonical values.",
    }
    return summary, review_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    summary, rows = audit(args.reference, args.predictions)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with args.output_prefix.with_suffix(".review.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=rows[0].keys() if rows else
                                ("accession_number", "event_id", "field", "reference_value", "reference_relevance",
                                 "candidate_count_in_filing", "top_candidate", "top_candidate_score",
                                 "top_candidate_quote", "match_review"))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
