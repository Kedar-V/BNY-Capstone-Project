"""Settlement timing rules (GT is mostly Payment:/promptly language)."""

from __future__ import annotations

from src.evaluation.tender import soft_match
from src.preprocess.rules_ids import RULE_FIELD_HINTS, find_settlement


def test_settlement_owned_by_rules() -> None:
    assert "settlement_date" in RULE_FIELD_HINTS


def test_find_settlement_pay_date() -> None:
    text = (
        "As of January 22, 2026, in accordance with the terms of the Offer, "
        "the Company accepted for payment all of the Tendered Shares."
    )
    pred = find_settlement(text)
    assert pred == "January 22, 2026"
    assert soft_match(pred, "Acceptance for payment: 1/22/2026")


def test_find_settlement_promptly_beats_nearby_date() -> None:
    """Promptly-pay language wins over a nearby calendar date (CR shape)."""
    text = (
        "The Offer will expire on February 8, 2026. Purchaser will pay for "
        "all Shares accepted for payment promptly after the Expiration Date."
    )
    pred = find_settlement(text)
    assert pred == "Payment: promptly"
    assert soft_match(pred, "Acceptance: after the expiration of the Offer | Payment: promptly")


def test_find_settlement_promptly_following() -> None:
    text = "Properly tendered Shares will be accepted for payment promptly following expiration of the Offer."
    pred = find_settlement(text)
    assert pred == "Payment: promptly"
    assert soft_match(
        pred,
        "Acceptance: promptly following expiration of the Offer | Payment: promptly following expiration of the Offer",
    )
    assert soft_match(pred, "Acceptance: after the expiration of the Offer | Payment: promptly")


def test_find_settlement_promptly_short() -> None:
    text = "After the expiration of the Offer, Purchaser will promptly pay for all Shares accepted."
    pred = find_settlement(text)
    assert pred == "Payment: promptly"
    assert soft_match(pred, "Acceptance: after the expiration of the Offer | Payment: promptly")
