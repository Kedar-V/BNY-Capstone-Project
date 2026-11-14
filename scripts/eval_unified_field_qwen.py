#!/usr/bin/env python3
"""Unified per-field extract: ActionPack + rules→GLiNER/temporal cascade → LLM.

V2 harness (schema-swappable):
  Pass A: RULES-only if rules exist
  Pass B: GLiNER + TEMPORAL if A null / no rules
  Pass C: optional validate (pack.validate_fields or after Pass B)

Default LLM: OpenRouter free (often rate-limited). Prefer ``--backend orin`` + ``gemma4:26b``
on the AGX Orin hub (``OLLAMA_HOST``).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.action_packs import get_pack, retrieve_clause
from src.evaluation.action_packs.base import ActionPack
from src.evaluation.experiments import ensure_holdout
from src.evaluation.llm_backends import load_dotenv, make_backend
from src.evaluation.tender import load_gt, normalize, soft_match, gt_event_ids_from_corpus
from src.preprocess.rules_ids import find_settlement
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

# Temporal NER (local CPU is fine; LLM is hosted)
import importlib.util

_temporal_path = ROOT / "scripts" / "eval_temporal_tagger_dates.py"
_spec = importlib.util.spec_from_file_location("eval_temporal_tagger_dates", _temporal_path)
_temporal = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_temporal)
extract_timex = _temporal.extract_timex
_window = _temporal._window

TEMPORAL_MODEL = "satyaalmasian/temporal_tagger_BERT_tokenclassifier"
# qwen/qwen3-4b:free retired on OpenRouter; use a free hosted model instead.
DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified"})
MAX_RAW = 160
MAX_PASSAGE = 220
MAX_GLINER = 25
MAX_TEMPORAL = 25
ORACLE_MICRO = 0.837
ALLSPANS_MICRO = 0.481
PROMPT_V2_MICRO = 0.468


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _load_rep(path_name: str, eid: str) -> dict[str, Any]:
    p = Path(DEFAULT_PREPROCESS_ROOT) / path_name / "events" / eid / "concise" / "event_rep.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_spans(path_name: str, eid: str) -> list[dict[str, Any]]:
    p = Path(DEFAULT_PREPROCESS_ROOT) / path_name / "events" / eid / "spans.json"
    if not p.exists():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("spans") or [])


# Aesha FT label → pack field_hint (pass-through otherwise)
_FT_FIELD_ALIAS = {
    "expected_closing": "effective_date",
    "closing": "effective_date",
    "consummation": "effective_date",
    "merger_subsidiary": "acquirer",  # buyer-side; primary_entity filter drops target
    "purchaser": "acquirer",
    "parent": "acquirer",
    "exchange_ratio": "stock_exchange_ratio",
    "vote_date": "shareholder_vote_date",
    "meeting_date": "shareholder_vote_date",
}


def _load_ft_candidate_spans(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Aesha FT GLiNER candidates jsonl → ALL span-shaped evidence keyed by accession.

    Keeps every candidate (not top-1). Dedupes identical (field, value) to the
    highest-score hit so the prompt gets every distinct value + best context.
    Sorted score-desc so any later cap still prefers stronger spans.
    """
    by_acc: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return by_acc
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        acc = str(obj.get("accession_number") or "").strip()
        if not acc:
            continue
        best: dict[tuple[str, str], dict[str, Any]] = {}
        for c in obj.get("candidates") or []:
            field = str(c.get("field") or "").strip().lower().replace(" ", "_")
            field = _FT_FIELD_ALIAS.get(field, field)
            raw = str(c.get("value") or c.get("text") or "").strip()
            if not field or not raw:
                continue
            score = float(c.get("score") or 0.0)
            key = (field, raw.casefold())
            prev = best.get(key)
            if prev is not None and float(prev.get("score") or 0.0) >= score:
                continue
            best[key] = {
                "field_hint": field,
                "label": field,
                "text": raw[:MAX_RAW],
                "passage": str(c.get("context") or "")[:MAX_PASSAGE],
                "score": score,
                "start": c.get("start"),
                "end": c.get("end"),
            }
        spans = sorted(best.values(), key=lambda s: -float(s.get("score") or 0.0))
        by_acc[acc] = spans
    return by_acc


