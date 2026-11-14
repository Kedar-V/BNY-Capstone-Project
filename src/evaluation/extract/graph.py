"""LangGraph wiring for per-field extraction.

init -> retrieve -> [prompt -> llm] -> advance -> (retrieve | normalize) -> [validate] -> finish
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.dtos import FieldExtractRequest, FieldExtractResult
from src.evaluation.extract.nodes import (
    make_advance,
    make_finish,
    make_init,
    make_llm,
    make_normalize,
    make_prompt,
    make_retrieve,
    make_validate,
)
from src.evaluation.extract.nodes.validate import should_validate
from src.evaluation.extract.providers import EvidenceProvider
from src.evaluation.extract.state import ExtractState

# 4 steps per stage + init/normalize/validate/finish; generous for explicit policies
RECURSION_LIMIT = 200


def _route(state: ExtractState) -> str:
    return state.next


def _after_normalize(state: ExtractState) -> str:
    return "validate" if should_validate(state) else "finish"


def build_extract_graph(pack: ActionPack, backend, provider: EvidenceProvider):
    """Compile once per (pack, backend, provider); safe to invoke from many threads."""
    g = StateGraph(ExtractState)
    g.add_node("init", make_init(pack, provider))
    g.add_node("retrieve", make_retrieve(pack, provider))
    g.add_node("prompt", make_prompt(pack))
    g.add_node("llm", make_llm(pack, backend))
    g.add_node("advance", make_advance())
    g.add_node("normalize", make_normalize(pack))
    g.add_node("validate", make_validate(pack, backend))
    g.add_node("finish", make_finish())

    g.add_edge(START, "init")
    g.add_conditional_edges("init", _route, ["retrieve", "normalize"])
    g.add_conditional_edges("retrieve", _route, ["prompt", "advance", "normalize"])
    g.add_edge("prompt", "llm")
    g.add_edge("llm", "advance")
    g.add_conditional_edges("advance", _route, ["retrieve", "normalize"])
    g.add_conditional_edges("normalize", _after_normalize, ["validate", "finish"])
    g.add_edge("validate", "finish")
    g.add_edge("finish", END)
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})


def run_field(graph, req: FieldExtractRequest) -> FieldExtractResult:
    """Invoke the graph for one field; any exception becomes a ``pass_used="error"`` result."""
    try:
        out: Any = graph.invoke({"request": req})
        result = out["result"] if isinstance(out, dict) else out.result
        if result is None:
            raise RuntimeError("extract graph finished without a result")
        return result
    except Exception as e:  # noqa: BLE001
        return FieldExtractResult(
            pred=None, pass_used="error", n_evidence_chars=0, n_rules=0, raw_llm=str(e)[:400]
        )
