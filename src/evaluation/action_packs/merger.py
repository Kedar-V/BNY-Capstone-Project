"""Merger ActionPack (core GT columns + defs distilled from MERGER_PROMPT)."""

from __future__ import annotations

from typing import Any, Mapping

from src.evaluation.action_packs.base import ActionPack, PackHooks
from src.evaluation.action_packs.orgs import same_org

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
        "Entity acquiring the target. Prefer the acquiring parent over a merger sub. "
        "Do not invent a role when the filing is a merger of equals."
    ),
    "target": (
        "Entity being acquired. Distinguish from acquirer / merger sub / other parties."
    ),
    "consideration_type": (
        'Form paid to holders: "Cash", "Stock", "Mixed cash and stock", '
        '"Elective consideration", or a short description of other components. '
        "Fractional-share cash alone does not make stock into mixed."
    ),
    "cash_consideration": (
        "Cash per share/unit with currency when stated. Preserve ranges/formulas. "
        "Not aggregate deal value, fees, or market price."
    ),
    "stock_exchange_ratio": (
        "Shares of new security per share of old security, with direction and classes. "
        "Copy stated ratio/formula; do not compute from prices."
    ),
    "shareholder_vote_date": (
        "Date/time of the shareholder vote on the merger when explicitly stated."
    ),
    "election_deadline": (
        "Deadline for holders to elect among consideration options, when stated."
    ),
    "effective_date": (
        "Legal closing / consummation / effectiveness date of the merger."
    ),
    "security_description": (
        "Short class/type of the affected security (e.g. common stock)."
    ),
    "ticker": "Exchange ticker symbol(s) from evidence.",
    "cusip": "9-character CUSIP from evidence. Copy exactly.",
    "isin": "ISIN from evidence. Copy exactly.",
}

FIELD_PICK: dict[str, str] = {
    "acquirer": (
        "Prefer purchaser/parent buyer — NOT the filing company / primary_entity / target. "
        "On a DEFM14A the registrant is usually the target, not the acquirer."
    ),
    "target": (
        "Prefer primary_entity / filing company being acquired. "
        "Not the purchaser/parent buyer, counsel, or agents."
    ),
    "stock_exchange_ratio": (
        "Prefer an explicit X-for-Y ratio with both securities named. "
        "If evidence says cash-only / no ratio, return exactly: No stock consideration."
    ),
    "consideration_type": (
        "If evidence shows a cash per-share price and no stock ratio, return Cash. "
        "Pick the label that matches holder consideration, not financing."
    ),
    "cash_consideration": "Prefer per-share cash; skip aggregate $ millions / fees.",
    "shareholder_vote_date": "Prefer the vote/meeting date, not mailing or effectiveness.",
    "election_deadline": "Only return a date with election/choice cues; else null.",
    "effective_date": "Prefer closing/consummation/effective; not vote or mailing dates.",
    "security_description": "If a security_description span exists, return it.",
    "ticker": "If any ticker value is listed, return it.",
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
# Keep validate narrow — Pass C was dropping correct B picks (acquirer, "No stock consideration").
VALIDATE_FIELDS = frozenset(
    {
        "consideration_type",
        "cash_consideration",
        "effective_date",
        "shareholder_vote_date",
    }
)


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
    junk_roles=frozenset({"parent", "merger sub", "merger subsidiary", "company", "purchaser"}),
    drop_span=_drop_span,
    rules_prelude=_rules_prelude,
    direct_prior=_direct_prior,
    synth_spans=_synth_spans,
    prior_label="A_inventory",
    prior_hint="primary_entity",
    extras_from_inventory=_extras_from_inventory,
)

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
    system_prompt=(
        "You are a merger field extractor. Evidence is already filtered for this field "
        "(RULES facts, GLiNER/passage spans, temporal DATE spans). "
        "Your job is to PICK the best matching listed value — not to abstain. "
        "Return one JSON object only. Copy values from evidence (light cleanup OK). "
        "Do not invent CUSIP/ISIN/ticker/date/price strings that are not in the evidence."
    ),
)
