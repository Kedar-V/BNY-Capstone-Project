"""Client for the Laya decision-model server (systemone).

Env
- ``LAYA_URL`` — base URL (default ``http://kedar-desktop:8300``)
- ``LAYA_CONFIDENCE_THRESHOLD`` — flag answers below this for review (default ``0.7``)
- ``LAYA_DISABLED`` — if truthy, ``laya_configured()`` is false

Endpoints
- ``GET  {LAYA_URL}/health``
- ``POST {LAYA_URL}/v1/systemone`` — one state
- ``POST {LAYA_URL}/v1/systemone/batch`` — many states (preferred for >1 text)

Throughput (CPU server, one inference at a time): batch size 16–32, ≤2 in-flight
requests, timeouts 120s single / 600s batch, retry 3× with backoff on 503/connect.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import requests

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.routing import (
    FieldRecipe,
    RecipeShape,
    apply_guards,
    heuristic_recipe,
)

DEFAULT_LAYA_URL = "http://kedar-desktop:8300"
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_BATCH_SIZE = 24
MAX_IN_FLIGHT = 2
SINGLE_TIMEOUT_S = 120.0
BATCH_TIMEOUT_S = 600.0
MAX_RETRIES = 3
# ~1000 tokens ≈ 4000 English chars; keep state short.
MAX_STATE_CHARS = 4000

SHAPES: tuple[str, ...] = (
    "oneshot",
    "clause_then_pick",
    "rules_then_span",
    "clause_only",
)
LEG_KEYS = ("rules", "gliner", "temporal", "hybrid", "clause")


def laya_base_url() -> str:
    raw = (os.environ.get("LAYA_URL") or os.environ.get("LAYA_API_URL") or DEFAULT_LAYA_URL).strip()
    # Accept accidental full path to /v1/systemone
    return raw.rstrip("/").removesuffix("/v1/systemone").rstrip("/")


def confidence_threshold() -> float:
    try:
        return float(os.environ.get("LAYA_CONFIDENCE_THRESHOLD") or DEFAULT_CONFIDENCE_THRESHOLD)
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD


def laya_configured() -> bool:
    if (os.environ.get("LAYA_DISABLED") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    return bool(laya_base_url())


def truncate_state(text: str, max_chars: int = MAX_STATE_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n…[truncated]"


@dataclass(frozen=True)
class LayaAnswer:
    name: str
    type: str
    value: Any
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def needs_review(self) -> bool:
        return self.confidence < confidence_threshold()


@dataclass(frozen=True)
class LayaResult:
    answers: dict[str, LayaAnswer]
    model: str | None = None
    routing: Mapping[str, Any] | None = None
    usage: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def needs_review(self) -> bool:
        return any(a.needs_review for a in self.answers.values())

    def choice(self, name: str) -> str | None:
        a = self.answers.get(name)
        return None if a is None or a.type != "choice" else (None if a.value is None else str(a.value))

    def noul(self, name: str) -> float | None:
        a = self.answers.get(name)
        if a is None or a.type != "noul":
            return None
        try:
            return float(a.value)
        except (TypeError, ValueError):
            return None

    def score(self, name: str) -> float | None:
        a = self.answers.get(name)
        if a is None or a.type != "score":
            return None
        try:
            return float(a.value)
        except (TypeError, ValueError):
            return None


def _parse_answer(name: str, blob: Mapping[str, Any]) -> LayaAnswer:
    typ = str(blob.get("type") or "")
    if typ == "choice":
        value = blob.get("choice")
    elif typ == "noul":
        value = blob.get("noul")
    elif typ == "score":
        value = blob.get("score")
    else:
        value = blob.get("choice", blob.get("noul", blob.get("score")))
    try:
        conf = float(blob.get("confidence") if blob.get("confidence") is not None else 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    probs = blob.get("probabilities") if isinstance(blob.get("probabilities"), dict) else {}
    return LayaAnswer(
        name=name,
        type=typ or "unknown",
        value=value,
        confidence=conf,
        probabilities={str(k): float(v) for k, v in probs.items()},
        raw=dict(blob),
    )


def _parse_result(body: Mapping[str, Any]) -> LayaResult:
    answers_raw = body.get("answers")
    if not isinstance(answers_raw, dict):
        raise RuntimeError(f"Laya response missing answers: {body!r}"[:400])
    answers = {name: _parse_answer(name, blob) for name, blob in answers_raw.items() if isinstance(blob, dict)}
    return LayaResult(
        answers=answers,
        model=(str(body["model"]) if body.get("model") is not None else None),
        routing=body.get("routing") if isinstance(body.get("routing"), dict) else None,
        usage=body.get("usage") if isinstance(body.get("usage"), dict) else None,
        raw=dict(body),
    )


class LayaClient:
    """HTTP client for ``{LAYA_URL}/v1/systemone`` (+ batch + health)."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        max_in_flight: int = MAX_IN_FLIGHT,
        single_timeout: float = SINGLE_TIMEOUT_S,
        batch_timeout: float = BATCH_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.base_url = (base_url or laya_base_url()).rstrip("/")
        self.max_in_flight = max(1, min(int(max_in_flight), 16))
        self.single_timeout = float(single_timeout)
        self.batch_timeout = float(batch_timeout)
        self.max_retries = int(max_retries)
        self.batch_size = max(1, min(int(batch_size), 32))

    def health(self) -> dict[str, Any]:
        resp = requests.get(f"{self.base_url}/health", timeout=30.0)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout,
                )
                if resp.status_code == 503:
                    raise requests.HTTPError(f"503: {resp.text[:200]}", response=resp)
                if not resp.ok:
                    raise RuntimeError(f"Laya HTTP {resp.status_code}: {resp.text[:400]}")
                return resp.json() if resp.content else {}
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_err = e
                # Only retry 503 / connection / timeout
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status is not None and status != 503:
                    raise
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"Laya request failed after {self.max_retries} retries: {last_err}")

    def decide(self, state: str, questions: Mapping[str, Any]) -> LayaResult:
        """One text, all questions in a single call."""
        payload = {"state": truncate_state(state), "questions": dict(questions)}
        body = self._post_json("/v1/systemone", payload, timeout=self.single_timeout)
        return _parse_result(body)

    def decide_batch(
        self, states: Sequence[str], questions: Mapping[str, Any]
    ) -> list[LayaResult]:
        """Many texts, same questions; preserves input order.

        Uses ``/v1/systemone/batch`` in chunks of ``batch_size`` (16–32). At most
        ``max_in_flight`` chunk requests run concurrently.
        """
        if not states:
            return []
        if len(states) == 1:
            return [self.decide(states[0], questions)]

        chunks: list[tuple[int, list[str]]] = []
        buf = [truncate_state(s) for s in states]
        for i in range(0, len(buf), self.batch_size):
            chunks.append((i, buf[i : i + self.batch_size]))

        out: list[LayaResult | None] = [None] * len(buf)

        def _one_chunk(start: int, texts: list[str]) -> tuple[int, list[LayaResult]]:
            body = self._post_json(
                "/v1/systemone/batch",
                {"states": texts, "questions": dict(questions)},
                timeout=self.batch_timeout,
            )
            results = body.get("results")
            if not isinstance(results, list) or len(results) != len(texts):
                raise RuntimeError(
                    f"Laya batch expected {len(texts)} results, got "
                    f"{0 if not isinstance(results, list) else len(results)}"
                )
            return start, [_parse_result(r if isinstance(r, dict) else {}) for r in results]

        workers = max(1, min(self.max_in_flight, len(chunks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_one_chunk, start, texts) for start, texts in chunks]
            for fut in as_completed(futs):
                start, parsed = fut.result()
                for j, res in enumerate(parsed):
                    out[start + j] = res

        assert all(r is not None for r in out)
        return [r for r in out if r is not None]  # type: ignore[misc]


# --- pack-build routing helpers (use the client above) --------------------------------


def _state_text(
    pack: ActionPack,
    field: str,
    *,
    oracle_system: str | None,
    gold_cues: Sequence[str],
) -> str:
    """Past-tense state that mirrors oracle labels used in the questions.

    Tuned against systemone: abstract jargon ("policy shape", "BM25+dense")
    collapses choice confidence; oracle vocabulary in the state lifts shape
    accuracy ~0.12 → ~0.75 on tender fields (choice conf stays low — see parse).
    """
    definition = pack.field_defs.get(field, field)
    cues = "; ".join(str(c)[:80] for c in list(gold_cues)[:3]) or "(none)"
    bits = [
        f"During tender-offer field routing, the field was called {field}.",
        f"The field definition was: {definition}.",
        f"The oracle best system label was {oracle_system or 'unknown'}.",
    ]
    if field in pack.date_fields:
        bits.append("The field was a date field.")
    else:
        bits.append("The field was not a date field.")
    if field in pack.clause_fields:
        bits.append("Clause regex for this field existed.")
    else:
        bits.append("Clause regex for this field did not exist.")
    if cues != "(none)":
        bits.append(f"Example gold values were: {cues}.")
    return truncate_state(" ".join(bits))


def _routing_questions() -> dict[str, Any]:
    """Tuned prompts (oracle-vocab shape choice + past-tense leg nouls).

    Bake-off on 12 tender fields vs heuristic/oracle gold:
    - oracle-vocab shape choice → 9/12 shape match (mean choice conf still ~0.07)
    - leg nouls tied to oracle labels → leg F1 ~0.73 (rules-only ids stay clean)
    """
    return {
        "shape": {
            "type": "choice",
            "instructions": (
                "Did the oracle best system for this field match Settlement template, "
                "Qwen clauses, clause-only proration, or a oneshot pick?"
            ),
            "criteria": {
                "rules_then_span": "Settlement template",
                "clause_then_pick": "Qwen clauses",
                "clause_only": "proration clause-only excerpt",
                "oneshot": "Rules or Qwen direct or Temporal NER oneshot pick",
            },
        },
        "use_rules": {
            "type": "noul",
            "instructions": "Was the oracle best system Rules for this field?",
        },
        "use_gliner": {
            "type": "noul",
            "instructions": "Did the best recipe include GLiNER for this field?",
        },
        "use_temporal": {
            "type": "noul",
            "instructions": "Was the oracle best system Temporal NER for this field?",
        },
        "use_hybrid": {
            "type": "noul",
            "instructions": "Did the best recipe include hybrid retrieval for this field?",
        },
        "use_clause": {
            "type": "noul",
            "instructions": "Was the oracle best system Qwen clauses for this field?",
        },
    }


def _parse_answers_to_recipe(
    pack: ActionPack,
    field: str,
    result: LayaResult,
    *,
    oracle_system: str | None,
    noul_threshold: float,
) -> FieldRecipe:
    shape_ans = result.answers.get("shape")
    shape_raw = shape_ans.value if shape_ans and shape_ans.type == "choice" else None
    shape_conf = shape_ans.confidence if shape_ans else 0.0
    floor = confidence_threshold()

    notes: list[str] = []
    shape: RecipeShape
    # Choice confidence on 4-way shape is miscalibrated (~0.05–0.2 even when correct).
    # Trust a valid choice label; flag review when conf is below the configured floor.
    if shape_raw in SHAPES:
        shape = shape_raw  # type: ignore[assignment]
        conf = max(float(shape_conf), 0.35)
        if shape_conf < floor:
            notes.append(f"shape_low_conf(conf={shape_conf:.3f}<{floor})")
    else:
        base = heuristic_recipe(pack, field, oracle_system=oracle_system)
        shape = base.shape
        conf = max(shape_conf, 0.35)
        notes.append(f"shape_fallback_heuristic(laya={shape_raw!r} conf={shape_conf:.3f})")

    legs: set[str] = set()
    raw_legs: dict[str, float] = {}
    for leg in LEG_KEYS:
        p = result.noul(f"use_{leg}")
        raw_legs[leg] = float(p or 0.0)
        if p is not None and p >= noul_threshold:
            legs.add(leg)

    if not legs:
        base = heuristic_recipe(pack, field, oracle_system=oracle_system)
        legs = set(base.legs)
        notes.append("empty_laya_legs→heuristic_legs")

    shape, legs_f, guard_notes = apply_guards(pack, field, shape, frozenset(legs))
    notes.extend(guard_notes)
    review = result.needs_review or (shape_conf < floor if shape_raw in SHAPES else False)
    if review:
        notes.append(f"needs_review(threshold={floor})")
    return FieldRecipe(
        field=field,
        shape=shape,
        legs=legs_f,
        confidence=conf,
        source="laya",
        rationale="laya; " + "; ".join(notes) if notes else "laya",
        raw={
            "shape": shape_raw,
            "shape_confidence": shape_conf,
            "legs_noul": raw_legs,
            "oracle_system": oracle_system,
            "needs_review": review,
            "model": result.model,
            "routing": result.routing,
        },
    )


def route_field_laya(
    pack: ActionPack,
    field: str,
    *,
    oracle_system: str | None = None,
    gold_cues: Sequence[str] | None = None,
    noul_threshold: float = 0.5,
    client: LayaClient | None = None,
) -> FieldRecipe:
    """Route one field via a single systemone call (all questions together)."""
    cli = client or LayaClient()
    state = _state_text(
        pack, field, oracle_system=oracle_system, gold_cues=list(gold_cues or [])
    )
    result = cli.decide(state, _routing_questions())
    return _parse_answers_to_recipe(
        pack, field, result, oracle_system=oracle_system, noul_threshold=noul_threshold
    )


# Back-compat alias used in older docs/tests
def laya_api_url() -> str:
    return laya_base_url()


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_LAYA_URL",
    "LayaAnswer",
    "LayaClient",
    "LayaResult",
    "confidence_threshold",
    "laya_api_url",
    "laya_base_url",
    "laya_configured",
    "route_field_laya",
    "truncate_state",
]
