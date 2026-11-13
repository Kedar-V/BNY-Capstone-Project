#!/usr/bin/env python3
"""Holdout probe: effective_date via Qwen-only vs Temporal-spans→Qwen.

Modes:
  qwen     — FAQ/priority excerpts only (focused effective-date prompt)
  hybrid   — temporal NER date spans + local windows → Qwen chooses or nulls

Anti-overfit: no holdout-tuned thresholds; single holdout score after freeze.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import ensure_holdout
from src.evaluation.tender import (
    load_gt,
    soft_match,
    normalize,
    gt_event_ids_from_corpus,
)
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

import importlib.util

_temporal_path = ROOT / "scripts" / "eval_temporal_tagger_dates.py"
_spec = importlib.util.spec_from_file_location("eval_temporal_tagger_dates", _temporal_path)
_temporal = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_temporal)
DATE_FIELDS = _temporal.DATE_FIELDS
extract_timex = _temporal.extract_timex
_window = _temporal._window
_cue_score = _temporal._cue_score
parse_passage = _temporal.parse_passage
_quotes_for_field = _temporal._quotes_for_field
_all_date_quotes = _temporal._all_date_quotes

MODEL_ID = "qwen3:4b"
FIELD = "effective_date"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown"})

SYSTEM = (
    'Return only JSON {"effective_date": string|null}. '
    "effective_date is when the transaction legally takes effect "
    "(follow-on merger closed/consummated/effective, or issuer shares "
    "actually repurchased as-of a stated Valuation Date/time). "
    "Standalone tender offers usually have none. null unless explicitly "
    "supported. Never use commencement/start/'offer begins', Expiration Date, "
    "withdrawal deadlines, settlement/payment-only, or filing/notice/"
    "'first published' dates."
)


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _excerpts(store: ArtifactStore, eid: str, *, max_chars: int = 40_000) -> str:
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
        block = f"[{heading or 'section'}]\n{text}"
        if kind in {"faq", "priority_section"} or seg.get("priority") or "summary term" in heading:
            preferred.append(block)
        elif kind in {"toc_section", "full_doc"}:
            fallback.append(block)
        # Prefer commencement-ish headings
        if any(k in heading for k in ("commenc", "effective", "introduction", "summary")):
            preferred.insert(0, block)
    parts: list[str] = []
    n = 0
    for block in preferred + fallback:
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


def _temporal_evidence(tagger, passage: dict, excerpts: str, *, max_spans: int = 25) -> str:
    """Collect DATE/TIME spans with cue windows for Qwen to judge."""
    quotes = _quotes_for_field(passage, FIELD) or _all_date_quotes(passage)
    texts = list(quotes)
    if excerpts:
        # Chunk excerpts for NER (same max as temporal probe)
        for i in range(0, min(len(excerpts), 12_000), 1800):
            texts.append(excerpts[i : i + 1800])
    lines: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for sp in extract_timex(tagger, text):
            key = sp["text"].lower()
            if key in seen or len(key) < 4:
                continue
            seen.add(key)
            win = _window(text, sp["start"], sp["end"], radius=140)
            cues = {
                f: _cue_score(win, f)
                for f in DATE_FIELDS
            }
            lines.append(
                f"- date={sp['text']!r} label={sp['label']} "
                f"cues={cues} window={win[:220]!r}"
            )
            if len(lines) >= max_spans:
                return "\n".join(lines)
    return "\n".join(lines) if lines else "(no temporal spans)"


def _prompt_qwen(excerpts: str) -> str:
    return (
        "Extract effective_date: when the transaction legally takes effect "
        "(merger closed/consummated/effective, or issuer repurchase as-of), "
        "only if the text states it. Standalone tenders usually → null.\n"
        "Do not use commencement, expiration, settlement, or filing dates.\n"
        'Return JSON {"effective_date": string|null}.\n\n'
        f"EXCERPTS:\n{excerpts if excerpts.strip() else '(none)'}\n"
    )


def _prompt_hybrid(evidence: str) -> str:
    return (
        "Choose effective_date from TEMPORAL SPANS only (copy a listed date/time or null).\n"
        "GT meaning: legal effectiveness of the transaction — not offer start.\n"
        "ACCEPT only:\n"
        "1) Merger/acquisition closed, consummated, completed, or became legally "
        "effective on <date> (certificate/articles of merger filed/accepted).\n"
        "2) Issuer tender results: shares were repurchased/purchased as of <date> "
        "or Valuation Date/time when that is the stated repurchase as-of "
        "(include time/timezone if in the span/window).\n"
        "REJECT (return null if only these appear):\n"
        "- commencement / 'offer begins' / 'tender offer period will begin'\n"
        "- Expiration Date / expires / tender by <date>\n"
        "- withdrawal rights / '40 business days after commencement'\n"
        "- 'originally filed on' / 'first published' / notice dates\n"
        "- expected Closing Date, payment/settlement-only dates\n"
        "- NAV/valuation used only as a price basis, without repurchase-as-of language\n"
        "If no ACCEPT span is clear, return null. Prefer null over a guess.\n"
        'Return JSON {"effective_date": string|null}.\n\n'
        f"TEMPORAL SPANS:\n{evidence}\n"
    )


def _parse(raw: str) -> str | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        obj = json.loads(m.group(0)) if m else {}
    if not isinstance(obj, dict):
        return None
    v = obj.get("effective_date")
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in _NA:
        return None
    return v[:200]


def llm(client, model: str, user: str) -> tuple[str | None, str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": 120,
            "repeat_penalty": 1.15,
            "num_ctx": 32768,
        },
        "format": "json",
    }
    if "qwen3" in model.lower():
        kwargs["think"] = False
    resp = client.chat(**kwargs)
    raw = ""
    if isinstance(resp, dict):
        raw = (resp.get("message") or {}).get("content") or ""
    else:
        raw = getattr(getattr(resp, "message", None), "content", "") or ""
    return _parse(raw), raw


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="effective_date: Qwen vs Temporal→Qwen")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--mode", choices=("qwen", "hybrid", "both"), default="both")
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--device", default=None)
    args = p.parse_args(argv)

    import ollama
    import torch
    from transformers import pipeline

    client = ollama.Client()
    store = ArtifactStore("tender", DEFAULT_PREPROCESS_ROOT)

    tagger = None
    if args.mode in {"hybrid", "both"}:
        if args.device:
            device = args.device
        elif torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
        tagger = pipeline(
            "token-classification",
            model="satyaalmasian/temporal_tagger_BERT_tokenclassifier",
            aggregation_strategy="simple",
            device=0 if device in {"cuda", "mps"} else -1,
        )

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    if args.split == "holdout":
        rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    else:
        rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() not in holdout]
    if args.limit:
        rows = rows[: args.limit]

    acc_to_eid = (
        gt_event_ids_from_corpus(
            {(r.get("accession_number") or "").strip() for r in rows},
            args.documents_parquet,
        )
        if args.documents_parquet.exists()
        else {}
    )

    modes = ["qwen", "hybrid"] if args.mode == "both" else [args.mode]
    print(json.dumps({"modes": modes, "split": args.split, "n_rows": len(rows)}, indent=2))

    for mode in modes:
        stats = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
        details: list[dict[str, Any]] = []
        from tqdm import tqdm

        for row in tqdm(rows, desc=f"effective|{mode}|{args.model}", unit="doc"):
            acc = (row.get("accession_number") or "").strip()
            gold = (row.get(FIELD) or "").strip()
            has_gt = _gt_ok(gold)
            eid = acc_to_eid.get(acc) or ""
            excerpts = _excerpts(store, eid) if eid else ""
            passage = parse_passage(row.get("passage") or "")

            if mode == "qwen":
                # Prefer passage effective quotes + excerpts
                pq = "\n".join(_quotes_for_field(passage, FIELD))
                text = (pq + "\n\n" + excerpts).strip() if pq else excerpts
                pred, raw = llm(client, args.model, _prompt_qwen(text[:40_000]))
                evidence_n = len(text)
            else:
                assert tagger is not None
                evidence = _temporal_evidence(tagger, passage, excerpts)
                pred, raw = llm(client, args.model, _prompt_hybrid(evidence))
                evidence_n = len(evidence)

            has_pred = bool(normalize(pred))
            if has_gt:
                stats["gt_present"] += 1
            if has_pred:
                stats["pred_present"] += 1
            if has_gt and has_pred and soft_match(pred, gold):
                stats["tp"] += 1
                outcome = "tp"
            elif has_pred and not has_gt:
                stats["fp"] += 1
                outcome = "fp_no_gt"
            elif has_pred and has_gt:
                stats["fp"] += 1
                stats["fn"] += 1
                outcome = "mismatch"
            elif has_gt:
                stats["fn"] += 1
                outcome = "fn"
            else:
                outcome = "skip"

            details.append(
                {
                    "accession": acc,
                    "event_id": eid,
                    "outcome": outcome,
                    "gold": gold if has_gt else None,
                    "pred": pred,
                    "evidence_chars": evidence_n,
                    "raw_llm": (raw or "")[:300],
                }
            )
            tqdm.write(f"  [{mode}] {acc} {outcome} pred={pred!r}")

        metrics = _prf(stats["tp"], stats["fp"], stats["fn"])
        summary = {
            "field": FIELD,
            "mode": mode,
            "model": args.model,
            "split": args.split,
            "n_rows": len(rows),
            **stats,
            **metrics,
            "baselines": {
                "temporal_no_abstain_f1": 0.231,
                "temporal_abstain_v2_f1": 0.0,
                "qwen_direct_multifield_f1": None,
                "hybrid_gliner_qwen_f1": None,
            },
            "anti_overfit": {
                "holdout_frozen": True,
                "note": "Hybrid prompt aligned to GT: legal effectiveness (merger close / repurchase as-of); reject commence/expire/filed-on. No holdout threshold search.",
            },
        }
        model_tag = args.model.replace(":", "_").replace("/", "_")
        run = f"effective_date_{mode}_{model_tag}_{args.split}"
        out_dir = args.out / "experiments" / "runs" / run
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
        with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["field", "tp", "fp", "fn", "gt_present", "pred_present", "precision", "recall", "f1"],
            )
            w.writeheader()
            w.writerow(
                {
                    "field": FIELD,
                    "tp": stats["tp"],
                    "fp": stats["fp"],
                    "fn": stats["fn"],
                    "gt_present": stats["gt_present"],
                    "pred_present": stats["pred_present"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                }
            )
        print(json.dumps(summary, indent=2))
        print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
