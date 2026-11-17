"""Hybrid retrieval: BM25 + dense embeddings, fused with RRF (PipesHub-style).

Used as a *supplemental* evidence leg alongside GLiNER — not a fallthrough-only
path. The SLM still sees a short EXCERPT block; scores never go to the model.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import requests

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class HybridHit:
    text: str
    score: float
    rank: int


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def chunk_text(
    text: str,
    *,
    chunk_chars: int = 900,
    overlap: int = 120,
) -> list[str]:
    """Split filing text into overlapping windows for retrieval."""
    blob = _WS.sub(" ", (text or "").strip())
    if not blob:
        return []
    if len(blob) <= chunk_chars:
        return [blob]
    step = max(1, chunk_chars - overlap)
    out: list[str] = []
    i = 0
    while i < len(blob):
        piece = blob[i : i + chunk_chars].strip()
        if len(piece) >= 40:
            out.append(piece)
        if i + chunk_chars >= len(blob):
            break
        i += step
    return out


def bm25_rank(
    query: str,
    chunks: Sequence[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[int, float]]:
    """Okapi BM25 ranks as (chunk_index, score), best first."""
    if not chunks:
        return []
    q_toks = _tokenize(query)
    if not q_toks:
        return []
    docs = [_tokenize(c) for c in chunks]
    N = len(docs)
    dl = [len(d) or 1 for d in docs]
    avgdl = sum(dl) / N
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    scores = [0.0] * N
    for t in q_toks:
        n_t = df.get(t, 0)
        if n_t == 0:
            continue
        idf = math.log(1.0 + (N - n_t + 0.5) / (n_t + 0.5))
        for i, d in enumerate(docs):
            tf = d.count(t)
            if tf == 0:
                continue
            denom = tf + k1 * (1.0 - b + b * dl[i] / avgdl)
            scores[i] += idf * (tf * (k1 + 1.0) / denom)
    ranked = sorted(enumerate(scores), key=lambda kv: (-kv[1], kv[0]))
    return [(i, s) for i, s in ranked if s > 0]


def rrf(
    legs: Sequence[Sequence[int]],
    *,
    limit: int,
    k: int = 60,
) -> list[tuple[int, float]]:
    """Reciprocal rank fusion over ranked chunk-index lists (PipesHub k=60)."""
    scores: dict[int, float] = {}
    for leg in legs:
        for rank, idx in enumerate(leg):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def embedding_config() -> tuple[str, str]:
    base = (
        os.environ.get("EMBEDDING_BASE_URL")
        or os.environ.get("EMBEDDINGS_BASE_URL")
        or "http://kedar-desktop:8200/v1"
    ).rstrip("/")
    model = os.environ.get("EMBEDDING_MODEL") or "bge-large-en-v1.5"
    return base, model


# After one embed failure, skip dense for the rest of the process (BM25 still runs).
_dense_disabled: bool = False


def dense_available() -> bool:
    return not _dense_disabled


def reset_dense_circuit() -> None:
    """Test helper: re-enable dense after a simulated failure."""
    global _dense_disabled
    _dense_disabled = False


# ~512 BGE tokens ≈ 4 chars/token for English SEC text; keep inputs under the model window.
_MAX_EMBED_CHARS = 2000


def _truncate_for_embed(text: str, max_chars: int = _MAX_EMBED_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars]


def embed_texts(
    texts: Sequence[str],
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    batch_size: int = 32,
    concurrency: int = 4,
) -> list[list[float]]:
    """OpenAI-compatible /embeddings (e.g. bge-large-en-v1.5 on :8200).

    Batches of ``batch_size`` (default 32); up to ``concurrency`` (default 4)
    HTTP requests in flight. Each text is truncated to stay under ~512 tokens.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    global _dense_disabled
    if not texts:
        return []
    if _dense_disabled:
        raise RuntimeError("dense embeddings disabled after prior failure")
    base, default_model = embedding_config()
    url = (base_url or base).rstrip("/") + "/embeddings"
    model_name = model or default_model
    trimmed = [_truncate_for_embed(t) for t in texts]
    batches = [trimmed[i : i + batch_size] for i in range(0, len(trimmed), batch_size)]
    results: list[list[list[float]] | None] = [None] * len(batches)

    def _one(batch: list[str]) -> list[list[float]]:
        resp = requests.post(
            url,
            json={"model": model_name, "input": batch},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        by_idx = {int(item["index"]): item["embedding"] for item in data}
        return [list(by_idx[j]) for j in range(len(batch))]

    try:
        workers = max(1, min(int(concurrency), len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_one, b): i for i, b in enumerate(batches)}
            for fut in as_completed(futs):
                i = futs[fut]
                results[i] = fut.result()
    except Exception:
        _dense_disabled = True
        raise
    out: list[list[float]] = []
    for part in results:
        assert part is not None
        out.extend(part)
    return out


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return mat / norms


def dense_rank(
    query: str,
    chunks: Sequence[str],
    *,
    chunk_vectors: np.ndarray | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[list[tuple[int, float]], np.ndarray]:
    """Cosine rank; returns ((idx, score)…, chunk_vectors) for reuse."""
    if not chunks:
        return [], np.zeros((0, 0), dtype=np.float32)
    if chunk_vectors is None or chunk_vectors.shape[0] != len(chunks):
        emb = embed_texts(list(chunks), base_url=base_url, model=model)
        chunk_vectors = _l2_normalize(np.asarray(emb, dtype=np.float32))
    q = embed_texts([query], base_url=base_url, model=model)
    qv = _l2_normalize(np.asarray(q, dtype=np.float32))[0]
    sims = chunk_vectors @ qv
    ranked = sorted(enumerate(sims.tolist()), key=lambda kv: (-kv[1], kv[0]))
    return ranked, chunk_vectors


def field_query(pack_field_def: str, field: str, *, extra: str = "") -> str:
    """Build a retrieval query from the pack field definition (+ optional cues)."""
    parts = [field.replace("_", " "), (pack_field_def or "").strip(), (extra or "").strip()]
    return " ".join(p for p in parts if p)


def hybrid_retrieve(
    query: str,
    doc_text: str,
    *,
    top_k: int = 4,
    max_chars: int = 2200,
    chunk_chars: int = 900,
    overlap: int = 120,
    chunk_vectors: np.ndarray | None = None,
    use_dense: bool = True,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, np.ndarray | None]:
    """Return formatted HYBRID EXCERPTS block and cached chunk vectors.

    Dense failures fall back to BM25-only so evidence still supplements GLiNER.
    """
    chunks = chunk_text(doc_text, chunk_chars=chunk_chars, overlap=overlap)
    if not chunks or not (query or "").strip():
        return "", chunk_vectors

    sparse = bm25_rank(query, chunks)
    sparse_ids = [i for i, _ in sparse]

    dense_ids: list[int] = []
    vectors = chunk_vectors
    if use_dense:
        try:
            dense, vectors = dense_rank(
                query, chunks, chunk_vectors=chunk_vectors, base_url=base_url, model=model
            )
            dense_ids = [i for i, _ in dense]
        except Exception:
            dense_ids = []
            vectors = chunk_vectors

    legs = [leg for leg in (sparse_ids, dense_ids) if leg]
    if not legs:
        return "", vectors

    fused = rrf(legs, limit=max(top_k * 2, top_k))
    parts: list[str] = []
    n = 0
    for rank, (idx, score) in enumerate(fused):
        if rank >= top_k:
            break
        hit = chunks[idx].strip()
        if not hit:
            continue
        if n + len(hit) > max_chars:
            remain = max_chars - n
            if remain < 80:
                break
            hit = hit[:remain]
        parts.append(hit)
        n += len(hit)
        if n >= max_chars:
            break
    if not parts:
        return "", vectors
    block = "HYBRID EXCERPTS:\n" + "\n---\n".join(parts)
    return block, vectors


__all__ = [
    "HybridHit",
    "bm25_rank",
    "chunk_text",
    "dense_available",
    "dense_rank",
    "embed_texts",
    "embedding_config",
    "field_query",
    "hybrid_retrieve",
    "reset_dense_circuit",
    "rrf",
]
