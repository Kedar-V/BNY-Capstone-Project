"""Prompt builders and response parsers for per-field extraction (pure functions)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from src.evaluation.action_packs.base import ActionPack

_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified"})
# Prefer null over a wrong neighboring date (temporal bags are noisy).
_ABSTAIN_OK_FIELDS = frozenset(
    {
        "effective_date",
        "withdrawal_deadline",
        "election_deadline",
        "shareholder_vote_date",
    }
)


def select_prompt(
    pack: ActionPack,
    field: str,
    evidence: str,
    *,
    mode: Literal["copy", "pick"],
) -> str:
    """Build the extraction prompt.

    copy mode: ``evidence`` is the raw excerpt text (no prefix); the pack's
    clause prompt is formatted with it. pick mode: ``evidence`` is the
    rules/GLiNER evidence pack.
    """
    if mode == "copy":
        spec = pack.clause_fields[field]
        return spec.extract_prompt.format(excerpt=evidence, field=field)

    definition = pack.field_defs.get(field, field)
    pick = pack.field_pick.get(field, "Pick the best listed value for this field.")
    if evidence.startswith("(no "):
        return (
            f"Extract `{field}`.\n"
            f"DEFINITION: {definition}\n"
            "Evidence pack is empty for this field → return null.\n"
            f'Return JSON {{"{field}": null}}.\n\n'
            f"EVIDENCE:\n{evidence}\n"
        )
    if field in _ABSTAIN_OK_FIELDS:
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Prefer higher field_cues= when several candidates compete; ignore Act years "
            "(1934/1940), signature blocks, and superseded prior-year dates.\n"
            "- Many listed dates are the WRONG type for this field. "
            "If none clearly match the DEFINITION, return null — do not pick the nearest date.\n"
            "- If HYBRID EXCERPTS disagree with a GLiNER/temporal value=, prefer hybrid when it "
            "better matches the definition.\n"
            "- Copy a date=/value= string or a short hybrid span; light cleanup OK.\n"
            "- Never invent dates absent from the evidence.\n\n"
        )
    elif field == "offer_price":
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Formula (NAV / Valuation Date / Early Repurchase / private-offering price) beats "
            "any GLiNER dollar span, including higher score= amounts.\n"
            "- Discard aggregates, par value, fees, and caps.\n"
            "- Prefer HYBRID EXCERPTS formula wording over GLiNER value= when both appear.\n"
            "- Bare number only for an explicit fixed per-share cash price.\n"
            "- Never invent prices absent from the evidence.\n\n"
        )
    elif field in ("acquirer", "target"):
        role = (
            "acquiring parent / ultimate buyer"
            if field == "acquirer"
            else "company being acquired (target / subject)"
        )
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            f"- Return the full legal name of the {role}.\n"
            "- NEVER return bare role nouns: Parent, Holdco, Company, Merger Sub, Purchaser, "
            "Buyer, Issuer, Registrant, Newco, Pubco, SPAC.\n"
            "- When both buyer and target appear, apply the DEFINITION role — score= does not win.\n"
            "- Prefer HYBRID EXCERPTS legal names over short GLiNER nicknames when both appear.\n"
            "- Do NOT return null if a full legal name for this role is listed.\n"
            "- Never invent party names absent from the evidence.\n\n"
        )
    elif field == "ticker":
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Return the TARGET / subject-company ticker only (often next to its legal name).\n"
            "- If several tickers appear, pick the issuer being acquired — not the acquirer/parent.\n"
            "- Reject exchange names (Nasdaq/NYSE/OTC), CUSIP/ISIN digit strings, and person names.\n"
            "- Multi-class listings may be comma-separated (e.g. FSHP, FSHPR, FSHPU) — copy that set.\n"
            "- Never invent tickers absent from the evidence.\n\n"
        )
    elif field == "security_description":
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Prefer the title / cover class of the security being acquired or exchanged "
            "(e.g. 'common stock', 'Class B Common Stock'), not a financing preferred or "
            "parent ordinary-share nickname.\n"
            "- Keep Class A vs Class B / ordinary vs preferred exactly as labeled for the "
            "subject security.\n"
            "- Reject bare 'Equity Interest', 'Real Common Shares', or parent-share labels "
            "when a clearer subject class is listed.\n"
            "- Never invent a class absent from the evidence.\n\n"
        )
    elif field == "stock_exchange_ratio":
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Prefer an explicit per-share ratio ('N share(s) of X per share') or a named "
            "Exchange Ratio formula sentence — copy it, do not shorten to a floating factor alone.\n"
            "- If the deal is cash-only / no stock, return exactly: No stock consideration.\n"
            "- Do NOT return null when a ratio or 'No stock consideration' cue is in the bag.\n"
            "- Do NOT return aggregate share counts (e.g. millions newly issued) as the ratio.\n"
            "- Never invent a ratio from prices.\n\n"
        )
    elif field == "cash_consideration":
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Prefer per-share merger consideration with currency (e.g. $15.00 per share).\n"
            "- If holders get only stock / no cash, return exactly: No cash consideration.\n"
            "- Reject aggregates, fees, market quotes, par value ($0.0001), and trust totals "
            "when a real per-share price or 'No cash consideration' is listed.\n"
            "- Never invent a dollar amount absent from the evidence.\n\n"
        )
    elif pack.hybrid_enabled:
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Apply DEFINITION role rules before scores. If spans contradict (Parent vs "
            "Merger Sub, Fund vs Adviser, issuer vs support-agreement party), pick the role "
            "the definition names — a higher score= does not win.\n"
            "- Among role-compatible candidates, prefer higher score= / field_cues=.\n"
            "- If HYBRID EXCERPTS disagree with a GLiNER value=, prefer the hybrid wording "
            "when it better matches the definition (GLiNER can be confidently wrong).\n"
            "- Copy the value= (or date=) string, or a short span from HYBRID EXCERPTS; "
            "light cleanup of whitespace is OK.\n"
            "- Do NOT return null if at least one listed value or hybrid excerpt "
            "plausibly matches the definition.\n"
            "- null ONLY when every listed item and hybrid excerpt is clearly wrong "
            "for this field.\n"
            "- Never invent identifiers/dates/prices absent from the evidence.\n\n"
        )
    else:
        how = (
            "HOW TO CHOOSE:\n"
            f"- {pick}\n"
            "- Apply DEFINITION role rules before scores when spans contradict.\n"
            "- Among role-compatible candidates, prefer higher score= / field_cues=.\n"
            "- Copy the value= (or date=) string; light cleanup of whitespace is OK.\n"
            "- Do NOT return null if at least one listed value plausibly matches the definition.\n"
            "- null ONLY when every listed item is clearly wrong for this field.\n"
            "- Never invent identifiers/dates/prices absent from the evidence.\n\n"
        )
    shots = _format_field_shots(pack, field)
    return (
        f"Extract `{field}` from the evidence pack below.\n\n"
        f"DEFINITION: {definition}\n\n"
        f"{how}"
        f"{shots}"
        f'Return JSON {{"{field}": "<string>"}} or {{"{field}": null}}.\n\n'
        f"EVIDENCE:\n{evidence}\n"
    )


def _format_field_shots(pack: ActionPack, field: str) -> str:
    shots = (getattr(pack, "field_shots", None) or {}).get(field) or ()
    if not shots:
        return ""
    blocks: list[str] = ["EXAMPLES (follow the same JSON shape; do not copy these answers):\n"]
    for i, shot in enumerate(shots, 1):
        ans = "null" if shot.answer is None else json.dumps(shot.answer, ensure_ascii=False)
        note = f"  # {shot.note}" if shot.note else ""
        blocks.append(
            f"Example {i}:{note}\n"
            f"EVIDENCE:\n{shot.evidence.strip()}\n"
            f'→ {{"{field}": {ans}}}\n'
        )
    return "\n".join(blocks) + "\n"


def validate_prompt(pack: ActionPack, field: str, value: str, evidence: str) -> str:
    definition = pack.field_defs.get(field, field)
    extra = ""
    if field == "effective_date":
        extra = (
            "keep=false if the candidate is an expiration, withdrawal, valuation, filing, "
            "signature, or acceptance-for-payment date rather than legal effectiveness / "
            "merger Effective Time. keep=false when the filing is only a standalone tender "
            "with no stated effectiveness date.\n"
        )
    elif field == "withdrawal_deadline":
        extra = (
            "keep=false if the candidate is only an expiration/valuation/filing date and the "
            "evidence never describes withdrawal rights. keep=true for an expiration deadline "
            "only when the text says withdrawal continues until expiration.\n"
        )
    elif field == "offer_price":
        extra = (
            "keep=false for aggregates (total proceeds / millions), par value, fees, or caps. "
            "keep=false for a bare dollar print when EVIDENCE states a NAV/Valuation Date/"
            "Early Repurchase/private-offering formula — prefer the formula. "
            "keep=true for a fixed per-share cash price or a stated formula.\n"
        )
    elif field == "security_description":
        if pack.name == "merger":
            extra = (
                "keep=true for the subject/title security class being acquired or exchanged "
                "(common / Class A/B / ordinary). keep=false for financing preferred, "
                "parent-share nicknames, bare 'Equity Interest', or the opposite party's class "
                "when the subject class is also listed.\n"
            )
        else:
            extra = (
                "keep=false if the candidate is only a class/title line without the issuer/fund "
                "name when the issuer appears in EVIDENCE. keep=true when issuer+class are present.\n"
            )
    elif field == "proration_terms":
        extra = (
            "keep=true for an oversubscription / \"If more than…\" / pro rata clause copied "
            "from EVIDENCE. keep=false only if it is unrelated text or a bare purchase cap "
            "with no allocation rule.\n"
        )
    elif field == "settlement_date":
        extra = (
            "keep=true for the template 'Payment: promptly' when EVIDENCE supports promptly-pay "
            "/ acceptance-for-payment timing. keep=true for a calendar payment/acceptance date "
            "with a pay cue. keep=false for expiration, valuation, or filing dates.\n"
        )
    elif field == "stock_exchange_ratio":
        extra = (
            "keep=true for 'No stock consideration' when EVIDENCE is cash-only / has no ratio. "
            "keep=true for an explicit X-for-Y / shares-per-share / exchange-ratio sentence. "
            "keep=false for a price-derived number with no stated exchange ratio.\n"
        )
    elif field == "cash_consideration":
        extra = (
            "keep=true for per-share merger consideration cash (with currency) or "
            "'No cash consideration'. "
            "keep=false for aggregate deal value / $ millions / fees / market quotes / "
            "trust-account totals that are not the per-share price.\n"
        )
    elif field == "consideration_type":
        extra = (
            "keep=true for Cash/Stock/Mixed/Elective matching holder consideration. "
            "keep=false when EVIDENCE has conversion/exchange-ratio language and the "
            "candidate is Cash-only, or when the candidate is financing/trust cash only.\n"
        )
    elif field == "shareholder_vote_date":
        extra = (
            "keep=true for the shareholder meeting / vote date on the merger. "
            "keep=false for mailing, record, effectiveness, closing, or election dates.\n"
        )
    elif field in ("acquirer", "target"):
        who = "acquiring parent/buyer" if field == "acquirer" else "company being acquired"
        extra = (
            f"keep=true only if the candidate is the {who} (full legal name when listed). "
            "keep=false for merger sub / Holdco / bare 'Company' / filing shortname alone, "
            "counsel, agents, or the opposite party.\n"
        )
    elif field == "ticker":
        extra = (
            "keep=true for the target/subject issuer ticker symbol (letters near the company name). "
            "keep=false for acquirer/parent tickers, CUSIP/ISIN digit strings, or exchange "
            "names (Nasdaq/NYSE) alone.\n"
        )
    elif field == "election_deadline":
        extra = (
            "keep=true only with election/choice/form-of-election cues. "
            "keep=false for vote-only, closing-only, or placeholder ([•]/ []) dates.\n"
        )
    return (
        f"Validate a candidate for `{field}`.\n"
        f"DEFINITION: {definition}\n"
        f"CANDIDATE: {value!r}\n\n"
        "Return JSON {\"keep\": true|false}. "
        "keep=true only if the candidate satisfies the definition and is supported by EVIDENCE. "
        "keep=false for counsel-as-party, wrong date type, currency guesses without $/£/€ offer price, etc.\n"
        f"{extra}\n"
        f"EVIDENCE:\n{evidence}\n"
    )


def parse_field(raw: str, field: str) -> str | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    obj: Any = {}
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = {}
    if not isinstance(obj, dict):
        return None
    v = obj.get(field)
    if v is None and "value" in obj:
        v = obj.get("value")
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in _NA:
        return None
    return v[:400]


def parse_keep(raw: str) -> bool | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    obj: Any = {}
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                # ponytail: Qwen validate sometimes returns huge broken JSON — keep pred
                return None
    if not isinstance(obj, dict) or "keep" not in obj:
        return None
    return bool(obj["keep"])
