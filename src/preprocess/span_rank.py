"""Value-aware ranking/filtering of GLiNER spans + passage expansion.

Does not discover new spans from raw filings — only ranks/filters model outputs.
"""

from __future__ import annotations

import re
from typing import Any

from src.preprocess.contracts import LABEL_LIKE_PHRASES, LABEL_TO_FIELD_HINT

_MONEY = re.compile(r"\$\s*[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:per\s+share|/share)\b", re.I)
_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)
_CUSIP = re.compile(r"^[0-9A-Za-z]{9}$")
_TICKER = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")
_CORP_SUFFIX = re.compile(
    r"\b(?:Inc\.?|Corp\.?|Corporation|Ltd\.?|LLC|L\.?P\.?|PLC|N\.?A\.?|Company|Co\.?)\b",
    re.I,
)
# Depositary / information / exchange / paying agents — not offeror/purchaser/target.
_AGENT_ROLE = re.compile(
    r"\b(?:"
    r"computershare|information\s+agent|depositary|depository|"
    r"depository\s+trust|dtc|"
    r"exchange\s+agent|paying\s+agent|transfer\s+agent|"
    r"macken(?:zie)?\s+partners|georgeson|innisfree|"
    r"df\s*king|okapi\s+partners|morrow\s+sodali|"
    r"trustee|trust\s+company|jefferies"
    r")\b",
    re.I,
)
_SHELL_PARTY = re.compile(
    r"^(?:parent|merger\s*sub(?:sidiary)?|purchaser|offeror|company|the\s+company|"
    r"target\s+company|acquiring\s+company|"
    r"acquisition\s+sub(?:sidiary)?|buyer)$",
    re.I,
)
_WEAK_SECURITY = frozenset(
    {
        "shares",
        "share",
        "common stock",
        "stock",
        "securities",
        "class a",
        "class b",
        "ordinary shares",
    }
)

