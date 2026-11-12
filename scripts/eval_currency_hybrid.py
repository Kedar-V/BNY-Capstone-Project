#!/usr/bin/env python3
"""Holdout probe: currency via price/currency spans → Qwen (hybrid).

Evidence = GT passage quotes (offer_price / offer_price_currency / currency)
plus GLiNER spans whose field_hint is currency or offer_price. Qwen chooses
ISO code or null using the tender GT currency rules.

Anti-overfit: no holdout-tuned thresholds; score holdout once after freeze.
"""

from __future__ import annotations

import argparse
import ast
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
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT

MODEL_ID = "qwen3:4b"
FIELD = "currency"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown"})

SYSTEM = (
    'Return only JSON {"currency": string|null}. '
    "currency is the per-security cash offer price currency only. Prefer an "
    "explicit three-letter code (USD, EUR, GBP, …) or the words "
    '"U.S. dollars". Map $→USD / £→GBP / €→EUR ONLY when that symbol prices '
    "the tender (e.g. '$25.00 per Share', 'purchase price of $…'). "
    "null for silence, share-for-share/noncash, NAV-only funds without a cash "
    "offer price, par value, fees, aggregate offering size, or total payment "
    "amounts. Do not invent a currency from a lone $."
)

# Explicit ISO / currency words (generic; not holdout-tuned).
_EXPLICIT_CCY = re.compile(
    r"(?i)\b(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|U\.?\s*S\.?\s*dollars?|euros?|pounds?\s+sterling)\b"
)
# Cash tender / purchase price cue near a currency symbol (not par value).
_OFFER_PRICE_CUE = re.compile(
    r"(?i)(?:purchase\s+price|offer\s+price|cash\s+consideration|"
    r"tender(?:ed)?\s+at\s+a\s+price|price\s+per\s+(?:share|unit)|"
    r"\$\s*\d[\d,]*(?:\.\d+)?\s*(?:in\s+cash|per\s+(?:share|unit)))"
)
_DOLLAR = re.compile(r"[$£€]")
_PAR_VALUE = re.compile(r"(?i)par\s+value")


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


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


def _quotes(passage: dict, *fields: str, max_chars: int = 1800) -> list[str]:
    parts: list[str] = []
    n = 0
    for field in fields:
        items = passage.get(field) or []
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if not isinstance(it, dict):
                continue
            q = (it.get("quote") or "").strip()
            if len(q) < 8:
                continue
            if n + len(q) > max_chars:
                q = q[: max(0, max_chars - n)]
            if q:
                parts.append(f"[{field}] {q}")
                n += len(q)
            if n >= max_chars:
                return parts
    return parts


def _load_spans(eid: str) -> list[dict[str, Any]]:
    p = Path(DEFAULT_PREPROCESS_ROOT) / "tender" / "events" / eid / "spans.json"
    if not p.exists():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("spans") or [])


def _span_evidence(spans: list[dict[str, Any]], *, max_n: int = 20) -> list[str]:
    lines: list[str] = []
    for sp in spans:
        hint = (sp.get("field_hint") or sp.get("label") or "").lower()
        if hint not in {"currency", "offer_price", "price", "offerprice"}:
            continue
        raw = str(sp.get("text") or sp.get("raw") or "").strip()
        if not raw:
            continue
        ctx = str(sp.get("passage") or sp.get("segment_text") or "")[:180].replace("\n", " ")
        conf = sp.get("score") or sp.get("confidence")
        conf_s = f" score={float(conf):.2f}" if conf is not None else ""
        lines.append(f"- hint={hint}{conf_s} value={raw[:120]!r} context={ctx!r}")
        if len(lines) >= max_n:
            break
    return lines


