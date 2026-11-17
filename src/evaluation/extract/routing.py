"""Per-field evidence routing for pack freeze (Laya or heuristic).

Chooses a policy *shape* plus independent evidence *legs* (including hybrid
combinations). Used at evidence-pack build time — not in the hot LLM loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.policies import DIRECT_RULES_FIELDS, FieldPolicy, Stage

RecipeShape = Literal["oneshot", "clause_then_pick", "rules_then_span", "clause_only"]
RecipeSource = Literal["laya", "heuristic", "override"]
Leg = Literal["rules", "gliner", "temporal", "hybrid", "clause"]

ALL_LEGS: frozenset[str] = frozenset({"rules", "gliner", "temporal", "hybrid", "clause"})
DEFAULT_ORACLE_PATH = Path(
    "outputs/tender_eval/experiments/runs/best_per_field_effective_gt_prompt.json"
)
# Pack-scoped oracle assemblies (missing file → empty priors; no cross-pack leak).
PACK_ORACLE_PATHS: dict[str, Path] = {
    "tender": DEFAULT_ORACLE_PATH,
    "merger": Path("outputs/merger_eval/experiments/runs/best_per_field.json"),
}
_DATE_RE = re.compile(r"\b(date|deadline|expir|withdraw|settlement|effective|election)\b", re.I)
_ID_RE = re.compile(r"\b(cusip|isin|ticker)\b", re.I)


@dataclass(frozen=True)
class FieldRecipe:
    field: str
    shape: RecipeShape
    legs: frozenset[str]
    confidence: float
    source: RecipeSource
    rationale: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "shape": self.shape,
            "legs": sorted(self.legs),
            "confidence": self.confidence,
            "source": self.source,
            "rationale": self.rationale,
            "raw": dict(self.raw) if self.raw else {},
        }


def load_oracle_priors(
    path: Path | None = None, *, pack_name: str | None = None
) -> dict[str, str]:
    """field -> oracle system label (e.g. 'Temporal NER').

    Prefer an explicit ``path``. Else use ``PACK_ORACLE_PATHS[pack_name]`` when
    given, else the tender default. Missing files yield ``{}`` (field-cue
    heuristics only) — never reuse another pack's oracle JSON.
    """
    if path is None:
        if pack_name is not None:
            path = PACK_ORACLE_PATHS.get(pack_name)
            if path is None:
                return {}
        else:
            path = DEFAULT_ORACLE_PATH
    p = path
    if not p.is_absolute():
        # resolve relative to repo root (parents[3] from this file: extract→evaluation→src→root)
        root = Path(__file__).resolve().parents[3]
        p = root / p
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for name, meta in (data.get("fields") or {}).items():
        sys = (meta or {}).get("system")
        if sys:
            out[str(name)] = str(sys)
    return out


def _date_like(pack: ActionPack, field: str) -> bool:
    if field in pack.date_fields:
        return True
    blob = f"{field} {pack.field_defs.get(field, '')}"
    return bool(_DATE_RE.search(blob))


def _id_like(field: str) -> bool:
    return bool(_ID_RE.search(field))


def apply_guards(
    pack: ActionPack,
    field: str,
    shape: RecipeShape,
    legs: frozenset[str],
) -> tuple[RecipeShape, frozenset[str], list[str]]:
    """Clamp illegal combos; return (shape, legs, notes)."""
    notes: list[str] = []
    legs = frozenset(x for x in legs if x in ALL_LEGS)

    if shape == "clause_only":
        if field not in pack.clause_fields:
            shape = "oneshot"
            notes.append("clause_only→oneshot (no clause_fields)")
            legs = frozenset({"rules", "gliner", "hybrid"})
        else:
            legs = frozenset({"clause"})
    elif shape == "clause_then_pick":
        if field not in pack.clause_fields:
            shape = "oneshot"
            notes.append("clause_then_pick→oneshot (no clause_fields)")
            legs = (legs - {"clause"}) or frozenset({"rules", "gliner", "hybrid"})
        else:
            legs = legs | {"clause"}
            # pick legs exclude clause (separate stage)
            pick = legs - {"clause"}
            if not pick:
                pick = frozenset({"rules", "gliner", "hybrid"})
                notes.append("added default pick legs")
            legs = frozenset({"clause"}) | pick

    if "temporal" in legs and not _date_like(pack, field):
        legs = legs - {"temporal"}
        notes.append("dropped temporal (not date-like)")

    if "hybrid" in legs and pack.hybrid is None:
        legs = legs - {"hybrid"}
        notes.append("dropped hybrid (pack.hybrid unset)")

    if "clause" in legs and field not in pack.clause_fields and shape not in {
        "clause_only",
        "clause_then_pick",
    }:
        legs = legs - {"clause"}
        notes.append("dropped clause (not in clause_fields)")

    # Never leave empty legs
    if not legs:
        legs = frozenset({"rules", "gliner", "hybrid"} if pack.hybrid else {"rules", "gliner"})
        shape = "oneshot"
        notes.append("empty legs→default oneshot mix")

    # clause_only must only be clause
    if shape == "clause_only":
        legs = frozenset({"clause"})

    return shape, frozenset(legs), notes


def _ordered_legs(*wanted: str, available: frozenset[str]) -> tuple[str, ...]:
    order = ("rules", "gliner", "temporal", "hybrid")
    return tuple(x for x in order if x in wanted and x in available)


def recipe_to_policy(
    pack: ActionPack,
    recipe: FieldRecipe,
    *,
    validate: bool | None = None,
) -> FieldPolicy:
    """Compile a FieldRecipe into Stage sources the extract graph understands."""
    shape, legs, _ = apply_guards(pack, recipe.field, recipe.shape, recipe.legs)
    in_validate = pack.fields and (
        recipe.field in pack.validate_fields if validate is None else validate
    )
    # settle accept gate when present on pack policy for settlement_date
    accept = None
    if recipe.field == "settlement_date" and recipe.field in pack.policies:
        for st in pack.policies[recipe.field].stages:
            if st.accept is not None:
                accept = st.accept
                break

    if shape == "clause_only":
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
                    validate=bool(in_validate),
                    empty_label="clause_miss",
                ),
            )
        )

    if shape == "clause_then_pick":
        pick = _ordered_legs("rules", "gliner", "temporal", "hybrid", available=legs)
        if not pick:
            pick = ("rules", "gliner")
        return FieldPolicy(
            stages=(
                Stage(
                    name="clause",
                    sources=("clause",),
                    prompt_mode="copy",
                    on_empty="skip",
                    pass_label="clause",
                    null_label="clause_null",
                    direct_from_rules=False,
                    validate=bool(in_validate),
                    empty_label="clause_miss",
                ),
                Stage(
                    name="oneshot",
                    sources=pick,
                    prompt_mode="pick",
                    on_empty="ask",
                    pass_label="oneshot",
                    null_label="oneshot",
                    direct_from_rules=False,
                    validate=bool(in_validate),
                    accept=accept,
                ),
            ),
            stop_at_first_hit=True,
        )

    if shape == "rules_then_span":
        span = _ordered_legs("gliner", "temporal", "hybrid", available=legs)
        if not span:
            span = ("gliner",)
        rules_direct = (
            recipe.field in {"ticker", "cusip", "isin", "settlement_date"}
            and "rules" in legs
        )
        return FieldPolicy(
            stages=(
                Stage(
                    name="rules",
                    sources=("rules",),
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="A",
                    null_label=None,
                    direct_from_rules=rules_direct,
                    validate=bool(in_validate),
                    accept=accept,
                ),
                Stage(
                    name="span",
                    sources=span,
                    prompt_mode="pick",
                    on_empty="skip",
                    pass_label="B",
                    null_label="B_null",
                    direct_from_rules=False,
                    validate=bool(in_validate),
                    accept=accept,
                ),
            ),
            stop_at_first_hit=True,
        )

    # oneshot — Rules-only id fields match the oracle Rules path (no LLM).
    sources = _ordered_legs("rules", "gliner", "temporal", "hybrid", available=legs)
    if not sources:
        sources = ("rules", "gliner")
    rules_direct = (
        recipe.field in DIRECT_RULES_FIELDS
        and sources == ("rules",)
    )
    return FieldPolicy(
        stages=(
            Stage(
                name="oneshot",
                sources=sources,
                prompt_mode="pick",
                on_empty="ask",
                pass_label="oneshot",
                null_label="oneshot",
                direct_from_rules=rules_direct,
                validate=bool(in_validate),
                accept=accept,
            ),
        )
    )


def heuristic_recipe(
    pack: ActionPack,
    field: str,
    *,
    oracle_system: str | None = None,
) -> FieldRecipe:
    """Deterministic router seeded by oracle system labels + field cues."""
    sys = (oracle_system or "").strip().lower()
    notes: list[str] = []

    if "settlement template" in sys or field == "settlement_date":
        shape: RecipeShape = "rules_then_span"
        legs: frozenset[str] = frozenset({"rules", "gliner", "temporal", "hybrid"})
        notes.append("oracle/settlement→rules_then_span")
    elif "clause" in sys or field in ("proration_terms",):
        # Proration: clause-only misses ~half the holdout; hybrid retrieval
        # recovers gold on all labeled rows (holdout probe). Prefer
        # clause_then_pick so a clause hit still short-circuits.
        if field == "proration_terms" and field in pack.clause_fields:
            shape, legs = "clause_then_pick", frozenset({"clause", "rules", "gliner", "hybrid"})
            notes.append("proration→clause_then_pick+hybrid (clause-only under-recalls)")
        elif field in pack.clause_fields:
            shape, legs = "clause_then_pick", frozenset({"clause", "rules", "gliner", "hybrid"})
            notes.append("oracle/clause")
        else:
            shape, legs = "oneshot", frozenset({"rules", "gliner", "hybrid"})
            notes.append("oracle/clause but no clause_fields→oneshot")
    elif "temporal ner" in sys:
        shape, legs = "oneshot", frozenset({"temporal", "hybrid"})
        notes.append("oracle temporal NER")
    elif "temporal to qwen" in sys or field == "effective_date":
        shape, legs = "oneshot", frozenset({"temporal", "gliner", "hybrid"})
        notes.append("oracle temporal→slm")
    elif sys == "rules" or _id_like(field):
        # Merger ticker: rules-only under-recalls (~0.18); hybrid lifts ~0.72–0.77.
        # Tender ticker did not benefit from hybrid in holdout probes — leave rules-only.
        if (
            pack.name == "merger"
            and field == "ticker"
            and pack.hybrid is not None
        ):
            shape, legs = "oneshot", frozenset({"rules", "gliner", "hybrid"})
            notes.append("merger ticker→rules+hybrid (rules-only under-recalls)")
        else:
            shape, legs = "oneshot", frozenset({"rules"})
            notes.append("oracle/rules or id-like")
    elif "currency hybrid" in sys:
        shape, legs = "oneshot", frozenset({"rules", "gliner", "hybrid"})
        notes.append("oracle currency hybrid")
    elif "qwen direct" in sys or "qwen" in sys:
        shape, legs = "oneshot", frozenset({"rules", "gliner", "hybrid"})
        notes.append("oracle qwen direct→mixed")
    elif not sys and field in pack.date_fields:
        # No pack oracle yet (e.g. merger): mirror Temporal NER bags.
        shape, legs = "oneshot", frozenset({"temporal", "hybrid"})
        notes.append("date field→temporal+hybrid")
    else:
        shape, legs = "oneshot", frozenset({"rules", "gliner", "hybrid"})
        notes.append("default mixed")

    # Field cues refine legs
    if _date_like(pack, field) and "temporal" not in legs and shape != "clause_only":
        legs = legs | {"temporal"}
        notes.append("date cue→+temporal")
    if field in ("minimum_tender_condition", "security_description") and field in pack.clause_fields:
        if shape == "oneshot":
            shape = "clause_then_pick"
            legs = legs | {"clause"}
            notes.append("clause field→clause_then_pick")
    # offer_price: GLiNER finds par ($0.001) / aggregates; NAV/formula prices need hybrid prose.
    if field == "offer_price":
        if "gliner" in legs:
            legs = legs - {"gliner"}
            notes.append("offer_price→no gliner (par/aggregate traps; formulas via hybrid)")
        if pack.hybrid is not None and "hybrid" not in legs and shape != "clause_only":
            legs = legs | {"hybrid"}
            notes.append("offer_price→+hybrid")

    shape, legs, guard_notes = apply_guards(pack, field, shape, legs)
    notes.extend(guard_notes)
    return FieldRecipe(
        field=field,
        shape=shape,
        legs=legs,
        confidence=0.7 if oracle_system else 0.5,
        source="heuristic",
        rationale="; ".join(notes),
        raw={"oracle_system": oracle_system},
    )


def route_fields(
    pack: ActionPack,
    fields: Sequence[str],
    *,
    mode: Literal["auto", "laya", "heuristic"] = "auto",
    oracle_priors: Mapping[str, str] | None = None,
    gold_cues: Mapping[str, Sequence[str]] | None = None,
    noul_threshold: float = 0.5,
) -> dict[str, FieldRecipe]:
    """Route every field. ``auto`` uses Laya when env is configured, else heuristic."""
    priors = (
        dict(oracle_priors)
        if oracle_priors is not None
        else load_oracle_priors(pack_name=pack.name)
    )
    use_laya = mode == "laya"
    if mode == "auto":
        from src.evaluation.extract.laya_client import laya_configured

        use_laya = laya_configured()

    out: dict[str, FieldRecipe] = {}
    if use_laya:
        from src.evaluation.extract.laya_client import route_field_laya

        for f in fields:
            try:
                out[f] = route_field_laya(
                    pack,
                    f,
                    oracle_system=priors.get(f),
                    gold_cues=list((gold_cues or {}).get(f) or []),
                    noul_threshold=noul_threshold,
                )
            except Exception as e:  # noqa: BLE001 — fall back per field
                base = heuristic_recipe(pack, f, oracle_system=priors.get(f))
                out[f] = FieldRecipe(
                    field=base.field,
                    shape=base.shape,
                    legs=base.legs,
                    confidence=base.confidence * 0.5,
                    source="heuristic",
                    rationale=f"laya_failed:{e}; {base.rationale}",
                    raw=base.raw,
                )
        return out

    for f in fields:
        out[f] = heuristic_recipe(pack, f, oracle_system=priors.get(f))
    return out


def recipe_from_dict(d: Mapping[str, Any]) -> FieldRecipe:
    return FieldRecipe(
        field=str(d["field"]),
        shape=d["shape"],  # type: ignore[arg-type]
        legs=frozenset(d.get("legs") or ()),
        confidence=float(d.get("confidence") or 0.0),
        source=d.get("source") or "override",  # type: ignore[arg-type]
        rationale=str(d.get("rationale") or ""),
        raw=dict(d.get("raw") or {}),
    )


def pack_with_recipes(
    pack: ActionPack,
    recipes: Mapping[str, FieldRecipe],
    *,
    validate: bool | None = None,
) -> ActionPack:
    """Return a copy of ``pack`` whose ``policies`` are the routed recipes."""
    import dataclasses

    policies = {
        f: recipe_to_policy(pack, recipes[f], validate=validate) for f in recipes
    }
    # Keep any pack policies for fields not in recipes
    merged = dict(pack.policies)
    merged.update(policies)
    return dataclasses.replace(pack, policies=merged)


def load_routing_file(path: Path) -> dict[str, FieldRecipe]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = data.get("fields") or {}
    return {f: recipe_from_dict(meta) for f, meta in fields.items()}


__all__ = [
    "ALL_LEGS",
    "DEFAULT_ORACLE_PATH",
    "PACK_ORACLE_PATHS",
    "FieldRecipe",
    "apply_guards",
    "heuristic_recipe",
    "load_oracle_priors",
    "load_routing_file",
    "pack_with_recipes",
    "recipe_from_dict",
    "recipe_to_policy",
    "route_fields",
]
