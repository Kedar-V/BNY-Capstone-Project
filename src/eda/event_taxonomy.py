"""MVP corporate-action taxonomy: target event types and public SEC sources.

BNY-aligned MVP focus (voluntary / mandatory-with-options / complex narrative):

  1. Tender offers
  2. Exchange offers
  3. Rights issues
  4. Mergers
  5. Conversions

The current downloaded corpus is tender-centric (Schedule TO + SC 14D9).
Other types are defined here so EDA / datastore design can measure coverage gaps
and drive the next corpus expansion without inventing field percentages.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MvpEventType:
    """One target corporate-action class for the notification MVP."""

    key: str
    label: str
    bny_corporate_action_type: str  # suggested BNY-facing label
    description: str
    primary_sec_forms: tuple[str, ...]
    supporting_sec_forms: tuple[str, ...]
    typical_extractable_fields: tuple[str, ...]
    corpus_status: str  # collected | partial_in_tender_corpus | not_collected
    notes: str


MVP_EVENT_TYPES: tuple[MvpEventType, ...] = (
    MvpEventType(
        key="tender_offer",
        label="Tender offer",
        bny_corporate_action_type="TENDER OFFER",
        description=(
            "Cash or mixed tender where holders may tender securities by a deadline. "
            "Includes third-party (SC TO-T) and issuer self-tenders (SC TO-I)."
        ),
        primary_sec_forms=("SC TO-T", "SC TO-T/A", "SC TO-I", "SC TO-I/A"),
        supporting_sec_forms=("SC 14D9", "SC 14D9/A"),
        typical_extractable_fields=(
            "corporate_action_type",
            "security_description",
            "cusip",
            "ticker",
            "election_deadline",
            "response_deadline",
            "cash_amount",  # offer price proxy
            "notification_status",
            "available_options",
            "cancellation_reason",
        ),
        corpus_status="collected",
        notes="Primary corpus today. Prefer third-party + 14D9 mixed events for MVP v1.",
    ),
    MvpEventType(
        key="exchange_offer",
        label="Exchange offer",
        bny_corporate_action_type="EXCHANGE",
        description=(
            "Holders exchange old securities for new securities and/or cash. "
            "Often filed on Schedule TO and/or Form S-4."
        ),
        primary_sec_forms=("SC TO-T", "SC TO-T/A", "SC TO-I", "SC TO-I/A", "S-4", "S-4/A"),
        supporting_sec_forms=("SC 14D9", "SC 14D9/A", "424B3", "8-K", "425"),
        typical_extractable_fields=(
            "corporate_action_type",
            "old_security_description",
            "new_security_description",
            "conversion_ratio",  # exchange ratio
            "election_deadline",
            "available_options",
            "cusip",
            "settlement_date",
        ),
        corpus_status="collected",
        notes=(
            "S-4 now collected via merger_exchange track. Some exchange offers also appear "
            "inside Schedule TO; prefer S-4 + TO narrative for exchange-specific fields."
        ),
    ),
    MvpEventType(
        key="rights_issue",
        label="Rights issue",
        bny_corporate_action_type="RIGHTS ISSUE",
        description=(
            "Tradable or non-tradable rights to subscribe for new shares, usually with "
            "subscription price, ratio, and expiration."
        ),
        primary_sec_forms=("424B2", "424B3", "424B5", "S-3", "S-3ASR"),
        supporting_sec_forms=("8-K", "424B4"),
        typical_extractable_fields=(
            "corporate_action_type",
            "security_description",
            "record_date",
            "ex_date",
            "election_deadline",
            "conversion_ratio",  # rights ratio
            "cash_amount",  # subscription price proxy
            "available_options",
            "default_option",
        ),
        corpus_status="collected",
        notes="Collected via EFTS 424B2/3/5 + rights-offering text filter (not all 424B filings).",
    ),
    MvpEventType(
        key="merger",
        label="Merger",
        bny_corporate_action_type="MERGER",
        description=(
            "Merger / business combination with cash, stock, or election consideration. "
            "Often mandatory-with-options for shareholders."
        ),
        primary_sec_forms=("DEFM14A", "PREM14A", "S-4", "S-4/A", "SC 13E3", "SC 13E3/A"),
        supporting_sec_forms=("8-K", "425"),
        typical_extractable_fields=(
            "corporate_action_type",
            "security_description",
            "old_security_description",
            "new_security_description",
            "available_options",
            "default_option",
            "election_deadline",
            "effective_date",
            "conversion_ratio",
            "cash_amount",
        ),
        corpus_status="collected",
        notes="Collected DEFM14A / PREM14A / S-4 / SC 13E3 / 425 via EFTS (2020–2025).",
    ),
    MvpEventType(
        key="conversion",
        label="Conversion",
        bny_corporate_action_type="CONVERSION",
        description=(
            "Convertibles / mandatory conversions / issuer-forced conversions into "
            "another security class, with ratio and conversion price."
        ),
        primary_sec_forms=("8-K", "424B2", "424B3", "S-3", "S-3ASR"),
        supporting_sec_forms=("10-K", "10-Q"),  # indenture exhibits often attached historically
        typical_extractable_fields=(
            "corporate_action_type",
            "old_security_description",
            "new_security_description",
            "conversion_ratio",
            "conversion_price",
            "effective_date",
            "election_deadline",
            "cusip",
            "isin",
        ),
        corpus_status="collected",
        notes=(
            "Collected via EFTS 8-K + conversion-language filter. Still noisy — "
            "manual/event-type labeling recommended before extraction eval."
        ),
    ),
)


MVP_EVENT_TYPE_BY_KEY = {t.key: t for t in MVP_EVENT_TYPES}

# Ordered labels for plots / tables
MVP_EVENT_TYPE_KEYS = tuple(t.key for t in MVP_EVENT_TYPES)

# Union of forms we eventually want in the multi-type public datastore
MVP_ALL_PRIMARY_FORMS: tuple[str, ...] = tuple(
    dict.fromkeys(f for t in MVP_EVENT_TYPES for f in t.primary_sec_forms)
)
MVP_ALL_FORMS: tuple[str, ...] = tuple(
    dict.fromkeys(
        f
        for t in MVP_EVENT_TYPES
        for f in (*t.primary_sec_forms, *t.supporting_sec_forms)
    )
)

# Heuristic narrative cues used only to flag possible subtypes inside downloaded text.
# Presence ≠ confirmed event-type label.
SUBTYPE_TEXT_CUES: dict[str, tuple[str, ...]] = {
    "tender_offer": (r"\btender\s+offer\b", r"\boffer\s+to\s+purchase\b"),
    "exchange_offer": (r"\bexchange\s+offer\b", r"\bexchange\s+ratio\b", r"\bsecurities\s+to\s+be\s+exchanged\b"),
    "rights_issue": (r"\brights?\s+offering\b", r"\bsubscription\s+rights?\b", r"\brights?\s+issue\b"),
    "merger": (r"\bmerger\s+agreement\b", r"\bagreement\s+and\s+plan\s+of\s+merger\b", r"\bbusiness\s+combination\b"),
    "conversion": (r"\bconversion\s+(ratio|price|rate)\b", r"\bmandatory\s+conversion\b", r"\bconvertible\s+(notes?|bonds?|debentures?)\b"),
}


# Field relevance priors by MVP event type (assumption-labeled in EDA outputs).
# values: relevant | optional | not_relevant
_INTERNAL = {
    "eligible_quantity": "not_relevant",
    "position_quantity": "not_relevant",
    "debit_credit_indicator": "not_relevant",
    "processing_status": "not_relevant",
}

RELEVANCE_BY_MVP_TYPE: dict[str, dict[str, str]] = {
    "tender_offer": {
        **_INTERNAL,
        "coupon_rate": "optional",
        "maturity_date": "optional",
        "old_security_description": "optional",
        "old_security_isin": "optional",
        "new_security_description": "optional",
        "new_security_isin": "optional",
        "conversion_ratio": "optional",
        "conversion_price": "optional",
        "redemption_amount": "optional",
        "call_price": "optional",
        "record_date": "optional",
        "ex_date": "not_relevant",
    },
    "exchange_offer": {
        **_INTERNAL,
        "coupon_rate": "optional",
        "maturity_date": "optional",
        "old_security_description": "relevant",
        "new_security_description": "relevant",
        "conversion_ratio": "relevant",
        "conversion_price": "optional",
        "cash_amount": "optional",
        "available_options": "relevant",
        "election_deadline": "relevant",
        "ex_date": "optional",
        "record_date": "optional",
    },
    "rights_issue": {
        **_INTERNAL,
        "record_date": "relevant",
        "ex_date": "relevant",
        "conversion_ratio": "relevant",
        "election_deadline": "relevant",
        "cash_amount": "relevant",
        "available_options": "relevant",
        "default_option": "relevant",
        "old_security_description": "optional",
        "new_security_description": "relevant",
        "coupon_rate": "not_relevant",
        "maturity_date": "not_relevant",
        "call_price": "not_relevant",
        "redemption_amount": "not_relevant",
    },
    "merger": {
        **_INTERNAL,
        "available_options": "relevant",
        "default_option": "relevant",
        "election_deadline": "relevant",
        "effective_date": "relevant",
        "conversion_ratio": "relevant",
        "cash_amount": "relevant",
        "old_security_description": "relevant",
        "new_security_description": "relevant",
        "coupon_rate": "not_relevant",
        "maturity_date": "not_relevant",
        "call_price": "not_relevant",
        "ex_date": "optional",
        "record_date": "optional",
    },
    "conversion": {
        **_INTERNAL,
        "conversion_ratio": "relevant",
        "conversion_price": "relevant",
        "old_security_description": "relevant",
        "new_security_description": "relevant",
        "old_security_isin": "relevant",
        "new_security_isin": "relevant",
        "effective_date": "relevant",
        "election_deadline": "optional",
        "available_options": "optional",
        "cash_amount": "optional",
        "coupon_rate": "optional",
        "maturity_date": "optional",
        "ex_date": "not_relevant",
        "record_date": "optional",
    },
}


def taxonomy_overview_table():
    """Return a pandas DataFrame summarizing MVP event types (lazy import)."""
    import pandas as pd

    rows = []
    for t in MVP_EVENT_TYPES:
        rows.append(
            {
                "mvp_event_type": t.key,
                "label": t.label,
                "bny_corporate_action_type": t.bny_corporate_action_type,
                "corpus_status": t.corpus_status,
                "primary_sec_forms": ", ".join(t.primary_sec_forms),
                "supporting_sec_forms": ", ".join(t.supporting_sec_forms),
                "notes": t.notes,
            }
        )
    return pd.DataFrame(rows)


def corpus_gap_table(collected_forms: set[str] | None = None):
    """Compare target forms vs forms present in the loaded document table."""
    import pandas as pd

    collected_forms = collected_forms or set()
    rows = []
    for t in MVP_EVENT_TYPES:
        primary = set(t.primary_sec_forms)
        supporting = set(t.supporting_sec_forms)
        primary_hit = sorted(primary & collected_forms)
        supporting_hit = sorted(supporting & collected_forms)
        missing_primary = sorted(primary - collected_forms)
        rows.append(
            {
                "mvp_event_type": t.key,
                "label": t.label,
                "corpus_status": t.corpus_status,
                "primary_forms_in_corpus": ", ".join(primary_hit) or "(none)",
                "supporting_forms_in_corpus": ", ".join(supporting_hit) or "(none)",
                "missing_primary_forms": ", ".join(missing_primary) or "(none)",
                "n_primary_forms_present": len(primary_hit),
                "n_primary_forms_target": len(primary),
                "primary_form_coverage_pct": round(100.0 * len(primary_hit) / max(len(primary), 1), 1),
            }
        )
    return pd.DataFrame(rows)
