"""ActionPack: swappable schema + instructions for the unified harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from src.evaluation.extract.policies import FieldPolicy


NormalizeFn = Callable[[str, str], str]


def _default_normalize(field_name: str, value: str) -> str:
    v = value.replace("\xa0", " ").replace("\n", " ")
    v = " ".join(v.split())
    if field_name == "proration_terms":
        v = v.replace(",", "")
    return v[:400]


@dataclass(frozen=True)
class ClauseFieldSpec:
    """Pack-tunable clause retrieval + extract prompt for one schema field.

    This is the main knob for long-form fields (proration, min tender, …):
    passage quotes → regex hits (~max_chars), then a field-specific prompt.
    """

    quote_field: str
    patterns: tuple[str, ...]
    extract_prompt: str
    max_chars: int = 2200
    use_passage_quotes: bool = True
    # If set, passage quotes must match before they are accepted as primary
    quote_accept_re: str | None = None


@dataclass(frozen=True)
class PackHooks:
    """Optional pack-specific evidence logic. ``extras`` is EventContext.extras."""

    junk_roles: frozenset[str] = frozenset()
    # (field, raw span text, extras) -> True to drop the span
    drop_span: Callable[[str, str, Mapping[str, str]], bool] | None = field(
        default=None, compare=False
    )
    # (field, extras) -> extra RULES lines to prepend
    # NB: a rules_prelude without a matching direct_prior makes cascade Pass A run on prelude-only evidence
    rules_prelude: Callable[[str, Mapping[str, str]], list[str]] | None = field(
        default=None, compare=False
    )
    # (field, extras) -> value to trust before any LLM pass, or None
    direct_prior: Callable[[str, Mapping[str, str]], str | None] | None = field(
        default=None, compare=False
    )
    # (field, gliner_lines, spans, extras) -> extra evidence lines when gliner_lines is empty
    synth_spans: Callable[[str, list[str], list[dict], Mapping[str, str]], list[str]] | None = (
        field(default=None, compare=False)
    )
    prior_label: str = "A_inventory"
    # hint= name on the evidence line of a direct_prior hit: "RULES:\n- hint=<prior_hint> value=..."
    prior_hint: str = "prior"
    # (event inventory.json dict, {} when absent/unreadable) -> EventContext.extras.
    # None = no extras (every hook then sees an empty mapping).
    extras_from_inventory: Callable[[Mapping[str, Any]], Mapping[str, str]] | None = field(
        default=None, compare=False
    )


@dataclass(frozen=True)
class ActionPack:
    """Input schema + instructions; harness stays fixed; output follows ``fields``.

    Temporal NER is gated by ``date_fields`` only — non-date fields never
    load/run the tagger or get TEMPORAL SPANS evidence.
    """

    name: str
    fields: tuple[str, ...]
    field_defs: dict[str, str]
    field_pick: dict[str, str]
    hint_allow: dict[str, frozenset[str]]
    gt_to_hint: dict[str, str]
    # Schema gate: temporal BERT runs / TEMPORAL evidence only for these fields
    date_fields: frozenset[str]
    temporal_cues: dict[str, tuple[str, ...]] = field(default_factory=dict)
    validate_fields: frozenset[str] = field(default_factory=frozenset)
    # Tunable per-field clause retrieval (oracle-style); empty = span/rules path only
    clause_fields: dict[str, ClauseFieldSpec] = field(default_factory=dict)
    # Optional explicit per-field policies; empty = derive from legacy knobs
    policies: dict[str, FieldPolicy] = field(default_factory=dict)
    hooks: PackHooks | None = None
    system_prompt: str = (
        "You extract one schema field from structured evidence "
        "(RULES facts, GLiNER spans, temporal DATE spans). "
        "PICK the best matching listed value. Return one JSON object only. "
        "Do not invent identifiers, dates, or prices absent from the evidence."
    )
    normalize: NormalizeFn = field(default=_default_normalize, compare=False)

    def __post_init__(self) -> None:
        unknown = self.date_fields - set(self.fields)
        if unknown:
            raise ValueError(f"{self.name}: date_fields not in fields: {sorted(unknown)}")
        cue_extra = set(self.temporal_cues) - self.date_fields
        if cue_extra:
            raise ValueError(
                f"{self.name}: temporal_cues keys must be date_fields only: {sorted(cue_extra)}"
            )

        bad_pol = set(self.policies) - set(self.fields)
        if bad_pol:
            raise ValueError(f"{self.name}: policies keys not in fields: {sorted(bad_pol)}")

    def uses_temporal(self, field: str) -> bool:
        return field in self.date_fields
