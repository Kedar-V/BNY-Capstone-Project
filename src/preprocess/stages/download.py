"""Download stage: fetch priority HTML into raw/."""

from __future__ import annotations

from typing import Any

from src.eda.sec_client import SecClient
from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
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
        n_ok = n_skip = n_err = n_empty = 0
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

        pbar = stage_progress(
            doc_jobs,
            desc="download",
            total=len(doc_jobs),
            unit="doc",
            show=ctx.show_progress,
        )
        for eid, doc in pbar:
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
                    n_skip += 1
                else:
                    if not cik or not accession or not filename:
                        raise ValueError("missing cik/accession/filename")
                    url = self.client.document_url(cik, accession, filename)
                    record["url"] = url
                    if ctx.dry_run:
                        record["status"] = "dry_run"
                        n_skip += 1
                    else:
                        data = self.client.get_bytes(url)
                        if not data:
                            record.update({"status": "empty", "bytes": 0, "sha1": None})
                            n_empty += 1
                        else:
                            out.write_bytes(data)
                            record.update(
                                {
                                    "status": "ok",
                                    "bytes": len(data),
                                    "sha1": sha1_bytes(data),
                                }
                            )
                            n_ok += 1
            except Exception as exc:  # noqa: BLE001
                record["status"] = "http_error"
                record["error"] = str(exc)
                n_err += 1
                errors.append(f"{eid}/{filename}: {exc}")

            man_path = store.download_manifest_path(eid)
            existing = {"event_id": eid, "docs": [], "updated_at": utc_now_iso()}
            if man_path.exists():
                existing = store.read_json(man_path)
            docs_list = [
                d
                for d in existing.get("docs", [])
                if d.get("filename") != filename or d.get("accession") != accession
            ]
            docs_list.append(record)
            existing["docs"] = docs_list
            existing["updated_at"] = utc_now_iso()
            store.write_json(man_path, existing)
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_ok, skip=n_skip, err=n_err, refresh=False)

        metrics = {
            "n_docs_attempted": len(doc_jobs),
            "n_ok": n_ok,
            "n_skipped_cached": n_skip,
            "n_http_error": n_err,
            "n_empty": n_empty,
            "n_events_pending": len(event_ids),
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
