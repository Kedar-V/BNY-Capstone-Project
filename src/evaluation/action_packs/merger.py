"""Merger ActionPack (core GT columns + defs distilled from MERGER_PROMPT)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from src.evaluation.action_packs.base import (
    ActionPack,
    FieldShot,
    HybridSpec,
    PackHooks,
    _default_normalize,
)
from src.evaluation.action_packs.orgs import norm_org, same_org

# Bare role labels the model sometimes returns instead of a legal name.
_BARE_PARTY = frozenset(
    {
        "parent",
        "holdco",
        "company",
        "the company",
        "purchaser",
        "buyer",
        "seller",
        "merger sub",
        "merger subsidiary",
        "acquisition sub",
        "issuer",
        "registrant",
        "newco",
        "pubco",
        "spac",
    }
)
_EXCHANGE_NAMES = frozenset(
    {
        "nasdaq",
        "nyse",
        "otc",
        "nyse american",
        "nasdaq global market",
        "nasdaq global select",
        "nasdaq capital market",
    }
)

# Core scored set — full GT has more narrative fields (closing_conditions, etc.).
CORE_MERGER_FIELDS: tuple[str, ...] = (
    "acquirer",
    "target",
    "consideration_type",
    "cash_consideration",
    "stock_exchange_ratio",
    "shareholder_vote_date",
    "election_deadline",
    "effective_date",
    "security_description",
    "ticker",
    "cusip",
    "isin",
)

FIELD_DEFS: dict[str, str] = {
    "acquirer": (
        "Entity acquiring the target — the acquiring parent / ultimate buyer. "
        "Not a merger sub, Holdco shell, bare 'Company', or the filing target. "
        "Do not invent a role when the filing is a merger of equals."
    ),
    "target": (
        "Entity being acquired (full legal name). Distinguish from acquirer / "
        "merger sub / Holdco / bare 'Company' / other parties."
    ),
    "consideration_type": (
        'Form paid to holders: "Cash", "Stock", "Mixed cash and stock", '
        '"Elective consideration", or a short description of other components. '
        "Prefer Stock or Mixed when conversion / exchange-ratio language is present. "
        "Trust-account or financing cash alone is not deal type. "
        "Fractional-share cash alone does not make stock into mixed."
    ),
    "cash_consideration": (
        "Per-share merger consideration cash with currency when stated. "
        "Preserve ranges/formulas. Not aggregate deal value, fees, market price, "
        "or trust-account totals."
    ),
    "stock_exchange_ratio": (
        "Shares of new security per share of old security, with direction and classes. "
        "Copy the stated ratio / exchange-ratio sentence or formula verbatim; "
        "do not compute from prices. Cash-only → 'No stock consideration'."
    ),
    "shareholder_vote_date": (
        "Date/time of the shareholder meeting / vote on the merger when explicitly stated. "
        "Not mailing, record, election, or effectiveness dates."
    ),
    "election_deadline": (
        "Deadline for holders to elect among consideration options, when stated. "
        "Null when the filing has no election / form-of-election deadline."
    ),
    "effective_date": (
        "Legal closing / consummation / effectiveness date of the merger. "
        "Null when not explicitly stated."
    ),
    "security_description": (
        "Short class/type of the affected title security (e.g. common stock / Class A). "
        "Prefer the security named in the merger title / cover, not a side class."
    ),
    "ticker": (
        "Target / subject-company exchange ticker from evidence "
        "(symbol next to the company name). Not acquirer ticker, CUSIP, or exchange name."
    ),
    "cusip": "9-character CUSIP from evidence. Copy exactly.",
    "isin": "ISIN from evidence. Copy exactly.",
}

FIELD_PICK: dict[str, str] = {
    "acquirer": (
        "Prefer the acquiring parent / ultimate buyer full legal name — NOT a merger sub, "
        "Holdco label alone, bare 'Company', filing company / primary_entity / target. "
        "On a DEFM14A the registrant is usually the target, not the acquirer. "
        "Do not return counsel or agents. "
        "Conflict examples (return the second name): "
        "Holdco vs Northwind Holdings Limited → Northwind Holdings Limited; "
        "selling stockholder Redwood Capital vs Maple Beverage Co. (buyer) → Maple Beverage Co."
    ),
    "target": (
        "Prefer primary_entity / filing company being acquired (full legal name). "
        "Not the purchaser/parent buyer, merger sub, Holdco alone, bare 'Company', "
        "counsel, or agents. "
        "Conflict examples (return the second name): "
        "Company vs Aurora Acquisition Corp. (primary_entity) → Aurora Acquisition Corp.; "
        "LeafCo (brand) vs Greenfield Organics Corp. (legal) → Greenfield Organics Corp."
    ),
    "stock_exchange_ratio": (
        "Copy an explicit X-for-Y / shares-per-share / exchange-ratio sentence from EVIDENCE "
        "when present (both securities named when listed). "
        "If evidence says cash-only / no ratio, return exactly: No stock consideration. "
        "Do not invent a numeric ratio from prices; do not return null when a ratio "
        "sentence is in the bag. "
        "Conflict examples: '2,500,000 newly issued shares' vs "
        "'1 share of Newco Class A Common Stock per share' → the per-share ratio; "
        "cash-only deal → No stock consideration."
    ),
    "consideration_type": (
        "If EVIDENCE has conversion / exchange-ratio / stock-for-stock language, prefer "
        "Stock or Mixed cash and stock — do not collapse to Cash. "
        "Cash only when holders receive cash per share and no stock ratio. "
        "Ignore financing / trust-account cash when labeling deal type. "
        "Pick the label that matches holder consideration."
    ),
    "cash_consideration": (
        "Prefer per-share merger consideration cash with currency; skip aggregate "
        "$ millions / fees / market quotes / trust totals / par value. "
        "If holders receive only stock / no cash, return exactly: No cash consideration. "
        "Conflict examples: $0.0001 (par) vs $15.00 per share → $15.00 per share; "
        "stock-for-stock with a stray $ quote → No cash consideration."
    ),
    "shareholder_vote_date": (
        "Prefer the shareholder meeting / vote date on the merger. "
        "Not mailing, record, election, or effectiveness/closing dates. "
        "Conflict example: proxy mailed 2025-09-30 vs meeting March 3, 2026 → March 3, 2026."
    ),
    "election_deadline": (
        "Only return a date/time with election/choice/form-of-election cues. "
        "If EVIDENCE has no election deadline, return null — do not guess vote or closing dates."
    ),
    "effective_date": (
        "Prefer closing/consummation/Effective Time only when explicitly stated. "
        "If EVIDENCE has no effectiveness/closing date, return null — do not use vote, "
        "mailing, or placeholder dates."
    ),
    "security_description": (
        "Prefer the title / cover security class of the shares being acquired or exchanged "
        "(e.g. 'common stock', 'Class B Common Stock'). Keep Class A vs B / ordinary vs "
        "preferred exact. Reject financing preferred, parent-share nicknames, and bare "
        "'Equity Interest' when a clearer subject class is listed. "
        "Conflict examples: Preferred stock (financing) vs common stock (title) → common stock; "
        "Parent Class A vs Class B being converted → Class B Common Stock."
    ),
    "ticker": (
        "Return the target / subject-company exchange ticker from EVIDENCE — prefer the "
        "symbol shown next to the company/issuer name. "
        "If multiple tickers appear, pick the issuer being acquired, not the acquirer. "
        "Copy multi-symbol sets when listed (e.g. ABCU, ABCUR, ABCWU). "
        "Never return the acquirer/parent ticker, CUSIP/ISIN digits, person names, or "
        "exchange names (Nasdaq/NYSE) alone. "
        "Conflict examples: PRNT (acquirer) vs TGTX (target) → TGTX; "
        "Nasdaq vs ABCU/ABCUR/ABCWU → ABCU, ABCUR, ABCWU."
    ),
    "cusip": "If any cusip value is listed, return it.",
    "isin": "If any isin value is listed, return it.",
}

HINT_ALLOW: dict[str, frozenset[str]] = {
    # Buyer side: purchaser/parent, plus offeror spans that are NOT the filing target
    # (filtered via primary_entity in the drop_span hook).
    "acquirer": frozenset({"acquirer", "purchaser", "parent", "offeror", "buyer"}),
    # Filing company is usually the target; GLiNER often tags it offeror/issuer.
    "target": frozenset({"target", "subject_company", "issuer", "offeror"}),
    "consideration_type": frozenset(
        {"consideration_type", "consideration", "offer_price", "price"}
    ),
    "cash_consideration": frozenset(
        {"cash_consideration", "offer_price", "price", "cash_per_share"}
    ),
    "stock_exchange_ratio": frozenset(
        {"stock_exchange_ratio", "exchange_ratio", "ratio"}
    ),
    "shareholder_vote_date": frozenset(
        {"shareholder_vote_date", "vote_date", "meeting_date"}
    ),
    "election_deadline": frozenset({"election_deadline", "election"}),
    "effective_date": frozenset(
        {
            "effective_date",
            "effective",
            "closing",
            "consummation",
            "expected_closing",
        }
    ),
    "security_description": frozenset({"security_description", "security"}),
    "ticker": frozenset({"ticker"}),
    "cusip": frozenset({"cusip"}),
    "isin": frozenset({"isin"}),
}

TEMPORAL_CUES: dict[str, tuple[str, ...]] = {
    "shareholder_vote_date": (
        "shareholder vote",
        "special meeting",
        "vote on the merger",
        "meeting of stockholders",
        "record date",
    ),
    "election_deadline": (
        "election deadline",
        "election form",
        "elect",
        "make an election",
        "consideration election",
    ),
    "effective_date": (
        "effective",
        "closing",
        "consummat",
        "merger became effective",
        "completed the merger",
    ),
}

# Temporal NER config: only these schema fields get TEMPORAL SPANS evidence
DATE_FIELDS = frozenset(TEMPORAL_CUES)
# Pass C: validate fields where wrong keeps are common; skip parties/vote —
# few-shot + normalize already gate bare Holdco/Parent, and Pass C was dropping TPs.
VALIDATE_FIELDS = frozenset(
    {
        "consideration_type",
        "cash_consideration",
        "stock_exchange_ratio",
        "effective_date",
        "security_description",
        "ticker",
    }
)


def _merger_normalize(field: str, value: str) -> str:
    v = _default_normalize(field, value)
    if field in ("acquirer", "target"):
        low = " ".join(v.lower().split())
        if low in _BARE_PARTY or norm_org(v) in _BARE_PARTY:
            return ""
    if field == "ticker":
        low = " ".join(v.lower().split())
        if low in _EXCHANGE_NAMES:
            return ""
        # CUSIP-like digit strings, not tickers
        if re.fullmatch(r"[\d\s]{6,}", v):
            return ""
    if field == "stock_exchange_ratio":
        stripped = v.strip().strip("'\"")
        if stripped.lower() == "no stock consideration":
            return "No stock consideration"
        return stripped
    if field == "cash_consideration":
        stripped = v.strip().strip("'\"")
        if stripped.lower() == "no cash consideration":
            return "No cash consideration"
        return stripped
    return v


def _extras_from_inventory(inv: Mapping[str, Any]) -> dict[str, str]:
    primary_entity = ""
    forms: list[str] = []
    try:
        primary_entity = str(inv.get("primary_entity") or "").strip()
        forms = [
            str(d.get("form") or d.get("file_type") or "").upper()
            for d in (inv.get("docs") or [])
        ]
    except Exception:  # noqa: BLE001
        primary_entity, forms = "", []
    is_proxy = any("14A" in f or "14C" in f for f in forms)
    return {"primary_entity": primary_entity, "is_proxy_filing": "1" if is_proxy else "0"}


def _primary(extras: Mapping[str, str]) -> str:
    return (extras.get("primary_entity") or "").strip()


def _is_proxy(extras: Mapping[str, str]) -> bool:
    # *14A/14C proxies only (extras["is_proxy_filing"] = "1"/"true"/"yes"); not S-4/8-K
    return str(extras.get("is_proxy_filing", "")).strip().lower() in {"1", "true", "yes"}


def _drop_span(field: str, raw: str, extras: Mapping[str, str]) -> bool:
    # Drop bare role nouns from party evidence bags.
    if field in ("acquirer", "target"):
        low = " ".join((raw or "").lower().split())
        if low in _BARE_PARTY or norm_org(raw) in _BARE_PARTY:
            return True
    if field == "ticker":
        low = " ".join((raw or "").lower().split())
        if low in _EXCHANGE_NAMES:
            return True
    # DEFM14A/proxy: the filing's primary entity is the target; drop it from acquirer evidence
    pe = _primary(extras)
    return field == "acquirer" and bool(pe) and same_org(raw, pe)


def _rules_prelude(field: str, extras: Mapping[str, str]) -> list[str]:
    pe = _primary(extras)
    if field == "target" and pe and _is_proxy(extras):
        return [f"- hint=primary_entity method=inventory value={pe!r}"]
    return []


def _direct_prior(field: str, extras: Mapping[str, str]) -> str | None:
    pe = _primary(extras)
    return pe if field == "target" and pe and _is_proxy(extras) else None


def _synth_spans(
    field: str, gliner: list[str], spans: list[dict], extras: Mapping[str, str]
) -> list[str]:
    # Cash-only deals: GT often stores an explicit "No stock consideration"
    if field != "stock_exchange_ratio" or gliner:
        return []
    # Lazy: extract.evidence imports this package (via action_packs.orgs) at load time
    from src.evaluation.extract.evidence import gliner_lines

    if not gliner_lines(MERGER_PACK, spans, "cash_consideration", extras=extras):
        return []
    # Legacy guard: stock/ratio labels or share-swap text in ANY span suppress the synthesis
    labels = " ".join(str(sp.get("field_hint") or sp.get("label") or "").lower() for sp in spans)
    texts = " ".join(str(sp.get("text") or "").lower() for sp in spans)
    stockish = (
        "exchange_ratio" in labels
        or "stock_exchange" in labels
        or "exchange ratio" in texts
        or ("shares of" in texts and "per share" in texts)
        or "mixed" in texts
    )
    if stockish:
        return []
    return [
        "- hint=stock_exchange_ratio value='No stock consideration' "
        "note='no ratio span; cash consideration present'"
    ]


MERGER_HOOKS = PackHooks(
    junk_roles=frozenset(
        {
            "parent",
            "merger sub",
            "merger subsidiary",
            "company",
            "purchaser",
            "holdco",
        }
    ),
    drop_span=_drop_span,
    rules_prelude=_rules_prelude,
    direct_prior=_direct_prior,
    synth_spans=_synth_spans,
    prior_label="A_inventory",
    prior_hint="primary_entity",
    extras_from_inventory=_extras_from_inventory,
)

# Synthetic few-shots (fictional parties; not holdout rows) for remaining Qwen failure modes.
FIELD_SHOTS: dict[str, tuple[FieldShot, ...]] = {
    "acquirer": (
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=acquirer value='Holdco'\n"
                "- hint=parent value='Northwind Holdings Limited'\n"
                "- hint=target value='Cedar Technologies, Inc.'\n"
                "HYBRID EXCERPTS:\n"
                "- Parent (Northwind Holdings Limited) will acquire Cedar via merger sub Holdco."
            ),
            answer="Northwind Holdings Limited",
            note="named parent over Holdco / target",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=purchaser value='Redwood Capital Partners LLC'\n"
                "- hint=acquirer value='Maple Beverage Co.'\n"
                "HYBRID EXCERPTS:\n"
                "- Maple Beverage Co. agreed to acquire the Company; "
                "Redwood Capital Partners LLC is a selling stockholder."
            ),
            answer="Maple Beverage Co.",
            note="buyer legal name, not selling stockholder / sponsor",
        ),
    ),
    "target": (
        FieldShot(
            evidence=(
                "RULES:\n"
                "- hint=primary_entity method=inventory value='Aurora Acquisition Corp.'\n"
                "GLiNER SPANS:\n"
                "- hint=target value='Company'\n"
                "- hint=acquirer value='Summit Minerals Inc.'\n"
                "HYBRID EXCERPTS:\n"
                "- Aurora Acquisition Corp. (the 'Company') will merge with a Summit subsidiary."
            ),
            answer="Aurora Acquisition Corp.",
            note="full target legal name, not bare Company / buyer",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=target value='LeafCo'\n"
                "- hint=issuer value='Greenfield Organics Corp.'\n"
                "HYBRID EXCERPTS:\n"
                "- Greenfield Organics Corp. (formerly LeafCo) is the subject company being acquired."
            ),
            answer="Greenfield Organics Corp.",
            note="legal subject name over short brand",
        ),
    ),
    "ticker": (
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=ticker value='PRNT'\n"
                "- hint=ticker value='TGTX'\n"
                "HYBRID EXCERPTS:\n"
                "- Target Tidegate Corp. (OTC: TGTX); acquirer ParentCo Inc. (NYSE: PRNT)."
            ),
            answer="TGTX",
            note="target ticker, not acquirer",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=ticker value='Nasdaq'\n"
                "- hint=ticker value='ABCU'\n"
                "- hint=ticker value='ABCUR'\n"
                "- hint=ticker value='ABCWU'\n"
                "HYBRID EXCERPTS:\n"
                "- Units trade as ABCWU; common ABCU and rights ABCUR on Nasdaq."
            ),
            answer="ABCU, ABCUR, ABCWU",
            note="copy multi-symbol set; reject exchange name",
        ),
    ),
    "security_description": (
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=security_description value='Preferred stock'\n"
                "- hint=security_description value='common stock'\n"
                "HYBRID EXCERPTS:\n"
                "- Title of securities: common stock, par value $0.001 (financing includes Preferred stock)."
            ),
            answer="common stock",
            note="title/subject class, not financing preferred",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=security_description value='Class A Common Stock'\n"
                "- hint=security_description value='Class B Common Stock'\n"
                "HYBRID EXCERPTS:\n"
                "- Each share of Class B Common Stock will be converted; Class A remains outstanding at Parent."
            ),
            answer="Class B Common Stock",
            note="class being exchanged, not parent Class A",
        ),
    ),
    "stock_exchange_ratio": (
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=stock_exchange_ratio value='2,500,000 newly issued shares'\n"
                "- hint=exchange_ratio value='1 share of Newco Class A Common Stock per share'\n"
                "HYBRID EXCERPTS:\n"
                "- Exchange Ratio means 1 share of Newco Class A Common Stock per share of Company stock."
            ),
            answer="1 share of Newco Class A Common Stock per share",
            note="per-share ratio, not aggregate share count",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=cash_consideration value='$12.50 per share'\n"
                "HYBRID EXCERPTS:\n"
                "- Holders will receive only cash; the merger agreement provides no stock consideration."
            ),
            answer="No stock consideration",
            note="cash-only → exact absence label",
        ),
        FieldShot(
            evidence=(
                "HYBRID EXCERPTS:\n"
                "- Exchange Ratio = (Fully Diluted Parent Common Stock × Valuation Ratio) / "
                "Fully Diluted Company Common Stock."
            ),
            answer=(
                "Exchange Ratio = (Fully Diluted Parent Common Stock × Valuation Ratio) / "
                "Fully Diluted Company Common Stock"
            ),
            note="copy formula sentence when that is the stated ratio",
        ),
    ),
    "cash_consideration": (
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=cash_consideration value='$0.0001'\n"
                "- hint=offer_price value='$15.00 per share'\n"
                "HYBRID EXCERPTS:\n"
                "- Merger consideration is $15.00 per share in cash (par value $0.0001)."
            ),
            answer="$15.00 per share",
            note="per-share price, not par value",
        ),
        FieldShot(
            evidence=(
                "GLiNER SPANS:\n"
                "- hint=cash_consideration value='$22.10'\n"
                "HYBRID EXCERPTS:\n"
                "- Stock-for-stock merger; holders receive Parent shares and no cash consideration."
            ),
            answer="No cash consideration",
            note="stock-only → exact absence label",
        ),
    ),
    "consideration_type": (
        FieldShot(
            evidence=(
                "HYBRID EXCERPTS:\n"
                "- Each Company share converts into 0.85 Parent shares; no cash election."
            ),
            answer="Stock",
            note="exchange-ratio language → Stock, not Cash",
        ),
    ),
    "shareholder_vote_date": (
        FieldShot(
            evidence=(
                "TEMPORAL SPANS:\n"
                "- hint=shareholder_vote_date date='2025-09-30' field_cues=1\n"
                "- hint=shareholder_vote_date date='March 3, 2026 10:00 a.m. Eastern' field_cues=3\n"
                "HYBRID EXCERPTS:\n"
                "- Special meeting of stockholders on March 3, 2026 at 10:00 a.m. Eastern Time. "
                "Proxy mailed September 30, 2025."
            ),
            answer="March 3, 2026 10:00 a.m. Eastern",
            note="meeting/vote date, not mailing date",
        ),
    ),
}

MERGER_PACK = ActionPack(
    name="merger",
    fields=CORE_MERGER_FIELDS,
    field_defs=FIELD_DEFS,
    field_pick=FIELD_PICK,
    hint_allow=HINT_ALLOW,
    gt_to_hint={f: f for f in CORE_MERGER_FIELDS},
    date_fields=DATE_FIELDS,
    temporal_cues=TEMPORAL_CUES,
    validate_fields=VALIDATE_FIELDS,
    hooks=MERGER_HOOKS,
    normalize=_merger_normalize,
    field_shots=FIELD_SHOTS,
    # Same always-on hybrid supplement as tender (BM25+dense next to GLiNER)
    hybrid=HybridSpec(
        top_k=6,
        max_chars=2800,
        query_extra={
            "cash_consideration": "cash per share merger consideration",
            "stock_exchange_ratio": (
                "exchange ratio shares of per share No stock consideration "
                "Exchange Ratio equals converts into"
            ),
            "effective_date": "effective consummated closed merger",
            "election_deadline": "election deadline choose consideration form of election",
            "ticker": (
                "trading symbol ticker Nasdaq NYSE OTC under the symbol "
                "Trading Symbols Class A common stock"
            ),
            "acquirer": "acquiring parent purchaser buyer entered into merger agreement",
            "target": "target company being acquired subject company",
            "consideration_type": "cash stock mixed consideration exchange ratio",
            "security_description": "common stock class shares title security",
            "shareholder_vote_date": "special meeting shareholder vote date",
        },
    ),
    system_prompt=(
        "You are a merger field extractor. Evidence is already filtered for this field "
        "(RULES facts, GLiNER/passage spans, HYBRID EXCERPTS, temporal DATE spans). "
        "Pick the best listed value when one clearly matches the definition; return null "
        "when none do — especially dates, tickers, and roles with only wrong-party spans. "
        "Never return bare Holdco / Company / Merger Sub alone as a party name. "
        "When GLiNER conflicts with HYBRID EXCERPTS, prefer the hybrid wording if it better "
        "matches the field definition. "
        "Return one JSON object only. Copy values from evidence (light cleanup OK). "
        "Do not invent CUSIP/ISIN/ticker/date/price strings that are not in the evidence."
    ),
)
