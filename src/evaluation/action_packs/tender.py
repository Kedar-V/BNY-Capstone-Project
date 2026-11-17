"""Tender-offer ActionPack (CORE_GT_FIELDS + GT-aligned instructions)."""

from __future__ import annotations

from src.evaluation.action_packs.base import ActionPack, ClauseFieldSpec, HybridSpec, PackHooks
from src.evaluation.extract.policies import FieldPolicy, Stage
from src.evaluation.tender import CORE_GT_FIELDS, GT_TO_HINT

# Field definitions aligned to TENDER_OFFER_PROMPT in
# notebooks/evaluation/extract_gt_action_filings.ipynb (GT creation).
FIELD_DEFS: dict[str, str] = {
    "subject_company": (
        "The issuer of the securities sought. Use the full legal name when provided. "
        "In an issuer tender offer, the issuer is both subject_company and bidder. "
        "Do not assume a role from the filer alone; prefer the operating company/fund, not counsel or agents."
    ),
    "bidder": (
        "The person making the offer (offeror/purchaser). Use the full legal name when provided. "
        "In an issuer tender offer, the issuer is both subject_company and bidder. "
        "When GLiNER lists several organizations as offeror/purchaser, resolve contradictions: "
        "prefer the entity that is making the offer — Merger Sub / Purchaser / Filing Person "
        "(Offeror), not Parent, not the investment adviser, not a support-agreement party, "
        "and not counsel, depositary, or information agent. "
        "A higher GLiNER score does not override that role hierarchy."
    ),
    "security_description": (
        "The securities sought: include the issuer/fund legal name AND the class/series "
        "(and par value when stated). Example: \"Coatue Innovative Strategies Fund Class S, "
        "Class D and Class I Shares of beneficial interest\" — not the class line alone. "
        "For debt, include interest rate and maturity when stated. "
        "Do not include CUSIP, ISIN, or ticker."
    ),
    "cusip": "CUSIP identifier(s) explicitly stated in the evidence. Copy exactly; separate multiples with '; '.",
    "isin": "ISIN identifier(s) explicitly stated in the evidence. Copy exactly; separate multiples with '; '.",
    "ticker": "Exchange ticker symbol(s) explicitly stated in the evidence. Copy exactly.",
    "offer_price": (
        "The stated per-share (or per-unit) offer consideration. "
        "If the offer price is a formula (NAV / net asset value as of a Valuation Date, "
        "less Early Repurchase Deduction/Fee, or \"price equal to the most recent private-offering "
        "closing price\"), return that formula wording — not a later printed dollar amount. "
        "Only return a bare number (e.g. \"25.00\") when the offer states a fixed cash price per share. "
        "Never return: aggregate deal/tender proceeds (hundreds of thousands / millions), "
        "par value ($0.001), fees, market prices, or purchase caps."
    ),
    "currency": (
        "Currency of the offer price (maps to GT offer_price_currency): a three-letter code when the "
        "currency is explicitly identified (e.g. USD). If the text gives only an ambiguous symbol such "
        "as \"$\", return that symbol. Do not invent a code from context alone when only \"$\" appears "
        "without \"U.S. dollars\" / USD; skip par value, fees, and aggregate millions."
    ),
    "expiration_date": (
        "When the offer expires. Format \"M/D/YYYY h:mm AM/PM time zone\" when time/zone are stated; "
        "date only when no time is stated. Preserve midnight/noon when stated. "
        "Do not confuse with announcement, filing, settlement, guaranteed delivery, or withdrawal dates. "
        "Do not add \"unless extended\". Use an explicitly amended date when the text says it replaces an earlier one."
    ),
    "withdrawal_deadline": (
        "The last date and time holders may withdraw tendered securities (same date/time formatting as expiration). "
        "Return a date only when the evidence explicitly discusses withdrawal rights "
        "(e.g. \"may withdraw\", \"withdrawal rights\", \"Notice of Withdrawal\"). "
        "If those rights run until expiration and the expiration deadline is stated, return that deadline. "
        "If withdrawal is explicitly prohibited without exceptions, return exactly \"Withdrawal not permitted\". "
        "If the evidence only states when the offer expires — with no withdrawal language — return null "
        "(do not copy the expiration date). "
        "Ignore Act years, valuation dates, filing/signature dates, and superseded prior-year OTPs."
    ),
    "settlement_date": (
        "The stated timing for acceptance for payment and payment for tendered securities. "
        "Do not confuse with the expiration date. "
        "If acceptance and payment have different stated timings, preserve both with labels separated by \" | \", "
        "e.g. \"Acceptance: 11/20/2026 | Payment: 11/23/2026\". "
        "If only relative timing is stated, return that wording (e.g. \"promptly after expiration\"). "
        "Do not assume acceptance and payment occur simultaneously."
    ),
    "effective_date": (
        "When a transaction legally takes effect (e.g. merger Effective Time after the offer), "
        "only when the text states a legal-effectiveness / consummation date. "
        "A standalone issuer self-tender usually has none — return null. "
        "Never substitute: offer expiration, withdrawal deadline, valuation date, acceptance-for-payment "
        "wording without a calendar date, filing/signature blocks, commencement, or settlement. "
        "Prefer null over guessing when spans are only ordinary offer dates."
    ),
    "minimum_tender_condition": (
        "The minimum number, percentage, or principal amount that must be tendered for the offer to proceed. "
        "Include its calculation basis, treatment of securities owned by the bidder or affiliates, and whether "
        "the condition may be waived when stated. Do not convert \"a majority\" into a percentage. "
        "Do not confuse with a purchase cap or other closing conditions. "
        "Use exactly \"No minimum tender condition\" only when explicitly stated."
    ),
    "proration_terms": (
        "How securities are accepted when tenders exceed the amount the bidder will purchase. "
        "When the excerpt has an oversubscription / \"If more than…\" / \"If Shares in excess of…\" / "
        "pro rata clause, copy that sentence (trigger + allocation); do not return null. "
        "Include when stated: purchase limit, odd-lot or other priority, conditional tenders, rounding. "
        "Do not calculate a proration percentage. Do not infer proration from a purchase limit alone. "
        "Use exactly \"No proration\" only when explicitly stated. Preserve numbers (drop thousands commas)."
    ),
}

