"""GLiNER over the Orin GLiNER HTTP API (small | medium | large), same interface as GlinerBackend."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from src.preprocess.backends.base import iter_windows

DEFAULT_URL = "http://192.168.0.212:8100"
_SIZE = {"small": "small", "medium": "medium", "large": "large"}


def _size_for(model_id: str) -> str:
    """Map 'urchade/gliner_large-v2.1' (or 'large') to the API's model name."""
    low = (model_id or "").lower()
    for key in ("large", "medium", "small"):
        if key in low:
            return key
    raise ValueError(f"no Orin GLiNER model matches {model_id!r}")


class ApiGlinerBackend:
    """Sliding-window GLiNER served by the Orin API (/extract_batch per segment)."""

    def __init__(
        self,
        model_id: str = "urchade/gliner_large-v2.1",
        *,
        url: str | None = None,
        window_chars: int = 900,
        overlap_chars: int = 150,
        max_windows: int = 8,
        threshold: float = 0.4,
        timeout: float = 120.0,
    ) -> None:
        self.model_id = model_id
        self.size = _size_for(model_id)
        self.url = (url or os.environ.get("GLINER_API_URL") or DEFAULT_URL).rstrip("/")
        self.window_chars = window_chars
        self.overlap_chars = overlap_chars
        self.max_windows = max_windows
        self.threshold = threshold
        self.timeout = timeout
        self._load_error: str | None = None
        self.available = True

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def predict(self, text: str, labels: list[str]) -> list[dict[str, Any]]:
        if not text or not text.strip() or not labels:
            return []
        windows = iter_windows(
            text,
            window_chars=self.window_chars,
            overlap_chars=self.overlap_chars,
            max_windows=self.max_windows,
        )
        body = self._post(
            "/extract_batch",
            {
                "model": self.size,
                "texts": [chunk for chunk, _, _ in windows],
                "labels": list(labels),
                "threshold": self.threshold,
            },
        )
        out: list[dict[str, Any]] = []
        for (chunk, offset, chunk_id), ents in zip(windows, body.get("results") or []):
            for ent in ents or []:
                out.append(
                    {
                        "label": ent.get("label"),
                        "text": ent.get("text"),
                        "score": float(ent.get("score", 0.0)),
                        "start": int(ent.get("start", 0)) + offset,
                        "end": int(ent.get("end", 0)) + offset,
                        "chunk_id": chunk_id,
                    }
                )
        return out
