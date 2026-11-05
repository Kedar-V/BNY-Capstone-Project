"""Assemble Concise Rep from inventory + segments + spans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.preprocess.contracts import LABEL_TO_FIELD_HINT, StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
from src.preprocess.rules_ids import RULE_FIELD_HINTS, extract_id_currency_facts, load_sec_tickers
from src.preprocess.stages.cleanup import _event_ids
from src.preprocess.store import SCHEMA_VERSION, ArtifactStore, utc_now_iso


class AssembleStage:
    name = "assemble"

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        event_ids = _event_ids(store, ctx, stage=self.name)
        n_ok = n_fail = 0
        n_facts = n_entities = 0
        errors: list[str] = []

        pbar = stage_progress(
            event_ids, desc="assemble", total=len(event_ids), unit="event", show=ctx.show_progress
        )
        for eid in pbar:
            try:
                inv = store.read_json(store.inventory_path(eid))
                spans_path = store.spans_path(eid)
                if not spans_path.exists():
                    raise FileNotFoundError("missing spans.json")
                spans_payload = store.read_json(spans_path)
                if spans_payload.get("status") == "gliner_unavailable":
                    raise RuntimeError("gliner_unavailable")

                # doc inventory statuses from download manifest if present
                doc_inventory = []
                dl_path = store.download_manifest_path(eid)
                dl_docs = {}
                if dl_path.exists():
                    for d in store.read_json(dl_path).get("docs") or []:
                        dl_docs[(d.get("accession"), d.get("filename"))] = d
                for doc in inv.get("docs") or []:
                    key = (doc.get("accession"), doc.get("filename"))
                    dl = dl_docs.get(key, {})
                    doc_inventory.append(
                        {
                            "role": doc.get("role"),
                            "status": dl.get("status", "unknown"),
                            "sha1": dl.get("sha1"),
                            "hit_id": doc.get("hit_id"),
                            "accession": doc.get("accession"),
                            "filename": doc.get("filename"),
                        }
                    )

                entities: list[dict[str, Any]] = []
                facts: list[dict[str, Any]] = []
                for sp in spans_payload.get("spans") or []:
                    label = sp.get("label")
                    field_hint = sp.get("field_hint") or LABEL_TO_FIELD_HINT.get(label, label)
                    # IDs / currency come from rules, not GLiNER
                    if field_hint in RULE_FIELD_HINTS:
                        continue
                    ent = {
                        "label": label,
                        "text": sp.get("text"),
                        "score": sp.get("score"),
                        "rank_score": sp.get("rank_score"),
                        "doc_role": sp.get("doc_role"),
                        "segment_id": sp.get("segment_id"),
                        "faq_question": sp.get("question"),
                        "section": sp.get("heading") if not sp.get("question") else None,
                        "chunk_id": sp.get("chunk_id"),
                    }
                    entities.append(ent)
                    facts.append(
                        {
                            "field_hint": field_hint,
                            "raw": sp.get("text"),
                            "passage": sp.get("passage"),
                            "method": "gliner",
                            "confidence": sp.get("score"),
                            "rank_score": sp.get("rank_score"),
                            "doc_role": sp.get("doc_role"),
                            "section": sp.get("heading"),
                            "faq_question": sp.get("question"),
                            "char_span": [sp.get("start"), sp.get("end")],
                            "source_hit_id": sp.get("hit_id"),
                            "source_accession": sp.get("accession"),
                            "label": label,
                            "chunk_id": sp.get("chunk_id"),
                        }
                    )

                # Offer price (GLiNER) feeds currency rule
                offer_by_acc: dict[str, str] = {}
                offer_rank: dict[str, float] = {}
                for f in facts:
                    if f.get("field_hint") != "offer_price":
                        continue
                    raw = str(f.get("raw") or "")
                    if not raw:
                        continue
                    rank = float(f.get("rank_score") or f.get("confidence") or 0)
                    acc = str(f.get("source_accession") or "").strip()
                    for key in ({acc} if acc else set()) | {""}:
                        if rank >= offer_rank.get(key, -1.0):
                            offer_rank[key] = rank
                            offer_by_acc[key] = raw

                segments: list[dict[str, Any]] = []
                seg_path = store.segments_path(eid)
                if seg_path.exists():
                    segments = list(store.read_json(seg_path).get("segments") or [])

                sec_tickers = {}
                sec_path = ctx.extra.get("sec_tickers_csv") if isinstance(ctx.extra, dict) else None
                if sec_path:
                    sec_tickers = load_sec_tickers(Path(sec_path))

                rule_facts = extract_id_currency_facts(
                    segments,
                    offer_price_by_accession=offer_by_acc,
                    sec_tickers=sec_tickers,
                )
                facts.extend(rule_facts)
                for rf in rule_facts:
                    entities.append(
                        {
                            "label": rf.get("label"),
                            "text": rf.get("raw"),
                            "score": 1.0,
                            "rank_score": 1.0,
                            "doc_role": rf.get("doc_role"),
                            "method": "rules",
                        }
                    )

                # Prefer rank_score ordering in Concise Rep
                facts.sort(key=lambda f: float(f.get("rank_score") or f.get("confidence") or 0), reverse=True)
                entities.sort(key=lambda e: float(e.get("rank_score") or e.get("score") or 0), reverse=True)

                allowed = {"gliner", "rules"}
                if any(f.get("method") not in allowed for f in facts):
                    raise ValueError("unexpected fact method in facts")

                exception_flags = []
                if not any(d.get("role") == "sc_14d9" and d.get("status") == "ok" for d in doc_inventory):
                    if inv.get("has_14d9"):
                        exception_flags.append("14d9_download_missing_or_failed")

                n_rules = sum(1 for f in facts if f.get("method") == "rules")
                n_gliner = sum(1 for f in facts if f.get("method") == "gliner")
                rep = {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": eid,
                    "mvp_event_type": inv.get("mvp_event_type") or cfg.mvp_event_type,
                    "cohort": inv.get("cohort"),
                    "preprocess_status": "ok",
                    "nlp_versions": {
                        "pipeline": "to_preprocess_gliner_rules",
                        "gliner_model": spans_payload.get("gliner_model"),
                        "id_currency": "rules_ids",
                    },
                    "doc_inventory": doc_inventory,
                    "entities": entities,
                    "candidate_facts": facts,
                    "exception_flags": exception_flags,
                    "written_at": utc_now_iso(),
                    "n_facts_gliner": n_gliner,
                    "n_facts_rules": n_rules,
                }
                store.write_json(store.event_rep_path(eid), rep)
                n_ok += 1
                n_facts += len(facts)
                n_entities += len(entities)
            except Exception as exc:  # noqa: BLE001
                n_fail += 1
                errors.append(f"{eid}: {exc}")
                # write failed stub rep when possible
                try:
                    store.write_json(
                        store.event_rep_path(eid),
                        {
                            "schema_version": SCHEMA_VERSION,
                            "event_id": eid,
                            "preprocess_status": "failed",
                            "exception_flags": [str(exc)],
                            "candidate_facts": [],
                            "entities": [],
                            "written_at": utc_now_iso(),
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_ok, fail=n_fail, refresh=False)

        metrics = {
            "n_reps_ok": n_ok,
            "n_reps_failed": n_fail,
            "n_candidate_facts": n_facts,
            "n_entities": n_entities,
            "id_currency": "rules",
            "n_events_pending": len(event_ids),
        }
        man = store.write_stage_manifest(self.name, {"status": "ok", "metrics": metrics, "errors": errors[:30]})
        return StageResult(
            stage=self.name,
            status="ok",
            n_success=n_ok,
            n_failed=n_fail,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(man)],
        )
