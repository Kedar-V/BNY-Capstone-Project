"""Stage and backend protocols + shared context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class StageContext:
    path_name: str
    preprocess_root: Path
    event_ids: list[str] | None = None
    cohort: str | None = None
    limit: int | None = None
    force: bool = False
    dry_run: bool = False
    show_progress: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def path_root(self) -> Path:
        return self.preprocess_root / self.path_name

    def event_dir(self, event_id: str) -> Path:
        return self.path_root() / "events" / event_id


@dataclass
class StageResult:
    stage: str
    status: str  # ok | failed | stub_not_implemented | skipped
    n_success: int = 0
    n_failed: int = 0
    n_skipped: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)


@runtime_checkable
class Stage(Protocol):
    name: str

    def run(self, ctx: StageContext) -> StageResult: ...


@runtime_checkable
class SpanBackend(Protocol):
    """Zero-shot / span NER backend (GLiNER or fake)."""

    model_id: str

    def predict(self, text: str, labels: list[str]) -> list[dict[str, Any]]:
        """Return spans: {label, text, score, start, end} (offsets in `text`)."""
        ...


# Value-oriented zero-shot labels (avoid heading echo)
GLINER_LABELS_TO = [
    "offeror_organization",
    "target_organization",
    "purchaser_organization",
    "security_name",
    "cusip_code",
    "isin_code",
    "ticker_symbol",
    "offer_price_amount",
    "expiration_datetime",
    "withdrawal_datetime",
    "effective_datetime",
    "settlement_datetime",
    "minimum_tender_condition",
    "proration_terms",
    "available_option",
    "currency_code",
]

# Narrow second-pass labels when pass-1 is label-like only
GLINER_PASS2_LABELS = [
    "money_amount",
    "calendar_date",
    "org_name",
]

LABELS_SUMMARY_FAQ = [
    "offer_price_amount",
    "expiration_datetime",
    "withdrawal_datetime",
    "offeror_organization",
    "target_organization",
    "purchaser_organization",
    "currency_code",
    "available_option",
    "minimum_tender_condition",
    "cusip_code",
    "ticker_symbol",
]

LABELS_COVER = [
    "offeror_organization",
    "target_organization",
    "purchaser_organization",
    "security_name",
    "cusip_code",
    "ticker_symbol",
    "offer_price_amount",
]

LABEL_TO_FIELD_HINT = {
    # v2 value-oriented
    "offeror_organization": "offeror",
    "target_organization": "target",
    "purchaser_organization": "purchaser",
    "security_name": "security_description",
    "cusip_code": "cusip",
    "isin_code": "isin",
    "ticker_symbol": "ticker",
    "offer_price_amount": "offer_price",
    "expiration_datetime": "expiration_date",
    "withdrawal_datetime": "withdrawal_deadline",
    "effective_datetime": "effective_date",
    "settlement_datetime": "settlement_date",
    "minimum_tender_condition": "minimum_tender_condition",
    "proration_terms": "proration_terms",
    "available_option": "available_option",
    "currency_code": "currency",
    # pass-2 generics
    "money_amount": "offer_price",
    "calendar_date": "expiration_date",
    "org_name": "offeror",
    # legacy v1 labels (still map if present)
    "offeror": "offeror",
    "target": "target",
    "purchaser": "purchaser",
    "security": "security_description",
    "cusip": "cusip",
    "isin": "isin",
    "ticker": "ticker",
    "offer_price": "offer_price",
    "expiration_date": "expiration_date",
    "withdrawal_deadline": "withdrawal_deadline",
    "effective_date": "effective_date",
    "settlement_date": "settlement_date",
    "currency": "currency",
}

# Phrases that are headings / boilerplate, not values (for rank demotion)
LABEL_LIKE_PHRASES = {
    "offer price",
    "offer expiration time",
    "expiration time",
    "expiration date",
    "effective time",
    "effective date",
    "withdrawal rights",
    "withdrawal deadline",
    "settlement date",
    "minimum condition",
    "parent",
    "the offeror",
    "the company",
    "target company",
    "shares",
    "share",
    "common stock",
    "cusip number",
    "title of class of securities",
    "filing persons",
    "subject company",
}

PRIORITY_HEADING_PATTERNS = (
    "summary term sheet",
    "important dates",
    "summary of the offer",
    "questions and answers",
    "q&a",
)
