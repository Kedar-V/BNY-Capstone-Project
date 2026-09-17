"""Thin orchestrator: wire stages by name only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.preprocess.contracts import StageContext, StageResult
from src.preprocess.stages import STAGE_REGISTRY
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT


PIPELINE_ORDER = [
    "inventory",
    "download",
    "cleanup",
    "segment",
    "gliner",
    "assemble",
    "load_db",
]


def run_stage(
    stage_name: str,
    *,
    path_name: str = "tender",
    preprocess_root: Path | None = None,
    event_ids: list[str] | None = None,
    cohort: str | None = None,
    limit: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    show_progress: bool = True,
    extra: dict[str, Any] | None = None,
    stage_kwargs: dict[str, Any] | None = None,
) -> StageResult:
    if stage_name not in STAGE_REGISTRY:
        raise KeyError(f"Unknown stage: {stage_name}. Known: {list(STAGE_REGISTRY)}")
    cls = STAGE_REGISTRY[stage_name]
    stage = cls(**(stage_kwargs or {}))
    ctx = StageContext(
        path_name=path_name,
        preprocess_root=preprocess_root or DEFAULT_PREPROCESS_ROOT,
        event_ids=event_ids,
        cohort=cohort,
        limit=limit,
        force=force,
        dry_run=dry_run,
        show_progress=show_progress,
        extra=extra or {},
    )
    return stage.run(ctx)


def run_pipeline(
    *,
    path_name: str = "tender",
    stages: list[str] | None = None,
    skip_db: bool = False,
    **kwargs: Any,
) -> list[StageResult]:
    order = stages or list(PIPELINE_ORDER)
    results: list[StageResult] = []
    extra = dict(kwargs.pop("extra", None) or {})
    if skip_db:
        extra["skip_db"] = True
    for name in order:
        if name == "load_db" and skip_db:
            continue
        results.append(run_stage(name, path_name=path_name, extra=extra, **kwargs))
    return results
