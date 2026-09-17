"""On-disk artifact I/O for preprocess stages."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.eda.config import PROJECT_ROOT

DEFAULT_PREPROCESS_ROOT = PROJECT_ROOT / "data" / "preprocess"
SCHEMA_VERSION = "1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_text(text: str) -> str:
    return sha1_bytes(text.encode("utf-8", errors="replace"))


class ArtifactStore:
    def __init__(self, path_name: str, root: Path | None = None) -> None:
        self.path_name = path_name
        self.root = root or DEFAULT_PREPROCESS_ROOT
        self.path_root = self.root / path_name

    def event_dir(self, event_id: str) -> Path:
        d = self.path_root / "events" / event_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def raw_dir(self, event_id: str) -> Path:
        d = self.event_dir(event_id) / "raw"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def clean_dir(self, event_id: str) -> Path:
        d = self.event_dir(event_id) / "clean"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def concise_dir(self, event_id: str) -> Path:
        d = self.event_dir(event_id) / "concise"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def raw_path(self, event_id: str, accession: str, filename: str) -> Path:
        safe = f"{accession}__{Path(filename).name}"
        return self.raw_dir(event_id) / safe

    def clean_text_path(self, event_id: str, accession: str, filename: str) -> Path:
        safe = f"{accession}__{Path(filename).name}.txt"
        return self.clean_dir(event_id) / safe

    def clean_meta_path(self, event_id: str, accession: str, filename: str) -> Path:
        safe = f"{accession}__{Path(filename).name}.meta.json"
        return self.clean_dir(event_id) / safe

    def write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_stage_manifest(self, stage: str, payload: dict[str, Any]) -> Path:
        runs = self.path_root / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        out = {
            "stage": stage,
            "path": self.path_name,
            "written_at": utc_now_iso(),
            **payload,
        }
        path = runs / f"{stage}_manifest.json"
        return self.write_json(path, out)

    def inventory_path(self, event_id: str) -> Path:
        return self.event_dir(event_id) / "inventory.json"

    def segments_path(self, event_id: str) -> Path:
        return self.event_dir(event_id) / "segments.json"

    def spans_path(self, event_id: str) -> Path:
        return self.event_dir(event_id) / "spans.json"

    def event_rep_path(self, event_id: str) -> Path:
        return self.concise_dir(event_id) / "event_rep.json"

    def download_manifest_path(self, event_id: str) -> Path:
        return self.event_dir(event_id) / "download_manifest.json"

    def cohort_index_path(self) -> Path:
        return self.path_root / "cohort_index.json"
