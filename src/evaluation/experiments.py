"""Experiment ledger: one change per run, snapshot metrics, deltas vs parent."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FOCUS_FIELDS = (
    "offer_price",
    "bidder",
    "subject_company",
    "security_description",
    "expiration_date",
)

LEDGER_COLUMNS = [
    "run_id",
    "timestamp",
    "parent_run_id",
    "change_summary",
    "gliner_threshold",
    "gliner_model",
    "label_set",
    "max_windows",
    "fields",
    "scope",
    "n_accessions",
    "git_commit",
    "micro_f1",
    "micro_precision",
    "micro_recall",
    "micro_accuracy",
    "micro_accuracy_when_gt",
    *[f"f1_{f}" for f in FOCUS_FIELDS],
    "delta_micro_f1",
    *[f"delta_f1_{f}" for f in FOCUS_FIELDS],
    "keep",
]


def experiments_root(eval_out: Path) -> Path:
    return eval_out / "experiments"


def ledger_path(eval_out: Path) -> Path:
    return experiments_root(eval_out) / "ledger.csv"


def holdout_path(eval_out: Path) -> Path:
    return experiments_root(eval_out) / "holdout_accessions.txt"


def git_commit(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


def ensure_holdout(eval_out: Path, accessions: list[str], n: int = 20) -> list[str]:
    """Create fixed holdout list once; reuse thereafter."""
    root = experiments_root(eval_out)
    root.mkdir(parents=True, exist_ok=True)
    path = holdout_path(eval_out)
    if path.exists():
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    chosen = list(accessions[:n])
    path.write_text("\n".join(chosen) + "\n", encoding="utf-8")
    return chosen


def _f1_map(per_field: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for f in FOCUS_FIELDS:
        m = per_field.get(f) or {}
        v = m.get("f1")
        out[f] = float(v) if v is not None else None
    return out


def _read_ledger(eval_out: Path) -> list[dict[str, str]]:
    path = ledger_path(eval_out)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parent_metrics(eval_out: Path, parent_run_id: str | None) -> dict[str, Any] | None:
    if not parent_run_id:
        return None
    # baseline lives at experiments/baseline/
    if parent_run_id.startswith("baseline"):
        summary = experiments_root(eval_out) / "baseline" / "summary.json"
        pf = experiments_root(eval_out) / "baseline" / "per_field.csv"
    else:
        summary = experiments_root(eval_out) / "runs" / parent_run_id / "summary.json"
        pf = experiments_root(eval_out) / "runs" / parent_run_id / "per_field.csv"
    if not summary.exists():
        rows = _read_ledger(eval_out)
        for row in reversed(rows):
            if row.get("run_id") == parent_run_id:
                return {
                    "micro_f1": _float(row.get("micro_f1")),
                    **{f"f1_{f}": _float(row.get(f"f1_{f}")) for f in FOCUS_FIELDS},
                }
        return None
    data = json.loads(summary.read_text(encoding="utf-8"))
    micro = data.get("micro") or {}
    per_field = data.get("per_field")
    if per_field is None and pf.exists():
        per_field = {}
        with pf.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                per_field[row["field"]] = {
                    "f1": _float(row.get("f1")),
                }
    f1s = _f1_map(per_field or {})
    return {
        "micro_f1": micro.get("f1"),
        **{f"f1_{f}": f1s[f] for f in FOCUS_FIELDS},
    }


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _delta(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None:
        return None
    return cur - prev


def snapshot_baseline(eval_out: Path, *, run_id: str = "baseline_2026-10-12") -> Path:
    """Copy current eval metrics into experiments/baseline/ and ledger row."""
    root = experiments_root(eval_out)
    dest = root / "baseline"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("summary.json", "per_field.csv"):
        src = eval_out / name
        if src.exists():
            shutil.copy2(src, dest / name)
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "change_summary": "baseline before Phase A",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {}
    if (dest / "summary.json").exists():
        summary = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
    per_field = summary.get("per_field") or {}
    if not per_field and (dest / "per_field.csv").exists():
        with (dest / "per_field.csv").open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                per_field[row["field"]] = {"f1": _float(row.get("f1"))}
    record_experiment(
        eval_out,
        run_id=run_id,
        change_summary="baseline before Phase A",
        parent_run_id=None,
        result=summary if summary.get("micro") else {"micro": {}, "per_field": per_field},
        config={
            "gliner_threshold": "",
            "gliner_model": "",
            "label_set": "all",
            "max_windows": "",
            "fields": "all",
            "scope": "full",
            "n_accessions": summary.get("n_gt_accessions") or "",
        },
        keep=True,
        dest_dir=dest,
        skip_copy=True,
    )
    return dest


def record_experiment(
    eval_out: Path,
    *,
    run_id: str,
    change_summary: str,
    parent_run_id: str | None,
    result: dict[str, Any],
    config: dict[str, Any],
    keep: bool | None = None,
    repo: Path | None = None,
    dest_dir: Path | None = None,
    skip_copy: bool = False,
) -> dict[str, Any]:
    """Snapshot run artifacts and append ledger row with deltas vs parent."""
    root = experiments_root(eval_out)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = dest_dir or (root / "runs" / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    if not skip_copy:
        for name in (
            "summary.json",
            "per_field.csv",
            "pipeline_predictions.csv",
            "pipeline_vs_gt.csv",
        ):
            src = eval_out / name
            if src.exists():
                shutil.copy2(src, run_dir / name)

    micro = result.get("micro") or {}
    per_field = result.get("per_field") or {}
    f1s = _f1_map(per_field)
    parent = _parent_metrics(eval_out, parent_run_id)

    delta_micro = _delta(micro.get("f1"), (parent or {}).get("micro_f1"))
    focus_deltas = {
        f: _delta(f1s[f], (parent or {}).get(f"f1_{f}")) for f in FOCUS_FIELDS
    }

    # Auto keep: micro F1 up, or any focus F1 up without micro drop > 0.02
    if keep is None:
        micro_ok = delta_micro is not None and delta_micro > 0
        focus_up = any(d is not None and d > 0 for d in focus_deltas.values())
        micro_not_tanked = delta_micro is None or delta_micro >= -0.02
        keep = bool(micro_ok or (focus_up and micro_not_tanked))

    meta = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parent_run_id": parent_run_id,
        "change_summary": change_summary,
        "config": config,
        "keep": keep,
        "git_commit": git_commit(repo) if repo else "",
        "micro": micro,
        "focus_f1": f1s,
        "deltas": {"micro_f1": delta_micro, **{f"f1_{k}": v for k, v in focus_deltas.items()}},
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if result.get("micro") and not (run_dir / "summary.json").exists():
        (run_dir / "summary.json").write_text(
            json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2) + "\n",
            encoding="utf-8",
        )

    row = {
        "run_id": run_id,
        "timestamp": meta["timestamp"],
        "parent_run_id": parent_run_id or "",
        "change_summary": change_summary,
        "gliner_threshold": config.get("gliner_threshold", ""),
        "gliner_model": config.get("gliner_model", ""),
        "label_set": config.get("label_set", ""),
        "max_windows": config.get("max_windows", ""),
        "fields": config.get("fields", ""),
        "scope": config.get("scope", ""),
        "n_accessions": config.get("n_accessions", result.get("n_gt_accessions", "")),
        "git_commit": meta["git_commit"],
        "micro_f1": micro.get("f1"),
        "micro_precision": micro.get("precision"),
        "micro_recall": micro.get("recall"),
        "micro_accuracy": micro.get("accuracy"),
        "micro_accuracy_when_gt": micro.get("accuracy_when_gt"),
        **{f"f1_{f}": f1s[f] for f in FOCUS_FIELDS},
        "delta_micro_f1": delta_micro,
        **{f"delta_f1_{f}": focus_deltas[f] for f in FOCUS_FIELDS},
        "keep": keep,
    }

    path = ledger_path(eval_out)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        if write_header:
            w.writeheader()
        w.writerow({k: ("" if row.get(k) is None else row[k]) for k in LEDGER_COLUMNS})

    # Mirror into MLflow (no-op if MLFLOW_ENABLED=0 or package missing).
    try:
        from src.evaluation.mlflow_tracking import log_eval_run

        mlflow_result = {
            **result,
            "deltas": meta.get("deltas") or {},
        }
        mlflow_run = log_eval_run(
            run_id=run_id,
            change_summary=change_summary,
            parent_run_id=parent_run_id,
            result=mlflow_result,
            config=config,
            keep=keep,
            git_commit=meta.get("git_commit") or "",
            run_dir=run_dir,
        )
        if mlflow_run:
            meta["mlflow_run_id"] = mlflow_run
            (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        meta["mlflow_error"] = str(exc)
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return meta