# Multiplicative / additive bonuses by (field_hint, doc_role).
_DOC_ROLE_BONUS: dict[tuple[str, str], float] = {
    ("cusip", "cover"): 0.25,
    ("ticker", "cover"): 0.2,
    ("security_description", "cover"): 0.2,
    ("target", "cover"): 0.2,
    ("offeror", "cover"): 0.1,
    ("offer_price", "otp"): 0.2,
    ("expiration_date", "otp"): 0.2,
    ("withdrawal_deadline", "otp"): 0.15,
    ("cash_amount", "otp"): 0.1,
    ("offer_price", "cover"): -0.05,
    ("expiration_date", "cover"): -0.05,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def is_label_like(text: str) -> bool:
    n = _norm(text)
    if not n or len(n) < 2:
        return True
    if n in LABEL_LIKE_PHRASES:
        return True
    # heading-ish Title Case short phrases without digits
    if len(n) < 40 and not re.search(r"\d", n) and n.endswith(("price", "time", "date", "condition")):
        return True
    return False


def is_agent_org(text: str) -> bool:
    """True if org looks like depositary / info agent / trustee, not deal party."""
    return bool(_AGENT_ROLE.search(text or ""))


def is_shell_party(text: str) -> bool:
    return bool(_SHELL_PARTY.match((text or "").strip()))


def looks_like_legal_name(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 5:
        return False
    if _CORP_SUFFIX.search(t) and len(t.split()) >= 2:
        return True
    if "," in t and len(t.split()) >= 2:
        return True
    return False


def value_bonus(field_hint: str, text: str) -> float:
    t = text or ""
    hint = field_hint or ""
    if hint in {"offer_price", "cash_amount"} and _MONEY.search(t):
        return 0.45
    if hint in {"expiration_date", "withdrawal_deadline", "effective_date", "settlement_date", "payment_date"}:
        if _DATE.search(t):
            return 0.45
    if hint == "cusip" and _CUSIP.match(t.strip()):
        return 0.5
    if hint == "ticker" and _TICKER.match(t.strip()):
        return 0.35
    if hint in {"offeror", "target", "purchaser"}:
        if is_label_like(t) or is_shell_party(t):
            return -0.35
        if is_agent_org(t):
            return -0.55
        if looks_like_legal_name(t):
            return 0.3
        if len(t.split()) >= 2 and not is_label_like(t):
            return 0.1
        if len(t.strip()) < 5:
            return -0.25
    if hint == "security_description":
        if _norm(t) in _WEAK_SECURITY:
            return -0.4
        if len(t.strip()) < 5:
            return -0.35
        if looks_like_legal_name(t) or len(t) > 20:
            return 0.2
    if hint == "currency":
        if t.strip().upper() in {"USD", "EUR", "GBP", "CAD", "JPY"}:
            return 0.4
        if "$" in t and len(t.strip()) <= 3:
            return 0.1
        if "\n" in t or len(t) > 12:
            return -0.3
    return 0.0


def doc_role_bonus(field_hint: str, doc_role: str | None, segment_kind: str | None = None) -> float:
    role = (doc_role or "").lower()
    hint = field_hint or ""
    bonus = _DOC_ROLE_BONUS.get((hint, role), 0.0)
    kind = (segment_kind or "").lower()
    if hint in {"offer_price", "expiration_date", "withdrawal_deadline"} and kind in {
        "faq",
        "priority_section",
    }:
        bonus += 0.08
    return bonus


def rank_score(span: dict[str, Any]) -> float:
    label = span.get("label") or ""
    hint = LABEL_TO_FIELD_HINT.get(label, label)
    text = span.get("text") or ""
    base = float(span.get("score") or 0.0)
    score = base + value_bonus(hint, text)
    score += doc_role_bonus(hint, span.get("doc_role"), span.get("segment_kind"))
    if is_label_like(text):
        score -= 0.55
    # slight priority for summary/faq segments
    kind = (span.get("segment_kind") or "").lower()
    if kind in {"faq", "priority_section"} or span.get("priority"):
        score += 0.05
    return score


def expand_passage(text: str, start: int, end: int, *, radius: int = 400) -> str:
    if not text:
        return ""
    start = max(0, int(start or 0))
    end = max(start, int(end or start))
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    # snap to sentence-ish boundaries when possible
    if left > 0:
        for sep in (". ", ".\n", "\n\n"):
            i = text.rfind(sep, left, start)
            if i >= left:
                left = i + len(sep)
                break
    if right < len(text):
        for sep in (". ", ".\n", "\n\n"):
            i = text.find(sep, end, right)
            if i >= 0:
                right = i + 1
                break
    return text[left:right].strip()


def only_label_like_for_family(spans: list[dict[str, Any]], family: str) -> bool:
    """True if family has spans but none look like values."""
    fam_spans = []
    for sp in spans:
        hint = LABEL_TO_FIELD_HINT.get(sp.get("label") or "", sp.get("label") or "")
        if family == "price" and hint == "offer_price":
            fam_spans.append(sp)
        elif family == "date" and hint in {
            "expiration_date",
            "withdrawal_deadline",
            "effective_date",
            "settlement_date",
        }:
            fam_spans.append(sp)
        elif family == "org" and hint in {"offeror", "target", "purchaser"}:
            fam_spans.append(sp)
    if not fam_spans:
        return False
    if family == "price":
        return not any(_MONEY.search(sp.get("text") or "") for sp in fam_spans)
    if family == "date":
        return not any(_DATE.search(sp.get("text") or "") for sp in fam_spans)
    if family == "org":
        return all(
            is_label_like(sp.get("text") or "") or is_shell_party(sp.get("text") or "") or is_agent_org(sp.get("text") or "")
            for sp in fam_spans
        )
    return False


def _prefer_legal_over_shell(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within a party hint, demote shell/agent when a legal-name candidate exists."""
    has_legal = any(looks_like_legal_name(sp.get("text") or "") and not is_agent_org(sp.get("text") or "") for sp in items)
    if not has_legal:
        return items
    adjusted = []
    for sp in items:
        text = sp.get("text") or ""
        rs = float(sp.get("rank_score") or 0.0)
        if is_agent_org(text) or is_shell_party(text) or len(text.strip()) < 5:
            rs -= 0.4
            sp = {**sp, "rank_score": rs}
        adjusted.append(sp)
    return adjusted


def _prefer_long_security(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_strong = any(
        looks_like_legal_name(sp.get("text") or "") or len((sp.get("text") or "").strip()) > 12 for sp in items
    )
    if not has_strong:
        return items
    adjusted = []
    for sp in items:
        text = sp.get("text") or ""
        rs = float(sp.get("rank_score") or 0.0)
        if _norm(text) in _WEAK_SECURITY or len(text.strip()) < 5:
            rs -= 0.35
            sp = {**sp, "rank_score": rs}
        adjusted.append(sp)
    return adjusted


def _demote_ticker_as_target(by_hint: dict[str, list[dict[str, Any]]]) -> None:
    """If top target equals a ticker span, prefer org containing that ticker in passage."""
    tickers = {_norm(sp.get("text") or "") for sp in by_hint.get("ticker") or []}
    targets = by_hint.get("target") or []
    if not tickers or not targets:
        return
    adjusted = []
    for sp in targets:
        text = _norm(sp.get("text") or "")
        rs = float(sp.get("rank_score") or 0.0)
        if text in tickers and len(text) <= 5:
            rs -= 0.3
            # boost if a longer org mentions this ticker in passage
            for other in targets:
                ot = other.get("text") or ""
                if looks_like_legal_name(ot) and text.upper() in (other.get("passage") or other.get("text") or "").upper():
                    other["rank_score"] = float(other.get("rank_score") or 0) + 0.15
            sp = {**sp, "rank_score": rs}
        adjusted.append(sp)
    by_hint["target"] = adjusted


def dedupe_nms(spans: list[dict[str, Any]], *, top_k_per_hint: int = 12) -> list[dict[str, Any]]:
    by_hint: dict[str, list[dict[str, Any]]] = {}
    for sp in spans:
        hint = LABEL_TO_FIELD_HINT.get(sp.get("label") or "", sp.get("label") or "other")
        sp = {**sp, "rank_score": rank_score(sp), "field_hint": hint}
        by_hint.setdefault(hint, []).append(sp)

    for hint in ("offeror", "target", "purchaser"):
        if hint in by_hint:
            by_hint[hint] = _prefer_legal_over_shell(by_hint[hint])
    if "security_description" in by_hint:
        by_hint["security_description"] = _prefer_long_security(by_hint["security_description"])
    _demote_ticker_as_target(by_hint)

    out: list[dict[str, Any]] = []
    for hint, items in by_hint.items():
        items = sorted(items, key=lambda x: float(x.get("rank_score") or 0), reverse=True)
        seen: set[str] = set()
        kept = 0
        for sp in items:
            key = _norm(sp.get("text") or "")
            if key in seen:
                continue
            seen.add(key)
            out.append(sp)
            kept += 1
            if kept >= top_k_per_hint:
                break
    return sorted(out, key=lambda x: float(x.get("rank_score") or 0), reverse=True)


def enrich_spans_with_passages(
    spans: list[dict[str, Any]],
    segment_texts: dict[str, str],
) -> list[dict[str, Any]]:
    out = []
    for sp in spans:
        seg_id = sp.get("segment_id") or ""
        text = segment_texts.get(seg_id) or ""
        passage = expand_passage(text, sp.get("start") or 0, sp.get("end") or 0)
        out.append({**sp, "passage": passage or sp.get("passage") or ""})
    return out
