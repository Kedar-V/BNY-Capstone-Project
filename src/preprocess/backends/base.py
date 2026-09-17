"""SpanBackend implementations with sliding-window prediction."""

from __future__ import annotations

from typing import Any


def iter_windows(
    text: str,
    *,
    window_chars: int = 900,
    overlap_chars: int = 150,
    max_windows: int = 8,
) -> list[tuple[str, int, str]]:
    """Return (chunk_text, start_offset, chunk_id)."""
    text = text or ""
    if not text.strip():
        return []
    if len(text) <= window_chars:
        return [(text, 0, "w0")]

    windows: list[tuple[str, int, str]] = []
    start = 0
    idx = 0
    while start < len(text) and idx < max_windows - 1:
        end = min(start + window_chars, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + window_chars // 2, end)
            if cut > start:
                end = cut
        chunk = text[start:end]
        windows.append((chunk, start, f"w{idx}"))
        idx += 1
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)

    if windows and windows[-1][1] + len(windows[-1][0]) < len(text):
        tail_start = max(len(text) - window_chars, 0)
        if not any(abs(s - tail_start) < 50 for _, s, _ in windows):
            windows.append((text[tail_start:], tail_start, f"w{idx}"))
    return windows[:max_windows]


class FakeSpanBackend:
    """Deterministic backend for tests."""

    def __init__(self, spans_by_substr: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.model_id = "fake"
        self.spans_by_substr = spans_by_substr or {}

    def predict(self, text: str, labels: list[str]) -> list[dict[str, Any]]:
        label_set = set(labels)
        out: list[dict[str, Any]] = []
        for substr, spans in self.spans_by_substr.items():
            if substr not in text:
                continue
            for sp in spans:
                if sp["label"] not in label_set:
                    continue
                raw = sp.get("text", substr)
                start = text.find(raw)
                if start < 0:
                    start = text.find(substr)
                out.append(
                    {
                        "label": sp["label"],
                        "text": raw,
                        "score": float(sp.get("score", 0.9)),
                        "start": max(start, 0),
                        "end": max(start, 0) + len(raw),
                        "chunk_id": "w0",
                    }
                )
        return out


class GlinerBackend:
    """Lazy-loaded GLiNER with sliding-window inference."""

    def __init__(
        self,
        model_id: str = "urchade/gliner_medium-v2.1",
        *,
        window_chars: int = 900,
        overlap_chars: int = 150,
        max_windows: int = 8,
        threshold: float = 0.4,
    ) -> None:
        self.model_id = model_id
        self.window_chars = window_chars
        self.overlap_chars = overlap_chars
        self.max_windows = max_windows
        self.threshold = threshold
        self._model = None
        self._load_error: str | None = None

    def _ensure(self) -> None:
        if self._model is not None or self._load_error:
            return
        try:
            from gliner import GLiNER

            self._model = GLiNER.from_pretrained(self.model_id)
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)

    @property
    def available(self) -> bool:
        self._ensure()
        return self._model is not None

    def predict(self, text: str, labels: list[str]) -> list[dict[str, Any]]:
        self._ensure()
        if self._model is None:
            raise RuntimeError(f"gliner_unavailable: {self._load_error}")
        if not text or not text.strip() or not labels:
            return []

        out: list[dict[str, Any]] = []
        for chunk, offset, chunk_id in iter_windows(
            text,
            window_chars=self.window_chars,
            overlap_chars=self.overlap_chars,
            max_windows=self.max_windows,
        ):
            raw = self._model.predict_entities(chunk, labels, threshold=self.threshold)
            for ent in raw:
                start = int(ent.get("start", 0)) + offset
                end = int(ent.get("end", 0)) + offset
                out.append(
                    {
                        "label": ent.get("label"),
                        "text": ent.get("text"),
                        "score": float(ent.get("score", 0.0)),
                        "start": start,
                        "end": end,
                        "chunk_id": chunk_id,
                    }
                )
        return out