FIELD_PICK: dict[str, str] = {
    "subject_company": "Pick the issuer of the securities sought (full legal name); not counsel or agents.",
    "bidder": (
        "Pick the offeror/purchaser legal name only. "
        "Discard any span whose context calls it Adviser / investment adviser, Parent only, "
        "support-agreement party, counsel, depositary, or information agent. "
        "Schedule TO 'Filing Person (Offeror and Issuer)' wins when present. "
        "Conflict examples (return the second name): "
        "XOMA (Parent) vs XRA 7 (Merger Sub) → XRA 7; Merck vs Caymus Purchaser → Caymus; "
        "Lord Abbett … Advisor LLC vs Lord Abbett … Fund (Offeror and Issuer) → the Fund; "
        "Icahn vs Enzon (issuer filing the TO) → Enzon. "
        "Self-tender: bidder = subject_company."
    ),
    "security_description": (
        "Return issuer/fund name + class/series (+ par if stated). "
        "If the cover lists a subject-company name and a separate \"Title of Class\" line, "
        "combine them (fund/issuer first). Never class-only; never CUSIP/ISIN/ticker."
    ),
    "offer_price": (
        "If hybrid/GLiNER shows a NAV / Valuation Date / Early Repurchase / private-offering "
        "formula, return that formula (prefer hybrid wording over a GLiNER dollar span). "
        "Return a bare per-share number only for an explicit fixed cash offer price. "
        "Discard aggregates (e.g. 775,178 or 14,256,398), par ($0.001), fees, and caps — "
        "even if score= is highest."
    ),
    "cusip": "If any cusip value is listed, return it exactly.",
    "isin": "If any isin value is listed, return it exactly.",
    "ticker": "If any exchange ticker is listed, return it; ignore CUSIP-like strings and XBRL junk.",
    "expiration_date": (
        "Pick the offer expiration date/time (highest expiration cues). "
        "Include time/zone when present. Do not return withdrawal/settlement/filing dates."
    ),
    "withdrawal_deadline": (
        "Return a withdrawal deadline only if withdrawal rights are explicitly described. "
        "If rights continue until expiration, copy that expiration date/time. "
        "If you only see expiration / valuation / filing dates with no withdrawal wording → null. "
        "Do not copy a lone expiration date just because dates are listed. "
        "\"Withdrawal not permitted\" only when explicitly prohibited."
    ),
    "settlement_date": (
        "Return acceptance/payment timing as stated (calendar dates and/or relative wording). "
        "If both acceptance and payment are stated separately, use \"Acceptance: … | Payment: …\"."
    ),
    "currency": (
        "Return an explicit ISO code when identified; if only \"$\" is shown without U.S. dollars/USD, "
        "return \"$\"; else null."
    ),
    "effective_date": (
        "Return a merger/consummation Effective Time (or stated legal-effectiveness date) only. "
        "Standalone tender with no follow-on merger language → null. "
        "Never return expiration, withdrawal, valuation, acceptance-for-payment prose, or signature dates "
        "even if they are the only dates listed (null is correct)."
    ),
    "minimum_tender_condition": (
        "Return the threshold clause (or \"No minimum tender condition\" if explicit). "
        "Do not invent a % from \"majority\"."
    ),
    "proration_terms": (
        "If any excerpt/span states oversubscription / pro rata / \"If more than…\", copy that "
        "clause (do not null it). \"No proration\" only when explicit. Do not invent a %."
    ),
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

# --- tender retrieval config (tune here) ---------------------------------------------
# Everything tender-specific about WHERE evidence comes from lives in this block:
# clause regexes + copy prompts (CLAUSE_FIELDS), explicit per-field policies (POLICIES)
# and pack-level knobs (TEMPORAL_*). To add another corporate action, copy this block
# into its pack and replace the patterns/prompts; the graph code stays untouched.
# Patterns target generic SEC schedule / offer-document wording (never a particular
# filer); each pattern was required to match >= 3 distinct dev filings
# (scripts/eval_retrieval_recall.py --split dev --pattern-counts). retrieve_clause tries
# the patterns IN ORDER and keeps the hits of the first pattern that matches anything,
# so order = priority. Windows are fixed-width (not period-terminated) so "i.e." /
# "U.S." cannot truncate them.

# proration_terms: oversubscription / pro-rata sentence.
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
    "- If the excerpt contains such a trigger/pro-rata rule, you MUST copy it "
    "(do not return null).\n"
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

# minimum_tender_condition: Offer-to-Purchase condition language.
_MIN_TENDER_PATTERNS = (
    # Absence statement (issuer self-tenders): "The Offer is not conditioned upon any
    # minimum number of Shares being tendered" / "not subject to ... minimum amount of
    # Units" / "there is no minimum number of Shares that must be tendered".
    r"(?is)(.{0,150}(?:\bnot\s+(?:be\s+)?(?:conditioned|subject|contingent)\s+(?:up)?on\s+.{0,80}?"
    r"|\bno\s+)minimum\s+(?:number|amount|percentage|aggregate\s+amount)\s+of\s+.{0,200})",
    # Third-party offers: windows around the standard defined term "Minimum Condition" /
    # "Minimum Tender Condition" (its definition and "... has been satisfied" updates).
    # (A narrower definition-only pattern was dropped: it matched a single dev event.)
    r"(?is)(.{0,200}\bminimum\s+(?:tender\s+)?condition\b.{0,300})",
)

_MIN_TENDER_EXTRACT_PROMPT = (
    "Extract minimum_tender_condition from the EXCERPT only.\n"
    'Return JSON {{"minimum_tender_condition": "..."}}.\n'
    "Rules:\n"
    "- If the excerpt states the minimum number, percentage or majority of securities that "
    "must be validly tendered (and not withdrawn) for the offer to proceed, copy that exact "
    "phrase from the excerpt.\n"
    "- If the excerpt says the offer is not conditioned on any minimum number or amount of "
    'securities being tendered, return exactly "No minimum tender condition".\n'
    "- Ignore minimum account balances, minimum investments and purchase limits.\n"
    '- If the excerpt says neither, {{"minimum_tender_condition": null}}.\n\n'
    "EXCERPT:\n{excerpt}\n"
)

# security_description: the class of securities sought.
_SECURITY_PATTERNS = (
    # Schedule TO / 14D-9 cover page: the class name printed right above the
    # "(Title of Class of Securities)" caption, with the issuer-name caption before it.
    r"(?is)(.{0,300}\(\s*title\s+of\s+class(?:es)?\s+of\s+securities\s*\))",
    # Offer-document opening: "offer to purchase ... of its outstanding common stock,
    # par value $0.001 per share (the "Shares")": defined term of the sought securities.
    r"(?is)((?:offer(?:s|ing)?\s+to\s+(?:purchase|repurchase|exchange|acquire)|tender\s+offer\s+for)"
    r"\b.{0,300}?\(\s*(?:each,?\s+an?\s+|collectively,?\s+)?(?:the\s+)?[\"“]"
    r"(?:shares?|units?|notes|securities|interests?|common\s+stock|warrants)[\"”]\s*\))",
)

_SECURITY_EXTRACT_PROMPT = (
    "Extract security_description from the EXCERPT only.\n"
    'Return JSON {{"security_description": "..."}}.\n'
    "Rules:\n"
    "- Include the issuer/fund name AND the class/series of securities sought.\n"
    "- On a Schedule TO cover, combine \"(Name of Subject Company)\" with the line before "
    "\"(Title of Class of Securities)\" "
    '(e.g. \"Coatue Innovative Strategies Fund Class S, Class D and Class I Shares…\").\n'
    "- Or copy the securities described before a defined term such as (the \"Shares\"), "
    "keeping issuer + class/par when present.\n"
    "- Keep class names, par value and series wording as written; light cleanup OK.\n"
    "- Do not return class/title alone without the issuer/fund name.\n"
    "- Do not return a CUSIP or a filing-person caption alone.\n"
    '- If the excerpt names no class of securities, {{"security_description": null}}.\n\n'
    "EXCERPT:\n{excerpt}\n"
)

CLAUSE_FIELDS: dict[str, ClauseFieldSpec] = {
    "proration_terms": ClauseFieldSpec(
        quote_field="proration_terms",
        patterns=_PRORATION_PATTERNS,
        extract_prompt=_PRORATION_EXTRACT_PROMPT,
        max_chars=2200,
        use_passage_quotes=True,
        quote_accept_re=r"(?i)if\s+more\s+than|pro[\s-]?rata|proration|oversubscription",
    ),
    # GT passage quotes are gold-derived: the new clause fields retrieve from documents only
    "minimum_tender_condition": ClauseFieldSpec(
        quote_field="minimum_tender_condition",
        patterns=_MIN_TENDER_PATTERNS,
        extract_prompt=_MIN_TENDER_EXTRACT_PROMPT,
        max_chars=1500,
        use_passage_quotes=False,
    ),
    "security_description": ClauseFieldSpec(
        quote_field="security_description",
        patterns=_SECURITY_PATTERNS,
        extract_prompt=_SECURITY_EXTRACT_PROMPT,
        max_chars=1200,
        use_passage_quotes=False,
    ),
}


def _clause_then_spans(field: str) -> FieldPolicy:
    """Stage 1 clause copy (empty -> skip); stage 2 the oneshot rules+GLiNER pick.

    The clause stage falls through when retrieval is empty OR its LLM answer is null;
    a clause answer ends the policy (stop_at_first_hit). Explicit policies apply in both
    oneshot and cascade runs, so stage 2 is the oneshot pick in both.
    """
    validate = field in VALIDATE_FIELDS
    return FieldPolicy(
        stages=(
            Stage(
                name="clause",
                sources=("clause",),
                prompt_mode="copy",
                on_empty="skip",
                pass_label="clause",
                null_label="clause_null",
                direct_from_rules=False,
                validate=validate,
                empty_label="clause_miss",
            ),
            Stage(
                name="oneshot",
                # hybrid always supplements GLiNER (GLiNER spans can be confidently wrong)
                sources=("rules", "gliner", "hybrid"),
                prompt_mode="pick",
                on_empty="ask",
                pass_label="oneshot",
                null_label="oneshot",
                direct_from_rules=False,
                validate=validate,
            ),
        ),
        stop_at_first_hit=True,
    )


def _settlement_cascade() -> FieldPolicy:
    """Settlement cascade mirroring oracle Settlement template (Rules).

    Pass A takes ``find_settlement`` / rules-direct hits without an LLM rewrite
    (``direct_from_rules``), keeping ``Payment: promptly`` when present. Calendar dates
    still need a payment cue via ``settlement_accept``. Pass B spans use the same gate.
    """
    from src.preprocess.rules_ids import settlement_accept

    validate = "settlement_date" in VALIDATE_FIELDS
    return FieldPolicy(
        stages=(
            Stage(
                name="rules",
                sources=("rules",),
                prompt_mode="pick",
                on_empty="skip",
                pass_label="A",
                null_label="A_null",
                direct_from_rules=True,
                validate=validate,
                accept=settlement_accept,
            ),
            Stage(
                name="span",
                sources=("gliner", "temporal", "hybrid"),
                prompt_mode="pick",
                on_empty="skip",
                pass_label="B",
                null_label="B_null",
                direct_from_rules=False,
                validate=validate,
                accept=settlement_accept,
            ),
        ),
        stop_at_first_hit=True,
    )


POLICIES: dict[str, FieldPolicy] = {
    f: _clause_then_spans(f) for f in ("minimum_tender_condition", "security_description")
}
POLICIES["settlement_date"] = _settlement_cascade()

# Temporal NER scan: the excerpts run to 24,000 chars; scan all of them and keep up to
# 40 DATE/TIME lines per field (dev recall plateaued at 40; 60 only added length).
TEMPORAL_SCAN_CHARS = 24_000
TEMPORAL_MAX_SPANS = 40

# Always-on BM25+dense supplemental excerpts next to GLiNER (not fallthrough-only).
HYBRID = HybridSpec(
    top_k=4,
    max_chars=2200,
    query_extra={
        "offer_price": "purchase price per share net asset value consideration cash",
        "proration_terms": "if more than pro rata proration oversubscription",
        "effective_date": "effective consummated closed merger effective time",
        "expiration_date": "offer will expire expiration time",
        "withdrawal_deadline": "withdrawal rights withdraw tender",
        "minimum_tender_condition": "minimum tender condition majority shares",
        "settlement_date": "payment acceptance for payment promptly",
        "currency": "U.S. dollars USD currency",
        "bidder": (
            "filing person offeror purchaser merger sub wholly owned subsidiary "
            "names of filing person offeror and issuer"
        ),
        "subject_company": "name of subject company issuer title of class of securities",
    },
)
# --- end tender retrieval config ------------------------------------------------------


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
    clause_fields=CLAUSE_FIELDS,
    policies=POLICIES,
    hybrid=HYBRID,
    temporal_scan_chars=TEMPORAL_SCAN_CHARS,
    temporal_max_spans=TEMPORAL_MAX_SPANS,
    system_prompt=(
        "You are a tender-offer field extractor. Evidence is already filtered for this field "
        "(RULES facts, GLiNER spans, HYBRID EXCERPTS, temporal DATE spans, or clause excerpts). "
        "Your job is to PICK or COPY the best matching listed value — not to abstain. "
        "When GLiNER conflicts with HYBRID EXCERPTS, prefer the hybrid wording if it better "
        "matches the field definition. "
        "When GLiNER spans contradict each other (e.g. Parent vs Merger Sub both labeled offeror), "
        "apply the field definition's role rules — do not blindly take the highest score. "
        "Return one JSON object only. Copy values from evidence (light cleanup OK). "
        "Do not invent CUSIP/ISIN/ticker/date/price strings that are not in the evidence."
    ),
)

