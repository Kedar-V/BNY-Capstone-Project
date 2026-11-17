from __future__ import annotations

from src.preprocess.rules_ids import find_settlement_date


def test_payment_date_wired_on_is_returned_normalized():
    text = "The Fund paid on or about January 5, 2026 to the tendering Unit Holders a total of $6,368,623.73."
    assert find_settlement_date(text) == "1/5/2026"


def test_valuation_and_fiscal_dates_are_not_chosen():
    text = ("The Fund accepted for payment Shares as of March 31, 2025, the net asset value as of "
            "December 31, 2024. Payment for the Shares was wired on April 22, 2025.")
    assert find_settlement_date(text) == "4/22/2025"


def test_relative_timing_returns_none_not_template():
    text = "Properly tendered Shares will be accepted for payment promptly following expiration of the Offer."
    assert find_settlement_date(text) is None


def test_no_pay_context_returns_none():
    assert find_settlement_date("The Offer expires on February 8, 2026.") is None
