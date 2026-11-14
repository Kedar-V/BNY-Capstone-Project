"""Download stage: fetch priority HTML into raw/ (threaded)."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from src.eda.sec_client import SecClient
from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.parallel import default_workers, map_parallel
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.resume import resolve_event_ids
from src.preprocess.store import ArtifactStore, sha1_bytes, utc_now_iso


class DownloadStage:
    name = "download"

    def __init__(self, client: SecClient | None = None) -> None:
        self.client = client or SecClient()

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        event_ids = resolve_event_ids(store, ctx, stage=self.name)
        errors: list[str] = []
        doc_jobs: list[tuple[str, dict[str, Any]]] = []

        for eid in event_ids:
            inv_path = store.inventory_path(eid)
            if not inv_path.exists():
                errors.append(f"{eid}: missing inventory")
                continue
            inv = store.read_json(inv_path)
            if ctx.cohort and inv.get("cohort") != ctx.cohort:
                continue
            for doc in inv.get("docs") or []:
                doc_jobs.append((eid, doc))

        workers = default_workers(ctx.extra.get("workers"))
        # thread-local SEC clients so throttle state isn't shared
        local = threading.local()

        def _client() -> SecClient:
            c = getattr(local, "client", None)
            if c is None:
                c = SecClient()
                local.client = c
            return c

        def _one(job: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
            eid, doc = job
            accession = doc.get("accession") or ""
            filename = doc.get("filename") or ""
            cik = str(doc.get("primary_cik") or "")
            role = doc.get("role")
            out = store.raw_path(eid, accession, filename)
            record: dict[str, Any] = {
                "role": role,
                "accession": accession,
                "filename": filename,
                "hit_id": doc.get("hit_id"),
                "local_path": str(out),
            }
            try:
                if out.exists() and out.stat().st_size > 0 and not ctx.force:
                    data = out.read_bytes()
                    record.update(
                        {
                            "status": "skipped",
                            "bytes": len(data),
                            "sha1": sha1_bytes(data),
                        }
                    )
                else:
                    if not cik or not accession or not filename:
                        raise ValueError("missing cik/accession/filename")
                    url = _client().document_url(cik, accession, filename)
                    record["url"] = url
                    if ctx.dry_run:
                        record["status"] = "dry_run"
                    else:
                        data = _client().get_bytes(url)
                        if not data:
                            record.update({"status": "empty", "bytes": 0, "sha1": None})
                        else:
                            out.write_bytes(data)
                            record.update(
                                {
                                    "status": "ok",
                                    "bytes": len(data),
                                    "sha1": sha1_bytes(data),
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                record["status"] = "http_error"
                record["error"] = str(exc)
            return eid, record

        n_ok = n_skip = n_err = n_empty = 0
        by_eid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        counts = {"ok": 0, "skip": 0, "err": 0}

        def _on_result(item: tuple[str, dict[str, Any]]) -> None:
            eid, record = item
            by_eid[eid].append(record)
            st = record.get("status")
            if st == "ok":
                counts["ok"] += 1
            elif st in {"skipped", "dry_run"}:
                counts["skip"] += 1
            elif st == "http_error":
                counts["err"] += 1
                errors.append(f"{eid}/{record.get('filename')}: {record.get('error')}")
            elif st == "empty":
                n_empty_box[0] += 1

        n_empty_box = [0]
        map_parallel(
            doc_jobs,
            _one,
            workers=workers,
            desc="download",
            show_progress=ctx.show_progress,
            on_result=_on_result,
            postfix=lambda: {"ok": counts["ok"], "skip": counts["skip"], "err": counts["err"]},
        )
        n_ok, n_skip, n_err, n_empty = counts["ok"], counts["skip"], counts["err"], n_empty_box[0]

        for eid, records in by_eid.items():
            man_path = store.download_manifest_path(eid)
            existing = {"event_id": eid, "docs": [], "updated_at": utc_now_iso()}
            if man_path.exists():
                existing = store.read_json(man_path)
            docs_list = list(existing.get("docs") or [])
            for record in records:
                docs_list = [
                    d
                    for d in docs_list
                    if not (
                        d.get("filename") == record.get("filename")
                        and d.get("accession") == record.get("accession")
                    )
                ]
                docs_list.append(record)
            existing["docs"] = docs_list
            existing["updated_at"] = utc_now_iso()
            store.write_json(man_path, existing)

        metrics = {
            "n_docs_attempted": len(doc_jobs),
            "n_ok": n_ok,
            "n_skipped_cached": n_skip,
            "n_http_error": n_err,
            "n_empty": n_empty,
            "n_events_pending": len(event_ids),
            "workers": workers,
        }
        man = store.write_stage_manifest(self.name, {"status": "ok", "metrics": metrics, "errors": errors[:30]})
        return StageResult(
            stage=self.name,
            status="ok",
            n_success=n_ok,
            n_failed=n_err,
            n_skipped=n_skip,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(man)],
        )
