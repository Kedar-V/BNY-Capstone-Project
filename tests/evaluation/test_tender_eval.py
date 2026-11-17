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
    # Thousands separators are noise (bare number ≡ comma-formatted)
    assert soft_match("1,400", "1400")
    assert soft_match("1400", "1,400.00")
    assert not soft_match("1,400", "140")
    # Currency field: symbol ≡ ISO (and not a price amount)
    assert soft_match("$", "USD")
    assert soft_match("USD", "$")
    assert soft_match("US$", "USD")
    assert soft_match("€", "EUR")
    assert soft_match("U.S. dollars", "USD")
    assert not soft_match("$18.75", "USD")
    assert not soft_match("$", "EUR")
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


def test_no_minimum_tender_condition_is_treated_as_empty():
    from src.evaluation.tender import normalize, soft_match

    assert normalize("No minimum tender condition") == ""
    assert normalize("no Minimum Tender Condition ") == ""
    assert normalize("∅") == ""
    assert normalize("No proration") == ""
    assert (
        normalize(
            "The Offer is being made to all Shareholders of the Fund and is not "
            "conditioned on any minimum number of Shares being tendered."
        )
        == ""
    )
    assert normalize("The Offer is not conditioned upon any minimum number of Shares.") == ""
    assert not soft_match("No minimum tender condition", "No minimum tender condition")
    assert normalize("a majority of the outstanding Shares") != ""
    # Real threshold text must stay present even if it mentions "minimum".
    assert normalize("at least 50% minimum tender condition") != ""


def test_currency_backfilled_from_passage_and_undecided_rows():
    from src.evaluation.tender import _backfill_currency, _gold_rows

    ok = {"accession_number": "a", "offer_price": "30.00", "currency": "",
          "passage": str({"offer_price": [{"quote": "purchase price of $30.00 per Share"}]})}
    _backfill_currency(ok)
    assert ok["currency"] == "USD"

    unk = {"accession_number": "b", "offer_price": "Net asset value per Share", "currency": "",
           "passage": str({"offer_price": [{"quote": "net asset value per Share as of the Valuation Date"}]})}
    _backfill_currency(unk)
    assert unk["currency"] == "" and unk["_currency_undecided"] == "1"
    (_, _, fields), = _gold_rows([unk])
    assert fields["_undecided"] == {"currency"} and "currency" not in fields

    nop = {"accession_number": "c", "offer_price": "", "currency": "", "passage": "{}"}
    _backfill_currency(nop)
    assert "_currency_undecided" not in nop


def test_bare_number_gold_matches_priced_predictions():
    from src.evaluation.tender import soft_match

    for pred in ("$30.00", "$30.00 per Share", "30.00 per share", "30.00"):
        assert soft_match(pred, "30.00"), pred
    assert not soft_match("$0.001", "30.00")
    assert not soft_match("$252 billion", "30")
