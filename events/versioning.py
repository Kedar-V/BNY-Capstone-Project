"""Replay an event's filings in order and record what each one changed.

Each filing is merged into the state left by the filings before it, with the same rule the store uses
(store.merge_value), so a blank in an amendment never erases an earlier value. A filing's Version lists the fields
it changed, and the fields it restated with no change.

Three kinds of change:
- value:  a parsed field (date, price, ratio) moved, e.g. expiration 11/20/2026 -> 12/4/2026
- text:   a descriptive field (conditions, options) says something different, not just reworded
- status: the event's status moved, e.g. pending -> terminated
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import parsers
from .store import _SKIP, PARSED, STATUS, Event, Filing, merge_value

# Parsed fields tracked per action: the store's fields plus ones only an amendment check needs.
TRACKED: dict[str, dict[str, tuple[str, Callable]]] = {
    "tender_offer": {**PARSED["tender_offer"], "settlement_date": ("settlement_date", parsers.parse_date)},
    "merger": dict(PARSED["merger"]),
    "rights_issue": dict(PARSED["rights_issue"]),
}
# Descriptive fields compared as text. A change here needs judgment: rules cannot tell what it means for holders.
TEXT_FIELDS: dict[str, list[str]] = {
    "tender_offer": ["minimum_tender_condition", "proration_terms", "tendering_conditions", "conditions_restrictions",
                     "available_options", "default_option"],
    "merger": ["consideration_type", "closing_conditions", "available_options", "default_option"],
    "rights_issue": ["available_options", "default_option"],
}
# Word overlap at or above this is the same text reworded: extraction runs phrase the same terms differently.
SAME_TEXT = 0.8


@dataclass
class FieldChange:
    key: str
    kind: str  # value | text | status
    previous: Any
    current: Any
    source: str  # extraction field the value came from
    quote: str | None = None
    location: str | None = None
    similarity: float | None = None  # text changes only


@dataclass
class Version:
    index: int
    filing: Filing
    before: dict[str, Any]
    after: dict[str, Any]
    text_before: dict[str, str]
    text_after: dict[str, str]
    status_before: str | None
    status_after: str | None
    changes: list[FieldChange] = field(default_factory=list)
    restated: list[str] = field(default_factory=list)  # fields this filing states with no change


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()))


def text_similarity(a: str, b: str) -> float:
    """Share of distinct words in common (Jaccard). Case, punctuation and item order do not count."""
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x | y else 1.0


def _quote(f: Filing, source: str) -> tuple[str | None, str | None]:
    quotes = f.passages.get(source) or []
    return (quotes[0]["quote"], quotes[0]["location"] or None) if quotes else (None, None)


def replay(event: Event) -> list[Version]:
    """One Version per filing, oldest first."""
    tracked, text_fields, parse_status = TRACKED[event.action], TEXT_FIELDS[event.action], STATUS[event.action]
    state: dict[str, Any] = {}
    text: dict[str, str] = {}
    status: str | None = None
    versions: list[Version] = []
    for i, f in enumerate(event.filings):
        before, text_before, status_before = dict(state), dict(text), status
        changes: list[FieldChange] = []
        restated: list[str] = []
        for key, (source, parse) in tracked.items():
            value = parse(f.fields.get(source))
            if value is None:
                continue
            prev = state.get(key)
            merged = merge_value(key, prev, value)
            if merged is _SKIP or merged == prev:
                restated.append(key)
                continue
            state[key] = merged
            changes.append(FieldChange(key, "value", prev, merged, source, *_quote(f, source)))
        for name in text_fields:
            raw = f.fields.get(name)
            if not raw:
                continue
            prev = text.get(name)
            if prev is not None:
                sim = text_similarity(prev, raw)
                if sim >= SAME_TEXT:
                    restated.append(name)
                    continue
            else:
                sim = None
            text[name] = raw
            changes.append(FieldChange(name, "text", prev, raw, name, *_quote(f, name), similarity=sim))
        new_status = parse_status(f.fields.get("event_status"))
        if new_status and new_status != status:
            changes.append(FieldChange("event_status", "status", status, new_status, "event_status", *_quote(f, "event_status")))
            status = new_status
        versions.append(Version(i, f, before, dict(state), text_before, dict(text), status_before, status, changes, restated))
    return versions
