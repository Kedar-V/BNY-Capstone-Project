"""GLiNER IE stage: windowed prediction, two-pass, value-aware rank."""

from __future__ import annotations

from typing import Any

from src.preprocess.backends import FakeSpanBackend, GlinerBackend
from src.preprocess.contracts import (
    GLINER_LABELS_TO,
    GLINER_PASS2_LABELS,
    LABELS_COVER,
    LABELS_SUMMARY_FAQ,
    StageContext,
    StageResult,
)
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
from src.preprocess.span_rank import (
    dedupe_nms,
    enrich_spans_with_passages,
    only_label_like_for_family,
)
from src.preprocess.stages.cleanup import _event_ids
from src.preprocess.store import ArtifactStore, utc_now_iso


def _labels_for_segment(seg: dict[str, Any], default: list[str]) -> list[str]:
    kind = (seg.get("kind") or "").lower()
    role = (seg.get("doc_role") or "").lower()
    heading = (seg.get("heading") or "").lower()
    if kind in {"faq", "priority_section"} or "summary term" in heading or seg.get("priority"):
        return list(LABELS_SUMMARY_FAQ)
    if role == "cover" or kind == "full_doc" and role != "otp":
        return list(LABELS_COVER)
    return list(default)


class GlinerStage:
    name = "gliner"

    def __init__(self, backend=None) -> None:
        self.backend = backend

    def _backend(self, ctx: StageContext):
        if self.backend is not None:
            return self.backend
        if ctx.extra.get("span_backend") == "fake":
            return FakeSpanBackend(
                {
                    "$18.75": [
                        {"label": "offer_price_amount", "text": "$18.75", "score": 0.91},
                        {"label": "offer_price", "text": "Offer Price", "score": 0.95},
                    ],
                    "February 19, 2020": [
                        {"label": "expiration_datetime", "text": "February 19, 2020", "score": 0.88},
                        {"label": "expiration_date", "text": "Offer Expiration Time", "score": 0.93},
                    ],
                    "Dermira, Inc.": [
                        {"label": "target_organization", "text": "Dermira, Inc.", "score": 0.84},
                    ],
                    "Eli Lilly": [
                        {"label": "offeror_organization", "text": "Eli Lilly and Company", "score": 0.86},
                    ],
                }
            )
        model_id = ctx.extra.get("gliner_model") or "urchade/gliner_medium-v2.1"
        return GlinerBackend(model_id=model_id)

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        backend = self._backend(ctx)
        default_labels = cfg.gliner_labels or list(GLINER_LABELS_TO)
        event_ids = _event_ids(store, ctx, stage=self.name)

        unavailable = False
        unavailable_reason = None
        if isinstance(backend, GlinerBackend) and not backend.available:
            unavailable = True
            unavailable_reason = backend._load_error

        n_ok = n_fail = 0
        n_spans = 0
        n_segments = 0
        n_pass2 = 0
        errors: list[str] = []

        pbar = stage_progress(
            event_ids, desc="gliner", total=len(event_ids), unit="event", show=ctx.show_progress
        )
        for eid in pbar:
            try:
                seg_path = store.segments_path(eid)
                if not seg_path.exists():
                    raise FileNotFoundError("missing segments.json")
                seg_payload = store.read_json(seg_path)
                if unavailable:
                    store.write_json(
                        store.spans_path(eid),
                        {
                            "event_id": eid,
                            "gliner_model": getattr(backend, "model_id", None),
                            "status": "gliner_unavailable",
                            "error": unavailable_reason,
                            "spans": [],
                            "written_at": utc_now_iso(),
                        },
                    )
                    n_fail += 1
                    errors.append(f"{eid}: gliner_unavailable")
                    continue

                segment_texts: dict[str, str] = {}
                spans_raw: list[dict[str, Any]] = []

                for seg in seg_payload.get("segments") or []:
                    n_segments += 1
                    text = seg.get("text") or ""
                    seg_id = seg.get("segment_id") or ""
                    segment_texts[seg_id] = text
                    labels = _labels_for_segment(seg, default_labels)
                    preds = backend.predict(text, labels)
                    for sp in preds:
                        spans_raw.append(
                            {
                                "segment_id": seg_id,
                                "segment_kind": seg.get("kind"),
                                "priority": bool(seg.get("priority")),
                                "doc_role": seg.get("doc_role"),
                                "heading": seg.get("heading"),
                                "question": seg.get("question"),
                                "accession": seg.get("accession"),
                                "filename": seg.get("filename"),
                                "hit_id": seg.get("hit_id"),
                                "label": sp.get("label"),
                                "text": sp.get("text"),
                                "score": sp.get("score"),
                                "start": sp.get("start"),
                                "end": sp.get("end"),
                                "chunk_id": sp.get("chunk_id"),
                            }
                        )

                # Pass-2: always on priority/FAQ; also when families are label-only.
                weak_families = (
                    only_label_like_for_family(spans_raw, "price")
                    or only_label_like_for_family(spans_raw, "date")
                    or only_label_like_for_family(spans_raw, "org")
                )
                pass2_segs = []
                for seg in seg_payload.get("segments") or []:
                    text = seg.get("text") or ""
                    if len(text) < 40:
                        continue
                    kind = (seg.get("kind") or "").lower()
                    priority = bool(seg.get("priority")) or kind in {"faq", "priority_section"}
                    if priority:
                        pass2_segs.append(seg)
                    elif weak_families and (
                        kind in {"toc_section"} or (seg.get("doc_role") or "") == "otp"
                    ):
                        pass2_segs.append(seg)

                need_pass2 = bool(pass2_segs)
                if need_pass2:
                    n_pass2 += 1
                    seen_seg: set[str] = set()
                    for seg in pass2_segs:
                        sid = seg.get("segment_id") or ""
                        if sid in seen_seg:
                            continue
                        seen_seg.add(sid)
                        preds2 = backend.predict(seg.get("text") or "", list(GLINER_PASS2_LABELS))
                        for sp in preds2:
                            spans_raw.append(
                                {
                                    "segment_id": sid,
                                    "segment_kind": seg.get("kind"),
                                    "priority": bool(seg.get("priority")),
                                    "doc_role": seg.get("doc_role"),
                                    "heading": seg.get("heading"),
                                    "question": seg.get("question"),
                                    "accession": seg.get("accession"),
                                    "filename": seg.get("filename"),
                                    "hit_id": seg.get("hit_id"),
                                    "label": sp.get("label"),
                                    "text": sp.get("text"),
                                    "score": sp.get("score"),
                                    "start": sp.get("start"),
                                    "end": sp.get("end"),
                                    "chunk_id": sp.get("chunk_id"),
                                    "pass": 2,
                                }
                            )

                ranked = dedupe_nms(spans_raw)
                ranked = enrich_spans_with_passages(ranked, segment_texts)
                n_spans += len(ranked)

                store.write_json(
                    store.spans_path(eid),
                    {
                        "event_id": eid,
                        "gliner_model": getattr(backend, "model_id", None),
                        "status": "ok",
                        "n_spans": len(ranked),
                        "n_spans_raw": len(spans_raw),
                        "pass2": need_pass2,
                        "spans": ranked,
                        "written_at": utc_now_iso(),
                    },
                )
                n_ok += 1
            except Exception as exc:  # noqa: BLE001
                n_fail += 1
                errors.append(f"{eid}: {exc}")
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_ok, fail=n_fail, pass2=n_pass2, refresh=False)

        metrics = {
            "n_events_ok": n_ok,
            "n_failed": n_fail,
            "n_segments_scored": n_segments,
            "n_spans": n_spans,
            "n_pass2_events": n_pass2,
            "gliner_unavailable": unavailable,
            "gliner_model": getattr(backend, "model_id", None),
            "n_events_pending": len(event_ids),
        }
        status = "failed" if unavailable and n_ok == 0 else "ok"
        man = store.write_stage_manifest(self.name, {"status": status, "metrics": metrics, "errors": errors[:30]})
        return StageResult(
            stage=self.name,
            status=status,
            n_success=n_ok,
            n_failed=n_fail,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(man)],
        )
