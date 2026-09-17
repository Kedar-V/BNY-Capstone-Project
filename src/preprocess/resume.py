"""Resume helpers: resolve cohort event ids and skip completed stage work."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.preprocess.contracts import StageContext
from src.preprocess.store import SCHEMA_VERSION, ArtifactStore, utc_now_iso


def sync_cohort_index_from_disk(store: ArtifactStore) -> dict[str, Any]:
    """Rebuild cohort_index.json from per-event inventory.json files (merge-safe)."""
    events_root = store.path_root / "events"
    cohort_lists: dict[str, list[str]] = {
        "gold": [],
        "needs_otp_resolve": [],
        "incomplete": [],
    }
    otp_methods: dict[str, int] = {}
    if events_root.exists():
        for d in sorted(events_root.iterdir()):
            if not d.is_dir():
                continue
            inv_path = d / "inventory.json"
            if not inv_path.exists():
                continue
            try:
                inv = store.read_json(inv_path)
            except Exception:  # noqa: BLE001
                continue
            cohort = inv.get("cohort") or "incomplete"
            if cohort not in cohort_lists:
                cohort = "incomplete"
            eid = str(inv.get("event_id") or d.name)
            if eid not in cohort_lists[cohort]:
                cohort_lists[cohort].append(eid)
            method = inv.get("otp_method") or "missing"
            otp_methods[method] = otp_methods.get(method, 0) + 1

    index = {
        "schema_version": SCHEMA_VERSION,
        "path": store.path_name,
        "n_events": sum(len(v) for v in cohort_lists.values()),
        "cohorts": {k: len(v) for k, v in cohort_lists.items()},
        "cohort_event_ids": cohort_lists,
        "otp_method_mix": otp_methods,
        "written_at": utc_now_iso(),
        "source": "disk_inventories",
    }
    store.write_json(store.cohort_index_path(), index)
    return index


def merge_cohort_index(store: ArtifactStore, new_lists: dict[str, list[str]], otp_methods: dict[str, int]) -> dict[str, Any]:
    """Merge newly inventoried ids into existing cohort_index (do not drop prior events)."""
    existing: dict[str, Any] = {}
    idx_path = store.cohort_index_path()
    if idx_path.exists():
        try:
            existing = store.read_json(idx_path)
        except Exception:  # noqa: BLE001
            existing = {}
    merged: dict[str, list[str]] = {
        "gold": [],
        "needs_otp_resolve": [],
        "incomplete": [],
    }
    for key in merged:
        seen: set[str] = set()
        for eid in list((existing.get("cohort_event_ids") or {}).get(key) or []) + list(new_lists.get(key) or []):
            if eid not in seen:
                merged[key].append(eid)
                seen.add(eid)
    methods = dict(existing.get("otp_method_mix") or {})
    for k, v in otp_methods.items():
        methods[k] = methods.get(k, 0) + v
    index = {
        "schema_version": SCHEMA_VERSION,
        "path": store.path_name,
        "n_events": sum(len(v) for v in merged.values()),
        "cohorts": {k: len(v) for k, v in merged.items()},
        "cohort_event_ids": merged,
        "otp_method_mix": methods,
        "written_at": utc_now_iso(),
        "source": "inventory_merge",
    }
    store.write_json(store.cohort_index_path(), index)
    return index


def stage_artifact_ready(store: ArtifactStore, event_id: str, stage: str) -> bool:
    """True if stage output already exists and looks usable."""
    if stage == "inventory":
        return store.inventory_path(event_id).exists()
    if stage == "download":
        inv_path = store.inventory_path(event_id)
        if not inv_path.exists():
            return False
        inv = store.read_json(inv_path)
        docs = inv.get("docs") or []
        if not docs:
            return False
        return all(
            store.raw_path(event_id, d.get("accession") or "", d.get("filename") or "").exists()
            and store.raw_path(event_id, d.get("accession") or "", d.get("filename") or "").stat().st_size > 0
            for d in docs
        )
    if stage == "cleanup":
        inv_path = store.inventory_path(event_id)
        if not inv_path.exists():
            return False
        inv = store.read_json(inv_path)
        docs = inv.get("docs") or []
        raw_docs = [
            d
            for d in docs
            if store.raw_path(event_id, d.get("accession") or "", d.get("filename") or "").exists()
        ]
        if not raw_docs:
            return False
        return all(
            store.clean_text_path(event_id, d.get("accession") or "", d.get("filename") or "").exists()
            for d in raw_docs
        )
    if stage == "segment":
        path = store.segments_path(event_id)
        if not path.exists():
            return False
        try:
            return int(store.read_json(path).get("n_segments") or 0) > 0
        except Exception:  # noqa: BLE001
            return False
    if stage == "gliner":
        path = store.spans_path(event_id)
        if not path.exists():
            return False
        try:
            payload = store.read_json(path)
            return payload.get("status") == "ok" and int(payload.get("n_spans") or 0) >= 0
        except Exception:  # noqa: BLE001
            return False
    if stage == "assemble":
        path = store.event_rep_path(event_id)
        if not path.exists():
            return False
        try:
            return store.read_json(path).get("preprocess_status") == "ok"
        except Exception:  # noqa: BLE001
            return False
    if stage == "load_db":
        return stage_artifact_ready(store, event_id, "assemble")
    return False


def resolve_event_ids(
    store: ArtifactStore,
    ctx: StageContext,
    *,
    stage: str | None = None,
    sync_index: bool = True,
) -> list[str]:
    """Resolve event ids for a stage, optionally skipping completed work.

    - Uses explicit ``ctx.event_ids`` when set.
    - Else reads cohort_index (syncing from disk inventories first).
    - Without ``--force``, skips events that already have this stage's artifact.
    - ``pending_only`` further restricts to events missing Concise Rep (assemble).
    - ``ctx.limit`` applies **after** skip filtering (so each run advances).
    """
    if sync_index and not ctx.event_ids:
        sync_cohort_index_from_disk(store)

    if ctx.event_ids:
        ids = list(ctx.event_ids)
    else:
        idx_path = store.cohort_index_path()
        if not idx_path.exists():
            sync_cohort_index_from_disk(store)
        data = store.read_json(store.cohort_index_path()) if store.cohort_index_path().exists() else {}
        cohorts = data.get("cohort_event_ids") or {}
        if ctx.cohort:
            ids = list(cohorts.get(ctx.cohort, []))
        else:
            ids = []
            for key in ("gold", "needs_otp_resolve", "incomplete"):
                ids.extend(cohorts.get(key) or [])

        if not ids:
            events_root = store.path_root / "events"
            if events_root.exists():
                ids = sorted(
                    p.name for p in events_root.iterdir() if p.is_dir() and (p / "inventory.json").exists()
                )

    pending_only = bool(ctx.extra.get("pending_only"))
    if pending_only and not ctx.force:
        ids = [eid for eid in ids if not stage_artifact_ready(store, eid, "assemble")]

    if stage and not ctx.force:
        ids = [eid for eid in ids if not stage_artifact_ready(store, eid, stage)]

    if ctx.limit is not None:
        ids = ids[: ctx.limit]
    return ids
