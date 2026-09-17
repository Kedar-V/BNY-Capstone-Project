"""Roll up stage manifests into metrics CSV."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.eda.config import PROJECT_ROOT
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT


def collect_stage_metrics(path_name: str = "tender", root: Path | None = None) -> pd.DataFrame:
    root = root or DEFAULT_PREPROCESS_ROOT
    runs = root / path_name / "runs"
    rows: list[dict[str, Any]] = []
    if not runs.exists():
        return pd.DataFrame()
    for path in sorted(runs.glob("*_manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        metrics = data.get("metrics") or {}
        flat = {
            "path": data.get("path") or path_name,
            "stage": data.get("stage") or path.stem.replace("_manifest", ""),
            "status": data.get("status"),
            "written_at": data.get("written_at"),
        }
        for k, v in metrics.items():
            if isinstance(v, (dict, list)):
                flat[k] = json.dumps(v)
            else:
                flat[k] = v
        rows.append(flat)
    return pd.DataFrame(rows)


def write_metrics_csv(
    path_name: str = "tender",
    root: Path | None = None,
    out: Path | None = None,
) -> Path:
    out = out or (PROJECT_ROOT / "outputs" / "to_preprocess_metrics.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df = collect_stage_metrics(path_name, root)
    df.to_csv(out, index=False)
    return out
