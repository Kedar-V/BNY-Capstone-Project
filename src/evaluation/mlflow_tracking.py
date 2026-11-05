"""MLflow tracking for tender GLiNER train + eval.

Defaults to SQLite at ``outputs/mlflow.db`` (artifacts in ``outputs/mlartifacts``).
Override with ``MLFLOW_TRACKING_URI``. Disable with ``MLFLOW_ENABLED=0``.

Usage (train / eval scripts already call this)::

    from src.evaluation.mlflow_tracking import log_train_run, log_eval_run

    with log_train_run(run_name="small_passage_500", params={...}) as run:
        ...
        run.log_metrics({"train_loss": 0.99})
        run.log_artifact("models/tender_gliner_small/final")

UI::

    python scripts/mlflow_ui.py
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
# SQLite is the supported local backend (file:// mlruns is deprecated in MLflow 3+).
DEFAULT_TRACKING_URI = f"sqlite:///{(REPO_ROOT / 'outputs' / 'mlflow.db').resolve()}"
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "outputs" / "mlartifacts"

EXPERIMENT_TRAIN = "tender_gliner_train"
EXPERIMENT_EVAL = "tender_eval"

_CONFIGURED = False


def enabled() -> bool:
    return os.environ.get("MLFLOW_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def tracking_uri() -> str:
    return (os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_TRACKING_URI).strip()


def artifact_root() -> Path:
    raw = os.environ.get("MLFLOW_ARTIFACT_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_ARTIFACT_ROOT.resolve()


def tracking_dir() -> Path:
    """Directory containing the local SQLite DB (or legacy file store)."""
    uri = tracking_uri()
    if uri.startswith("sqlite:///"):
        return Path(uri.removeprefix("sqlite:///")).resolve().parent
    if uri.startswith("file:"):
        return Path(uri.removeprefix("file://").removeprefix("file:")).resolve()
    return (REPO_ROOT / "outputs").resolve()


def configure(*, uri: str | None = None, experiment: str | None = None) -> Any:
    """Import mlflow, set tracking URI, optionally activate an experiment."""
    global _CONFIGURED
    if not enabled():
        return None
    import mlflow

    track = (uri or tracking_uri()).strip()
    if track.startswith("sqlite:///"):
        db_path = Path(track.removeprefix("sqlite:///")).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_root().mkdir(parents=True, exist_ok=True)
    elif track.startswith("file:"):
        # Legacy path — only works if MLFLOW_ALLOW_FILE_STORE=true
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        tracking_dir().mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(track)
    if experiment:
        mlflow.set_experiment(experiment)
    _CONFIGURED = True
    return mlflow


def _safe_key(key: str) -> str:
    """MLflow param/metric keys: alnum, _, -, ., space, :, /."""
    k = re.sub(r"[^\w\-./: ]+", "_", str(key))
    return k[:250] or "key"


def _flat_params(params: Mapping[str, Any], *, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in params.items():
        key = _safe_key(f"{prefix}{k}" if not prefix else f"{prefix}.{k}")
        if v is None:
            continue
        if isinstance(v, Mapping):
            out.update(_flat_params(v, prefix=key))
        elif isinstance(v, (list, tuple, set)):
            out[key] = ",".join(str(x) for x in v)[:500]
        else:
            out[key] = str(v)[:500]
    return out


def _flat_metrics(metrics: Mapping[str, Any], *, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in metrics.items():
        key = _safe_key(f"{prefix}{k}" if not prefix else f"{prefix}.{k}")
        if v is None or v == "":
            continue
        if isinstance(v, Mapping):
            out.update(_flat_metrics(v, prefix=key))
            continue
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            continue
    return out


@dataclass
class TrackedRun:
    """Thin wrapper so callers don't import mlflow directly."""

    run_id: str
    experiment: str
    run_name: str
    _active: bool = field(default=True, repr=False)

    def log_params(self, params: Mapping[str, Any]) -> None:
        if not self._active or not enabled():
            return
        import mlflow

        flat = _flat_params(params)
        if flat:
            mlflow.log_params(flat)

    def log_metrics(self, metrics: Mapping[str, Any], *, step: int | None = None) -> None:
        if not self._active or not enabled():
            return
        import mlflow

        flat = _flat_metrics(metrics)
        for k, v in flat.items():
            mlflow.log_metric(k, v, step=step)

    def set_tags(self, tags: Mapping[str, Any]) -> None:
        if not self._active or not enabled():
            return
        import mlflow

        for k, v in tags.items():
            if v is None:
                continue
            mlflow.set_tag(_safe_key(k), str(v)[:5000])

    def log_artifact(self, path: str | Path, artifact_path: str | None = None) -> None:
        if not self._active or not enabled():
            return
        import mlflow

        p = Path(path)
        if not p.exists():
            return
        if p.is_dir():
            mlflow.log_artifacts(str(p), artifact_path=artifact_path)
        else:
            mlflow.log_artifact(str(p), artifact_path=artifact_path)

    def log_dict(self, data: Mapping[str, Any], artifact_file: str) -> None:
        if not self._active or not enabled():
            return
        import mlflow

        mlflow.log_dict(dict(data), artifact_file)