def _passages_obj(raw: str | None) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _spans_from_passages(passages: dict[str, Any]) -> list[dict[str, Any]]:
    """GT passage quotes → span-shaped evidence when preprocess spans are missing."""
    spans: list[dict[str, Any]] = []
    for field, items in passages.items():
        hint = str(field or "").lower().replace(" ", "_")
        for it in items or []:
            if not isinstance(it, dict):
                continue
            quote = str(it.get("quote") or "").strip()
            if not quote:
                continue
            spans.append(
                {
                    "field_hint": hint,
                    "label": hint,
                    "text": quote[:MAX_RAW],
                    "passage": quote[:MAX_PASSAGE],
                    "score": 1.0,
                }
            )
    return spans


def _excerpts_from_passages(passages: dict[str, Any], *, max_chars: int = 24_000) -> str:
    parts: list[str] = []
    n = 0
    for field, items in passages.items():
        for it in items or []:
            if not isinstance(it, dict):
                continue
            quote = str(it.get("quote") or "").strip()
            if not quote:
                continue
            block = f"[{field}]\n{quote}"
            if n + len(block) > max_chars:
                remain = max_chars - n
                if remain < 200:
                    return "\n\n---\n\n".join(parts)
                block = block[:remain]
            parts.append(block)
            n += len(block)
            if n >= max_chars:
                return "\n\n---\n\n".join(parts)
    return "\n\n---\n\n".join(parts)

def _segment_blob(store: ArtifactStore, eid: str, *, max_chars: int = 200_000) -> str:
    """Concatenated segment text for clause regex (not priority-truncated)."""
    path = store.segments_path(eid)
    if not path.exists():
        return ""
    parts: list[str] = []
    n = 0
    for seg in store.read_json(path).get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if n + len(text) > max_chars:
            text = text[: max(0, max_chars - n)]
        parts.append(text)
        n += len(text)
        if n >= max_chars:
            break
    return "\n\n".join(parts)


def _excerpts(store: ArtifactStore, eid: str, *, max_chars: int = 24_000) -> str:
    path = store.segments_path(eid)
    if not path.exists():
        return ""
    segs = list(store.read_json(path).get("segments") or [])
    preferred, fallback = [], []
    for seg in segs:
        kind = (seg.get("kind") or "").lower()
        heading = (seg.get("heading") or "").lower()
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if kind in {"faq", "priority_section"} or seg.get("priority") or "summary term" in heading:
            preferred.append((heading, text))
        elif kind in {"toc_section", "full_doc"}:
            fallback.append((heading, text))
    parts: list[str] = []
    n = 0
    for heading, text in preferred + fallback:
        block = f"[{heading or 'section'}]\n{text}"
        if n + len(block) > max_chars:
            remain = max_chars - n
            if remain < 200:
                break
            block = block[:remain]
        parts.append(block)
        n += len(block)
        if n >= max_chars:
            break
    return "\n\n---\n\n".join(parts)


def _cue_score(window: str, cues: tuple[str, ...]) -> int:
    return sum(1 for c in cues if c in window)


# Identifier fields: trust rules values directly (Qwen often echoes the pack instead).
# ticker excluded for merger — rules often surface the acquirer ticker on target proxies.
_RULES_DIRECT_FIELDS = frozenset({"cusip", "isin"})


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
    max_lines: int | None = None,
) -> list[str]:
    allow = pack.hint_allow.get(field, frozenset({pack.gt_to_hint.get(field, field)}))
    scored: list[tuple[float, str]] = []
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
        score = float(conf) if conf is not None else 0.0
        conf_s = f" score={score:.2f}" if conf is not None else ""
        lab_s = f" label={label}" if label and label != hint else ""
        line = (
            f"- hint={hint or '?'}{lab_s}{conf_s} value={raw!r}"
            + (f" context={passage!r}" if passage else "")
        )
        scored.append((score, line))
    scored.sort(key=lambda t: -t[0])
    cap = MAX_GLINER if max_lines is None else max_lines
    if cap <= 0:
        return [ln for _, ln in scored]
    return [ln for _, ln in scored[:cap]]


