"""Frozen Pydantic DTOs for the per-field extract graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class FieldExtractRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    pack_name: str
    field: str
    event_id: str | None
    accession: str
    model: str
    validate_enabled: bool
    cascade: bool

    @field_validator("field")
    @classmethod
    def _field_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    source: Literal["clause", "rules", "gliner", "temporal", "mixed"]
    n_chars: int
    empty: bool


class FieldExtractResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    pred: str | None
    pass_used: str
    n_evidence_chars: int
    n_rules: int
    raw_llm: str
    validate_verdict: bool | None = None
