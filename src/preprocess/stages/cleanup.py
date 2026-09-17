"""Cleanup stage: SEC wrapper strip + html_to_text + meta."""

from __future__ import annotations

import re
from typing import Any

from src.eda.documents import html_to_text
from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
from src.preprocess.resume import resolve_event_ids
from src.preprocess.store import ArtifactStore, sha1_text, utc_now_iso

_DOC_TEXT = re.compile(
    r"<DOCUMENT>.*?<TEXT>(.*?)</TEXT>.*?</DOCUMENT>",
    re.I | re.S,
)


def strip_sec_wrapper(raw: str) -> str:
    """Remove EDGAR <DOCUMENT>/<TEXT> wrapper when present; keep inner HTML."""
    m = _DOC_TEXT.search(raw)
    if m:
        return m.group(1).strip()
    # Sometimes multiple documents — take first TEXT block
    m2 = re.search(r"<TEXT>(.*?)</TEXT>", raw, re.I | re.S)
    if m2:
        return m2.group(1).strip()
    return raw


def _event_ids(store: ArtifactStore, ctx: StageContext, *, stage: str | None = None) -> list[str]:
    return resolve_event_ids(store, ctx, stage=stage)


class CleanupStage:
    name = "cleanup"

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        event_ids = _event_ids(store, ctx, stage=self.name)
        n_ok = n_empty = n_fail = n_skip = 0
        errors: list[str] = []
        jobs: list[tuple[str, dict[str, Any]]] = []

        for eid in event_ids:
            inv_path = store.inventory_path(eid)
            if not inv_path.exists():
                continue
            inv = store.read_json(inv_path)
            for doc in inv.get("docs") or []:
                jobs.append((eid, doc))

        pbar = stage_progress(
            jobs, desc="cleanup", total=len(jobs), unit="doc", show=ctx.show_progress
        )
        for eid, doc in pbar:
            accession = doc.get("accession") or ""
            filename = doc.get("filename") or ""
            role = doc.get("role")
            raw_path = store.raw_path(eid, accession, filename)
            txt_path = store.clean_text_path(eid, accession, filename)
            meta_path = store.clean_meta_path(eid, accession, filename)
            try:
                if (
                    not ctx.force
                    and txt_path.exists()
                    and meta_path.exists()
                    and txt_path.stat().st_size > 0
                ):
                    n_skip += 1
                    if hasattr(pbar, "set_postfix"):
                        pbar.set_postfix(ok=n_ok, skip=n_skip, fail=n_fail, refresh=False)
                    continue
                if not raw_path.exists():
                    raise FileNotFoundError(f"missing raw {raw_path.name}")
                raw_bytes = raw_path.read_bytes()
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                inner = strip_sec_wrapper(raw_text)
                text = html_to_text(inner)
                words = len(text.split())
                meta = {
                    "doc_role": role,
                    "source_hit_id": doc.get("hit_id"),
                    "accession": accession,
                    "filename": filename,
                    "sha1": sha1_text(text),
                    "words": words,
                    "bytes": len(text.encode("utf-8")),
                    "raw_path": str(raw_path),
                    "written_at": utc_now_iso(),
                }
                if not ctx.dry_run:
                    txt_path.write_text(text, encoding="utf-8")
                    store.write_json(meta_path, meta)
                if words == 0:
                    n_empty += 1
                else:
                    n_ok += 1
            except Exception as exc:  # noqa: BLE001
                n_fail += 1
                errors.append(f"{eid}/{filename}: {exc}")
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_ok, skip=n_skip, fail=n_fail, refresh=False)

        metrics = {
            "n_docs_cleaned": n_ok,
            "n_empty_text": n_empty,
            "n_failed": n_fail,
            "n_skipped_cached": n_skip,
            "n_events_pending": len(event_ids),
        }
        man = store.write_stage_manifest(self.name, {"status": "ok", "metrics": metrics, "errors": errors[:30]})
        return StageResult(
            stage=self.name,
            status="ok",
            n_success=n_ok,
            n_failed=n_fail,
            n_skipped=n_skip,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(man)],
        )
