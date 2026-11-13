#!/usr/bin/env python3
"""Settlement template probe: GT-shaped Payment: promptly / pay-date rules.

Tunable only on --split train. Holdout is scored once for reporting.
Does not call an LLM.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import ensure_holdout
from src.evaluation.tender import load_gt, soft_match, normalize
from src.preprocess.rules_ids import find_settlement

_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—"})


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


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _settlement_text(row: dict[str, Any], passage: dict) -> str:
    parts: list[str] = []
    items = passage.get("settlement_date") or []
    if not isinstance(items, list):
        items = [items]
    for it in items:
        if isinstance(it, dict):
            q = (it.get("quote") or "").strip()
            if q:
                parts.append(q)
    # Also skim other date/payment-ish quotes for promptly language
    for key in ("expiration_date", "withdrawal_deadline", "offer_price", "proration_terms"):
        items = passage.get(key) or []
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if isinstance(it, dict):
                q = (it.get("quote") or "").strip()
                if q and ("prompt" in q.lower() or "payment" in q.lower() or "accept" in q.lower()):
                    parts.append(q)
    return "\n".join(parts)


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Settlement Payment: promptly template eval")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--split", choices=("holdout", "train"), default="holdout")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--run-name", default=None)
    args = p.parse_args(argv)

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

    tp = fp = fn = gt_n = pred_n = 0
    details: list[dict[str, Any]] = []
    for row in rows:
        acc = (row.get("accession_number") or "").strip()
        gold = (row.get("settlement_date") or "").strip()
        has_gt = _gt_ok(gold)
        passage = parse_passage(row.get("passage") or "")
        text = _settlement_text(row, passage)
        pred = find_settlement(text) if text else None
        has_pred = bool(normalize(pred))
        if has_gt:
            gt_n += 1
        if has_pred:
            pred_n += 1
        if has_gt and has_pred and soft_match(pred, gold):
            tp += 1
            outcome = "tp"
        elif has_pred and not has_gt:
            fp += 1
            outcome = "fp_no_gt"
        elif has_pred and has_gt:
            fp += 1
            fn += 1
            outcome = "mismatch"
        elif has_gt:
            fn += 1
            outcome = "fn"
        else:
            outcome = "skip"
        details.append(
            {
                "accession": acc,
                "outcome": outcome,
                "gold": gold if has_gt else None,
                "pred": pred,
                "n_chars": len(text),
            }
        )

    metrics = _prf(tp, fp, fn)
    summary = {
        "method": "find_settlement promptly-first template",
        "split": args.split,
        "n_rows": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "gt_present": gt_n,
        "pred_present": pred_n,
        **metrics,
        "anti_overfit": {
            "holdout_frozen": True,
            "note": "Promptly-before-date priority is principle-based (GT CR shape); validate on train, score holdout once.",
        },
        "prior_holdout_f1": {
            "hybrid_allspans": 0.64,
            "settlement_rules_v2": 0.56,
            "temporal": 0.324,
            "qwen_direct": 0.286,
        },
    }

    run_name = args.run_name or (
        "settlement_template_holdout"
        if args.split == "holdout"
        else "settlement_template_train"
    )
    out_dir = args.out / "experiments" / "runs" / run_name
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
                "field": "settlement_date",
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "gt_present": gt_n,
                "pred_present": pred_n,
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
