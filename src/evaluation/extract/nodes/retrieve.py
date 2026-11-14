"""retrieve: build the current stage's evidence bundle; apply on_empty and direct hits."""

from __future__ import annotations

from typing import Any

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.providers import EvidenceProvider
from src.evaluation.extract.state import ExtractState


def _direct_values(pack: ActionPack, provider: EvidenceProvider, state: ExtractState) -> list[str]:
    stage = state.stage()
    field = state.request.field
    assert state.ctx is not None
    if "prior" in stage.sources:
        hooks = pack.hooks
        if hooks is None or hooks.direct_prior is None:
            return []
        v = hooks.direct_prior(field, state.ctx.extras)
        return [v] if v is not None else []
    return provider.rules_direct(state.ctx, field, pack)


def make_retrieve(pack: ActionPack, provider: EvidenceProvider):
    def retrieve(state: ExtractState) -> dict[str, Any]:
        stage = state.stage()
        field = state.request.field
        assert state.ctx is not None
        bundle = provider.bundle(state.ctx, field, stage.sources, pack)
        # Once a stage has produced pred (only possible with stop_at_first_hit=False),
        # evidence_final stays that stage's evidence; llm / direct hits set it on a new hit.
        upd: dict[str, Any] = {"bundle": bundle}
        if state.pred is None:
            upd["evidence_final"] = "" if bundle.empty and stage.on_empty == "null" else bundle.text
        if bundle.empty:
            if stage.on_empty == "null":
                # Ends the whole policy, even when later stages remain
                upd["next"] = "normalize"
                if state.pass_used == "none":
                    upd["pass_used"] = stage.empty_label
                return upd
            if stage.on_empty == "skip":
                upd["next"] = "advance"
                return upd
            # "ask": the LLM still gets the (empty) evidence pack
        upd["next"] = "prompt"
        if stage.direct_from_rules and not bundle.empty:
            values = _direct_values(pack, provider, state)
            if values:
                pred = pack.normalize(field, values[0])
                upd.update(
                    pred=pred,
                    pred_normalized=True,
                    pred_stage=state.stage_idx,
                    evidence_final=bundle.text,
                    pass_used=stage.direct_label,
                    raw_log=[*state.raw_log, f"{stage.direct_label}:{pred!r}"],
                    next="advance",
                )
        return upd

    return retrieve
