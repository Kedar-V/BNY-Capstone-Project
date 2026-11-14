"""init / advance / normalize: policy resolution, stage stepping, pack.normalize."""

from __future__ import annotations

from typing import Any

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.policies import resolve_policy
from src.evaluation.extract.providers import EvidenceProvider
from src.evaluation.extract.state import ExtractState


def make_init(pack: ActionPack, provider: EvidenceProvider):
    def init(state: ExtractState) -> dict[str, Any]:
        req = state.request
        if req.pack_name != pack.name:
            raise ValueError(f"request pack {req.pack_name!r} != graph pack {pack.name!r}")
        policy = resolve_policy(pack, req.field, cascade=req.cascade)
        ctx = provider.context(req)
        return {
            "policy": policy,
            "ctx": ctx,
            "n_rules": provider.n_rules(ctx, req.field, pack),
            "stage_idx": 0,
            "next": "retrieve" if policy.stages else "normalize",
        }

    return init


def make_advance():
    def advance(state: ExtractState) -> dict[str, Any]:
        assert state.policy is not None
        if state.pred is not None and state.policy.stop_at_first_hit:
            return {"next": "normalize"}
        if state.stage_idx + 1 < len(state.policy.stages):
            return {"stage_idx": state.stage_idx + 1, "next": "retrieve"}
        upd: dict[str, Any] = {"next": "normalize"}
        if state.pass_used == "none":
            upd["pass_used"] = state.stage().empty_label
        return upd

    return advance


def make_normalize(pack: ActionPack):
    def normalize(state: ExtractState) -> dict[str, Any]:
        if state.pred is None or state.pred_normalized:
            return {}
        return {"pred": pack.normalize(state.request.field, state.pred), "pred_normalized": True}

    return normalize
