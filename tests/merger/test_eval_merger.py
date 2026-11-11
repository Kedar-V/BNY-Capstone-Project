import csv
import json
from pathlib import Path

from scripts.eval_merger import FIELDS, evaluate, evaluate_top1


def test_scores_only_reviewed_single_deal_canonical_values(tmp_path: Path):
    reference = tmp_path / "reference.csv"
    rows = [
        {"accession_number": "one", "review_status": "manually_reviewed", "acquirer": "Acme", "target": "Target"},
        {"accession_number": "two", "review_status": "candidate_not_verified", "acquirer": "Other"},
        {"accession_number": "three", "review_status": "manually_reviewed", "acquirer": "First"},
        {"accession_number": "three", "review_status": "manually_reviewed", "acquirer": "Second"},
    ]
    with reference.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["accession_number", "review_status", *FIELDS])
        writer.writeheader()
        writer.writerows(rows)
    predictions = tmp_path / "predictions.jsonl"
    with predictions.open("w") as stream:
        for accession, values in [("one", {"acquirer": " ACME ", "target": "Wrong"}),
                                  ("two", {"acquirer": "Other"}),
                                  ("three", {"acquirer": "First"})]:
            stream.write(json.dumps({"accession_number": accession, "canonical_fields": values}) + "\n")
    summary, details = evaluate(reference, predictions)
    assert summary["scored_filings"] == 1
    assert summary["excluded_overlap_filings"] == {
        "reference_not_reviewed": 1, "multiple_reference_rows_per_filing": 1,
    }
    assert summary["field_metrics"]["acquirer"]["f1"] == 1
    assert summary["field_metrics"]["target"] == {"tp": 0, "fp": 1, "fn": 1,
                                                    "precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert len(details) == len(FIELDS)


def test_top1_scores_reference_rows_and_marks_provisional(tmp_path: Path):
    reference = tmp_path / "reference.csv"
    with reference.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["accession_number", "event_id", "relevance", *FIELDS])
        writer.writeheader()
        writer.writerow({"accession_number": "one", "event_id": "deal-1",
                         "relevance": "candidate_not_verified", "acquirer": "Acme Corp", "target": "Beta Inc"})
        writer.writerow({"accession_number": "one", "event_id": "deal-2",
                         "relevance": "candidate_not_verified", "acquirer": "Other Corp", "target": "Gamma Inc"})
        writer.writerow({"accession_number": "missing", "event_id": "deal-3",
                         "relevance": "candidate_not_verified", "acquirer": "Missing Corp"})
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({"accession_number": "one", "candidates": {
        "acquirer": [{"value": "Acme Corp", "score": 0.9}],
        "target": [{"value": "Beta Inc", "score": 0.8}]}}) + "\n")
    summary, details = evaluate_top1(reference, predictions, fields=("acquirer", "target"))
    assert summary["rows_scored"] == 2
    assert summary["overlap_accessions"] == 1
    assert summary["micro"]["tp"] == 2
    assert summary["micro"]["fp"] == summary["micro"]["fn"] == 2
    assert summary["verified_accuracy"] is None
    assert len(details) == 4
    all_summary, _ = evaluate_top1(reference, predictions, fields=("acquirer",), scope="all")
    assert all_summary["rows_scored"] == 3
    assert all_summary["micro"]["fn"] == 2
