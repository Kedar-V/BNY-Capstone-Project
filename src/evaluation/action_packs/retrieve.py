"""Pack-tunable clause retrieval (passage quotes → regex hits)."""

from __future__ import annotations

import re
from typing import Any

from src.evaluation.action_packs.base import ClauseFieldSpec


def _quotes(passage: dict[str, Any], field: str, *, max_chars: int) -> str:
    items = passage.get(field) or []
    if not isinstance(items, list):
        items = [items]
    parts: list[str] = []
    n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        q = (it.get("quote") or "").strip()
        if len(q) < 12:
            continue
        if n + len(q) > max_chars:
            q = q[: max(0, max_chars - n)]
        parts.append(q)
        n += len(q)
        if n >= max_chars:
            break
    return "\n---\n".join(parts)


def _all_passage_text(passage: dict[str, Any]) -> str:
    chunks: list[str] = []
    for _field, items in (passage or {}).items():
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if isinstance(it, dict):
                q = (it.get("quote") or "").strip()
                if q:
                    chunks.append(q)
            elif isinstance(it, str) and it.strip():
                chunks.append(it.strip())
    return "\n".join(chunks)


def retrieve_clause(
    spec: ClauseFieldSpec,
    *,
    passages: dict[str, Any] | None,
    excerpts: str = "",
    doc_text: str = "",
) -> str:
    """GT passage quotes first; else regex hits from passages → excerpts → doc_text."""
    passage = passages or {}
    quote_key = spec.quote_field
    primary = ""
    if spec.use_passage_quotes and quote_key:
        primary = _quotes(passage, quote_key, max_chars=spec.max_chars)
        if len(primary) >= 40 and (
            not spec.quote_accept_re
            or re.search(spec.quote_accept_re, primary, flags=re.I)
        ):
            return primary

    # Union all sources for regex (passages often empty in current GT CSV)
    blob = "\n".join(
        x for x in (_all_passage_text(passage), doc_text or "", excerpts or "") if x
    )
    if not blob:
        return primary
    # Collapse SEC line-breaks so "pro rata\nbasis" matches as one phrase
    blob = re.sub(r"\s+", " ", blob)

    hits: list[str] = []
    for pat in spec.patterns:
        rx = re.compile(pat, flags=re.I | re.S)
        for m in rx.finditer(blob):
            s = re.sub(r"\s+", " ", (m.group(1) if m.lastindex else m.group(0))).strip()
            if len(s) >= 40 and s not in hits:
                hits.append(s)
        if hits:
            break
    if not hits:
        return primary

    out: list[str] = []
    n = 0
    for h in hits:
        if n + len(h) > spec.max_chars:
            break
        out.append(h)
        n += len(h)
    retrieved = "\n---\n".join(out)
    if primary and primary not in retrieved:
        return (primary + "\n---\n" + retrieved)[: spec.max_chars]
    return retrieved
