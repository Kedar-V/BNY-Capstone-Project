"""LangGraph state for one per-field extraction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.evaluation.extract.dtos import EvidenceBundle, FieldExtractRequest, FieldExtractResult
from src.evaluation.extract.policies import FieldPolicy, Stage
from src.evaluation.extract.providers import EventContext

Route = Literal["", "prompt", "advance", "retrieve", "normalize"]


class ExtractState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: FieldExtractRequest
    policy: FieldPolicy | None = None
    ctx: EventContext | None = None
    n_rules: int = 0
    stage_idx: int = 0
    bundle: EvidenceBundle | None = None
    prompt: str = ""
    pred: str | None = None
    # direct hits are normalized when taken (so raw_log shows the normalized value)
    pred_normalized: bool = False
    pred_stage: int | None = None
    pass_used: str = "none"
    raw_log: list[str] = Field(default_factory=list)
    evidence_final: str = ""
    # user prompt of the last extract LLM call, and of the call that produced pred
    # (None when pred did not come from an LLM call)
    last_prompt: str = ""
    pred_prompt: str | None = None
    validate_verdict: bool | None = None
    next: Route = ""
    result: FieldExtractResult | None = None

    def stage(self) -> Stage:
        assert self.policy is not None
        return self.policy.stages[self.stage_idx]
