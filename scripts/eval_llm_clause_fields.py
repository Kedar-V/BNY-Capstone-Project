#!/usr/bin/env python3
"""Holdout probe: small local LLM (Ollama qwen3:4b) on clause fields.

Fields: minimum_tender_condition, proration_terms
Offline only — does not change the GLiNER pipeline.
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
from src.evaluation.tender import load_gt, soft_match, normalize

FIELDS = ("minimum_tender_condition", "proration_terms")
MODEL_ID = "qwen3:4b"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "null", "none found"})
_JSON_OBJ = re.compile(r"\{[^{}]*\}", re.S)


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


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _quotes(passage: dict, field: str, *, max_chars: int = 2200) -> str:
    items = passage.get(field) or []
    if not isinstance(items, list):
        items = [items]
    parts: list[str] = []
    n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        q = (it.get("quote") or "").strip()
        if len(q) < 12:
            continue
        if n + len(q) > max_chars:
            q = q[: max(0, max_chars - n)]
        parts.append(q)
        n += len(q)
        if n >= max_chars:
            break
    return "\n---\n".join(parts)


def _prompt(field: str, text: str) -> str:
    if field == "minimum_tender_condition":
        return (
            "From the EXCERPT, copy the minimum tender condition into JSON "
            '{"value": "..."}.\n'
            'If there is no minimum, value must be exactly "No minimum tender condition".\n'
            "If only a %/share threshold is given, copy that sentence.\n"
            "If the excerpt only says a Minimum Condition was satisfied (no threshold), "
            '{"value": null}.\n'
            "Output keys allowed: value only.\n\n"
            "Example: {\"value\": \"No minimum tender condition\"}\n"
            "Example: {\"value\": \"at least one share more than 50% of shares outstanding\"}\n\n"
            f"EXCERPT:\n{text}\n"
        )
    return (
        "From the EXCERPT, copy the proration / oversubscription sentence into JSON "
        '{"value": "..."}.\n'
        "It usually starts with 'If more than ...'. Keep one sentence.\n"
        'If none, {"value": null}. Output keys allowed: value only.\n\n'
        'Example: {"value": "If more than 5% of Shares are duly tendered and not withdrawn, '
        'the Fund will accept Shares pro rata."}\n\n'
        f"EXCERPT:\n{text}\n"
    )


def _parse_value(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        # Model sometimes echoes the prompt as {"task","rules",...} — drop those.
        echo_keys = {"task", "rules", "excerpts", "excerpt", "examples", "output"}
        if echo_keys & set(obj) and "value" not in obj:
            return None
        if "value" in obj:
            v = obj.get("value")
            if v is None:
                return None
            v = str(v).strip()
            if not v or v.lower() in _NA:
                return None
            if v.lower().startswith(("extract ", "task", "field:")):
                return None
            return v[:600]
    m = re.search(r'"value"\s*:\s*("((?:\\.|[^"\\])*)"|null)', s)
    if m:
        if m.group(1) == "null":
            return None
        v = json.loads(m.group(1))
        v = str(v).strip()
        if not v or v.lower() in _NA:
            return None
        if v.lower().startswith(("extract ", "task")):
            return None
        return v[:600]
    return None


def llm_extract(client, model: str, field: str, text: str) -> tuple[str | None, str]:
    if not text.strip():
        return None, ""
    # Shrink aggressively on retries (repeat-limit aborts on long SEC prose)
    chunks = [text[:2200], text[:1200], text[:700]]
    last_err = ""
    for attempt, chunk in enumerate(chunks):
        try:
            resp = client.chat(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": 'Return only {"value": string|null}. No other keys.',
                    },
                    {"role": "user", "content": _prompt(field, chunk)},
                ],
                options={
                    "temperature": 0.0,
                    "num_predict": 160,
                    "repeat_penalty": 1.2,
                    "num_ctx": 32768,
                },
                format="json",
                think=False,
            )
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue
        raw = ""
        if isinstance(resp, dict):
            raw = (resp.get("message") or {}).get("content") or ""
        else:
            raw = getattr(getattr(resp, "message", None), "content", "") or ""
        val = _parse_value(raw)
        if val is not None:
            return val, raw
        # Retry on empty/null or instruction-echo JSON
        if '"task"' in raw or '"rules"' in raw or '"excerpts"' in raw:
            last_err = "echo_json"
            continue
        if raw.strip():
            # valid null answer
            return None, raw
    return None, last_err


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe Ollama LLM on clause fields")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    import ollama

    client = ollama.Client()
    print(json.dumps({"model": args.model, "fields": list(FIELDS)}, indent=2))

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    if args.limit:
        rows = rows[: args.limit]
    print(f"holdout rows: {len(rows)}")

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in FIELDS}
    details: list[dict[str, Any]] = []

    for i, row in enumerate(rows, 1):
        acc = (row.get("accession_number") or "").strip()
        passage = parse_passage(row.get("passage") or "")
        row_d: dict[str, Any] = {"accession": acc, "fields": {}}
        for field in FIELDS:
            gold = (row.get(field) or "").strip()
            has_gt = _gt_ok(gold)
            text = _quotes(passage, field)
            pred, raw = llm_extract(client, args.model, field, text) if text else (None, "")
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

            row_d["fields"][field] = {
                "outcome": outcome,
                "gold": gold if has_gt else None,
                "pred": pred,
                "n_quote_chars": len(text),
                "raw_llm": (raw or "")[:400],
            }
        details.append(row_d)
        print(
            f"[{i}/{len(rows)}] {acc}  "
            f"min={row_d['fields']['minimum_tender_condition']['outcome']}  "
            f"pro={row_d['fields']['proration_terms']['outcome']}"
        )

    per_field: dict[str, Any] = {}
    for f in FIELDS:
        s = stats[f]
        per_field[f] = {**s, **_prf(s["tp"], s["fp"], s["fn"])}

    tp = sum(stats[f]["tp"] for f in FIELDS)
    fp = sum(stats[f]["fp"] for f in FIELDS)
    fn = sum(stats[f]["fn"] for f in FIELDS)
    summary = {
        "model": args.model,
        "n_rows": len(rows),
        "micro": _prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_field": per_field,
        "baseline_gliner_medium_holdout_f1": {
            "minimum_tender_condition": 0.0,
            "proration_terms": 0.0,
        },
    }

    out_dir = args.out / "experiments" / "runs" / "llm_qwen3_4b_holdout_clauses"
    out_dir.mkdir(parents=True, exist_ok=True)
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
        for field in FIELDS:
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

    print(json.dumps(summary, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
