"""Prompt builders and response parsers for per-field extraction (pure functions)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from src.evaluation.action_packs.base import ActionPack

_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified"})


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
    return (
        f"Extract `{field}` from the evidence pack below.\n\n"
        f"DEFINITION: {definition}\n\n"
        "HOW TO CHOOSE:\n"
        f"- {pick}\n"
        "- Prefer higher score= / higher field_cues= when several candidates compete.\n"
        "- Copy the value= (or date=) string; light cleanup of whitespace is OK.\n"
        "- Do NOT return null if at least one listed value plausibly matches the definition.\n"
        "- null ONLY when every listed item is clearly wrong for this field.\n"
        "- Never invent identifiers/dates/prices absent from the evidence.\n\n"
        f'Return JSON {{"{field}": "<string>"}} or {{"{field}": null}}.\n\n'
        f"EVIDENCE:\n{evidence}\n"
    )


def validate_prompt(pack: ActionPack, field: str, value: str, evidence: str) -> str:
    definition = pack.field_defs.get(field, field)
    return (
        f"Validate a candidate for `{field}`.\n"
        f"DEFINITION: {definition}\n"
        f"CANDIDATE: {value!r}\n\n"
        "Return JSON {\"keep\": true|false}. "
        "keep=true only if the candidate satisfies the definition and is supported by EVIDENCE. "
        "keep=false for counsel-as-party, wrong date type, currency guesses without $/£/€ offer price, etc.\n\n"
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