@contextmanager
def start_run(
    *,
    experiment: str,
    run_name: str,
    params: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
    description: str | None = None,
) -> Iterator[TrackedRun]:
    """Context-managed MLflow run. No-ops (yields dummy) when disabled."""
    if not enabled():
        yield TrackedRun(run_id="", experiment=experiment, run_name=run_name, _active=False)
        return

    mlflow = configure(experiment=experiment)
    assert mlflow is not None
    with mlflow.start_run(run_name=run_name, description=description) as active:
        tracked = TrackedRun(
            run_id=active.info.run_id,
            experiment=experiment,
            run_name=run_name,
        )
        if tags:
            tracked.set_tags(tags)
        if params:
            tracked.log_params(params)
        try:
            yield tracked
        except Exception:
            tracked.set_tags({"status": "failed"})
            raise
        else:
            tracked.set_tags({"status": "finished"})


def log_train_run(
    *,
    run_name: str,
    params: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
    artifact_paths: list[str | Path] | None = None,
    description: str | None = None,
) -> str | None:
    """One-shot train logging (when you don't need a live context)."""
    with start_run(
        experiment=EXPERIMENT_TRAIN,
        run_name=run_name,
        params=params,
        tags={"stage": "train", **(tags or {})},
        description=description,
    ) as run:
        if metrics:
            run.log_metrics(metrics)
        for path in artifact_paths or []:
            run.log_artifact(path)
        return run.run_id or None


def eval_metrics_from_result(result: Mapping[str, Any]) -> dict[str, float]:
    """Flatten evaluate_tender() result into MLflow metrics."""
    micro = result.get("micro") or {}
    metrics: dict[str, Any] = {
        "micro_f1": micro.get("f1"),
        "micro_precision": micro.get("precision"),
        "micro_recall": micro.get("recall"),
        "micro_accuracy": micro.get("accuracy"),
        "micro_accuracy_when_gt": micro.get("accuracy_when_gt"),
        "n_gt_accessions": result.get("n_gt_accessions"),
        "n_accessions_scored": result.get("n_accessions_scored"),
        "n_accessions_missing_prediction": result.get("n_accessions_missing_prediction"),
        "n_gt_rows": result.get("n_gt_rows"),
    }
    per_field = result.get("per_field") or {}
    for name, stats in per_field.items():
        if not isinstance(stats, Mapping):
            continue
        for key in ("f1", "precision", "recall", "tp", "fp", "fn", "gt_present"):
            if key in stats and stats[key] is not None:
                metrics[f"field.{name}.{key}"] = stats[key]
    return _flat_metrics(metrics)


def log_eval_run(
    *,
    run_id: str,
    change_summary: str,
    parent_run_id: str | None,
    result: Mapping[str, Any],
    config: Mapping[str, Any],
    keep: bool | None = None,
    git_commit: str = "",
    run_dir: Path | None = None,
    tags: Mapping[str, Any] | None = None,
) -> str | None:
    """Log a tender eval experiment (mirrors ``record_experiment``)."""
    if not enabled():
        return None

    deltas = {}
    if isinstance(result.get("deltas"), Mapping):
        deltas = dict(result["deltas"])  # type: ignore[index]
    # meta-style deltas may live outside result; callers pass via tags/config

    metrics = eval_metrics_from_result(result)
    # optional focus deltas if present on result
    for k, v in (result.get("deltas") or {}).items() if isinstance(result.get("deltas"), Mapping) else []:
        try:
            metrics[_safe_key(f"delta.{k}")] = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    with start_run(
        experiment=EXPERIMENT_EVAL,
        run_name=run_id,
        params=config,
        tags={
            "stage": "eval",
            "run_id": run_id,
            "parent_run_id": parent_run_id or "",
            "change_summary": change_summary,
            "keep": keep,
            "git_commit": git_commit,
            **(tags or {}),
        },
        description=change_summary,
    ) as run:
        run.log_metrics(metrics)
        if deltas:
            run.log_metrics({f"delta.{k}": v for k, v in deltas.items()})
        if run_dir and run_dir.exists():
            for name in (
                "summary.json",
                "meta.json",
                "per_field.csv",
                "pipeline_predictions.csv",
                "pipeline_vs_gt.csv",
            ):
                path = run_dir / name
                if path.exists():
                    run.log_artifact(path)
        return run.run_id or None
