"""Load Concise Rep JSON into path-specific Postgres tables."""

from __future__ import annotations

import json
from typing import Any

from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
from src.preprocess.stages.cleanup import _event_ids
from src.preprocess.store import ArtifactStore


_TABLE_PREFIX = {
    "tender": "tender",
    "exchange": "exchange",
    "rights": "rights",
    "merger": "merger",
    "conversion": "conversion",
}


class LoadDbStage:
    name = "load_db"

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        prefix = _TABLE_PREFIX[ctx.path_name]

        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            # Optionally insert stub header if DB available
            try:
                self._insert_stub_headers(prefix, ctx)
            except Exception:  # noqa: BLE001
                pass
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        if ctx.dry_run or ctx.extra.get("skip_db"):
            metrics = {"skipped": True, "reason": "dry_run_or_skip_db"}
            man = store.write_stage_manifest(self.name, {"status": "skipped", "metrics": metrics})
            return StageResult(stage=self.name, status="skipped", n_skipped=1, metrics=metrics, artifact_paths=[str(man)])

        event_ids = _event_ids(store, ctx)
        n_ok = n_fail = 0
        n_facts = n_entities = 0
        errors: list[str] = []

        try:
            # Import connection module directly to avoid package __init__ pulling load.py
            import importlib
            conn_mod = importlib.import_module("src.db.connection")
            connect = conn_mod.connect
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                stage=self.name,
                status="failed",
                n_failed=1,
                errors=[f"db connection import failed: {exc}"],
                metrics={"db_unavailable": True},
            )

        with connect() as conn:
            for eid in stage_progress(
                event_ids, desc="load_db", total=len(event_ids), unit="event", show=ctx.show_progress
            ):
                try:
                    rep_path = store.event_rep_path(eid)
                    if not rep_path.exists():
                        raise FileNotFoundError("missing event_rep.json")
                    rep = store.read_json(rep_path)
                    counts = self._upsert_rep(conn, prefix, rep, str(rep_path))
                    conn.commit()
                    n_ok += 1
                    n_facts += counts["facts"]
                    n_entities += counts["entities"]
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    n_fail += 1
                    errors.append(f"{eid}: {exc}")

        metrics = {
            "n_reps_upserted": n_ok,
            "n_facts_inserted": n_facts,
            "n_entities_inserted": n_entities,
            "n_failed": n_fail,
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

    def _insert_stub_headers(self, prefix: str, ctx: StageContext) -> None:
        import importlib

        connect = importlib.import_module("src.db.connection").connect

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {prefix}_concise_reps (
                        event_id, schema_version, pipeline, preprocess_status, exception_flags, nlp_versions
                    ) VALUES (
                        %s, '1', %s, 'stub_not_implemented', ARRAY[]::text[], '{{}}'::jsonb
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (f"stub-{ctx.path_name}", f"{ctx.path_name}_preprocess_stub"),
                )
            conn.commit()

    def _upsert_rep(self, conn, prefix: str, rep: dict[str, Any], artifact_path: str) -> dict[str, int]:
        event_id = rep["event_id"]
        with conn.cursor() as cur:
            # Ensure event exists (FK) — skip if missing to avoid partial load failure noise
            cur.execute("SELECT 1 FROM events WHERE event_id = %s", (event_id,))
            if cur.fetchone() is None:
                raise RuntimeError(f"event_id {event_id} not in events table — run init_db/load first")

            cur.execute(
                f"DELETE FROM {prefix}_concise_reps WHERE event_id = %s AND version_id IS NULL",
                (event_id,),
            )
            cur.execute(
                f"""
                INSERT INTO {prefix}_concise_reps (
                    event_id, version_id, schema_version, pipeline, gliner_model,
                    preprocess_status, exception_flags, cohort, artifact_path, nlp_versions, payload_json
                ) VALUES (
                    %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                )
                RETURNING concise_rep_id
                """,
                (
                    event_id,
                    rep.get("schema_version") or "1",
                    (rep.get("nlp_versions") or {}).get("pipeline") or "to_preprocess_gliner",
                    (rep.get("nlp_versions") or {}).get("gliner_model"),
                    rep.get("preprocess_status") or "ok",
                    rep.get("exception_flags") or [],
                    rep.get("cohort"),
                    artifact_path,
                    json.dumps(rep.get("nlp_versions") or {}),
                    json.dumps(rep),
                ),
            )
            rep_row = cur.fetchone()
            rep_id = rep_row["concise_rep_id"] if isinstance(rep_row, dict) else rep_row[0]

            for doc in rep.get("doc_inventory") or []:
                cur.execute(
                    f"""
                    INSERT INTO {prefix}_concise_docs (
                        concise_rep_id, doc_role, source_hit_id, source_accession, filename, download_status, content_sha1
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        rep_id,
                        doc.get("role"),
                        doc.get("hit_id"),
                        doc.get("accession"),
                        doc.get("filename"),
                        doc.get("status"),
                        doc.get("sha1"),
                    ),
                )

            n_ent = 0
            for ent in rep.get("entities") or []:
                cur.execute(
                    f"""
                    INSERT INTO {prefix}_concise_entities (
                        concise_rep_id, label, text, confidence, doc_role, segment_id, faq_question, section
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        rep_id,
                        ent.get("label"),
                        ent.get("text"),
                        ent.get("score"),
                        ent.get("doc_role"),
                        ent.get("segment_id"),
                        ent.get("faq_question"),
                        ent.get("section"),
                    ),
                )
                n_ent += 1

            n_facts = 0
            for fact in rep.get("candidate_facts") or []:
                method = fact.get("method") or "gliner"
                if method != "gliner":
                    raise ValueError(f"refusing non-gliner fact method={method}")
                span = fact.get("char_span") or [None, None]
                cur.execute(
                    f"""
                    INSERT INTO {prefix}_concise_facts (
                        concise_rep_id, field_hint, raw_text, passage, method, confidence,
                        doc_role, source_hit_id, source_accession, section, faq_question,
                        char_start, char_end, label
                    ) VALUES (%s, %s, %s, %s, 'gliner', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        rep_id,
                        fact.get("field_hint"),
                        fact.get("raw"),
                        fact.get("passage"),
                        fact.get("confidence"),
                        fact.get("doc_role"),
                        fact.get("source_hit_id"),
                        fact.get("source_accession"),
                        fact.get("section"),
                        fact.get("faq_question"),
                        span[0],
                        span[1],
                        fact.get("label"),
                    ),
                )
                n_facts += 1

        return {"facts": n_facts, "entities": n_ent}
