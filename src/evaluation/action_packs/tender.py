"""Tender-offer ActionPack (CORE_GT_FIELDS + GT-aligned instructions)."""

from __future__ import annotations

from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec, PackHooks
from src.evaluation.tender import CORE_GT_FIELDS, GT_TO_HINT

# Pack-tunable: proration uses clause retrieve + copy prompt (not GLiNER oneshot).
# Fixed-width windows (not period-terminated) so "i.e." / "U.S." cannot truncate.
_PRORATION_PATTERNS = (
    r"(?is)((?:if\s+more\s+than|if\s+shares?\s+in\s+excess\s+of|"
    r"if\s+shares?\s+exceeding).{80,650})",
    r"(?is)((?:pro[\s\-]*rata|proration|oversubscription).{40,500})",
)

_PRORATION_EXTRACT_PROMPT = (
    "Extract proration_terms from the EXCERPT only.\n"
    "Copy the oversubscription / pro-rata sentence(s) into JSON "
    '{{"proration_terms": "..."}}.\n'
    "Prefer the trigger clause ('If more than…' / 'If Shares in excess of…' / "
    "'If Shares exceeding…') plus allocation (pro rata), priorities, and rounding "
    "when they appear in the excerpt.\n"
    "Rules:\n"
    "- Copy wording from the excerpt; light cleanup OK.\n"
    "- Preserve numbers exactly as written; omit thousands separators "
    "(241710.20 not 241,710.20).\n"
    "- Do not calculate a proration percentage.\n"
    "- Do not infer proration from a purchase limit / max amount alone.\n"
    '- Use exactly "No proration" only when the text explicitly says there is none.\n'
    '- If the excerpt has no oversubscription/pro-rata rule, {{"proration_terms": null}}.\n\n'
    'Example: {{"proration_terms": "If more than 5% of Shares are duly tendered and not '
    'withdrawn, the Fund will accept Shares pro rata."}}\n\n'
    "EXCERPT:\n{excerpt}\n"
)

FIELD_DEFS: dict[str, str] = {
    "subject_company": (
        "Company whose securities are tendered (target / issuer). "
        "In an issuer self-tender, same as bidder. Prefer the operating company / fund "
        "name, not law firms or agents."
    ),
    "bidder": (
        "Offeror / purchasing party (GLiNER often labels this offeror or purchaser). "
        "In an issuer self-tender, same as subject_company. "
        "Prefer the company/fund signing the offer — not counsel, depositary, or info agent."
    ),
    "security_description": (
        "Short class/type of security being tendered (e.g. common stock / Class I Shares)."
    ),
    "cusip": "9-character CUSIP from evidence. Copy exactly.",
    "isin": "ISIN from evidence. Copy exactly.",
    "ticker": "Exchange ticker symbol(s) from evidence.",
    "offer_price": (
        "Consideration for tendered shares. Prefer cash like '$25.00 per share' when present; "
        "else NAV phrasing. Copy the best offer_price span value."
    ),
    "currency": (
        "Currency of the cash offer price (USD/GBP/EUR…). "
        "From explicit code/'U.S. dollars', or infer from per-share $ / £ / €. "
        "Skip par value, fees, and aggregate $ millions."
    ),
    "expiration_date": (
        "Offer expiration date/time. Prefer temporal spans with high field_cues for "
        "expiration. Include time/zone if in the span or window."
    ),
    "withdrawal_deadline": (
        "Withdrawal deadline. Prefer temporal spans with withdrawal cues; often same as expiration."
    ),
    "settlement_date": (
        "Payment/acceptance timing. If RULES has 'Payment: promptly', use that. "
        "Else prefer values with payment/settlement/acceptance cues."
    ),
    "effective_date": (
        "Legal effectiveness date (merger closed/consummated/effective, or repurchase as-of). "
        "Prefer temporal spans with effective/consummat cues. Do not use bare expiration dates."
    ),
    "minimum_tender_condition": (
        'Threshold clause, or exactly "No minimum tender condition" when evidence says there is none.'
    ),
    "proration_terms": (
        "Pro-rata / oversubscription sentence from evidence. "
        '"No proration" only if explicitly stated. Preserve numbers (drop thousands commas).'
    ),
}

