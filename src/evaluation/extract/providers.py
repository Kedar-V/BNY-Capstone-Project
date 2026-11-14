"""Evidence providers: per-event context loading + per-field evidence bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.action_packs.retrieve import retrieve_clause
from src.evaluation.extract import evidence as ev
from src.evaluation.extract.dtos import EvidenceBundle, FieldExtractRequest
from src.evaluation.extract.temporal import TemporalFor, default_temporal_for
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

NO_EVIDENCE = "(no rules/GLiNER/temporal evidence for this field)"
CLAUSE_PREFIX = "EXCERPT:\n"


@dataclass(frozen=True)
class EventContext:
    """Everything the evidence builders need for one event (immutable by convention)."""

    rep: dict[str, Any] = field(default_factory=dict)
    spans: list[dict[str, Any]] = field(default_factory=list)
    excerpts: str = ""
    passages: dict[str, Any] = field(default_factory=dict)
    doc_text: str = ""
    temporal_cache: dict[str, list[str]] = field(default_factory=dict)
    # Pack hook inputs (PackHooks.extras_from_inventory); {} for packs without that hook
    extras: Mapping[str, str] = field(default_factory=dict)
    event_id: str | None = None
    accession: str = ""


class EvidenceProvider(Protocol):
    def context(self, req: FieldExtractRequest) -> EventContext: ...

    def bundle(
        self, ctx: EventContext, field: str, sources: tuple[str, ...], pack: ActionPack
    ) -> EvidenceBundle: ...

    def rules_direct(self, ctx: EventContext, field: str, pack: ActionPack) -> list[str]: ...

    def n_rules(self, ctx: EventContext, field: str, pack: ActionPack) -> int: ...


# --- evidence assembly over an EventContext --------------------------------------


def _clause_bundle(pack: ActionPack, ctx: EventContext, field: str) -> EvidenceBundle:
    spec = pack.clause_fields.get(field)
    text = ""
    if spec is not None:
        text = retrieve_clause(
            spec,
            passages=ctx.passages,
            excerpts=ctx.excerpts,
            doc_text=ctx.doc_text or ctx.excerpts,
        )
    if not text.strip():
        return EvidenceBundle(text="", source="clause", n_chars=0, empty=True)
    full = CLAUSE_PREFIX + text
    return EvidenceBundle(text=full, source="clause", n_chars=len(full), empty=False)


def _prior_bundle(pack: ActionPack, ctx: EventContext, field: str) -> EvidenceBundle:
    hooks = pack.hooks
    value = None
    if hooks is not None and hooks.direct_prior is not None:
        value = hooks.direct_prior(field, ctx.extras)
    if value is None:
        return EvidenceBundle(text="", source="rules", n_chars=0, empty=True)
    assert hooks is not None
    text = f"RULES:\n- hint={hooks.prior_hint} value={value!r}"
    return EvidenceBundle(text=text, source="rules", n_chars=len(text), empty=False)


def build_bundle(
    pack: ActionPack, ctx: EventContext, field: str, sources: tuple[str, ...]
) -> EvidenceBundle:
    """Assemble the evidence pack for ``sources`` (legacy ``build_evidence`` order)."""
    if "clause" in sources:
        return _clause_bundle(pack, ctx, field)
    if "prior" in sources:
        return _prior_bundle(pack, ctx, field)

    blocks: list[str] = []
    if "rules" in sources:
        rules = ev.rules_prelude_lines(pack, field, ctx.extras) + ev.rules_lines(
            pack, ctx.rep, field, ctx.excerpts
        )
        if rules:
            blocks.append("RULES:\n" + "\n".join(rules))
    if "gliner" in sources:
        gliner = ev.gliner_lines(pack, ctx.spans, field, extras=ctx.extras)
        if gliner:
            blocks.append("GLINER SPANS:\n" + "\n".join(gliner))
        synth = ev.synth_lines(pack, field, gliner, ctx.spans, ctx.extras)
        if synth:
            blocks.append("GLINER SPANS:\n" + "\n".join(synth))
    # Config gate: temporal evidence only for pack.date_fields
    if "temporal" in sources and pack.uses_temporal(field):
        temporal = list(ctx.temporal_cache.get(field) or [])
        if temporal:
            blocks.append("TEMPORAL SPANS:\n" + "\n".join(temporal))

    real = [s for s in sources if s in {"rules", "gliner", "temporal"}]
    source = real[0] if len(real) == 1 else "mixed"
    if not blocks:
        return EvidenceBundle(text=NO_EVIDENCE, source=source, n_chars=len(NO_EVIDENCE), empty=True)
    text = "\n\n".join(blocks)
    return EvidenceBundle(text=text, source=source, n_chars=len(text), empty=False)


def context_rules_direct(pack: ActionPack, ctx: EventContext, field: str) -> list[str]:
    return ev.rules_raw_values(pack, ctx.rep, field, ctx.excerpts)


def context_n_rules(pack: ActionPack, ctx: EventContext, field: str) -> int:
    # Plain rules lines only (no pack prelude), as reported by the legacy harness
    return len(ev.rules_lines(pack, ctx.rep, field, ctx.excerpts))


# --- preprocess artifact helpers -----------------------------------------------


def _load_rep(store: ArtifactStore, eid: str) -> dict[str, Any]:
    p = store.path_root / "events" / eid / "concise" / "event_rep.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_spans(store: ArtifactStore, eid: str) -> list[dict[str, Any]]:
    p = store.path_root / "events" / eid / "spans.json"
    if not p.exists():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("spans") or [])


def _passages_obj(raw: str | None) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _spans_from_passages(passages: dict[str, Any]) -> list[dict[str, Any]]:
    """GT passage quotes -> span-shaped evidence when preprocess spans are missing."""
    spans: list[dict[str, Any]] = []
    for fname, items in passages.items():
        hint = str(fname or "").lower().replace(" ", "_")
        for it in items or []:
            if not isinstance(it, dict):
                continue
            quote = str(it.get("quote") or "").strip()
            if not quote:
                continue
            spans.append(
                {
                    "field_hint": hint,
                    "label": hint,
                    "text": quote[: ev.MAX_RAW],
                    "passage": quote[: ev.MAX_PASSAGE],
                    "score": 1.0,
                }
            )
    return spans


def _excerpts_from_passages(passages: dict[str, Any], *, max_chars: int = 24_000) -> str:
    parts: list[str] = []
    n = 0
    for fname, items in passages.items():
        for it in items or []:
            if not isinstance(it, dict):
                continue
            quote = str(it.get("quote") or "").strip()
            if not quote:
                continue
            block = f"[{fname}]\n{quote}"
            if n + len(block) > max_chars:
                remain = max_chars - n
                if remain < 200:
                    return "\n\n---\n\n".join(parts)
                block = block[:remain]
            parts.append(block)
            n += len(block)
            if n >= max_chars:
                return "\n\n---\n\n".join(parts)
    return "\n\n---\n\n".join(parts)


def _segment_blob(store: ArtifactStore, eid: str, *, max_chars: int = 200_000) -> str:
    """Concatenated segment text for clause regex (not priority-truncated)."""
    path = store.segments_path(eid)
    if not path.exists():
        return ""
    parts: list[str] = []
    n = 0
    for seg in store.read_json(path).get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if n + len(text) > max_chars:
            text = text[: max(0, max_chars - n)]
        parts.append(text)
        n += len(text)
        if n >= max_chars:
            break
    return "\n\n".join(parts)


def _excerpts(store: ArtifactStore, eid: str, *, max_chars: int = 24_000) -> str:
    path = store.segments_path(eid)
    if not path.exists():
        return ""
    segs = list(store.read_json(path).get("segments") or [])
    preferred, fallback = [], []
    for seg in segs:
        kind = (seg.get("kind") or "").lower()
        heading = (seg.get("heading") or "").lower()
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if kind in {"faq", "priority_section"} or seg.get("priority") or "summary term" in heading:
            preferred.append((heading, text))
        elif kind in {"toc_section", "full_doc"}:
            fallback.append((heading, text))
    parts: list[str] = []
    n = 0
    for heading, text in preferred + fallback:
        block = f"[{heading or 'section'}]\n{text}"
        if n + len(block) > max_chars:
            remain = max_chars - n
            if remain < 200:
                break
            block = block[:remain]
        parts.append(block)
        n += len(block)
        if n >= max_chars:
            break
    return "\n\n---\n\n".join(parts)


def _load_inventory(store: ArtifactStore, eid: str | None) -> dict[str, Any]:
    """The event's inventory.json, or {} when missing / unreadable / not an object."""
    if not eid:
        return {}
    inv_path = store.inventory_path(eid)
    if not inv_path.exists():
        return {}
    try:
        inv = store.read_json(inv_path)
    except Exception:  # noqa: BLE001
        return {}
    return inv if isinstance(inv, dict) else {}


