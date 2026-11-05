"""Minimal checks for tender GT evaluation."""

from __future__ import annotations

from src.evaluation.tender import (
    CORE_GT_FIELDS,
    GT_TO_HINT,
    GT_VALUE_FIELDS,
    evaluate_tender,
    field_coverage,
    soft_match,
)
from src.preprocess.contracts import LABEL_TO_FIELD_HINT, GLINER_LABELS_TO


def test_field_coverage_complete():
    cov = field_coverage()
    assert cov["ok"], cov
    assert set(GT_VALUE_FIELDS) == set(GT_TO_HINT)
    hints = set(LABEL_TO_FIELD_HINT.values())
    assert set(GT_TO_HINT.values()) <= hints


def test_gliner_labels_back_gt_hints():
    mapped = {LABEL_TO_FIELD_HINT[lab] for lab in GLINER_LABELS_TO if lab in LABEL_TO_FIELD_HINT}
    # Core scored fields must be reachable from pass-1 GLiNER labels
    needed = {GT_TO_HINT[f] for f in CORE_GT_FIELDS}
    assert needed <= mapped | {"offeror", "target", "purchaser"}


def test_soft_match_and_score():
    assert soft_match("$18.75 per share", "18.75")
    # Par value must not match NAV/formula offer text
    assert not soft_match("$0.001", "net asset value per Share as of December 31, 2025")
    assert soft_match("$25.53 per share", "$25.53")
    gt = [
        {
            "accession_number": "A1",
            "subject_company": "Dermira, Inc.",
            "bidder": "Eli Lilly",
            "offer_price": "$18.75",
            "expiration_date": "February 19, 2020",
            **{
                f: "N/A"
                for f in GT_VALUE_FIELDS
                if f not in {"subject_company", "bidder", "offer_price", "expiration_date"}
            },
        }
    ]
    preds = {
        "A1": {
            **{h: None for h in set(GT_TO_HINT.values())},
            "target": "Dermira, Inc.",
            "offeror": "Eli Lilly and Company",
            "offer_price": "$18.75 per Share",
            "expiration_date": "February 19, 2020",
            "_event_id": "e1",
            "_n_facts": 4,
        }
    }
    res = evaluate_tender(gt, preds)
    assert res["per_field"]["subject_company"]["tp"] == 1
    assert res["per_field"]["bidder"]["tp"] == 1
    assert res["per_field"]["offer_price"]["tp"] == 1
    assert res["n_accessions_scored"] == 1
    assert res["n_gt_rows"] == 1
    assert res["per_field"]["offer_price"]["accuracy"] == 1.0
    assert res["micro"]["accuracy"] is not None
    assert res["micro"]["accuracy_when_gt"] is not None

    # Sibling accession under same file-number event
    res_eid = evaluate_tender(
        gt,
        {},
        accession_to_event_id={"A1": "e1"},
        preds_by_event_id={"e1": preds["A1"]},
    )
    assert res_eid["n_accessions_joined_via_event_id"] == 1
    assert res_eid["per_field"]["offer_price"]["tp"] == 1

    # Multi GT rows for same accession each score independently
    gt2 = [
        {**gt[0], "security_description": "Class I"},
        {**gt[0], "security_description": "Class A"},
    ]
    preds2 = {
        "A1": {
            **preds["A1"],
            "security_description": "Class I",
        }
    }
    res2 = evaluate_tender(gt2, preds2, score_fields=CORE_GT_FIELDS)
    assert res2["n_gt_rows"] == 2
    assert res2["n_gt_accessions"] == 1
    assert res2["per_field"]["security_description"]["tp"] == 1
    assert res2["per_field"]["security_description"]["fn"] >= 1