FIELD_PICK: dict[str, str] = {
    "subject_company": "If multiple org spans exist, pick the target/issuer company, not counsel.",
    "bidder": "If multiple offeror/purchaser spans exist, pick the highest-score company/fund, not a law firm.",
    "offer_price": "If any offer_price span exists, you MUST return one of those values (not null).",
    "cusip": "If any cusip value is listed, return it.",
    "isin": "If any isin value is listed, return it.",
    "ticker": "If any ticker value is listed, return it.",
    "expiration_date": "If temporal spans exist, pick the one with the highest field_cues (then DATE over TIME).",
    "withdrawal_deadline": "If any temporal span has withdrawal cues>0, return that date; else null.",
    "settlement_date": "If RULES lists Payment: promptly / a pay date, return that string.",
    "currency": "If an offer_price span shows a clear $/£/€ per-share price, return USD/GBP/EUR.",
    "effective_date": "Only return a date when cues/window support legal effectiveness; else null.",
    "security_description": "If a security_description span exists, return it.",
    "minimum_tender_condition": "If a matching span/fact exists, return it; else null.",
    "proration_terms": "If a proration span/fact exists, return it; else null.",
}

HINT_ALLOW: dict[str, frozenset[str]] = {
    "subject_company": frozenset({"target", "subject_company", "issuer"}),
    "bidder": frozenset({"offeror", "bidder", "purchaser"}),
    "security_description": frozenset({"security_description", "security"}),
    "cusip": frozenset({"cusip"}),
    "isin": frozenset({"isin"}),
    "ticker": frozenset({"ticker"}),
    "offer_price": frozenset({"offer_price", "price", "offerprice"}),
    "currency": frozenset({"currency", "offer_price", "price", "offerprice"}),
    "expiration_date": frozenset({"expiration_date", "expiration"}),
    "withdrawal_deadline": frozenset({"withdrawal_deadline", "withdrawal"}),
    "settlement_date": frozenset({"settlement_date", "settlement"}),
    "effective_date": frozenset({"effective_date", "effective", "commencement"}),
    "minimum_tender_condition": frozenset(
        {"minimum_tender_condition", "minimum_condition", "min_tender"}
    ),
    "proration_terms": frozenset({"proration_terms", "proration"}),
}

TEMPORAL_CUES: dict[str, tuple[str, ...]] = {
    "expiration_date": (
        "expir",
        "offer period",
        "offer will expire",
        "termination of the offer",
        "until",
    ),
    "withdrawal_deadline": ("withdraw", "withdrawal", "rights of withdrawal"),
    "settlement_date": (
        "settlement",
        "payment",
        "pay for",
        "acceptance for payment",
        "promptly",
        "accept for payment",
    ),
    "effective_date": ("effective", "commencement", "commence", "offer commenced", "consummat"),
}

# Temporal NER config: only these schema fields get TEMPORAL SPANS evidence
DATE_FIELDS = frozenset(TEMPORAL_CUES)
VALIDATE_FIELDS = frozenset(
    {"currency", "effective_date", "withdrawal_deadline", "ticker", "expiration_date"}
)

TENDER_PACK = ActionPack(
    name="tender",
    fields=CORE_GT_FIELDS,
    field_defs=FIELD_DEFS,
    field_pick=FIELD_PICK,
    hint_allow=HINT_ALLOW,
    gt_to_hint={f: GT_TO_HINT[f] for f in CORE_GT_FIELDS},
    date_fields=DATE_FIELDS,
    temporal_cues=TEMPORAL_CUES,
    validate_fields=VALIDATE_FIELDS,
    # Preserves legacy parity: the legacy harness dropped these role nouns for every pack
    hooks=PackHooks(
        junk_roles=frozenset({"parent", "merger sub", "merger subsidiary", "company", "purchaser"})
    ),
    clause_fields={
        "proration_terms": ClauseFieldSpec(
            quote_field="proration_terms",
            patterns=_PRORATION_PATTERNS,
            extract_prompt=_PRORATION_EXTRACT_PROMPT,
            max_chars=2200,
            use_passage_quotes=True,
            quote_accept_re=(
                r"(?i)if\s+more\s+than|pro[\s-]?rata|proration|oversubscription"
            ),
        ),
    },
    system_prompt=(
        "You are a tender-offer field extractor. Evidence is already filtered for this field "
        "(RULES facts, GLiNER spans, temporal DATE spans, or clause excerpts). "
        "Your job is to PICK or COPY the best matching listed value — not to abstain. "
        "Return one JSON object only. Copy values from evidence (light cleanup OK). "
        "Do not invent CUSIP/ISIN/ticker/date/price strings that are not in the evidence."
    ),
)

