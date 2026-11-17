from __future__ import annotations

from src.preprocess.rules_ids import settlement_accept


def test_accepts_date_after_payment_cue():
    ev = "The Fund paid on or about January 5, 2026 to the tendering Unit Holders."
    assert settlement_accept("1/5/2026", ev)
    assert settlement_accept("January 5, 2026", ev)


def test_rejects_date_without_payment_cue():
    ev = "Valuation Date: March 31, 2025. The Offer expires on February 8, 2026."
    assert not settlement_accept("3/31/2025", ev)
    assert not settlement_accept("2/8/2026", ev)


def test_accepts_payment_promptly_template_when_cue_present():
    """Oracle Settlement template: keep GT-shaped promptly when evidence supports it."""
    ev = "Shares will be accepted for payment promptly following expiration of the Offer."
    assert settlement_accept("Payment: promptly", ev)
    assert not settlement_accept("promptly", ev)  # bare relative timing still rejected


def test_accepts_payment_promptly_even_without_filing_span_in_bundle():
    # Frozen rules bundles may omit the promptly span; template form is still kept.
    ev = "The Offer expires on February 8, 2026. Valuation Date: March 31, 2025."
    assert settlement_accept("Payment: promptly", ev)


def test_rejects_date_not_in_evidence():
    ev = "Payment was wired on April 22, 2025."
    assert not settlement_accept("5/29/2025", ev)


def test_rejects_non_date_values_and_empty_evidence():
    assert not settlement_accept("", "paid on 1/5/2026")
    assert not settlement_accept("1/5/2026 and more", "paid on 1/5/2026")
    assert not settlement_accept("1/5/2026", "")


def test_accepts_date_with_payment_word_nearby_not_only_strong_cue():
    ev = "Payment for the tendered Shares was made in cash on May 29, 2025, the settlement date."
    assert settlement_accept("5/29/2025", ev)


def test_rejects_valuation_date_even_near_payment_word():
    ev = "The Fund paid the net asset value as of March 31, 2025 to holders."
    assert not settlement_accept("3/31/2025", ev)