def _build_evidence(passage: dict, spans: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    quotes = _quotes(passage, "offer_price_currency", "currency", "offer_price")
    if quotes:
        blocks.append("PASSAGE QUOTES:\n" + "\n---\n".join(quotes))
    span_lines = _span_evidence(spans)
    if span_lines:
        blocks.append("GLINER SPANS:\n" + "\n".join(span_lines))
    return "\n\n".join(blocks) if blocks else "(no currency/price evidence)"


def _prompt(evidence: str) -> str:
    return (
        "Choose currency for the cash offer price from the evidence below.\n"
        "GT rules:\n"
        "1) Explicit code / 'U.S. dollars' → that ISO code.\n"
        "2) Per-share/unit cash tender price with only $ / £ / € "
        "(e.g. '$25.00 per Share') → USD / GBP / EUR.\n"
        "3) Otherwise null. Reject: par value $, fees, aggregate/$ million, "
        "NAV-only, total payment amounts, or a lone $ with no per-unit offer price.\n"
        "4) Prefer null over a guess.\n"
        'Return JSON {"currency": string|null}.\n\n'
        f"EVIDENCE:\n{evidence}\n"
    )


def _support_level(evidence: str) -> str:
    """Return 'explicit' | 'offer_symbol' | 'none' from evidence text."""
    if not evidence or evidence.startswith("(no currency"):
        return "none"
    if _EXPLICIT_CCY.search(evidence):
        return "explicit"
    # Require an offer-price cue and a currency symbol that is not only par-value $.
    if _OFFER_PRICE_CUE.search(evidence) and _DOLLAR.search(evidence):
        # If every $ sits inside a 'par value … $' window, treat as unsupported.
        weak_only = True
        for m in _DOLLAR.finditer(evidence):
            window = evidence[max(0, m.start() - 40) : m.end() + 10]
            if not _PAR_VALUE.search(window):
                weak_only = False
                break
        if not weak_only:
            return "offer_symbol"
    return "none"


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
    v = obj.get("currency")
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in _NA:
        return None
    # Normalize common symbol answers to ISO when model ignores mapping
    sym = {"$": "USD", "£": "GBP", "€": "EUR", "us$": "USD", "u.s.$": "USD"}
    if v in sym:
        return sym[v]
    if re.fullmatch(r"[A-Za-z]{3}", v):
        return v.upper()
    return v[:32]


def _gate_currency(pred: str | None, evidence: str) -> str | None:
    """Drop symbol-inferred ISO codes unless evidence supports them.

    Keeps explicit-code predictions; blocks lone-$ → USD hallucinations.
    """
    if not pred:
        return None
    level = _support_level(evidence)
    if level == "explicit":
        return pred
    if level == "offer_symbol" and pred in {"USD", "GBP", "EUR"}:
        return pred
    # Model invented an ISO code without support → abstain
    return None


def llm(client, model: str, user: str) -> tuple[str | None, str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": 60,
            "repeat_penalty": 1.15,
            "num_ctx": 16384,
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
    p = argparse.ArgumentParser(description="currency: passage/GLiNER spans → Qwen")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--run-name", default=None)
    p.add_argument("--gate", action="store_true",
                   help="Deterministic support gate: drop ISO preds without explicit/offer-price support")
    args = p.parse_args(argv)

    import ollama
    from tqdm import tqdm

    client = ollama.Client()
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

    print(json.dumps({"model": args.model, "split": args.split, "n_rows": len(rows)}, indent=2))

    stats = {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0}
    details: list[dict[str, Any]] = []

    for row in tqdm(rows, desc=f"currency|hybrid|{args.model}", unit="doc"):
        acc = (row.get("accession_number") or "").strip()
        gold = (row.get(FIELD) or "").strip()
        has_gt = _gt_ok(gold)
        eid = acc_to_eid.get(acc) or ""
        passage = parse_passage(row.get("passage") or "")
        spans = _load_spans(eid) if eid else []
        evidence = _build_evidence(passage, spans)
        raw_pred, raw = llm(client, args.model, _prompt(evidence))
        support = _support_level(evidence)
        pred = _gate_currency(raw_pred, evidence) if args.gate else raw_pred
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
                "raw_pred": raw_pred,
                "support": support,
                "gated": raw_pred != pred,
                "evidence_chars": len(evidence),
                "raw_llm": (raw or "")[:300],
            }
        )
        tqdm.write(
            f"  {acc} {outcome} pred={pred!r} raw_pred={raw_pred!r} "
            f"support={support} gold={gold if has_gt else None!r}"
        )

    metrics = _prf(stats["tp"], stats["fp"], stats["fn"])
    summary = {
        "field": FIELD,
        "mode": "hybrid_spans_qwen",
        "model": args.model,
        "split": args.split,
        "n_rows": len(rows),
        **stats,
        **metrics,
        "baselines": {
            "rules_f1": 0.267,
            "qwen_direct_f1": 0.16,
            "hybrid_allspans_f1": 0.167,
            "accounting_ner_f1": 0.235,
        },
        "anti_overfit": {
            "holdout_frozen": True,
            "note": "GT-aligned currency prompt; optional --gate blocks ISO without explicit/offer-price support. No holdout threshold search.",
        },
    }
    model_tag = args.model.replace(":", "_").replace("/", "_")
    run = args.run_name or f"currency_hybrid_{model_tag}_{args.split}"
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
