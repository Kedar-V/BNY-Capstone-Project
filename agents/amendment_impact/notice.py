"""Step 6: the draft replacement notice. A fixed template filled from the record, so every value is exact.

The notice waits in the review queue; operations approves it before anything reaches a client.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from agents.client_briefing.impact import fmt_date, fmt_ratio, fmt_unit_price
from events.store import Event
from events.versioning import FieldChange, Version

from .triage import LABEL, TIER_LABEL


def value_text(key: str, value: Any) -> str:
    """One extracted value in words, matching the client brief's formats."""
    if value is None:
        return "not stated"
    if isinstance(value, date):
        return fmt_date(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if key == "offer_price":
        kind = value.get("kind")
        if kind == "fixed":
            return f"{fmt_unit_price(value['amount'])} per share"
        if kind == "cash_plus":
            return f"{fmt_unit_price(value['amount'])} per share in cash plus a contingent right"
        if kind == "range":
            return f"{fmt_unit_price(value['low'])} to {fmt_unit_price(value['high'])} per share"
        return "a formula price" if kind == "formula" else "non-cash consideration"
    if key == "price":
        return "a formula price" if value.get("amount") is None else fmt_unit_price(value["amount"], value.get("currency"))
    if key == "ratio":
        parts = []
        if value.get("rights_per_share") is not None:
            parts.append(f"{fmt_ratio(value['rights_per_share'])} right per share")
        if value.get("shares_per_right") is not None:
            parts.append(f"{fmt_ratio(value['shares_per_right'])} new share per right")
        return "; ".join(parts)
    if key == "cash_per_share":
        return f"{fmt_unit_price(value)} per share"
    if key == "exchange_ratio":
        return f"{fmt_ratio(value)} shares per share"
    return str(value)


def change_line(c: FieldChange) -> str:
    label = LABEL.get(c.key, c.key)
    if c.kind == "status":
        return f"{label}: now {c.current}" + (f" (was {c.previous})" if c.previous else "")
    if c.kind == "text":
        return f"{label} changed. New wording: {c.current}"
    if c.previous is None:
        return f"{label}: {value_text(c.key, c.current)}"
    return f"{label}: {value_text(c.key, c.previous)} → {value_text(c.key, c.current)}"


def draft(event: Event, v: Version, tier: str, notified: list[FieldChange], holders: list[dict]) -> dict | None:
    """Notice for an action-needed or informational amendment; None when nothing is sent."""
    if tier not in {"action", "informational"} or not notified:
        return None
    f = v.filing
    held = [h for h in holders if not h["watch_only"]]
    return {
        "subject": f"{TIER_LABEL[tier]}: {event.title} amended",
        "lines": [change_line(c) for c in notified],
        "source": f"{f.form} filed {fmt_date(f.filed)}",
        "url": f.url,
        "evidence": [{"field": c.key, "quote": c.quote, "location": c.location} for c in notified if c.quote],
        "recipients": sorted({h["client"] for h in held}),
        "watchers": sorted({h["client"] for h in holders if h["watch_only"]}),
    }
