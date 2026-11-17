from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "clean_tender_gt", Path(__file__).resolve().parents[2] / "scripts" / "clean_tender_gt.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _row(**kw):
    base = {"settlement_date": "", "withdrawal_deadline": ""}
    base.update(kw)
    return base


def test_settlement_payment_date_preferred_and_normalized():
    r = _row(settlement_date="Acceptance: as of February 24, 2026 | Payment: no later than April 30, 2026, unless changed")
    m.clean_settlement(r, [])
    assert r["settlement_date"] == "4/30/2026"
    assert r["settlement_date_raw"].startswith("Acceptance:")
    assert r["settlement_payment"].startswith("no later than April 30")


def test_settlement_relative_timing_becomes_blank_but_text_kept():
    r = _row(settlement_date="Acceptance: promptly after expiration | Payment: promptly after expiration")
    m.clean_settlement(r, [])
    assert r["settlement_date"] == ""
    assert r["settlement_payment"] == "promptly after expiration"


def test_settlement_unlabeled_and_other_labels():
    r = _row(settlement_date="on or about 1/30/2026")
    m.clean_settlement(r, [])
    assert r["settlement_date"] == "1/30/2026"
    r = _row(settlement_date="Acceptance: when notified | Note delivery: within 65 days")
    m.clean_settlement(r, [])
    assert r["settlement_other"].startswith("Note delivery") and r["settlement_date"] == ""


def test_withdrawal_split_and_relative_left_alone():
    r = _row(withdrawal_deadline="1/30/2026 11:59 PM Eastern Time | If not accepted by 3/2/2026, withdrawal is also permitted")
    m.clean_withdrawal(r, [])
    assert r["withdrawal_deadline"] == "1/30/2026 11:59 PM Eastern Time"
    assert r["withdrawal_conditions"].startswith("If not accepted")
    r = _row(withdrawal_deadline="Prior to 40 business days following the Expiration Date, unless already accepted for payment")
    m.clean_withdrawal(r, [])
    assert r["withdrawal_conditions"] == "" and r["withdrawal_deadline"].startswith("Prior to")
    r = _row(withdrawal_deadline="2/6/2026 5:00 PM ET")
    m.clean_withdrawal(r, [])
    assert r["withdrawal_deadline"] == "2/6/2026 5:00 PM ET"
