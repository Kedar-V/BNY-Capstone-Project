"""Step 3: does the change matter to holders? Rules decide every clear case; only reworded text needs judgment.

Each change gets a tier, and the filing takes the most urgent one:
  action         holders may need to act, or act differently (deadline, price or terms moved, offer ended)
  needs_review   descriptive text changed and nobody has judged it yet (no LLM, or the LLM was unsure)
  informational  worth telling holders, nothing to do (offer completed, settlement or closing date set)
  log_only       nothing a holder acts on (results only, restated terms, same value written differently)
"""

from __future__ import annotations

from dataclasses import dataclass

from events.versioning import FieldChange

TIER_ORDER = ["action", "needs_review", "informational", "log_only"]
TIER_LABEL = {"action": "Action needed", "needs_review": "Needs review", "informational": "Informational", "log_only": "Log only"}

# A change in one of these alters what a holder receives, or what they must do and by when
ACTION_KEYS = {"expiration_date", "withdrawal_deadline", "election_deadline", "record_date", "vote_date",
               "offer_price", "price", "ratio", "cash_per_share", "exchange_ratio"}
INFO_KEYS = {"settlement_date", "effective_date", "oversubscription", "transferable", "security_class"}
DATE_KEYS = {"expiration_date", "withdrawal_deadline", "election_deadline", "record_date", "vote_date",
             "settlement_date", "effective_date"}
ENDED = {"terminated", "withdrawn"}

LABEL = {"expiration_date": "Expiration", "withdrawal_deadline": "Withdrawal deadline", "election_deadline": "Election deadline",
         "record_date": "Record date", "vote_date": "Shareholder vote", "offer_price": "Offer price", "price": "Subscription price",
         "ratio": "Subscription ratio", "cash_per_share": "Cash consideration", "exchange_ratio": "Stock consideration",
         "settlement_date": "Settlement date", "effective_date": "Closing / issuance date", "oversubscription": "Over-subscription",
         "transferable": "Rights transferable", "security_class": "Security", "event_status": "Status",
         "minimum_tender_condition": "Minimum tender condition", "proration_terms": "Proration terms",
         "tendering_conditions": "How to tender", "conditions_restrictions": "Offer conditions",
         "available_options": "Holder options", "default_option": "If no election is made",
         "consideration_type": "Consideration type", "closing_conditions": "Closing conditions"}


@dataclass
class Judgment:
    """A decision on a text change, by the LLM or a person."""

    material: bool | None
    reason: str
    quote: str | None = None
    source: str = "llm"


def change_tier(c: FieldChange, judgment: Judgment | None = None) -> tuple[str, str]:
    """(tier, reason) for one change."""
    label = LABEL.get(c.key, c.key)
    if c.kind == "status":
        if c.current in ENDED:
            return "action", f"Offer {c.current}: holders' instructions no longer apply"
        if c.current == "completed":
            return "informational", "Event completed: final results"
        return "log_only", f"Status now {c.current}"
    if c.kind == "text":
        if c.previous is None:
            return "log_only", f"{label} stated for the first time"
        if judgment is None or judgment.material is None:
            return "needs_review", f"{label} wording changed; needs a judgment on whether holders are affected"
        if judgment.material:
            return "action", f"{label} changed: {judgment.reason}"
        return "log_only", f"{label} reworded with no effect on holders: {judgment.reason}"
    if c.key in ACTION_KEYS:
        if c.previous is None:
            return "informational", f"{label} stated for the first time"
        return "action", f"{label} changed"
    if c.key in INFO_KEYS:
        return "informational", f"{label} {'set' if c.previous is None else 'changed'}"
    return "log_only", f"{label} changed"


def filing_tier(tiers: list[str]) -> str:
    return min(tiers, key=TIER_ORDER.index) if tiers else "log_only"
