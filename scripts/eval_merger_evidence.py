#!/usr/bin/env python3
"""Score provisional agreement between GLiNER spans and merger reference quotes."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score(reference_path: Path, predictions_path: Path) -> tuple[dict, list[dict]]:
    with reference_path.open(newline="", encoding="utf-8-sig") as source:
        reference = list(csv.DictReader(source))
    with predictions_path.open(encoding="utf-8") as source:
        predictions = [json.loads(line) for line in source if line.strip()]
    by_accession = {p["accession_number"]: p for p in predictions}
    if len(by_accession) != len(predictions):
        raise ValueError("Duplicate prediction accession")
    evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    reference_rows_in_overlap = 0
    for row in reference:
        accession = row["accession_number"].strip()
        if accession not in by_accession:
            continue
        reference_rows_in_overlap += 1
        try:
            passages = json.loads(row.get("passages") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid passages JSON for {accession}") from exc
        if not isinstance(passages, dict):
            raise ValueError(f"Passages must be an object for {accession}")
        for field, items in passages.items():
            if not isinstance(items, list):
                continue
            evidence[(accession, field)].extend(normalize(x.get("quote", "")) for x in items if isinstance(x, dict) and x.get("quote"))

    details = []
    by_field: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (accession, field), quotes in sorted(evidence.items()):
        if not quotes:
            continue
        candidates = by_accession[accession].get("candidates", {}).get(field, [])
        # One mention repeated many times in a filing is one candidate value.
        values: dict[str, str] = {}
        for candidate in candidates:
            raw = str(candidate.get("value", ""))
            key = normalize(raw)
            if len(key) >= 4:
                values.setdefault(key, raw)
        supported = {key: raw for key, raw in values.items() if any(key in quote for quote in quotes)}
        counts = by_field[field]
        counts["reference_accession_fields"] += 1
        counts["fields_with_supported_candidate"] += bool(supported)
        counts["unique_candidate_values"] += len(values)
        counts["quote_supported_candidate_values"] += len(supported)
        details.append({
            "accession_number": accession, "field": field,
            "reference_quote_count": len(quotes),
            "unique_candidate_values": len(values),
            "quote_supported_candidate_values": len(supported),
            "has_supported_candidate": bool(supported),
            "supported_values": json.dumps(list(supported.values()), ensure_ascii=False),
            "unsupported_values": json.dumps([raw for key, raw in values.items() if key not in supported], ensure_ascii=False),
            "review_status": "unverified",
        })
    field_results = {}
    totals = defaultdict(int)
    for field, count in sorted(by_field.items()):
        result = dict(count)
        result["quote_support_fraction"] = ratio(count["quote_supported_candidate_values"], count["unique_candidate_values"])
        result["field_coverage_fraction"] = ratio(count["fields_with_supported_candidate"], count["reference_accession_fields"])
        field_results[field] = result
        for key, value in count.items():
            totals[key] += value
    total = dict(totals)
    total["quote_support_fraction"] = ratio(totals["quote_supported_candidate_values"], totals["unique_candidate_values"])
    total["field_coverage_fraction"] = ratio(totals["fields_with_supported_candidate"], totals["reference_accession_fields"])
    summary = {
        "metric_type": "provisional_reference_evidence_agreement",
        "reference_rows": len(reference), "reference_rows_in_overlap": reference_rows_in_overlap,
        "reference_accessions": len({r["accession_number"] for r in reference}),
        "prediction_accessions": len(by_accession),
        "overlap_accessions": len({r["accession_number"] for r in reference} & by_accession.keys()),
        "reference_statuses": dict(Counter(r.get("relevance", "") for r in reference)),
        "totals": total, "by_field": field_results,
        "accuracy": None,
        "limitations": "Reference quotes are unverified and may omit true supporting passages. GLiNER uses partial filing windows. Multiple deals in one filing are pooled by accession and field. This measures literal span-in-quote agreement, not correctness, precision, recall, or F1.",
    }
    return summary, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    summary, details = score(args.reference, args.predictions)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with args.output_prefix.with_suffix(".details.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=("accession_number", "field", "reference_quote_count", "unique_candidate_values", "quote_supported_candidate_values", "has_supported_candidate", "supported_values", "unsupported_values", "review_status"))
        writer.writeheader()
        writer.writerows(details)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