_TAGGER_LOCK = threading.Lock()


def _temporal_lines(
    pack: ActionPack, tagger, excerpts: str, field: str
) -> list[str]:
    if field not in pack.date_fields or tagger is None or not excerpts.strip():
        return []
    cues = pack.temporal_cues.get(field, ())
    lines: list[str] = []
    seen: set[str] = set()
    # HF pipelines are not reliably thread-safe
    with _TAGGER_LOCK:
        for i in range(0, min(len(excerpts), 12_000), 1800):
            chunk = excerpts[i : i + 1800]
            for sp in extract_timex(tagger, chunk):
                key = sp["text"].lower()
                if key in seen or len(key) < 4:
                    continue
                seen.add(key)
                win = _window(chunk, sp["start"], sp["end"], radius=140)
                score = _cue_score(win, cues)
                lines.append(
                    f"- date={sp['text']!r} label={sp['label']} "
                    f"field_cues={score} window={win[:220]!r}"
                )
                if len(lines) >= MAX_TEMPORAL:
                    return lines
    return lines


def _precompute_temporal(
    pack: ActionPack, tagger, excerpts: str, fields: tuple[str, ...]
) -> dict[str, list[str]]:
    """Run BERT once per event; score cues only for ``pack.date_fields`` ∩ fields."""
    out: dict[str, list[str]] = {}
    date_fields = tuple(f for f in fields if pack.uses_temporal(f))
    if tagger is None or not excerpts.strip() or not date_fields:
        return out
    # Tag once — cue scoring is per date field (avoids 3× BERT on same text)
    raw_spans: list[dict[str, Any]] = []
    with _TAGGER_LOCK:
        for i in range(0, min(len(excerpts), 12_000), 1800):
            chunk = excerpts[i : i + 1800]
            for sp in extract_timex(tagger, chunk):
                raw_spans.append({**sp, "_chunk": chunk})
    for field in date_fields:
        cues = pack.temporal_cues.get(field, ())
        lines: list[str] = []
        seen: set[str] = set()
        for sp in raw_spans:
            key = str(sp["text"]).lower()
            if key in seen or len(key) < 4:
                continue
            seen.add(key)
            chunk = sp["_chunk"]
            win = _window(chunk, sp["start"], sp["end"], radius=140)
            score = _cue_score(win, cues)
            lines.append(
                f"- date={sp['text']!r} label={sp['label']} "
                f"field_cues={score} window={win[:220]!r}"
            )
            if len(lines) >= MAX_TEMPORAL:
                break
        out[field] = lines
    return out


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
    max_gliner_lines: int | None = None,
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
        gliner = _gliner_lines(
            pack,
            spans,
            field,
            primary_entity=primary_entity,
            max_lines=max_gliner_lines,
        )
        if gliner:
            blocks.append("GLINER SPANS:\n" + "\n".join(gliner))
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
        if field == "stock_exchange_ratio":
            return (
                f"Extract `{field}`.\n"
                f"DEFINITION: {definition}\n"
                "No exchange-ratio span was found. "
                "If this is a cash-only merger, return exactly: No stock consideration. "
                "Otherwise return null.\n"
                f'Return JSON {{"{field}": "No stock consideration"}} or {{"{field}": null}}.\n\n'
                f"EVIDENCE:\n{evidence}\n"
            )
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
    max_gliner_lines: int | None = None,
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
            max_gliner_lines=max_gliner_lines,
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
            # stock_exchange_ratio may still answer "No stock consideration" with empty spans
            if (not ev_b.startswith("(no ")) or field == "stock_exchange_ratio":
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


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def _party_soft_match(pred: str | None, gold: str | None) -> bool:
    """Org match tolerant of CORP/DE vs Corporation, Inc vs Incorporated."""
    if soft_match(pred, gold):
        return True
    p, g = normalize(pred), normalize(gold)
    if not p or not g:
        return False
    p = re.sub(r"/[a-z0-9]+$", "", p)
    g = re.sub(r"/[a-z0-9]+$", "", g)
    for long, short in (
        ("corporation", "corp"),
        ("incorporated", "inc"),
        ("company", "co"),
        ("limited", "ltd"),
    ):
        p, g = p.replace(long, short), g.replace(long, short)
    p, g = " ".join(p.split()), " ".join(g.split())
    return bool(p and g and (p == g or p in g or g in p))


