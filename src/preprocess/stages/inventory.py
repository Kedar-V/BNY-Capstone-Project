"""Inventory stage: cohort split + per-event source inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.eda.config import PROCESSED_DIR
from src.eda.mvp import tag_mvp_events
from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.paths.merger import select_priority_docs as select_merger_docs
from src.preprocess.paths.tender import select_priority_docs as select_tender_docs
from src.preprocess.progress import stage_progress
from src.preprocess.resume import merge_cohort_index
from src.preprocess.store import SCHEMA_VERSION, ArtifactStore, utc_now_iso


def load_catalog(
    events_path: Path | None = None,
    docs_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    events_path = events_path or (PROCESSED_DIR / "events.parquet")
    docs_path = docs_path or (PROCESSED_DIR / "documents.parquet")
    events = pd.read_parquet(events_path)
    docs = pd.read_parquet(docs_path)
    if "in_mvp_preferred" not in events.columns:
        events = tag_mvp_events(events)
    return events, docs


def _has_mvp_type(val: Any, want: str) -> bool:
    w = want.lower()
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    if isinstance(val, (list, tuple, set)):
        return any(w in str(t).lower() for t in val)
    return w in str(val).lower()


def _select_docs(path_name: str, event_docs: pd.DataFrame) -> dict[str, Any]:
    if path_name == "merger":
        return select_merger_docs(event_docs)
    return select_tender_docs(event_docs)

class InventoryStage:
    name = "inventory"

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(
                stage=self.name,
                status="stub_not_implemented",
                metrics=payload,
                artifact_paths=[str(path)],
            )

        events_path = Path(ctx.extra["events_path"]) if ctx.extra.get("events_path") else None
        docs_path = Path(ctx.extra["docs_path"]) if ctx.extra.get("docs_path") else None
        events, docs = load_catalog(events_path, docs_path)

        preferred = events[events["in_mvp_preferred"].fillna(False)].copy()
        # Merger path: keep events whose docs carry merger in mvp_event_types
        if cfg.mvp_event_type and cfg.mvp_event_type != "tender_offer":
            if "mvp_event_types" in docs.columns:
                merger_eids = {
                    str(e)
                    for e, g in docs.groupby(docs["event_id"].astype(str))
                    if any(_has_mvp_type(v, cfg.mvp_event_type) for v in g["mvp_event_types"])
                }
                preferred = preferred[preferred["event_id"].astype(str).isin(merger_eids)]
        if ctx.event_ids:
            preferred = preferred[preferred["event_id"].astype(str).isin(ctx.event_ids)]

        event_ids = preferred["event_id"].astype(str).tolist()

        # Prefer not-yet-inventoried events so --limit advances the cohort
        events_root = store.path_root / "events"
        already: set[str] = set()
        if events_root.exists():
            already = {
                p.name
                for p in events_root.iterdir()
                if p.is_dir() and (p / "inventory.json").exists()
            }
        if already and not ctx.force:
            fresh = [e for e in event_ids if e not in already]
            rest = [e for e in event_ids if e in already]
            event_ids = fresh + rest

        if ctx.limit is not None:
            event_ids = event_ids[: ctx.limit]

        docs = docs[docs["event_id"].astype(str).isin(event_ids)].copy()

        cohort_lists: dict[str, list[str]] = {
            "gold": [],
            "needs_otp_resolve": [],
            "incomplete": [],
        }
        otp_methods: dict[str, int] = {}
        n_success = 0
        n_skipped = 0
        errors: list[str] = []

        pbar = stage_progress(
            event_ids,
            desc="inventory",
            total=len(event_ids),
            unit="event",
            show=ctx.show_progress,
        )
        for eid in pbar:
            try:
                if not ctx.force and eid in already:
                    # Keep existing inventory; still count into merge via disk sync path
                    inv = store.read_json(store.inventory_path(eid))
                    cohort = inv.get("cohort") or "incomplete"
                    if ctx.cohort and cohort != ctx.cohort:
                        n_skipped += 1
                        continue
                    if cohort in cohort_lists and eid not in cohort_lists[cohort]:
                        cohort_lists[cohort].append(eid)
                    n_skipped += 1
                    if hasattr(pbar, "set_postfix"):
                        pbar.set_postfix(ok=n_success, skip=n_skipped, refresh=False)
                    continue
                edocs = docs[docs["event_id"].astype(str) == eid]
                selected = _select_docs(ctx.path_name, edocs)
                if ctx.cohort and selected["cohort"] != ctx.cohort:
                    n_skipped += 1
                    continue
                inv = {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": eid,
                    "path": ctx.path_name,
                    "mvp_event_type": cfg.mvp_event_type,
                    "primary_entity": None,
                    "primary_cik": None,
                    "written_at": utc_now_iso(),
                    **selected,
                }
                row = preferred[preferred["event_id"].astype(str) == eid]
                if not row.empty:
                    inv["primary_entity"] = row.iloc[0].get("primary_entity")
                    inv["primary_cik"] = row.iloc[0].get("primary_cik")

                store.write_json(store.inventory_path(eid), inv)
                cohort_lists[selected["cohort"]].append(eid)
                method = selected.get("otp_method") or "missing"
                otp_methods[method] = otp_methods.get(method, 0) + 1
                n_success += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{eid}: {exc}")
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_success, skip=n_skipped, refresh=False)

        index = merge_cohort_index(store, cohort_lists, otp_methods)
        # Re-sync from disk so skipped-but-existing inventories stay in the index
        from src.preprocess.resume import sync_cohort_index_from_disk

        index = sync_cohort_index_from_disk(store)
        index_path = store.cohort_index_path()

        coverage_rows = []
        for cohort, ids in (index.get("cohort_event_ids") or {}).items():
            for eid in ids:
                inv_path = store.inventory_path(eid)
                if not inv_path.exists():
                    continue
                inv = store.read_json(inv_path)
                coverage_rows.append(
                    {
                        "event_id": eid,
                        "cohort": cohort,
                        "has_cover": inv.get("has_cover"),
                        "has_otp": inv.get("has_otp"),
                        "otp_method": inv.get("otp_method"),
                        "has_lot": inv.get("has_lot"),
                        "has_14d9": inv.get("has_14d9"),
                        "n_amendments": inv.get("n_amendments"),
                        "download_ready": inv.get("download_ready"),
                    }
                )
        cov_df = pd.DataFrame(coverage_rows)
        out_csv = Path(ctx.extra.get("coverage_csv") or (Path("outputs") / "to_source_coverage.csv"))
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        if not cov_df.empty:
            cov_df.to_csv(out_csv, index=False)

        metrics: dict[str, Any] = {
            "n_events": index.get("n_events"),
            "n_gold": (index.get("cohorts") or {}).get("gold"),
            "n_needs_otp_resolve": (index.get("cohorts") or {}).get("needs_otp_resolve"),
            "n_incomplete": (index.get("cohorts") or {}).get("incomplete"),
            "n_inventoried_this_run": n_success,
            "n_skipped_cached": n_skipped,
            "otp_method_mix": index.get("otp_method_mix"),
            "coverage_csv": str(out_csv),
        }
        man = store.write_stage_manifest(
            self.name,
            {"status": "ok", "metrics": metrics, "n_failed": len(errors), "errors": errors[:20]},
        )
        return StageResult(
            stage=self.name,
            status="ok",
            n_success=n_success,
            n_failed=len(errors),
            n_skipped=n_skipped,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(index_path), str(man), str(out_csv)],
        )
