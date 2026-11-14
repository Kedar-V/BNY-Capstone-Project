"""FROZEN reference copy of the legacy per-field extract (do not edit).

Verbatim copy of `extract_field` plus exactly the helpers it needs, taken from the
snapshot of scripts/eval_unified_field_qwen.py dated 2026-11-13
(.superpowers/sdd/2026-11-13-extract-graph-dto/legacy_snapshot_20261113.py).
This is the permanent parity oracle for the LangGraph extract layer: if a test
disagrees with it, fix the graph, never this file.

Deviations from the snapshot (import-safety only, no logic change):
- no argparse / main / temporal-model loading at import time;
- `_temporal_lines` is a stub that raises: every caller passes `temporal_cache`
  (a dict), so the live tagger path is never taken.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.evaluation.action_packs import retrieve_clause
from src.evaluation.action_packs.base import ActionPack
from src.preprocess.rules_ids import find_settlement

_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified"})
MAX_RAW = 160
MAX_PASSAGE = 220
MAX_GLINER = 25
MAX_TEMPORAL = 25


def _cue_score(window: str, cues: tuple[str, ...]) -> int:
    return sum(1 for c in cues if c in window)



_RULES_DIRECT_FIELDS = frozenset({"ticker", "cusip", "isin"})


def _rules_raw_values(pack: ActionPack, rep: dict, field: str, excerpts: str) -> list[str]:
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


def _rules_lines(pack: ActionPack, rep: dict, field: str, excerpts: str) -> list[str]:
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


def _norm_org(s: str) -> str:
    s = (s or "").lower()
    for junk in (
        "incorporated",
        "inc.",
        "inc",
        "corporation",
        "corp.",
        "corp",
        "ltd.",
        "ltd",
        "llc",
        "l.l.c.",
        "co.",
        "company",
        "the ",
    ):
        s = s.replace(junk, " ")
    return " ".join(s.split())


def _same_org(a: str, b: str) -> bool:
    na, nb = _norm_org(a), _norm_org(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _gliner_lines(
    pack: ActionPack,
    spans: list[dict[str, Any]],
    field: str,
    *,
    primary_entity: str = "",
) -> list[str]:
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
        # Merger DEFM14A/proxy: filing primary_entity is the target — drop it from acquirer evidence
        if (
            pack.name == "merger"
            and field == "acquirer"
            and primary_entity
            and _same_org(raw, primary_entity)
        ):
            continue
        # Junk role nouns, not party names
        if _norm_org(raw) in {"parent", "merger sub", "merger subsidiary", "company", "purchaser"}:
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


def _temporal_lines(pack: ActionPack, tagger, excerpts: str, field: str) -> list[str]:
    raise NotImplementedError("legacy_extract is always called with temporal_cache")


def build_evidence(
    pack: ActionPack,
    *,
    field: str,
    rep: dict,
    spans: list[dict],
    excerpts: str,
    tagger,
    sources: tuple[str, ...],
    temporal_cache: dict[str, list[str]] | None = None,
    primary_entity: str = "",
    is_proxy_filing: bool = False,
) -> str:
    blocks: list[str] = []
    if "rules" in sources:
        rules = _rules_lines(pack, rep, field, excerpts)
        # Inventory prior: filing company on *14A proxies is almost always the target
        if (
            pack.name == "merger"
            and field == "target"
            and primary_entity.strip()
            and is_proxy_filing
        ):
            rules = [
                f"- hint=primary_entity method=inventory value={primary_entity.strip()!r}"
            ] + rules
        if rules:
            blocks.append("RULES:\n" + "\n".join(rules))
    if "gliner" in sources:
        gliner = _gliner_lines(pack, spans, field, primary_entity=primary_entity)
        if gliner:
            blocks.append("GLINER SPANS:\n" + "\n".join(gliner))
        # Cash-only deals: GT often stores explicit "No stock consideration".
        # Only when cash price spans exist and NO stock/ratio labels or share-swap text.
        if pack.name == "merger" and field == "stock_exchange_ratio" and not gliner:
            cash = _gliner_lines(
                pack, spans, "cash_consideration", primary_entity=primary_entity
            )
            labels = " ".join(
                str(sp.get("field_hint") or sp.get("label") or "").lower() for sp in spans
            )
            texts = " ".join(str(sp.get("text") or "").lower() for sp in spans)
            stockish = (
                "exchange_ratio" in labels
                or "stock_exchange" in labels
                or "exchange ratio" in texts
                or ("shares of" in texts and "per share" in texts)
                or "mixed" in texts
            )
            if cash and not stockish:
                blocks.append(
                    "GLINER SPANS:\n- hint=stock_exchange_ratio value='No stock consideration' "
                    "note='no ratio span; cash consideration present'"
                )
    # Config gate: temporal evidence only for pack.date_fields
    if "temporal" in sources and pack.uses_temporal(field):
        if temporal_cache is not None:
            temporal = list(temporal_cache.get(field) or [])
        else:
            temporal = _temporal_lines(pack, tagger, excerpts, field)
        if temporal:
            blocks.append("TEMPORAL SPANS:\n" + "\n".join(temporal))
    if not blocks:
        return "(no rules/GLiNER/temporal evidence for this field)"
    return "\n\n".join(blocks)

def _select_prompt(pack: ActionPack, field: str, evidence: str) -> str:
    # Pack-tunable clause prompt (proration / long-form fields)
    spec = pack.clause_fields.get(field)
    if spec is not None and evidence.startswith("EXCERPT:\n"):
        excerpt = evidence[len("EXCERPT:\n") :]
        return spec.extract_prompt.format(excerpt=excerpt, field=field)

    definition = pack.field_defs.get(field, field)
    pick = pack.field_pick.get(field, "Pick the best listed value for this field.")
    if evidence.startswith("(no "):
        return (
            f"Extract `{field}`.\n"
            f"DEFINITION: {definition}\n"
            "Evidence pack is empty for this field → return null.\n"
            f'Return JSON {{"{field}": null}}.\n\n'
            f"EVIDENCE:\n{evidence}\n"
        )
    return (
        f"Extract `{field}` from the evidence pack below.\n\n"
        f"DEFINITION: {definition}\n\n"
        "HOW TO CHOOSE:\n"
        f"- {pick}\n"
        "- Prefer higher score= / higher field_cues= when several candidates compete.\n"
        "- Copy the value= (or date=) string; light cleanup of whitespace is OK.\n"
        "- Do NOT return null if at least one listed value plausibly matches the definition.\n"
        "- null ONLY when every listed item is clearly wrong for this field.\n"
        "- Never invent identifiers/dates/prices absent from the evidence.\n\n"
        f'Return JSON {{"{field}": "<string>"}} or {{"{field}": null}}.\n\n'
        f"EVIDENCE:\n{evidence}\n"
    )


def _validate_prompt(pack: ActionPack, field: str, value: str, evidence: str) -> str:
    definition = pack.field_defs.get(field, field)
    return (
        f"Validate a candidate for `{field}`.\n"
        f"DEFINITION: {definition}\n"
        f"CANDIDATE: {value!r}\n\n"
        "Return JSON {\"keep\": true|false}. "
        "keep=true only if the candidate satisfies the definition and is supported by EVIDENCE. "
        "keep=false for counsel-as-party, wrong date type, currency guesses without $/£/€ offer price, etc.\n\n"
        f"EVIDENCE:\n{evidence}\n"
    )


def _parse_field(raw: str, field: str) -> str | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    obj: Any = {}
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = {}
    if not isinstance(obj, dict):
        return None
    v = obj.get(field)
    if v is None and "value" in obj:
        v = obj.get("value")
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in _NA:
        return None
    return v[:400]


def _parse_keep(raw: str) -> bool | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    obj: Any = {}
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                # ponytail: Qwen validate sometimes returns huge broken JSON — keep pred
                return None
    if not isinstance(obj, dict) or "keep" not in obj:
        return None
    return bool(obj["keep"])


def extract_field(
    *,
    pack: ActionPack,
    backend,
    model: str,
    field: str,
    rep: dict,
    spans: list[dict],
    excerpts: str,
    tagger,
    cascade: bool,
    validate: bool,
    temporal_cache: dict[str, list[str]] | None = None,
    passages: dict | None = None,
    doc_text: str = "",
    primary_entity: str = "",
    is_proxy_filing: bool = False,
) -> dict[str, Any]:
    """Run cascade (or one-shot) for one field. Returns pred + metadata."""
    rules = _rules_lines(pack, rep, field, excerpts)
    pass_used = "none"
    raw_log: list[str] = []
    pred: str | None = None
    evidence_final = ""

    def _call_select(evidence: str, label: str) -> str | None:
        nonlocal raw_log
        user = _select_prompt(pack, field, evidence)
        raw = backend.chat_json(system=pack.system_prompt, user=user, model=model)
        raw_log.append(f"{label}:{raw[:300]}")
        v = _parse_field(raw, field)
        if v:
            v = pack.normalize(field, v)
        return v

    def _ev(sources: tuple[str, ...]) -> str:
        return build_evidence(
            pack,
            field=field,
            rep=rep,
            spans=spans,
            excerpts=excerpts,
            tagger=tagger,
            sources=sources,
            temporal_cache=temporal_cache,
            primary_entity=primary_entity,
            is_proxy_filing=is_proxy_filing,
        )

    # Pack-tunable clause path (proration, …): retrieve hits, then field-specific prompt.
    # When the field is in clause_fields, this is the only extract path (no GLiNER fallthrough).
    clause_spec = pack.clause_fields.get(field)
    if clause_spec is not None:
        clause_text = retrieve_clause(
            clause_spec,
            passages=passages,
            excerpts=excerpts,
            doc_text=doc_text or excerpts,
        )
        if not clause_text.strip():
            return {
                "pred": None,
                "pass_used": "clause_miss",
                "n_evidence_chars": 0,
                "n_rules": len(rules),
                "raw_llm": "",
            }
        evidence_final = f"EXCERPT:\n{clause_text}"
        pred = _call_select(evidence_final, "clause")
        pass_used = "clause" if pred is not None else "clause_null"
        do_validate = validate and pred is not None and field in pack.validate_fields
        if do_validate and pred is not None:
            user = _validate_prompt(pack, field, pred, evidence_final)
            raw = backend.chat_json(
                system="Return JSON only. Be conservative: drop unsupported values.",
                user=user,
                model=model,
            )
            raw_log.append(f"C:{raw[:200]}")
            keep = _parse_keep(raw)
            if keep is False:
                pred = None
                pass_used = f"{pass_used}+C_drop"
            elif keep is True:
                pass_used = f"{pass_used}+C_keep"
        return {
            "pred": pred,
            "pass_used": pass_used,
            "n_evidence_chars": len(evidence_final),
            "n_rules": len(rules),
            "raw_llm": " | ".join(raw_log)[:500],
        }

    if cascade:
        # Merger: on *14A proxies the registrant is usually the target — not on S-4/8-K
        if (
            pack.name == "merger"
            and field == "target"
            and primary_entity.strip()
            and pred is None
            and is_proxy_filing
        ):
            pred = pack.normalize(field, primary_entity.strip())
            pass_used = "A_inventory"
            evidence_final = f"RULES:\n- hint=primary_entity value={primary_entity!r}"
            raw_log.append(f"A_inventory:{pred!r}")
        if rules and pred is None:
            ev_a = _ev(("rules",))
            evidence_final = ev_a
            # ponytail: ticker/cusip/isin — copy rules value; Qwen often echoes the pack
            if field in _RULES_DIRECT_FIELDS:
                direct = _rules_raw_values(pack, rep, field, excerpts)
                if direct:
                    pred = pack.normalize(field, direct[0])
                    pass_used = "A_rules"
                    raw_log.append(f"A_rules:{pred!r}")
            if pred is None:
                pred = _call_select(ev_a, "A")
                pass_used = "A"
        if pred is None:
            b_sources: tuple[str, ...] = (
                ("gliner", "temporal") if pack.uses_temporal(field) else ("gliner",)
            )
            ev_b = _ev(b_sources)
            evidence_final = ev_b
            if not ev_b.startswith("(no "):
                pred = _call_select(ev_b, "B")
                pass_used = "B" if pred is not None else "B_null"
            elif pass_used == "none":
                pass_used = "empty"
    else:
        oneshot_sources: tuple[str, ...] = (
            ("rules", "gliner", "temporal")
            if pack.uses_temporal(field)
            else ("rules", "gliner")
        )
        evidence_final = _ev(oneshot_sources)
        pred = _call_select(evidence_final, "oneshot")
        pass_used = "oneshot"

    # Pass C validate — only pack.validate_fields (not every B pick; C was dropping true positives)
    do_validate = (
        validate and pred is not None and field in pack.validate_fields
    )
    if do_validate and pred is not None:
        user = _validate_prompt(pack, field, pred, evidence_final)
        raw = backend.chat_json(
            system="Return JSON only. Be conservative: drop unsupported values.",
            user=user,
            model=model,
        )
        raw_log.append(f"C:{raw[:200]}")
        keep = _parse_keep(raw)
        if keep is False:
            pred = None
            pass_used = f"{pass_used}+C_drop"
        elif keep is True:
            pass_used = f"{pass_used}+C_keep"

    return {
        "pred": pred,
        "pass_used": pass_used,
        "n_evidence_chars": len(evidence_final),
        "n_rules": len(rules),
        "raw_llm": " | ".join(raw_log)[:500],
    }
