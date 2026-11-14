import csv
import json
from pathlib import Path

import pytest

from scripts.eval_merger_reviewed import (
    FIELDS, GOLD_COLUMNS, PRED_COLUMNS, compare, prepare, score, write_csv,
)


def test_prepare_keeps_reference_candidates_out_of_gold(tmp_path: Path):
    reference = tmp_path / "reference.csv"
    write_csv(reference, ("accession_number", "acquirer", "passages", "relevance", *FIELDS[1:]), [
        {"accession_number": "a1", "acquirer": "Acme", "relevance": "candidate_not_verified",
         "passages": json.dumps({"acquirer": [{"quote": "Acme bought Beta"}]})},
    ])
    gliner = tmp_path / "gliner.jsonl"
    gliner.write_text(json.dumps({"accession_number": "a1", "text_sha256": "hash",
                                  "candidates": {"acquirer": [{"value": "Acme", "score": 0.9,
                                                               "source_quote": "Acme bought Beta", "start": 0, "end": 4}]}}) + "\n")
    gold, predictions, summary = prepare(reference, gliner)
    assert summary["overlap_filings"] == 1
    assert len(gold) == len(predictions) == len(FIELDS)
    assert gold[0]["reference_candidate"] == "Acme"
    assert gold[0]["gold_value"] == ""
    assert gold[0]["review_status"] == "unreviewed"
    assert predictions[0]["predicted_value"] == "Acme"


def test_reviewed_scoring_counts_wrong_values_and_excludes_unknown(tmp_path: Path):
    gold = tmp_path / "gold.csv"
    preds = tmp_path / "pred.csv"
    base = {"reference_row_id": "r1", "accession_number": "a1", "deal_id": "deal-1",
            "review_status": "verified", "reviewer": "analyst", "gold_evidence": "verified SEC passage"}
    write_csv(gold, GOLD_COLUMNS, [
        {**base, "field": "acquirer", "gold_state": "present", "gold_value": "Acme"},
        {**base, "field": "target", "gold_state": "present", "gold_value": "Beta",
         "comparison_override": "mismatch", "comparison_reviewer": "analyst", "comparison_note": "different company"},
        {**base, "field": "ticker", "gold_state": "absent"},
        {**base, "field": "effective_date", "gold_state": "unknown"},
        {**base, "field": "closing_conditions", "gold_state": "present", "gold_value": "Regulatory approval"},
    ])
    write_csv(preds, PRED_COLUMNS, [
        {"accession_number": "a1", "field": "acquirer", "predicted_value": "Acme"},
        {"accession_number": "a1", "field": "target", "predicted_value": "Gamma"},
        {"accession_number": "a1", "field": "ticker", "predicted_value": "ABC"},
        {"accession_number": "a1", "field": "closing_conditions", "predicted_value": "Antitrust clearance"},
    ])
    summary, details = score(gold, preds)
    assert summary["micro"]["tp"] == 1
    assert summary["micro"]["fp"] == 2  # wrong target and spurious ticker
    assert summary["micro"]["fn"] == 1
    assert summary["excluded_cells"]["unknown_gold"] == 1
    assert summary["excluded_cells"]["needs_comparison_review"] == 1
    assert summary["micro"]["f1"] == 0.4
    assert len(details) == 4


def test_multi_deal_requires_prediction_alignment_and_override_audit(tmp_path: Path):
    gold, preds = tmp_path / "gold.csv", tmp_path / "pred.csv"
    rows = []
    for deal in ("d1", "d2"):
        rows.append({"reference_row_id": deal, "accession_number": "a1", "deal_id": deal,
                     "field": "acquirer", "gold_state": "present", "gold_value": "Acme",
                     "gold_evidence": "SEC quote", "review_status": "verified", "reviewer": "analyst"})
    write_csv(gold, GOLD_COLUMNS, rows)
    write_csv(preds, PRED_COLUMNS, [{"accession_number": "a1", "field": "acquirer", "predicted_value": "Acme"}])
    summary, _ = score(gold, preds)
    assert summary["accuracy_status"] == "not_scorable"
    assert summary["excluded_cells"]["multi_deal_unaligned"] == 2
    rows[0].update({"comparison_override": "match", "comparison_reviewer": "analyst", "comparison_note": "verified alias"})
    write_csv(gold, GOLD_COLUMNS, rows)
    write_csv(preds, PRED_COLUMNS, [{"accession_number": "a1", "deal_id": "d1", "field": "acquirer", "predicted_value": "Acme"}])
    summary, _ = score(gold, preds)
    assert summary["micro"]["tp"] == 1
    assert summary["excluded_cells"]["multi_deal_unaligned"] == 1
    assert compare("cash_consideration", "$539.22", "539.22 USD") == "match"
    assert compare("effective_date", "January 1, 2026", "2026-01-01") == "match"
