"""Step 4: checks that hold an amendment for an operations reviewer before anything is sent.

A check never changes the tier. It says why a person should look first.
"""

from __future__ import annotations

from datetime import date, timedelta

from events.versioning import Version

from . import config
from .triage import DATE_KEYS, Judgment

DEADLINE_KEYS = DATE_KEYS - {"settlement_date", "effective_date"}


def add_business_days(day: date, n: int) -> date:
    """Weekdays only; holidays are ignored."""
    d = day
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def check_version(action: str, v: Version, judgments: dict[str, Judgment], quote_checker=None) -> list[dict]:
    reasons: list[dict] = []

    def add(code: str, detail: str) -> None:
        reasons.append({"code": code, "detail": detail})

    filed = v.filing.filed
    for c in v.changes:
        if c.kind == "value" and c.key in DEADLINE_KEYS and c.previous is not None:
            if c.current < c.previous:
                add("deadline_moved_earlier", f"{c.key} moved earlier, from {c.previous.isoformat()} to {c.current.isoformat()}.")
            if c.current < filed:
                add("deadline_in_past", f"New {c.key} {c.current.isoformat()} is before the amendment was filed ({filed.isoformat()}); "
                                        "it may be a typo in the source.")
        if c.kind in {"value", "text"} and c.previous is not None and not c.quote:
            add("no_evidence", f"No supporting quote for the {c.key} change in this filing.")
        if quote_checker is not None and c.quote and quote_checker.verified(v.filing.accession, c.quote) is False:
            add("quote_not_found", f"The quote for {c.key} is not in the filing text.")
        if c.kind == "text" and c.previous is not None:
            j = judgments.get(c.key)
            if j is None or j.material is None:
                add("text_not_assessed", f"{c.key} wording changed and has not been judged" + (f": {j.reason}" if j else "."))

    # Rule 14e-1(b): after a price change the offer must stay open for 10 more business days
    price = next((c for c in v.changes if c.key == "offer_price" and c.previous is not None), None)
    if action == "tender_offer" and price:
        expiry = v.after.get("expiration_date")
        earliest = add_business_days(filed, config.PRICE_CHANGE_MIN_BUSINESS_DAYS)
        if expiry and expiry < earliest:
            add("price_change_window", f"Price changed on {filed.isoformat()} but the offer expires {expiry.isoformat()}, "
                                       f"before {earliest.isoformat()} ({config.PRICE_CHANGE_MIN_BUSINESS_DAYS} business days). "
                                       "Expect an extension, or check the dates.")
    return reasons
