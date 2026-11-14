"""Test doubles for the extract graph: scripted LLM backend + dict-backed provider."""

from __future__ import annotations

import ast
import json
import re
import threading
import zlib
from typing import Callable

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.dtos import EvidenceBundle, FieldExtractRequest
from src.evaluation.extract.providers import (
    EventContext,
    build_bundle,
    context_n_rules,
    context_rules_direct,
)

Reply = str | BaseException
ReplyFn = Callable[[str, str, str], Reply]


class FakeBackend:
    """Replies scripted by call order (``replies``) or computed by ``fn(system, user, model)``.

    Records every call as ``{"system", "user", "model"}``. Thread-safe.
    """

    def __init__(self, replies: list[Reply] | None = None, *, fn: ReplyFn | None = None) -> None:
        self._replies = list(replies or [])
        self._fn = fn
        self._lock = threading.Lock()
        self.calls: list[dict[str, str]] = []

    @property
    def prompts(self) -> list[str]:
        return [c["user"] for c in self.calls]

    def chat_json(self, *, system: str, user: str, model: str) -> str:
        with self._lock:
            self.calls.append({"system": system, "user": user, "model": model})
            idx = len(self.calls) - 1
        if self._fn is not None:
            reply = self._fn(system, user, model)
        elif idx < len(self._replies):
            reply = self._replies[idx]
        else:
            raise AssertionError(f"unexpected LLM call #{idx + 1}")
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeProvider:
    """EvidenceProvider over in-memory EventContexts keyed by accession.

    Records each ``bundle`` request as ``(field, sources)``.
    """

    def __init__(self, contexts: dict[str, EventContext] | None = None) -> None:
        self.contexts = dict(contexts or {})
        self._lock = threading.Lock()
        self.bundle_calls: list[tuple[str, tuple[str, ...]]] = []

    def context(self, req: FieldExtractRequest) -> EventContext:
        return self.contexts[req.accession]

    def bundle(
        self, ctx: EventContext, field: str, sources: tuple[str, ...], pack: ActionPack
    ) -> EvidenceBundle:
        with self._lock:
            self.bundle_calls.append((field, tuple(sources)))
        return build_bundle(pack, ctx, field, sources)

    def rules_direct(self, ctx: EventContext, field: str, pack: ActionPack) -> list[str]:
        return context_rules_direct(pack, ctx, field)

    def n_rules(self, ctx: EventContext, field: str, pack: ActionPack) -> int:
        return context_n_rules(pack, ctx, field)


_FIELD_RE = re.compile(r"Extract `?(\w+)`?")
_VALUE_RE = re.compile(r"""(?:value|date)=('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")


class EchoFirstBackend:
    """Deterministic backend: only control flow differs between implementations.

    Select prompts get ``{"<field>": <first value=/date= literal in the evidence>}`` (or
    the first line of an ``EXCERPT:`` block for clause prompts, or null). Validate
    prompts get ``{"keep": true}``.

    ``mode="noisy"`` additionally (as pure functions of the prompt text, so two
    instances agree) nulls ~1/4 of select replies and drops ~1/3 of validated values,
    to exercise the A->B cascade and the C_drop path.
    """

    def __init__(self, mode: str = "plain") -> None:
        assert mode in ("plain", "noisy")
        self.mode = mode
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, *, system: str, user: str, model: str) -> str:
        self.calls.append((system, user))
        if user.startswith("Validate a candidate"):
            keep = not (self.mode == "noisy" and zlib.crc32(b"k" + user.encode()) % 3 == 0)
            return json.dumps({"keep": keep})
        m = _FIELD_RE.match(user)
        field = m.group(1) if m else "value"
        if self.mode == "noisy" and zlib.crc32(b"n" + user.encode()) % 4 == 0:
            return json.dumps({field: None})
        if "EXCERPT:\n" in user:
            body = user.split("EXCERPT:\n", 1)[1].strip()
            return json.dumps({field: body.splitlines()[0][:120] if body else None})
        v = _VALUE_RE.search(user)
        return json.dumps({field: ast.literal_eval(v.group(1)) if v else None})