def _inventory_extras(pack: ActionPack, store: ArtifactStore, eid: str | None) -> dict[str, str]:
    """``EventContext.extras`` via the pack's ``extras_from_inventory`` hook ({} without one)."""
    hooks = pack.hooks
    if hooks is None or hooks.extras_from_inventory is None:
        return {}
    return dict(hooks.extras_from_inventory(_load_inventory(store, eid)))


class ArtifactProvider:
    """EvidenceProvider over preprocess artifacts (+ GT passages as fallback).

    ``event_id_for`` maps a GT row to its preprocess event id (pack-specific; injected).
    ``temporal_for(event_key, excerpts, date_fields)`` returns per-field temporal lines
    (always asked for every ``pack.date_fields`` entry, never a --fields subset);
    defaults to running ``tagger`` (no disk cache), or {} when ``tagger`` is None.
    Contexts are cached under ``key_for(row)`` (default: the row's accession) and
    looked up by ``FieldExtractRequest.accession``: the request's ``accession`` IS the
    context key, so a custom ``key_for`` must return exactly the string the harness
    puts in ``req.accession``. Pass a per-row ``key_for`` when GT rows that share an
    accession carry different passages (``prepare`` raises otherwise).
    """

    def __init__(
        self,
        pack: ActionPack,
        store: ArtifactStore | None = None,
        tagger: Any = None,
        rows_by_accession: Mapping[str, dict] | None = None,
        *,
        event_id_for: Callable[[dict], str | None],
        temporal_for: TemporalFor | None = None,
        key_for: Callable[[dict], str] | None = None,
    ) -> None:
        self.pack = pack
        self.store = store or ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
        self.tagger = tagger
        self.rows_by_accession = dict(rows_by_accession or {})
        self.event_id_for = event_id_for
        self.temporal_for = temporal_for or default_temporal_for(pack, tagger)
        self.key_for = key_for or (lambda row: (row.get("accession_number") or "").strip())
        self._contexts: dict[str, EventContext] = {}

    def _load(self, row: dict, idx: int, date_fields: tuple[str, ...]) -> EventContext:
        store = self.store
        acc = (row.get("accession_number") or "").strip()
        eid = self.event_id_for(row)
        rep = _load_rep(store, eid) if eid else {}
        spans = _load_spans(store, eid) if eid else []
        excerpts = _excerpts(store, eid) if eid else ""
        passages = _passages_obj(row.get("passages"))
        # GT passages fill gaps when preprocess artifacts are missing
        if passages and (not spans or not excerpts):
            if not spans:
                spans = _spans_from_passages(passages)
            if not excerpts:
                excerpts = _excerpts_from_passages(passages)
        doc_text = _segment_blob(store, eid) if eid and self.pack.clause_fields else ""
        extras = _inventory_extras(self.pack, store, eid)
        temporal_cache: dict[str, list[str]] = {}
        if date_fields:
            key = eid or acc or f"row{idx}"
            temporal_cache = dict(self.temporal_for(key, excerpts, date_fields) or {})
        return EventContext(
            rep=rep,
            spans=spans,
            excerpts=excerpts,
            passages=passages,
            doc_text=doc_text,
            temporal_cache=temporal_cache,
            extras=extras,
            event_id=eid,
            accession=acc,
        )

    def prepare(
        self, rows: Iterable[dict] | None = None, fields: tuple[str, ...] | None = None
    ) -> list[str]:
        """Load every row's event once (+ temporal lines); returns the context keys.

        Not thread-safe; call before concurrent runs. A later row with the same key
        replaces an earlier one only if its passages are identical; otherwise raises
        ``ValueError`` (pass ``key_for`` for per-row contexts).
        """
        rows = list(self.rows_by_accession.values() if rows is None else rows)
        fields = tuple(self.pack.fields if fields is None else fields)
        # Temporal lines are computed for ALL pack date fields whenever any requested field
        # needs them, so a cached result from a --fields subset still serves a full run.
        date_fields: tuple[str, ...] = ()
        if any(self.pack.uses_temporal(f) for f in fields):
            date_fields = tuple(f for f in self.pack.fields if self.pack.uses_temporal(f))
        keys: list[str] = []
        for idx, row in enumerate(rows):
            key = self.key_for(row)
            prev = self._contexts.get(key)
            if prev is not None and prev.passages != _passages_obj(row.get("passages")):
                raise ValueError(
                    f"rows share context key {key!r} but carry different passages; "
                    "pass key_for for per-row contexts (and use that key as req.accession)"
                )
            self._contexts[key] = self._load(row, idx, date_fields)
            keys.append(key)
        return keys

    def context(self, req: FieldExtractRequest) -> EventContext:
        try:
            return self._contexts[req.accession]
        except KeyError:
            raise KeyError(f"event not prepared: accession {req.accession!r}") from None

    def bundle(
        self, ctx: EventContext, field: str, sources: tuple[str, ...], pack: ActionPack
    ) -> EvidenceBundle:
        return build_bundle(pack, ctx, field, sources)

    def rules_direct(self, ctx: EventContext, field: str, pack: ActionPack) -> list[str]:
        return context_rules_direct(pack, ctx, field)

    def n_rules(self, ctx: EventContext, field: str, pack: ActionPack) -> int:
        return context_n_rules(pack, ctx, field)


__all__ = [
    "ArtifactProvider",
    "EventContext",
    "EvidenceProvider",
    "build_bundle",
    "context_n_rules",
    "context_rules_direct",
]
