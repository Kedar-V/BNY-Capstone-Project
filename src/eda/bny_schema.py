"""Canonical BNY client-notification schema for corporate-action EDA.

Field definitions come from the project target schema provided for the capstone.
Coverage estimates in this package distinguish:
  - observed_metadata: present in SEC/EFTS structured fields
  - inferred_regex_presence: heuristic mention detection in downloaded text
  - internal_only: cannot be obtained from public documents
  - not_applicable: typically irrelevant for the observed event type
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


EvidenceType = Literal[
    "observed_metadata",
    "inferred_regex_presence",
    "derived_rule",
    "internal_only",
    "not_measured",
]

SourceClass = Literal[
    "public_document_extractable",
    "derived_from_public",
    "bny_internal_only",
    "unclear_requires_investigation",
]

Difficulty = Literal["low", "medium", "high", "n/a"]
GroundTruthClass = Literal[
    "strong_automatic",
    "weak_heuristic",
    "requires_manual_annotation",
    "cannot_evaluate_from_public",
]


@dataclass(frozen=True)
class SchemaField:
    name: str
    group: str
    source_class: SourceClass
    explicit_or_derived: str
    default_difficulty: Difficulty
    ground_truth: GroundTruthClass
    relevance_note: str
    # Patterns used only for public/derived fields when scanning document text.
    patterns: tuple[re.Pattern[str], ...] = ()


def _p(*exprs: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(e, re.I | re.S) for e in exprs)


BNY_SCHEMA: list[SchemaField] = [
    # --- Notification / event metadata ---
    SchemaField(
        "notification_family",
        "notification_metadata",
        "derived_from_public",
        "derived",
        "low",
        "weak_heuristic",
        "Can be mapped from corporate-action family (e.g., tender/offer) but is a BNY taxonomy label.",
        _p(r"\btender\s+offer\b", r"\boffer\s+to\s+purchase\b"),
    ),
    SchemaField(
        "notification_type",
        "notification_metadata",
        "derived_from_public",
        "derived",
        "medium",
        "requires_manual_annotation",
        "BNY notification_type is distinct from corporate_action_type; needs mapping table.",
        _p(r"\b(new|amended|updated|cancelled|withdrawn)\b.{0,40}\b(offer|tender|notification)\b"),
    ),
    SchemaField(
        "notification_status",
        "notification_metadata",
        "derived_from_public",
        "derived",
        "medium",
        "weak_heuristic",
        "Approximated from initial vs /A filings and cancellation/withdrawal language.",
        _p(r"\b(amendment|amended|withdrawn|withdrawal|cancell?ed|terminated|expired|completed)\b"),
    ),
    SchemaField(
        "processing_status",
        "notification_metadata",
        "bny_internal_only",
        "internal",
        "n/a",
        "cannot_evaluate_from_public",
        "BNY workflow state; not present in public SEC filings.",
    ),
    SchemaField(
        "mandatory_voluntary_indicator",
        "notification_metadata",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Often stated for tenders (voluntary) but wording varies.",
        _p(r"\bvoluntary\s+tender\b", r"\bmandatory\b", r"\bholders?\s+may\s+tender\b", r"\boptional\b"),
    ),
    # --- Security ---
    SchemaField(
        "security_description",
        "security",
        "public_document_extractable",
        "explicit",
        "low",
        "weak_heuristic",
        "Usually in cover page / offer title; also partly in EFTS display names.",
        _p(r"\bcommon\s+stock\b", r"\bordinary\s+shares?\b", r"\bnotes?\b", r"\bdebentures?\b", r"\bpreferred\s+stock\b"),
    ),
    SchemaField(
        "isin",
        "security",
        "public_document_extractable",
        "explicit",
        "low",
        "requires_manual_annotation",
        "Present in many offer docs but not in EFTS metadata.",
        _p(r"\bISIN\b[:\s]*[A-Z]{2}[A-Z0-9]{9}\d\b", r"\bISIN\b"),
    ),
    SchemaField(
        "cusip",
        "security",
        "public_document_extractable",
        "explicit",
        "low",
        "requires_manual_annotation",
        "Common in U.S. tender materials.",
        _p(r"\bCUSIP\b[:\s]*[0-9A-Z]{6}[0-9A-Z]{2}[0-9]\b", r"\bCUSIP\b[:\sNo.]*[0-9A-Z]{8,9}\b", r"\bCUSIP\b"),
    ),
    SchemaField(
        "ticker",
        "security",
        "public_document_extractable",
        "explicit",
        "low",
        "weak_heuristic",
        "Sometimes in EFTS display_names; otherwise in document text.",
        _p(r"\bticker\s+symbol\b", r"\bNYSE\b", r"\bNasdaq\b", r"\bTrading\s+Symbol\b"),
    ),
    SchemaField(
        "currency",
        "security",
        "public_document_extractable",
        "explicit",
        "low",
        "weak_heuristic",
        "Often USD implied for U.S. cash tenders; explicit currency labels vary.",
        _p(r"\bU\.?S\.?\s*dollars?\b", r"\bUSD\b", r"\bEUR\b", r"\bpound\s+sterling\b", r"\bcurrency\b"),
    ),
    SchemaField(
        "coupon_rate",
        "security",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant mainly for debt tenders / exchange offers.",
        _p(r"\bcoupon\b", r"\binterest\s+rate\b", r"\b%\s*per\s+annum\b"),
    ),
    SchemaField(
        "maturity_date",
        "security",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant mainly for debt instruments.",
        _p(r"\bmaturit(?:y|ies)\b", r"\bdue\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\b"),
    ),
    # --- Event ---
    SchemaField(
        "corporate_action_type",
        "event",
        "derived_from_public",
        "derived",
        "low",
        "strong_automatic",
        "Derived from SEC form family (tender offer / issuer tender / target recommendation).",
        _p(r"\btender\s+offer\b", r"\bexchange\s+offer\b", r"\boffer\s+to\s+purchase\b"),
    ),
    SchemaField(
        "event_subtype",
        "event",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "E.g., cash tender, exchange offer, odd-lot, Dutch auction, fund repurchase.",
        _p(r"\bDutch\s+auction\b", r"\bmodified\s+Dutch\b", r"\bexchange\s+offer\b", r"\bodd[- ]lot\b", r"\bfixed[- ]price\b"),
    ),
    SchemaField(
        "effective_date",
        "event",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "May appear as commencement / effective date of the offer.",
        _p(r"\beffective\s+date\b", r"\bcommencement\s+date\b", r"\boffer\s+commences?\b"),
    ),
    SchemaField(
        "record_date",
        "event",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Less common for classic cash tenders; more for rights/exchange variants.",
        _p(r"\brecord\s+date\b"),
    ),
    SchemaField(
        "ex_date",
        "event",
        "unclear_requires_investigation",
        "derived",
        "high",
        "cannot_evaluate_from_public",
        "Typically market-calendar concept; rarely a primary Schedule TO field.",
        _p(r"\bex[- ](?:dividend|date)\b"),
    ),
    SchemaField(
        "payment_date",
        "event",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Often described as payment / settlement timing after expiration.",
        _p(r"\bpayment\s+date\b", r"\bwill\s+be\s+paid\b", r"\bpromptly\s+after\b.{0,40}\bexpir"),
    ),
    SchemaField(
        "settlement_date",
        "event",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Often narrative ('promptly after expiration') rather than a fixed date.",
        _p(r"\bsettlement\s+date\b", r"\bsettle(?:ment|d)\b"),
    ),
    # --- Conversion / exchange ---
    SchemaField(
        "old_security_description",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant for exchange offers / conversions.",
        _p(r"\bold\s+notes?\b", r"\bexisting\s+(common\s+stock|notes?|shares?)\b", r"\bsecurities\s+to\s+be\s+exchanged\b"),
    ),
    SchemaField(
        "old_security_isin",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant for exchange offers when ISINs are disclosed.",
        _p(r"\bISIN\b"),
    ),
    SchemaField(
        "new_security_description",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant for exchange offers / conversions.",
        _p(r"\bnew\s+notes?\b", r"\bexchange\s+for\b", r"\breplacement\s+securities\b"),
    ),
    SchemaField(
        "new_security_isin",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Relevant for exchange offers when ISINs are disclosed.",
        _p(r"\bISIN\b"),
    ),
    SchemaField(
        "conversion_ratio",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "high",
        "requires_manual_annotation",
        "Mostly exchange/conversion events; uncommon in pure cash tenders.",
        _p(r"\bconversion\s+ratio\b", r"\bexchange\s+ratio\b", r"\bper\s+share\b.{0,30}\bshare"),
    ),
    SchemaField(
        "conversion_price",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "high",
        "requires_manual_annotation",
        "Mostly convertible / exchange contexts.",
        _p(r"\bconversion\s+price\b"),
    ),
    SchemaField(
        "redemption_amount",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Debt redemption / tender contexts.",
        _p(r"\bredemption\s+(amount|price)\b", r"\bredeem(?:ed|able)?\b"),
    ),
    SchemaField(
        "call_price",
        "conversion_exchange",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Callable debt contexts.",
        _p(r"\bcall\s+price\b", r"\bmake[- ]whole\b"),
    ),
    # --- Election / response ---
    SchemaField(
        "election_required",
        "election_response",
        "derived_from_public",
        "derived",
        "medium",
        "weak_heuristic",
        "Inferred if holders must elect among options / tender or not.",
        _p(r"\belection\b", r"\bholders?\s+must\b", r"\bchoose\b", r"\belect\s+to\b"),
    ),
    SchemaField(
        "available_options",
        "election_response",
        "public_document_extractable",
        "explicit",
        "high",
        "requires_manual_annotation",
        "Cash/stock/mixed elections; option lists are narrative-heavy.",
        _p(r"\bcash\s+election\b", r"\bstock\s+election\b", r"\bmixed\s+consideration\b", r"\boption\s+[A-C]\b", r"\bproration\b"),
    ),
    SchemaField(
        "default_option",
        "election_response",
        "public_document_extractable",
        "explicit",
        "high",
        "requires_manual_annotation",
        "Often buried in election mechanics.",
        _p(r"\bdefault\s+(option|election)\b", r"\bif\s+no\s+election\b"),
    ),
    SchemaField(
        "election_deadline",
        "election_response",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "May coincide with expiration date for tenders.",
        _p(r"\belection\s+deadline\b", r"\bexpiration\s+date\b", r"\bexpir(?:e|es|ation)\b"),
    ),
    SchemaField(
        "response_deadline",
        "election_response",
        "public_document_extractable",
        "explicit",
        "medium",
        "requires_manual_annotation",
        "Overlap with expiration / withdrawal deadlines in tender docs.",
        _p(r"\bresponse\s+deadline\b", r"\bwithdraw(?:al)?\b.{0,40}\b(deadline|right|until)\b", r"\bExpiration\s+Date\b"),
    ),
    SchemaField(
        "cancellation_reason",
        "election_response",
        "public_document_extractable",
        "explicit",
        "high",
        "requires_manual_annotation",
        "Only when offer is terminated/withdrawn/cancelled.",
        _p(r"\b(terminat(?:e|ed|ion)|withdraw(?:n|al)|cancell?(?:ed|ation))\b.{0,80}\b(because|due to|reason)\b", r"\boffer\s+has\s+been\s+(terminated|withdrawn|cancelled)\b"),
    ),
    # --- Position / payment ---
    SchemaField(
        "eligible_quantity",
        "position_payment",
        "bny_internal_only",
        "internal",
        "n/a",
        "cannot_evaluate_from_public",
        "Client-position specific; not in public filings.",
    ),
    SchemaField(
        "position_quantity",
        "position_payment",
        "bny_internal_only",
        "internal",
        "n/a",
        "cannot_evaluate_from_public",
        "Client account holdings; internal BNY data.",
    ),
    SchemaField(
        "principal_amount",
        "position_payment",
        "unclear_requires_investigation",
        "derived",
        "high",
        "cannot_evaluate_from_public",
        "Public docs may state aggregate principal sought; client principal is internal.",
        _p(r"\bprincipal\s+amount\b", r"\baggregate\s+principal\b"),
    ),
    SchemaField(
        "interest_amount",
        "position_payment",
        "unclear_requires_investigation",
        "derived",
        "high",
        "cannot_evaluate_from_public",
        "Accrued interest terms may be public; client amount is internal.",
        _p(r"\baccrued\s+interest\b", r"\binterest\s+amount\b"),
    ),
    SchemaField(
        "cash_amount",
        "position_payment",
        "unclear_requires_investigation",
        "derived",
        "high",
        "cannot_evaluate_from_public",
        "Offer price is public; client cash proceeds require position * price.",
        _p(r"\$\s?\d+(?:\.\d+)?\s+per\s+(share|note)", r"\boffer\s+price\b", r"\bcash\s+consideration\b"),
    ),
    SchemaField(
        "debit_credit_indicator",
        "position_payment",
        "bny_internal_only",
        "internal",
        "n/a",
        "cannot_evaluate_from_public",
        "Ledger posting direction; BNY internal.",
    ),
]


SCHEMA_BY_NAME = {f.name: f for f in BNY_SCHEMA}


# Event-type relevance priors used only to separate N/A vs missing-relevant.
# These are analytical assumptions, labeled as such in outputs.
RELEVANCE_BY_ACTION: dict[str, dict[str, str]] = {
    # values: relevant | optional | not_relevant
    "third_party_tender": {
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
        "eligible_quantity": "not_relevant",
        "position_quantity": "not_relevant",
        "debit_credit_indicator": "not_relevant",
        "processing_status": "not_relevant",
    },
    "issuer_tender": {
        "coupon_rate": "optional",
        "maturity_date": "optional",
        "conversion_ratio": "optional",
        "conversion_price": "optional",
        "ex_date": "not_relevant",
        "eligible_quantity": "not_relevant",
        "position_quantity": "not_relevant",
        "debit_credit_indicator": "not_relevant",
        "processing_status": "not_relevant",
    },
    "target_recommendation": {
        "conversion_ratio": "optional",
        "conversion_price": "optional",
        "coupon_rate": "not_relevant",
        "maturity_date": "not_relevant",
        "eligible_quantity": "not_relevant",
        "position_quantity": "not_relevant",
        "debit_credit_indicator": "not_relevant",
        "processing_status": "not_relevant",
    },
}