def _score_one(
    stats: dict[str, Any], gold: str, pred: str | None, *, field: str = ""
) -> str:
    has_gt = _gt_ok(gold)
    has_pred = bool(normalize(pred))
    if has_gt:
        stats["gt_present"] += 1
    if has_pred:
        stats["pred_present"] += 1
    matched = (
        _party_soft_match(pred, gold)
        if field in {"acquirer", "target", "security_description"}
        else soft_match(pred, gold)
    )
    if has_gt and has_pred and matched:
        stats["tp"] += 1
        return "tp"
    if has_pred and not has_gt:
        stats["fp"] += 1
        return "fp_no_gt"
    if has_pred and has_gt:
        stats["fp"] += 1
        stats["fn"] += 1
        return "mismatch"
    if has_gt:
        stats["fn"] += 1
        return "fn"
    return "skip"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Unified ActionPack cascade extract (OpenRouter free default)")
    p.add_argument("--gt", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--pack", default="tender", help="ActionPack name (tender|merger)")
    p.add_argument(
        "--backend",
        default="orin",
        choices=("openrouter", "ollama", "free", "orin", "openai"),
    )
    p.add_argument("--model", default=None, help="Default: gemma4:26b for orin, else OpenRouter free")
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--limit", type=int, default=None, help="Max GT rows (after accession filter)")
    p.add_argument(
        "--limit-accessions",
        type=int,
        default=None,
        help="Keep only the first N unique accessions (avoids multi-security skew)",
    )
    p.add_argument(
        "--ft-candidates",
        type=Path,
        default=None,
        help="Aesha FT GLiNER candidates jsonl (replaces preprocess spans when present)",
    )
    p.add_argument("--fields", default="core", help="'core' or comma-separated subset")
    p.add_argument("--run-name", default=None)
    p.add_argument("--device", default="cpu", help="temporal NER device (cpu recommended)")
    p.add_argument("--no-temporal", action="store_true")
    p.add_argument("--no-cascade", action="store_true", help="v1 one-shot mixed evidence")
    p.add_argument("--validate", action="store_true", default=True)
    p.add_argument("--no-validate", action="store_true")
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Parallel LLM field-calls (1 = serial; Orin OLLAMA_NUM_PARALLEL=4 → use 4)",
    )
    args = p.parse_args(argv)

    pack = get_pack(args.pack)
    if args.gt is None:
        args.gt = (
            ROOT / "notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv"
            if pack.name == "merger"
            else ROOT / "notebooks/evaluation/tender_offers.csv"
        )
    if args.out is None:
        args.out = (
            ROOT / "outputs/merger_eval"
            if pack.name == "merger"
            else ROOT / "outputs/tender_eval"
        )
    if args.fields.strip().lower() == "core":
        fields: tuple[str, ...] = pack.fields
    else:
        fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
        bad = [f for f in fields if f not in pack.field_defs]
        if bad:
            print(f"unknown fields for pack={pack.name}: {bad}", file=sys.stderr)
            return 2

    cascade = not args.no_cascade
    validate = args.validate and not args.no_validate
    if not args.model:
        args.model = (
            "gemma4:26b"
            if args.backend in {"orin", "ollama", "openai"}
            else DEFAULT_MODEL
        )
    if args.backend in {"openrouter", "free"} and args.model in {"qwen3:4b", "qwen/qwen3-4b:free"}:
        args.model = DEFAULT_MODEL

    try:
        backend = make_backend(args.backend)
    except Exception as e:  # noqa: BLE001
        print(str(e), file=sys.stderr)
        return 3

    # ping
    try:
        backend.chat_json(
            system="Return JSON only.",
            user='Return {"ping": true}',
            model=args.model,
        )
    except Exception as e:  # noqa: BLE001
        print(f"LLM backend unreachable ({args.backend}/{args.model}): {e}", file=sys.stderr)
        return 3

    store = ArtifactStore(pack.name, DEFAULT_PREPROCESS_ROOT)
    tagger = None
    _tagger_holder: dict[str, Any] = {"pipe": None}

    def _ensure_tagger():
        """Lazy-load BERT only on temporal cache miss."""
        if args.no_temporal:
            return None
        if _tagger_holder["pipe"] is None:
            from transformers import pipeline

            print(f"loading temporal tagger on {args.device}…", flush=True)
            _tagger_holder["pipe"] = pipeline(
                "token-classification",
                model=TEMPORAL_MODEL,
                aggregation_strategy="simple",
                device=args.device,
            )
        return _tagger_holder["pipe"]

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    if args.split == "holdout":
        rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    else:
        rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() not in holdout]
    if args.limit_accessions:
        ordered: list[str] = []
        for r in rows:
            a = (r.get("accession_number") or "").strip()
            if a and a not in ordered:
                ordered.append(a)
            if len(ordered) >= args.limit_accessions:
                break
        keep = set(ordered)
        rows = [r for r in rows if (r.get("accession_number") or "").strip() in keep]
    if args.limit:
        rows = rows[: args.limit]

    acc_to_eid = (
        gt_event_ids_from_corpus(
            {(r.get("accession_number") or "").strip() for r in rows},
            args.documents_parquet,
        )
        if pack.name == "tender" and args.documents_parquet.exists()
        else {}
    )

    model_tag = args.model.replace("/", "_").replace(":", "_").replace(".", "")
    run = args.run_name or (
        f"unified_field_{pack.name}_v2_{model_tag}_{args.split}"
        if cascade
        else f"unified_field_{pack.name}_oneshot_{model_tag}_{args.split}"
    )
    out_dir = args.out / "experiments" / "runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)

    concurrency = max(1, int(args.concurrency))
    ft_by_acc = _load_ft_candidate_spans(args.ft_candidates) if args.ft_candidates else {}
    print(
        json.dumps(
            {
                "pack": pack.name,
                "backend": args.backend,
                "model": args.model,
                "cascade": cascade,
                "validate": validate,
                "concurrency": concurrency,
                "reasoning_effort": "none",
                "n_rows": len(rows),
                "n_fields": len(fields),
                "fields": list(fields),
                "run": run,
                "ft_candidates": str(args.ft_candidates) if args.ft_candidates else None,
                "ft_accessions_loaded": len(ft_by_acc),
            },
            indent=2,
        ),
        flush=True,
    )

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    pass_counts: dict[str, int] = {}
    from tqdm import tqdm

    ckpt_path = out_dir / "checkpoint.jsonl"
    # Shared across run-names so pause/fix/resume never re-NER the same filings
    temporal_dir = args.out / "temporal_cache" / pack.name
    temporal_dir.mkdir(parents=True, exist_ok=True)

    results_by_job: dict[tuple[int, str], dict[str, Any]] = {}
    if ckpt_path.exists():
        with ckpt_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results_by_job[(int(rec["ei"]), str(rec["field"]))] = rec["result"]
        print(f"resume: loaded {len(results_by_job)} checkpointed field-calls", flush=True)

    # Preload event artifacts once (temporal NER = disk cache only unless miss)
    prepared: list[dict[str, Any]] = []
    temporal_hits = temporal_misses = 0
    for row in tqdm(rows, desc="temporal+load", unit="row", file=sys.stderr):
        acc = (row.get("accession_number") or "").strip()
        # Prefer corpus preprocess ids — GT row.event_id (tender_offer_*) often has no artifacts
        eid = acc_to_eid.get(acc) or (row.get("event_id") or "").strip() or None
        if pack.name == "merger" and acc:
            eid = f"merger_{acc}"
        rep = _load_rep(pack.name, eid) if eid else {}
        spans = _load_spans(pack.name, eid) if eid else []
        use_ft = bool(ft_by_acc and acc in ft_by_acc)
        if use_ft:
            spans = ft_by_acc[acc]  # all distinct FT candidates, score-desc
        excerpts = _excerpts(store, eid) if eid else ""
        passages = _passages_obj(row.get("passages"))
        # GT passages fill gaps when preprocess artifacts missing
        if passages and (not spans or not excerpts):
            if not spans:
                spans = _spans_from_passages(passages)
            if not excerpts:
                excerpts = _excerpts_from_passages(passages)
        doc_text = _segment_blob(store, eid) if eid and pack.clause_fields else ""
        primary_entity = ""
        forms: list[str] = []
        if eid:
            inv_path = store.inventory_path(eid)
            if inv_path.exists():
                try:
                    inv = store.read_json(inv_path)
                    primary_entity = str(inv.get("primary_entity") or "").strip()
                    forms = [
                        str(d.get("form") or d.get("file_type") or "").upper()
                        for d in (inv.get("docs") or [])
                    ]
                except Exception:  # noqa: BLE001
                    primary_entity = ""
        is_proxy_filing = any("14A" in f or "14C" in f for f in forms)
        tkey = eid or acc or f"row{len(prepared)}"
        tpath = temporal_dir / f"{tkey}.json"
        if tpath.exists():
            temporal_cache = json.loads(tpath.read_text(encoding="utf-8"))
            temporal_hits += 1
        else:
            temporal_cache = _precompute_temporal(
                pack, _ensure_tagger(), excerpts, fields
            )
            tpath.write_text(json.dumps(temporal_cache), encoding="utf-8")
            temporal_misses += 1
        prepared.append(
            {
                "row": row,
                "accession": acc,
                "event_id": eid,
                "rep": rep,
                "spans": spans,
                "excerpts": excerpts,
                "passages": passages,
                "doc_text": doc_text,
                "temporal_cache": temporal_cache,
                "primary_entity": primary_entity,
                "is_proxy_filing": is_proxy_filing,
                # FT: pass every distinct candidate (max_lines=0). ZS preprocess keeps MAX_GLINER.
                "max_gliner_lines": 0 if use_ft else None,
            }
        )
    print(
        f"temporal_cache hits={temporal_hits} misses={temporal_misses} "
        f"(tagger_loaded={_tagger_holder['pipe'] is not None})",
        flush=True,
    )

    jobs: list[tuple[int, str]] = [
        (ei, field)
        for ei in range(len(prepared))
        for field in fields
        if (ei, field) not in results_by_job
    ]
    total = len(prepared) * len(fields)
    done = len(results_by_job)
    print(f"llm remaining={len(jobs)} done={done} total={total}", flush=True)

    def _run_job(ei: int, field: str) -> tuple[tuple[int, str], dict[str, Any]]:
        # Independent per-call: evidence built inside extract_field; shared backend is OK.
        ev = prepared[ei]
        try:
            result = extract_field(
                pack=pack,
                backend=backend,
                model=args.model,
                field=field,
                rep=ev["rep"],
                spans=ev["spans"],
                excerpts=ev["excerpts"],
                tagger=_tagger_holder["pipe"],
                cascade=cascade,
                validate=validate,
                temporal_cache=ev.get("temporal_cache"),
                passages=ev.get("passages") or {},
                doc_text=ev.get("doc_text") or "",
                primary_entity=ev.get("primary_entity") or "",
                is_proxy_filing=bool(ev.get("is_proxy_filing")),
                max_gliner_lines=ev.get("max_gliner_lines"),
            )
        except Exception as e:  # noqa: BLE001
            result = {
                "pred": None,
                "pass_used": "error",
                "n_evidence_chars": 0,
                "n_rules": 0,
                "raw_llm": str(e)[:400],
            }
        return (ei, field), result

    t0 = time.perf_counter()
    if jobs:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(_run_job, ei, field) for ei, field in jobs]
            pbar = tqdm(
                total=total,
                initial=done,
                desc="llm_fields",
                unit="call",
                file=sys.stderr,
            )
            try:
                with ckpt_path.open("a", encoding="utf-8") as ckpt_fh:
                    for fut in as_completed(futs):
                        key, result = fut.result()
                        results_by_job[key] = result
                        done += 1
                        ei, field = key
                        acc = prepared[ei]["accession"]
                        gold = (prepared[ei]["row"].get(field) or "").strip()
                        line = (
                            f"[{done}/{total}] {acc} {field} pass={result['pass_used']} "
                            f"GT={gold!r} pred={result['pred']!r}"
                        )
                        print(line, flush=True)
                        tqdm.write(line, file=sys.stderr)
                        ckpt_fh.write(
                            json.dumps(
                                {
                                    "ei": ei,
                                    "field": field,
                                    "accession": acc,
                                    "result": result,
                                }
                            )
                            + "\n"
                        )
                        ckpt_fh.flush()
                        pbar.set_postfix_str(
                            f"{acc[-14:]} {field} {result['pass_used']}", refresh=False
                        )
                        pbar.update(1)
            finally:
                pbar.close()
    wall_s = time.perf_counter() - t0

    details: list[dict[str, Any]] = []
    for ei, ev in enumerate(prepared):
        row = ev["row"]
        row_d: dict[str, Any] = {
            "accession": ev["accession"],
            "event_id": ev["event_id"],
            "n_spans": len(ev["spans"]),
            "n_excerpt_chars": len(ev["excerpts"]),
            "fields": {},
        }
        for field in fields:
            result = results_by_job[(ei, field)]
            gold = (row.get(field) or "").strip()
            outcome = _score_one(stats[field], gold, result["pred"], field=field)
            pass_counts[result["pass_used"]] = pass_counts.get(result["pass_used"], 0) + 1
            row_d["fields"][field] = {
                "outcome": outcome,
                "gold": gold if _gt_ok(gold) else None,
                **result,
            }
        details.append(row_d)

    per_field = {
        f: {**stats[f], **_prf(stats[f]["tp"], stats[f]["fp"], stats[f]["fn"])} for f in fields
    }
    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    micro = _prf(tp, fp, fn)
    summary = {
        "pack": pack.name,
        "backend": args.backend,
        "model": args.model,
        "mode": "cascade_v2" if cascade else "oneshot_v1",
        "validate": validate,
        "concurrency": concurrency,
        "reasoning_effort": "none",
        "wall_seconds": round(wall_s, 2),
        "n_rows": len(rows),
        "n_llm_jobs": total,
        "fields": list(fields),
        "micro": micro,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "pass_counts": pass_counts,
        "per_field": per_field,
        "baselines": {
            "hybrid_gliner_qwen_allspans_micro_f1": ALLSPANS_MICRO,
            "unified_prompt_v2_micro_f1": PROMPT_V2_MICRO,
            "oracle_routing_micro_f1": ORACLE_MICRO,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "field",
                "tp",
                "fp",
                "fn",
                "gt_present",
                "pred_present",
                "precision",
                "recall",
                "f1",
            ],
        )
        w.writeheader()
        for field in fields:
            row = per_field[field]
            w.writerow(
                {
                    "field": field,
                    "tp": row["tp"],
                    "fp": row["fp"],
                    "fn": row["fn"],
                    "gt_present": row["gt_present"],
                    "pred_present": row["pred_present"],
                    "precision": row["precision"],
                    "recall": row["recall"],
                    "f1": row["f1"],
                }
            )

    print(json.dumps(summary, indent=2), flush=True)
    print(
        f"micro_f1={micro.get('f1')}  vs_prompt_v2={PROMPT_V2_MICRO}  "
        f"vs_allspans={ALLSPANS_MICRO}  vs_oracle={ORACLE_MICRO}",
        flush=True,
    )
    print(f"wrote {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
