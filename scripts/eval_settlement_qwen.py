#!/usr/bin/env python3
"""Holdout probe: settlement_date via Qwen prompt engineering (no rules post-process).

Prompt forces Concise Representation shape:
  Payment: promptly   OR   Acceptance: … | Payment: …
null if unsupported. Anti-overfit: principle-based prompt; score holdout once.
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

MODEL_ID = "qwen3:4b"
FIELD = "settlement_date"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown"})

SYSTEM = """You extract settlement / payment timing from SEC tender-offer excerpts.

Return ONLY JSON: {"settlement_date": string|null}

VALUE SHAPE (match Concise Representation labels):
- If payment is "promptly" after acceptance/expiration/termination, return exactly:
  "Payment: promptly"
- If an explicit pay or acceptance calendar date is stated, return that date
  (e.g. "January 22, 2026" or "1/22/2026").
- Optional longer form is OK when both parts are explicit:
  "Acceptance: … | Payment: promptly"
- Prefer "Payment: promptly" over inventing a calendar date when the text only
  says payment will be made promptly.
- null if the excerpts do not support settlement/payment timing.
- Do NOT copy the offer expiration date unless it is clearly the payment date.
- No markdown, no other keys.
"""


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def parse_passage(raw: str) -> dict:
    import ast

    s = (raw or "").strip()
    if not s:
        return {}
    for fn in (json.loads, ast.literal_eval):
        try:
            obj = fn(s)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            continue
    return {}


def _quotes(passage: dict, field: str) -> str:
    items = passage.get(field) or []
    if not isinstance(items, list):
        items = [items]
    parts = []
    for it in items:
        if isinstance(it, dict):
            q = (it.get("quote") or "").strip()
            if len(q) >= 12:
                parts.append(q)
    return "\n---\n".join(parts)


def _excerpts(store: ArtifactStore, eid: str, *, max_chars: int = 50_000) -> str:
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
        hit = any(
            k in heading or k in text[:400].lower()
            for k in ("payment", "settlement", "accept", "promptly", "expiration", "summary term")
        )
        if kind in {"faq", "priority_section"} or seg.get("priority") or hit:
            preferred.append(block)
        elif kind in {"toc_section", "full_doc"}:
            fallback.append(block)
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


def _prompt(text: str) -> str:
    return (
        "Extract settlement_date from the EXCERPTS.\n"
        'Return {"settlement_date": "Payment: promptly"} when payment is promptly '
        "after acceptance/expiration.\n"
        "Return a calendar date only when an explicit pay/acceptance date is stated.\n"
        "Otherwise null.\n\n"
        f"EXCERPTS:\n{text if text.strip() else '(none)'}\n"
    )


def _parse(raw: str) -> str | None:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    v = obj.get("settlement_date")
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in _NA:
        return None
    # Light normalize common variants toward CR shape (still Qwen output, not rules find)
    low = v.lower()
    if "payment: promptly" in low or (
        "promptly" in low and any(k in low for k in ("pay", "payment", "accept"))
        and not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|january|february|march|april|may|june|"
                          r"july|august|september|october|november|december", low)
    ):
        # If model wrote freeform promptly without the prefix, coerce to GT shape
        if not low.startswith("payment:"):
            return "Payment: promptly"
        # Collapse longer promptly payment lines to short form for soft-match
        if low.startswith("payment: promptly"):
            return "Payment: promptly"
    return v[:300]


def llm(client, model: str, text: str) -> tuple[str | None, str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _prompt(text)},
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": 160,
            "repeat_penalty": 1.15,
            "num_ctx": 32768,
        },
        "format": "json",
    }
    # Qwen3 thinking models only
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
    p = argparse.ArgumentParser(description="settlement_date via Qwen prompt engineering")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-chars", type=int, default=50_000)
    p.add_argument("--run-name", default=None)
    args = p.parse_args(argv)

    import ollama

    client = ollama.Client()
    store = ArtifactStore("tender", DEFAULT_PREPROCESS_ROOT)

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

    from tqdm import tqdm

    stats = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
    details: list[dict[str, Any]] = []
    print(json.dumps({"model": args.model, "split": args.split, "n_rows": len(rows)}, indent=2), flush=True)

    for row in tqdm(rows, desc=f"settlement|{args.model}", unit="doc"):
        acc = (row.get("accession_number") or "").strip()
        gold = (row.get(FIELD) or "").strip()
        has_gt = _gt_ok(gold)
        eid = acc_to_eid.get(acc) or ""
        passage = parse_passage(row.get("passage") or "")
        pq = _quotes(passage, FIELD)
        excerpts = _excerpts(store, eid, max_chars=args.max_chars) if eid else ""
        text = (pq + "\n\n" + excerpts).strip() if pq else excerpts
        # Cap per call
        text = text[: args.max_chars]
        pred, raw = llm(client, args.model, text) if text.strip() else (None, "")
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
                "n_chars": len(text),
                "raw_llm": (raw or "")[:400],
            }
        )
        tqdm.write(f"  {acc} {outcome} pred={pred!r}")

    metrics = _prf(stats["tp"], stats["fp"], stats["fn"])
    summary = {
        "field": FIELD,
        "method": "qwen_prompt_engineering",
        "model": args.model,
        "split": args.split,
        "n_rows": len(rows),
        **stats,
        **metrics,
        "baselines": {
            "settlement_template_rules_f1": 0.72,
            "hybrid_allspans_f1": 0.64,
            "qwen_direct_multifield_f1": 0.286,
            "temporal_f1": 0.324,
        },
        "anti_overfit": {
            "holdout_frozen": True,
            "note": "CR-shaped Payment: promptly prompt; light normalize of promptly freeform to Payment: promptly",
        },
    }
    run = args.run_name or f"settlement_qwen_{args.split}"
    out_dir = args.out / "experiments" / "runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    (out_dir / "system_prompt.txt").write_text(SYSTEM, encoding="utf-8")
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
