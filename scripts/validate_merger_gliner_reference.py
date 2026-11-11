#!/usr/bin/env python3
"""Compare merger GLiNER spans with an unverified reference, without claiming accuracy."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


FIELDS = (
    "acquirer", "target", "cash_consideration", "stock_exchange_ratio",
    "shareholder_vote_date", "closing_conditions", "event_status",
    "security_description", "ticker", "cusip", "isin", "effective_date",
    "available_options", "default_option", "election_deadline",
)


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def match(reference: str, candidates: list[dict]) -> tuple[str, str]:
    """Use conservative text rules; a match is not factual correctness."""
    ref = normalize(reference)
    for candidate in candidates:
        value = candidate.get("value", "")
        if ref and normalize(value) == ref:
            return "exact_normalized", value
    for candidate in candidates:
        value = candidate.get("value", "")
        candidate_norm = normalize(value)
        # Short tokens and fragments are too easy to match accidentally.
        if len(candidate_norm) >= 8 and len(candidate_norm) >= len(ref) * 0.6 and candidate_norm in ref:
            return "subphrase", value
    return "no_match", ""


def validate(reference_path: Path, predictions_path: Path) -> tuple[dict, list[dict]]:
    with reference_path.open(newline="", encoding="utf-8-sig") as stream:
        refs = list(csv.DictReader(stream))
    with predictions_path.open(encoding="utf-8") as stream:
        preds = [json.loads(line) for line in stream if line.strip()]
    by_accession = {p["accession_number"]: p for p in preds}
    if len(by_accession) != len(preds):
        raise ValueError("Duplicate prediction accessions")
    overlaps = {r["accession_number"] for r in refs} & by_accession.keys()
    details = []
    counts = defaultdict(lambda: defaultdict(int))
    for ref in refs:
        accession = ref["accession_number"]
        if accession not in overlaps:
            continue
        pred = by_accession[accession]
        for field in FIELDS:
            value = ref.get(field, "").strip()
            if not value:
                continue
            candidates = pred.get("candidates", {}).get(field, [])
            rule, matched = match(value, candidates)
            counts[field]["reference_values"] += 1
            counts[field]["with_candidate"] += bool(candidates)
            counts[field][rule] += 1
            details.append({
                "accession_number": accession,
                "event_id": ref.get("event_id", ""),
                "field": field,
                "reference_value": value,
                "reference_status": ref.get("relevance", ""),
                "candidate_count": len(candidates),
                "match_rule": rule,
                "matched_candidate": matched,
                "review_status": "unreviewed",
            })
    totals = defaultdict(int)
    for row in details:
        totals["reference_values"] += 1
        totals["with_candidate"] += row["candidate_count"] > 0
        totals[row["match_rule"]] += 1
    summary = {
        "reference_rows": len(refs),
        "reference_accessions": len({r["accession_number"] for r in refs}),
        "prediction_accessions": len(preds),
        "overlap_accessions": len(overlaps),
        "overlap_reference_rows": sum(r["accession_number"] in overlaps for r in refs),
        "reference_statuses": dict(Counter(r.get("relevance", "") for r in refs)),
        "field_results": {f: dict(counts[f]) for f in FIELDS if counts[f]},
        "totals": dict(totals),
        "accuracy": None,
        "interpretation": "String agreement with unverified reference values on overlapping filings only. Multiple reference deals may share a filing; candidate spans are not deal-resolved. No precision, recall, or F1 is estimated.",
    }
    return summary, details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    summary, details = validate(args.reference, args.predictions)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with args.output_prefix.with_suffix(".details.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("accession_number", "event_id", "field", "reference_value", "reference_status", "candidate_count", "match_rule", "matched_candidate", "review_status"))
        writer.writeheader()
        writer.writerows(details)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
