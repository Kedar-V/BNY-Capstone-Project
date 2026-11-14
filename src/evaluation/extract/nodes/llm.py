"""llm: call the backend with the stage prompt and parse the field value."""

from __future__ import annotations

from typing import Any

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.prompts import parse_field
from src.evaluation.extract.state import ExtractState


def make_llm(pack: ActionPack, backend):
    def llm(state: ExtractState) -> dict[str, Any]:
        stage = state.stage()
        field = state.request.field
        raw = backend.chat_json(system=pack.system_prompt, user=state.prompt, model=state.request.model)
        value = parse_field(raw, field)
        raw_log = [*state.raw_log, f"{stage.pass_label}:{raw[:300]}"]
        if value is None and state.pred is not None:
            # stop_at_first_hit=False: a later null never erases an earlier stage's hit
            return {"raw_log": raw_log, "last_prompt": state.prompt, "next": "advance"}
        if value is not None:
            label = stage.pass_label
        else:
            label = stage.null_label if stage.null_label is not None else stage.pass_label
        assert state.bundle is not None
        return {
            "pred": value,
            "pred_normalized": False,
            "pred_stage": state.stage_idx,
            "pass_used": label,
            "raw_log": raw_log,
            "last_prompt": state.prompt,
            "pred_prompt": state.prompt if value is not None else None,
            # Pass C validates against the evidence of the stage that produced pred
            "evidence_final": state.bundle.text,
            "next": "advance",
        }

    return llm
