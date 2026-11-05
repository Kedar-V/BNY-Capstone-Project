#!/usr/bin/env python3
"""Holdout probe: HuggingFace temporal NER on the four tender date fields.

Uses satyaalmasian/temporal_tagger_BERT_tokenclassifier to find DATE/TIME spans
in GT passage quotes, then cue-maps to:
  expiration_date / withdrawal_deadline / settlement_date / effective_date

Does not touch the GLiNER pipeline — offline comparison only.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import ensure_holdout
from src.evaluation.tender import load_gt, soft_match, normalize

DATE_FIELDS = (
    "expiration_date",
    "withdrawal_deadline",
    "settlement_date",
    "effective_date",
)

MODEL_ID = "satyaalmasian/temporal_tagger_BERT_tokenclassifier"

# Cue lexicons for field assignment (window around each TIMEX span).
FIELD_CUES: dict[str, tuple[str, ...]] = {
    "expiration_date": (
        "expir",
        "offer period",
        "offer will expire",
        "termination of the offer",
        "until",
    ),
    "withdrawal_deadline": (
        "withdraw",
        "withdrawal",
        "rights of withdrawal",
    ),
    "settlement_date": (
        "settlement",
        "payment",
        "pay for",
        "acceptance for payment",
        "promptly",
        "accept for payment",
    ),
    "effective_date": (
        "effective",
        "commencement",
        "commence",
        "offer commenced",
    ),
}

_WS = re.compile(r"\s+")
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—"})


def parse_passage(raw: str) -> dict:
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


def _quotes_for_field(passage: dict, field: str) -> list[str]:
    items = passage.get(field) or []
    if not isinstance(items, list):
        items = [items]
    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            q = (it.get("quote") or "").strip()
            if len(q) >= 8:
                out.append(q)
    return out


def _all_date_quotes(passage: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in DATE_FIELDS:
        for q in _quotes_for_field(passage, f):
            key = q[:200]
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _window(text: str, start: int, end: int, radius: int = 120) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return text[a:b].lower()


def _cue_score(window: str, field: str) -> int:
    return sum(1 for c in FIELD_CUES[field] if c in window)


def extract_timex(
    tagger,
    text: str,
    *,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    """Run token-classification NER; return DATE/TIME-ish spans with offsets."""
    if not text:
        return []
    chunk = text if len(text) <= max_chars else text[:max_chars]
    raw = tagger(chunk)
    spans: list[dict[str, Any]] = []
    for ent in raw:
        label = (ent.get("entity_group") or ent.get("entity") or "").upper()
        # Accept DATE/TIME (+ TIMEX if model variant uses it)
        if not any(k in label for k in ("DATE", "TIME", "TIMEX", "DURATION")):
            continue
        # Skip pure durations/sets for field assignment preference later
        word = (ent.get("word") or "").replace(" ##", "").replace("##", "").strip()
        word = _WS.sub(" ", word)
        if len(word) < 4:
            continue
        spans.append(
            {
                "text": word,
                "label": label,
                "score": float(ent.get("score") or 0),
                "start": int(ent.get("start") or 0),
                "end": int(ent.get("end") or 0),
            }
        )
    return spans


def assign_fields(
    quotes: list[str],
    tagger,
) -> dict[str, str | None]:
    """Pick best DATE/TIME span per field via cue proximity."""
    best: dict[str, tuple[float, str]] = {}
    for quote in quotes:
        spans = extract_timex(tagger, quote)
        for sp in spans:
            win = _window(quote, sp["start"], sp["end"])
            for field in DATE_FIELDS:
                cues = _cue_score(win, field)
                # Prefer DATE over TIME/DURATION; cue hits matter most
                lab = sp["label"]
                lab_bonus = 0.15 if "DATE" in lab else (0.05 if "TIME" in lab else 0.0)
                score = cues * 1.0 + lab_bonus + 0.1 * sp["score"]
                # Require at least one cue unless only one field has GT later (caller filters)
                if cues == 0:
                    score -= 0.5
                prev = best.get(field)
                if prev is None or score > prev[0]:
                    best[field] = (score, sp["text"])
    return {f: (best[f][1] if f in best else None) for f in DATE_FIELDS}


def span_hit_any(quotes: list[str], gold: str, tagger) -> tuple[bool, str | None]:
    """True if any extracted DATE/TIME soft-matches gold (span recall)."""
    for quote in quotes:
        for sp in extract_timex(tagger, quote):
            if soft_match(sp["text"], gold):
                return True, sp["text"]
        # also: gold substring present but model missed → still count miss
    return False, None


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    if p is None or r is None or (p + r) == 0:
        f1 = None
    else:
        f1 = 2 * p * r / (p + r)
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe temporal NER on tender date fields")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--device", default=None, help="cpu / mps / cuda (default: auto)")
    p.add_argument("--limit", type=int, default=None, help="Limit GT rows (debug)")
    args = p.parse_args(argv)

    from transformers import pipeline
    import torch

    if args.device:
        device = args.device
    elif torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    print(json.dumps({"model": args.model, "device": device}, indent=2))
    tagger = pipeline(
        "token-classification",
        model=args.model,
        aggregation_strategy="simple",
        device=0 if device in {"cuda", "mps"} else -1,
    )

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    if args.limit:
        rows = rows[: args.limit]
    print(f"holdout rows: {len(rows)}")

    # Field-assignment counters
    stats: dict[str, dict[str, int]] = {
        f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in DATE_FIELDS
    }
    # Span-recall: among rows with GT + field quotes, did NER find a matching date?
    span_rec: dict[str, dict[str, int]] = {f: {"hit": 0, "miss": 0, "no_quote": 0} for f in DATE_FIELDS}
    details: list[dict[str, Any]] = []

    for row in rows:
        acc = (row.get("accession_number") or "").strip()
        passage = parse_passage(row.get("passage") or "")
        field_quotes = {f: _quotes_for_field(passage, f) for f in DATE_FIELDS}
        all_quotes = _all_date_quotes(passage)
        # Prefer field-specific quotes; fall back to all date quotes for assignment
        assign_text = all_quotes or [q for qs in field_quotes.values() for q in qs]
        preds = assign_fields(assign_text, tagger) if assign_text else {f: None for f in DATE_FIELDS}

        row_detail: dict[str, Any] = {"accession": acc, "fields": {}}
        for field in DATE_FIELDS:
            gold = (row.get(field) or "").strip()
            has_gt = _gt_ok(gold)
            pred = preds.get(field)
            has_pred = bool(normalize(pred))
            s = stats[field]
            if has_gt:
                s["gt_present"] += 1
            if has_pred:
                s["pred_present"] += 1

            if has_gt and has_pred and soft_match(pred, gold):
                s["tp"] += 1
                outcome = "tp"
            elif has_pred and not has_gt:
                s["fp"] += 1
                outcome = "fp_no_gt"
            elif has_pred and has_gt:
                s["fp"] += 1
                s["fn"] += 1
                outcome = "mismatch"
            elif has_gt:
                s["fn"] += 1
                outcome = "fn"
            else:
                outcome = "skip"

            # Span recall on field quotes (or all date quotes)
            quotes = field_quotes[field] or all_quotes
            span_hit = None
            span_pred = None
            if has_gt:
                if not quotes:
                    span_rec[field]["no_quote"] += 1
                else:
                    ok, span_pred = span_hit_any(quotes, gold, tagger)
                    span_hit = ok
                    span_rec[field]["hit" if ok else "miss"] += 1

            row_detail["fields"][field] = {
                "outcome": outcome,
                "gold": gold if has_gt else None,
                "pred": pred,
                "span_hit": span_hit,
                "span_pred": span_pred,
                "n_quotes": len(field_quotes[field]),
            }
        details.append(row_detail)
        print(f"  scored {acc}")

    per_field: dict[str, Any] = {}
    for f in DATE_FIELDS:
        s = stats[f]
        metrics = _prf(s["tp"], s["fp"], s["fn"])
        sr = span_rec[f]
        denom = sr["hit"] + sr["miss"]
        per_field[f] = {
            **s,
            **metrics,
            "span_recall": (sr["hit"] / denom) if denom else None,
            "span_hit": sr["hit"],
            "span_miss": sr["miss"],
            "span_no_quote": sr["no_quote"],
        }

    # micro over date fields
    tp = sum(stats[f]["tp"] for f in DATE_FIELDS)
    fp = sum(stats[f]["fp"] for f in DATE_FIELDS)
    fn = sum(stats[f]["fn"] for f in DATE_FIELDS)
    summary = {
        "model": args.model,
        "device": device,
        "n_rows": len(rows),
        "micro": _prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_field": per_field,
        "baseline_gliner_medium_holdout_f1": {
            "expiration_date": 0.162,
            "withdrawal_deadline": 0.200,
            "settlement_date": 0.0,
            "effective_date": 0.0,
        },
    }

    out_dir = args.out / "experiments" / "runs" / "temporal_tagger_holdout_dates"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")

    # CSV for quick glance
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
                "span_recall",
            ],
        )
        w.writeheader()
        for field in DATE_FIELDS:
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
                    "span_recall": row["span_recall"],
                }
            )

    print(json.dumps(summary, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
