"""validate (Pass C) and finish (build the result DTO)."""

from __future__ import annotations

from typing import Any

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.dtos import FieldExtractResult
from src.evaluation.extract.prompts import parse_keep, validate_prompt
from src.evaluation.extract.state import ExtractState

VALIDATE_SYSTEM = "Return JSON only. Be conservative: drop unsupported values."


def should_validate(state: ExtractState) -> bool:
    if not state.request.validate_enabled or state.pred is None or state.pred_stage is None:
        return False
    assert state.policy is not None
    return state.policy.stages[state.pred_stage].validate


def make_validate(pack: ActionPack, backend):
    def validate(state: ExtractState) -> dict[str, Any]:
        assert state.pred is not None
        user = validate_prompt(pack, state.request.field, state.pred, state.evidence_final)
        raw = backend.chat_json(system=VALIDATE_SYSTEM, user=user, model=state.request.model)
        keep = parse_keep(raw)
        upd: dict[str, Any] = {
            "raw_log": [*state.raw_log, f"C:{raw[:200]}"],
            "validate_verdict": keep,
        }
        if keep is False:
            upd.update(pred=None, pass_used=f"{state.pass_used}+C_drop")
        elif keep is True:
            upd["pass_used"] = f"{state.pass_used}+C_keep"
        return upd

    return validate


def make_finish():
    def finish(state: ExtractState) -> dict[str, Any]:
        return {
            "result": FieldExtractResult(
                pred=state.pred,
                pass_used=state.pass_used,
                n_evidence_chars=len(state.evidence_final),
                n_rules=state.n_rules,
                raw_llm=" | ".join(state.raw_log)[:500],
                validate_verdict=state.validate_verdict,
                evidence=state.evidence_final,
                prompt=state.pred_prompt if state.pred_prompt is not None else state.last_prompt,
            )
        }

    return finish
