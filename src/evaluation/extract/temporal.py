"""Temporal NER evidence lines (default ``temporal_for`` implementation).

The tagger helpers live in ``scripts/eval_temporal_tagger_dates.py``; it is loaded
lazily so importing this package never pulls the script (or transformers) in.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.evidence import cue_score

# Original span cap, kept for importers; the effective scan length / span cap come from
# ActionPack.temporal_scan_chars / temporal_max_spans (pack knobs, same defaults)
MAX_TEMPORAL = 25
CHUNK_CHARS = 1800
_ROOT = Path(__file__).resolve().parents[3]
_TAGGER_SCRIPT = _ROOT / "scripts" / "eval_temporal_tagger_dates.py"

# HF pipelines are not reliably thread-safe
_TAGGER_LOCK = threading.Lock()
_MODULE_LOCK = threading.Lock()
_module: ModuleType | None = None

TemporalFor = Callable[[str, str, tuple[str, ...]], dict[str, list[str]]]


def _tagger_module() -> ModuleType:
    global _module
    with _MODULE_LOCK:
        if _module is None:
            spec = importlib.util.spec_from_file_location(
                "eval_temporal_tagger_dates", _TAGGER_SCRIPT
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load temporal tagger helpers from {_TAGGER_SCRIPT}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _module = mod
        return _module


def _line(sp: dict[str, Any], win: str, score: int) -> str:
    return (
        f"- date={sp['text']!r} label={sp['label']} "
        f"field_cues={score} window={win[:220]!r}"
    )


def temporal_lines(pack: ActionPack, tagger, excerpts: str, field: str) -> list[str]:
    if field not in pack.date_fields or tagger is None or not excerpts.strip():
        return []
    mod = _tagger_module()
    cues = pack.temporal_cues.get(field, ())
    lines: list[str] = []
    seen: set[str] = set()
    max_spans = pack.temporal_max_spans
    with _TAGGER_LOCK:
        for i in range(0, min(len(excerpts), pack.temporal_scan_chars), CHUNK_CHARS):
            chunk = excerpts[i : i + CHUNK_CHARS]
            for sp in mod.extract_timex(tagger, chunk):
                key = sp["text"].lower()
                if key in seen or len(key) < 4:
                    continue
                seen.add(key)
                win = mod._window(chunk, sp["start"], sp["end"], radius=140)
                lines.append(_line(sp, win, cue_score(win, cues)))
                if len(lines) >= max_spans:
                    return lines
    return lines


def precompute_temporal(
    pack: ActionPack, tagger, excerpts: str, fields: tuple[str, ...]
) -> dict[str, list[str]]:
    """Run the tagger once per event; score cues only for ``pack.date_fields`` ∩ fields.

    Scans the first ``pack.temporal_scan_chars`` chars of ``excerpts`` (in 1,800-char
    chunks) and keeps at most ``pack.temporal_max_spans`` lines per field.
    """
    out: dict[str, list[str]] = {}
    date_fields = tuple(f for f in fields if pack.uses_temporal(f))
    if tagger is None or not excerpts.strip() or not date_fields:
        return out
    mod = _tagger_module()
    raw_spans: list[dict[str, Any]] = []
    with _TAGGER_LOCK:
        for i in range(0, min(len(excerpts), pack.temporal_scan_chars), CHUNK_CHARS):
            chunk = excerpts[i : i + CHUNK_CHARS]
            for sp in mod.extract_timex(tagger, chunk):
                raw_spans.append({**sp, "_chunk": chunk})
    for field in date_fields:
        cues = pack.temporal_cues.get(field, ())
        lines: list[str] = []
        seen: set[str] = set()
        for sp in raw_spans:
            key = str(sp["text"]).lower()
            if key in seen or len(key) < 4:
                continue
            seen.add(key)
            win = mod._window(sp["_chunk"], sp["start"], sp["end"], radius=140)
            lines.append(_line(sp, win, cue_score(win, cues)))
            if len(lines) >= pack.temporal_max_spans:
                break
        out[field] = lines
    return out


def default_temporal_for(pack: ActionPack, tagger) -> TemporalFor:
    """``temporal_for`` without disk caching; returns {} when ``tagger`` is None."""

    def temporal_for(_key: str, excerpts: str, fields: tuple[str, ...]) -> dict[str, list[str]]:
        if tagger is None:
            return {}
        return precompute_temporal(pack, tagger, excerpts, fields)

    return temporal_for
