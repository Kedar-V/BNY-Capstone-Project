import csv
import json
from pathlib import Path

from scripts.eval_merger_evidence import score


def test_quote_agreement_deduplicates_mentions_and_uses_field_evidence(tmp_path: Path):
    reference = tmp_path / "reference.csv"
    with reference.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["accession_number", "relevance", "passages"])
        writer.writeheader()
        writer.writerow({"accession_number": "one", "relevance": "candidate_not_verified",
                         "passages": json.dumps({"acquirer": [{"quote": "Acme Corp acquired Beta."}],
                                                 "target": [{"quote": "Beta was acquired."}]})})
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({"accession_number": "one", "candidates": {
        "acquirer": [{"value": "Acme Corp"}, {"value": "Acme Corp"}, {"value": "Other Corp"}],
        "target": [{"value": "Beta"}]}}) + "\n")
    summary, details = score(reference, predictions)
    assert summary["overlap_accessions"] == 1
    assert summary["totals"]["reference_accession_fields"] == 2
    assert summary["totals"]["unique_candidate_values"] == 3
    assert summary["totals"]["quote_supported_candidate_values"] == 2
    assert summary["totals"]["quote_support_fraction"] == 2 / 3
    assert summary["totals"]["field_coverage_fraction"] == 1
    assert summary["accuracy"] is None
    assert len(details) == 2
