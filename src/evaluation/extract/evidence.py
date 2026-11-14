"""Evidence-line builders for per-field extraction (pure functions)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from src.evaluation.action_packs.orgs import norm_org, same_org  # noqa: F401 (same_org re-exported)
from src.preprocess.rules_ids import find_settlement

if TYPE_CHECKING:
    from src.evaluation.action_packs.base import ActionPack

MAX_RAW = 160
MAX_PASSAGE = 220
MAX_GLINER = 25


def cue_score(window: str, cues: tuple[str, ...]) -> int:
    return sum(1 for c in cues if c in window)


def rules_raw_values(pack: ActionPack, rep: dict, field: str, excerpts: str) -> list[str]:
    hint = pack.gt_to_hint.get(field, field)
    allow = pack.hint_allow.get(field, frozenset())
    vals: list[str] = []
    for f in rep.get("candidate_facts") or []:
        if (f.get("method") or "") != "rules":
            continue
        fh = (f.get("field_hint") or "").lower()
        if fh != hint and fh not in allow:
            continue
        raw = str(f.get("raw") or f.get("value") or "").strip()[:MAX_RAW]
        if raw:
            vals.append(raw)
    if field == "settlement_date" and excerpts:
        for i in range(0, min(len(excerpts), 12_000), 1800):
            hit = find_settlement(excerpts[i : i + 1800])
            if hit:
                vals.append(hit)
                break
    return vals


def rules_lines(pack: ActionPack, rep: dict, field: str, excerpts: str) -> list[str]:
    hint = pack.gt_to_hint.get(field, field)
    allow = pack.hint_allow.get(field, frozenset())
    lines: list[str] = []
    for f in rep.get("candidate_facts") or []:
        if (f.get("method") or "") != "rules":
            continue
        fh = (f.get("field_hint") or "").lower()
        if fh != hint and fh not in allow:
            continue
        raw = str(f.get("raw") or f.get("value") or "").strip()[:MAX_RAW]
        if not raw:
            continue
        passage = str(f.get("passage") or f.get("segment_text") or "")[:MAX_PASSAGE].replace(
            "\n", " "
        )
        lines.append(
            f"- hint={fh or hint} value={raw!r}"
            + (f" context={passage!r}" if passage else "")
        )
    if field == "settlement_date" and excerpts:
        for i in range(0, min(len(excerpts), 12_000), 1800):
            hit = find_settlement(excerpts[i : i + 1800])
            if hit:
                lines.append(f"- hint=settlement_date method=settlement_template value={hit!r}")
                break
    return lines


def _hint_allowed(hint: str, label: str, allow: frozenset[str]) -> bool:
    """Match pack allow-lists to GLiNER labels like offeror_organization."""
    for token in (hint, label):
        if not token:
            continue
        if token in allow:
            return True
        for a in allow:
            if token.startswith(a + "_") or token.endswith("_" + a):
                return True
    return False


def gliner_lines(
    pack: ActionPack,
    spans: list[dict[str, Any]],
    field: str,
    *,
    extras: Mapping[str, str] | None = None,
) -> list[str]:
    hooks = pack.hooks
    junk = hooks.junk_roles if hooks else frozenset()
    drop = hooks.drop_span if hooks else None
    extras = extras or {}
    allow = pack.hint_allow.get(field, frozenset({pack.gt_to_hint.get(field, field)}))
    lines: list[str] = []
    for sp in spans:
        hint = (sp.get("field_hint") or sp.get("label") or "").lower().replace(" ", "_")
        label = (sp.get("label") or "").lower().replace(" ", "_")
        if not _hint_allowed(hint, label, allow):
            continue
        raw = str(sp.get("text") or sp.get("raw") or "").strip()
        if not raw:
            continue
        if drop is not None and drop(field, raw, extras):
            continue
        # Junk role nouns, not party names (pack-supplied)
        if norm_org(raw) in junk:
            continue
        raw = raw[:MAX_RAW]
        passage = str(sp.get("passage") or sp.get("segment_text") or "")[:MAX_PASSAGE].replace(
            "\n", " "
        )
        conf = sp.get("score") or sp.get("confidence")
        conf_s = f" score={float(conf):.2f}" if conf is not None else ""
        lab_s = f" label={label}" if label and label != hint else ""
        lines.append(
            f"- hint={hint or '?'}{lab_s}{conf_s} value={raw!r}"
            + (f" context={passage!r}" if passage else "")
        )
        if len(lines) >= MAX_GLINER:
            break
    return lines


def rules_prelude_lines(pack: ActionPack, field: str, extras: Mapping[str, str]) -> list[str]:
    if pack.hooks is None or pack.hooks.rules_prelude is None:
        return []
    return list(pack.hooks.rules_prelude(field, extras))


def synth_lines(
    pack: ActionPack,
    field: str,
    gliner: list[str],
    spans: list[dict[str, Any]],
    extras: Mapping[str, str],
) -> list[str]:
    if pack.hooks is None or pack.hooks.synth_spans is None:
        return []
    return list(pack.hooks.synth_spans(field, gliner, spans, extras))
