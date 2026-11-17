"""Frozen evidence packs: snapshot retrieval once, replay any SLM against it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.evaluation.action_packs.base import ActionPack, HybridSpec
from src.evaluation.extract.dtos import EvidenceBundle, FieldExtractRequest
from src.evaluation.extract.providers import EventContext

EVIDENCE_FILENAME = "evidence.jsonl"
MANIFEST_FILENAME = "manifest.json"
_BUNDLE_SOURCES = frozenset({"clause", "rules", "gliner", "temporal", "hybrid", "mixed"})


@dataclass(frozen=True)
class FrozenStage:
    name: str
    sources: tuple[str, ...]
    prompt_mode: str
    on_empty: str
    direct_from_rules: bool
    empty: bool
    text: str
    source: str
    n_chars: int
    validate: bool = False
    pass_label: str = ""
    null_label: str | None = None
    empty_label: str = "empty"
    direct_label: str = "A_rules"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sources": list(self.sources),
            "prompt_mode": self.prompt_mode,
            "on_empty": self.on_empty,
            "direct_from_rules": self.direct_from_rules,
            "empty": self.empty,
            "text": self.text,
            "source": self.source,
            "n_chars": self.n_chars,
            "validate": self.validate,
            "pass_label": self.pass_label,
            "null_label": self.null_label,
            "empty_label": self.empty_label,
            "direct_label": self.direct_label,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FrozenStage:
        return cls(
            name=str(d["name"]),
            sources=tuple(d.get("sources") or ()),
            prompt_mode=str(d.get("prompt_mode") or "pick"),
            on_empty=str(d.get("on_empty") or "ask"),
            direct_from_rules=bool(d.get("direct_from_rules")),
            empty=bool(d.get("empty")),
            text=str(d.get("text") or ""),
            source=str(d.get("source") or "mixed"),
            n_chars=int(d.get("n_chars") or 0),
            validate=bool(d.get("validate")),
            pass_label=str(d.get("pass_label") or ""),
            null_label=d.get("null_label"),
            empty_label=str(d.get("empty_label") or "empty"),
            direct_label=str(d.get("direct_label") or "A_rules"),
        )


@dataclass(frozen=True)
class FrozenFieldRecord:
    ei: int
    accession: str
    key: str
    event_id: str | None
    field: str
    gold: str
    stages: tuple[FrozenStage, ...]
    rules_direct: tuple[str, ...] = ()
    extras: Mapping[str, str] = field(default_factory=dict)
    n_rules: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ei": self.ei,
            "accession": self.accession,
            "key": self.key,
            "event_id": self.event_id,
            "field": self.field,
            "gold": self.gold,
            "stages": [s.to_dict() for s in self.stages],
            "rules_direct": list(self.rules_direct),
            "extras": dict(self.extras),
            "n_rules": self.n_rules,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FrozenFieldRecord:
        return cls(
            ei=int(d["ei"]),
            accession=str(d.get("accession") or ""),
            key=str(d["key"]),
            event_id=(str(d["event_id"]) if d.get("event_id") else None),
            field=str(d["field"]),
            gold=str(d.get("gold") or ""),
            stages=tuple(FrozenStage.from_dict(s) for s in (d.get("stages") or [])),
            rules_direct=tuple(str(x) for x in (d.get("rules_direct") or [])),
            extras=dict(d.get("extras") or {}),
            n_rules=int(d.get("n_rules") or 0),
        )


def _hybrid_manifest(spec: HybridSpec | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    return {
        "top_k": spec.top_k,
        "max_chars": spec.max_chars,
        "chunk_chars": spec.chunk_chars,
        "overlap": spec.overlap,
        "use_dense": spec.use_dense,
        "query_extra": dict(spec.query_extra),
    }


def build_manifest(
    *,
    pack_id: str,
    pack: ActionPack,
    fields: Sequence[str],
    cascade: bool,
    validate: bool,
    split: str,
    n_rows: int,
    accessions: Sequence[str],
    accession_hash: str,
    limit: int | None = None,
    router: str | None = None,
    routing_hash: str | None = None,
) -> dict[str, Any]:
    man: dict[str, Any] = {
        "pack_id": pack_id,
        "pack": pack.name,
        "fields": list(fields),
        "cascade": cascade,
        "validate": validate,
        "split": split,
        "limit": limit,
        "n_rows": n_rows,
        "n_records": n_rows * len(fields),
        "hybrid": _hybrid_manifest(pack.hybrid),
        "accessions": list(accessions),
        "accession_hash": accession_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if router is not None:
        man["router"] = router
    if routing_hash is not None:
        man["routing_hash"] = routing_hash
    return man


def write_evidence_pack(
    out_dir: Path,
    *,
    manifest: Mapping[str, Any],
    records: Iterable[FrozenFieldRecord],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ev_path = out_dir / EVIDENCE_FILENAME
    with ev_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(dict(manifest), indent=2), encoding="utf-8"
    )
    return out_dir


def load_evidence_pack(
    pack_dir: Path,
) -> tuple[dict[str, Any], list[FrozenFieldRecord], dict[tuple[str, str], FrozenFieldRecord]]:
    """Return (manifest, ordered records, lookup by (key, field))."""
    pack_dir = Path(pack_dir)
    man_path = pack_dir / MANIFEST_FILENAME
    ev_path = pack_dir / EVIDENCE_FILENAME
    if not man_path.exists() or not ev_path.exists():
        raise FileNotFoundError(f"evidence pack incomplete under {pack_dir}")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    records: list[FrozenFieldRecord] = []
    by_key: dict[tuple[str, str], FrozenFieldRecord] = {}
    with ev_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = FrozenFieldRecord.from_dict(json.loads(line))
            records.append(rec)
            by_key[(rec.key, rec.field)] = rec
    return manifest, records, by_key


class FrozenEvidenceProvider:
    """EvidenceProvider that serves precomputed stage bundles (no artifact I/O).

    ``FieldExtractRequest.accession`` must be the frozen record ``key`` (same as the
    live graph harness: ``<accession>#<row>``).
    """

    def __init__(self, records_by_key: Mapping[tuple[str, str], FrozenFieldRecord]) -> None:
        self._recs = dict(records_by_key)
        self._ctx_by_key: dict[str, EventContext] = {}
        self._key_by_ctx_id: dict[int, str] = {}
        for (key, _field), rec in self._recs.items():
            if key in self._ctx_by_key:
                continue
            ctx = EventContext(
                extras=dict(rec.extras),
                event_id=rec.event_id,
                accession=rec.accession,
            )
            self._ctx_by_key[key] = ctx
            self._key_by_ctx_id[id(ctx)] = key

    def context(self, req: FieldExtractRequest) -> EventContext:
        ctx = self._ctx_by_key.get(req.accession)
        if ctx is None:
            raise KeyError(f"no frozen context for key={req.accession!r}")
        return ctx

    def _rec(self, ctx: EventContext, field: str) -> FrozenFieldRecord:
        key = self._key_by_ctx_id.get(id(ctx))
        if key is None:
            raise KeyError(f"unknown frozen context accession={ctx.accession!r}")
        rec = self._recs.get((key, field))
        if rec is None:
            raise KeyError(f"no frozen record for key={key!r} field={field!r}")
        return rec

    def bundle(
        self, ctx: EventContext, field: str, sources: tuple[str, ...], pack: ActionPack
    ) -> EvidenceBundle:
        rec = self._rec(ctx, field)
        for stage in rec.stages:
            if stage.sources == sources:
                src = stage.source if stage.source in _BUNDLE_SOURCES else "mixed"
                return EvidenceBundle(
                    text=stage.text,
                    source=src,  # type: ignore[arg-type]
                    n_chars=stage.n_chars,
                    empty=stage.empty,
                )
        return EvidenceBundle(text="", source="mixed", n_chars=0, empty=True)

    def rules_direct(self, ctx: EventContext, field: str, pack: ActionPack) -> list[str]:
        vals = list(self._rec(ctx, field).rules_direct)
        if field != "settlement_date":
            return vals
        # Mirror oracle Settlement template on frozen packs: rescan stage text and
        # prefer Payment: promptly over nearby calendar dates.
        from src.preprocess.rules_ids import prefer_settlement_rules_values

        texts = "\n".join(s.text for s in self._rec(ctx, field).stages)
        return prefer_settlement_rules_values(vals, texts)

    def n_rules(self, ctx: EventContext, field: str, pack: ActionPack) -> int:
        return self._rec(ctx, field).n_rules


__all__ = [
    "EVIDENCE_FILENAME",
    "MANIFEST_FILENAME",
    "FrozenEvidenceProvider",
    "FrozenFieldRecord",
    "FrozenStage",
    "build_manifest",
    "load_evidence_pack",
    "write_evidence_pack",
]
