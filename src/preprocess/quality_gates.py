"""Upstream Concise Rep quality gates (gold / regression).

Checks ranking quality on assembled candidate_facts — does not discover fields.
"""

from __future__ import annotations

import re
from typing import Any

from src.preprocess.span_rank import is_agent_org, is_shell_party

_MONEY = re.compile(r"\$\s*[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:per\s+share|/share)\b", re.I)
_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)

_BOILERPLATE_SECURITY = frozenset({"shares", "share", "common stock", "stock", "securities"})


def _top1(facts: list[dict[str, Any]], hint: str) -> dict[str, Any] | None:
    items = [f for f in facts if (f.get("field_hint") or "") == hint]
    if not items:
        return None
    return max(items, key=lambda f: float(f.get("rank_score") or f.get("confidence") or 0))


def check_event_rep(rep: dict[str, Any]) -> dict[str, Any]:
    """Return {ok: bool, failures: [...], checks: {...}} for one Concise Rep."""
    facts = list(rep.get("candidate_facts") or [])
    failures: list[str] = []
    checks: dict[str, Any] = {}

    if any((f.get("method") or "") == "regex" for f in facts):
        failures.append("method_regex_present")

    price = _top1(facts, "offer_price")
    checks["top1_offer_price"] = (price or {}).get("raw")
    if not price or not _MONEY.search(price.get("raw") or ""):
        failures.append("top1_offer_price_not_money")

    exp = _top1(facts, "expiration_date")
    checks["top1_expiration_date"] = (exp or {}).get("raw")
    if not exp or not _DATE.search(exp.get("raw") or ""):
        failures.append("top1_expiration_date_not_calendar")

    offeror = _top1(facts, "offeror")
    checks["top1_offeror"] = (offeror or {}).get("raw")
    if offeror:
        raw = offeror.get("raw") or ""
        if is_agent_org(raw) or is_shell_party(raw):
            failures.append("top1_offeror_is_agent_or_shell")

    sec = _top1(facts, "security_description")
    checks["top1_security_description"] = (sec or {}).get("raw")
    if sec:
        n = re.sub(r"\s+", " ", (sec.get("raw") or "").strip().lower())
        if n in _BOILERPLATE_SECURITY:
            failures.append("top1_security_boilerplate")

    passages = [len(f.get("passage") or "") for f in facts if f.get("passage")]
    median_pass = sorted(passages)[len(passages) // 2] if passages else 0
    checks["passage_len_median"] = median_pass
    if passages and median_pass < 300:
        failures.append("passage_median_lt_300")

    return {"ok": not failures, "failures": failures, "checks": checks}


def check_gold_artifacts(event_reps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run gates on {event_id: event_rep}."""
    per_event = {eid: check_event_rep(rep) for eid, rep in event_reps.items()}
    ok = all(v["ok"] for v in per_event.values()) if per_event else False
    return {"ok": ok, "events": per_event}
