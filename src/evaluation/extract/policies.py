"""Per-field extraction policy: ordered stages, derived from legacy pack knobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.evaluation.action_packs.base import ActionPack

DIRECT_RULES_FIELDS = frozenset({"ticker", "cusip", "isin"})


@dataclass(frozen=True)
class Stage:
    name: str
    # values: clause | rules | gliner | temporal | prior
    sources: tuple[str, ...]
    prompt_mode: Literal["copy", "pick"]
    on_empty: Literal["null", "skip", "ask"]
    pass_label: str
    # pass_used when the LLM returns null; None = report pass_label (cascade Pass A)
    null_label: str | None
    direct_from_rules: bool
    validate: bool
    direct_label: str = "A_rules"
    # pass_used reported when the stage evidence is empty and nothing labelled the field
    # yet: on_empty == "null" reports it at once (a clause-style miss); in a cascade of
    # on_empty == "skip" stages the last stage's empty_label is reported when no stage
    # labelled. NB: on_empty == "null" in a non-final stage ENDS the whole policy (the
    # remaining stages never run) — see nodes/retrieve.py.
    empty_label: str = "empty"

    def __post_init__(self) -> None:
        # Direct hits come from rules values (rules_direct) or the pack prior (direct_prior)
        if self.direct_from_rules and self.sources not in {("rules",), ("prior",)}:
            raise ValueError(
                f"stage {self.name!r}: direct_from_rules needs sources ('rules',) or "
                f"('prior',), got {self.sources!r}"
            )


@dataclass(frozen=True)
class FieldPolicy:
    # Pass C runs only for stages with validate=True; derived policies set it to
    # field in pack.validate_fields for every stage (legacy Pass C gate)
    stages: tuple[Stage, ...]
    stop_at_first_hit: bool = True


def resolve_policy(pack: ActionPack, field: str, *, cascade: bool) -> FieldPolicy:
    """Return the pack's explicit policy for ``field`` or derive the legacy one."""
    if field in pack.policies:
        return pack.policies[field]
    in_validate = field in pack.validate_fields

    if field in pack.clause_fields:
        return FieldPolicy(
            stages=(
                Stage(
                    name="clause",
                    sources=("clause",),
                    prompt_mode="copy",
                    on_empty="null",
                    pass_label="clause",
                    null_label="clause_null",
                    direct_from_rules=False,
                    validate=in_validate,
                    empty_label="clause_miss",
                ),
            )
        )

    uses_temporal = pack.uses_temporal(field)
    if not cascade:
        sources = ("rules", "gliner", "temporal") if uses_temporal else ("rules", "gliner")
        return FieldPolicy(
            stages=(
                Stage(
                    name="oneshot",
                    sources=sources,
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="oneshot",
                    null_label="oneshot",
                    direct_from_rules=False,
                    validate=in_validate,
                ),
            )
        )

    stages: list[Stage] = []
    hooks = pack.hooks
    if hooks is not None and hooks.direct_prior is not None:
        # Executor skips this stage at run time when direct_prior(field, extras) is None
        stages.append(
            Stage(
                name="prior",
                sources=("prior",),
                prompt_mode="pick",
                on_empty="skip",
                pass_label=hooks.prior_label,
                null_label=None,
                direct_from_rules=True,
                direct_label=hooks.prior_label,
                validate=in_validate,
            )
        )
    return FieldPolicy(
        stages=tuple(stages)
        + (
            Stage(
                name="rules",
                sources=("rules",),
                prompt_mode="pick",
                on_empty="skip",
                pass_label="A",
                null_label=None,
                direct_from_rules=field in DIRECT_RULES_FIELDS,
                validate=in_validate,
            ),
            Stage(
                name="span",
                sources=("gliner", "temporal") if uses_temporal else ("gliner",),
                prompt_mode="pick",
                on_empty="skip",
                pass_label="B",
                null_label="B_null",
                direct_from_rules=False,
                validate=in_validate,
            ),
        )
    )
