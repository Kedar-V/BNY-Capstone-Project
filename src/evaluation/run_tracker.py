"""Lightweight intermediate tracking for a tender pipeline + eval run.

Writes into the run's output directory:
  run_manifest.json  config, GT file + sha256, git commit, per-stage status/timing, final summary.
                     Rewritten after every stage, so a crashed run still shows how far it got.
  progress.jsonl     one heartbeat line per `every` scored rows: elapsed, ETA, micro P/R/F1 and per-field F1.

`tail -f progress.jsonl` (or `jq -s last`) shows live state; the tqdm bar shows the same on the terminal.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True, timeout=5
        ).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


class RunTracker:
    def __init__(self, out_dir: Path, config: dict[str, Any], *, every: int = 10) -> None:
        self.out_dir = out_dir
        self.every = max(1, every)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = out_dir / "run_manifest.json"
        self.progress_path = out_dir / "progress.jsonl"
        self._t0 = time.monotonic()
        self._stage_t0: float | None = None
        self._rows_t0: float | None = None
        self._rows_done0 = 0
        self.manifest: dict[str, Any] = {
            "started_at": _now(),
            "status": "running",
            "config": config,
            "stages": [],
        }
        self._write()

    # -- manifest ---------------------------------------------------------------
    def _write(self) -> None:
        self.manifest["elapsed_s"] = round(time.monotonic() - self._t0, 1)
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.manifest_path)

    def note(self, **kv: Any) -> None:
        self.manifest.update(kv)
        self._write()

    @contextmanager
    def stage(self, name: str, **info: Any) -> Iterator[dict[str, Any]]:
        rec: dict[str, Any] = {"stage": name, "started_at": _now(), "status": "running", **info}
        self.manifest["stages"].append(rec)
        self._write()
        t0 = time.monotonic()
        try:
            yield rec
            rec["status"] = rec.get("status") if rec.get("status") not in (None, "running") else "ok"
        except BaseException as e:  # noqa: BLE001
            rec["status"] = "failed"
            rec["error"] = f"{type(e).__name__}: {e}"
            self.manifest["status"] = "failed"
            raise
        finally:
            rec["finished_at"] = _now()
            rec["duration_s"] = round(time.monotonic() - t0, 1)
            self._write()

    def finish(self, status: str = "ok", **summary: Any) -> None:
        self.manifest.update({"status": status, "finished_at": _now(), "summary": summary})
        self._write()

    # -- heartbeats -------------------------------------------------------------
    def eval_started(self, already_done: int) -> None:
        self._rows_t0 = time.monotonic()
        self._rows_done0 = already_done

    def on_row(self, live: dict[str, Any]) -> None:
        """Callback for evaluate_tender: called after every scored row."""
        done, total = live["n_done"], live["n_total"]
        if done % self.every and done != total:
            return
        elapsed = time.monotonic() - (self._rows_t0 or self._t0)
        fresh = max(1, done - self._rows_done0)
        rate = fresh / elapsed if elapsed > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else None
        micro = live.get("micro") or {}
        line = {
            "ts": _now(),
            "stage": "eval",
            "done": done,
            "total": total,
            "pct": round(100 * done / total, 1) if total else None,
            "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta, 1) if eta is not None else None,
            "missing_prediction": live.get("n_accessions_missing_prediction"),
            "micro": {k: micro.get(k) for k in ("precision", "recall", "f1")},
            "per_field_f1": {f: m.get("f1") for f, m in (live.get("per_field") or {}).items()},
        }
        with self.progress_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        self.manifest["last_heartbeat"] = {k: line[k] for k in ("ts", "done", "total", "pct", "eta_s")}
        self._write()
