#!/usr/bin/env python3
"""Holdout probe: GLiNER spans → Qwen3:4b field extraction (hybrid).

For each holdout GT row, collect ranked GLiNER candidate_facts / spans for the
event, pack them as evidence, and ask local Ollama qwen3:4b to emit JSON values
for core fields. Soft-match vs GT. Offline only.
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
    CORE_GT_FIELDS,
    GT_TO_HINT,
    load_gt,
    normalize,
    soft_match,
    gt_event_ids_from_corpus,
)
from src.preprocess.rules_ids import RULE_FIELD_HINTS
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT

MODEL_ID = "qwen3:4b"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—"})
MAX_PASSAGE = 220
MAX_RAW = 160


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _load_rep(eid: str) -> dict[str, Any]:
    p = Path(DEFAULT_PREPROCESS_ROOT) / "tender" / "events" / eid / "concise" / "event_rep.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_spans(eid: str) -> list[dict[str, Any]]:
    p = Path(DEFAULT_PREPROCESS_ROOT) / "tender" / "events" / eid / "spans.json"
    if not p.exists():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("spans") or [])


def _evidence_lines(rep: dict, spans: list[dict]) -> list[str]:
    """Pass ALL GLiNER spans to the LLM — no ranking / top-k / filtering.

    Also appends rules-owned candidate_facts (cusip/isin/ticker/…) so IDs are
    still visible; those are not GLiNER spans but are already in the rep.
    """
    lines: list[str] = []
    # 1) Every GLiNER span, document order (no score sort)
    for sp in spans:
        raw = str(sp.get("text") or sp.get("raw") or "").strip()
        if not raw:
            continue
        raw = raw[:MAX_RAW]
        hint = sp.get("field_hint") or sp.get("label") or "?"
        label = sp.get("label") or ""
        passage = str(sp.get("passage") or sp.get("segment_text") or "")[:MAX_PASSAGE].replace("\n", " ")
        conf = sp.get("score") or sp.get("confidence")
        conf_s = f" score={float(conf):.2f}" if conf is not None else ""
        lab_s = f" label={label}" if label and label != hint else ""
        lines.append(
            f"- field={hint}{lab_s}{conf_s} value={raw!r}"
            + (f" context={passage!r}" if passage else "")
        )

    # 2) Rules facts from concise rep (not ranked; skip empties)
    for f in rep.get("candidate_facts") or []:
        if (f.get("method") or "") != "rules":
            continue
        raw = str(f.get("raw") or "").strip()[:MAX_RAW]
        if not raw:
            continue
        hint = f.get("field_hint") or "?"
        passage = str(f.get("passage") or f.get("segment_text") or "")[:MAX_PASSAGE].replace("\n", " ")
        lines.append(
            f"- field={hint} method=rules value={raw!r}"
            + (f" context={passage!r}" if passage else "")
        )
    return lines


def _prompt(evidence: list[str], fields: tuple[str, ...]) -> str:
    field_list = ", ".join(fields)
    bullets = "\n".join(evidence) if evidence else "(no spans)"
    return (
        "You extract tender-offer fields using ONLY the GLiNER/rules spans below.\n"
        "All spans from the model are listed — none were pre-filtered or ranked for you.\n"
        "Return a JSON object with exactly these keys:\n"
        f"  {field_list}\n"
        "Rules:\n"
        "- Map each field to the best matching span value (use field=/label= as a hint).\n"
        "- You may lightly normalize (e.g. keep '$25.00', 'No minimum tender condition').\n"
        "- If several spans compete for a field, pick one — do not leave it null when a "
        "plausible span exists (especially subject_company / bidder / offeror / target).\n"
        "- null only when no span supports that field.\n"
        "- Do not invent ISINs/CUSIPs/dates/prices that are not in the spans.\n"
        "- Output JSON only.\n\n"
        f"SPANS ({len(evidence)}):\n{bullets}\n"
    )


def _parse_obj(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
    return {}


def llm_extract(client, model: str, evidence: list[str], fields: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    resp = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": "Return one JSON object only. Values are strings or null."},
            {"role": "user", "content": _prompt(evidence, fields)},
        ],
        options={
            "temperature": 0.0,
            "num_predict": 700,
            "repeat_penalty": 1.15,
            "num_ctx": 32768,
        },
        format="json",
        think=False,
    )
    raw = ""
    if isinstance(resp, dict):
        raw = (resp.get("message") or {}).get("content") or ""
    else:
        raw = getattr(getattr(resp, "message", None), "content", "") or ""
    return _parse_obj(raw), raw


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Hybrid GLiNER spans → Qwen holdout probe")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--fields", choices=["core", "gliner"], default="core",
                   help="core=all CORE_GT_FIELDS; gliner=exclude rules-owned hints")
    args = p.parse_args(argv)

    import ollama

    fields = CORE_GT_FIELDS
    if args.fields == "gliner":
        fields = tuple(f for f in CORE_GT_FIELDS if GT_TO_HINT[f] not in RULE_FIELD_HINTS)

    client = ollama.Client()
    print(json.dumps({"model": args.model, "n_fields": len(fields), "fields": list(fields)}, indent=2))

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    if args.limit:
        rows = rows[: args.limit]

    acc_to_eid = {}
    if args.documents_parquet.exists():
        acc_to_eid = gt_event_ids_from_corpus(holdout, args.documents_parquet)
    print(f"holdout rows: {len(rows)}  mapped events: {len(set(acc_to_eid.values()))}")

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    details: list[dict[str, Any]] = []

    for i, row in enumerate(rows, 1):
        acc = (row.get("accession_number") or "").strip()
        eid = acc_to_eid.get(acc)
        rep = _load_rep(eid) if eid else {}
        spans = _load_spans(eid) if eid else []
        evidence = _evidence_lines(rep, spans)
        try:
            pred_obj, raw = llm_extract(client, args.model, evidence, fields)
        except Exception as e:  # noqa: BLE001
            pred_obj, raw = {}, str(e)

        row_d: dict[str, Any] = {
            "accession": acc,
            "event_id": eid,
            "n_evidence": len(evidence),
            "fields": {},
            "raw_llm": (raw or "")[:800],
        }
        for field in fields:
            gold = (row.get(field) or "").strip()
            has_gt = _gt_ok(gold)
            pred_raw = pred_obj.get(field)
            pred = None if pred_raw is None else str(pred_raw).strip()
            if pred and pred.lower() in _NA:
                pred = None
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
            }
        details.append(row_d)
        n_tp = sum(1 for f in fields if row_d["fields"][f]["outcome"] == "tp")
        print(f"[{i}/{len(rows)}] {acc} evidence={len(evidence)} tp_fields={n_tp}")

    per_field: dict[str, Any] = {}
    for f in fields:
        s = stats[f]
        per_field[f] = {**s, **_prf(s["tp"], s["fp"], s["fn"])}

    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    summary = {
        "model": args.model,
        "hybrid": "gliner_all_spans→qwen",
        "evidence": "all GLiNER spans (no rank/top-k) + rules facts",
        "n_rows": len(rows),
        "fields": list(fields),
        "micro": _prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_field": per_field,
        "baseline_hybrid_topk_micro_f1": 0.439,
    }

    out_dir = args.out / "experiments" / "runs" / "hybrid_gliner_qwen_allspans_holdout"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "field", "tp", "fp", "fn", "gt_present", "pred_present",
                "precision", "recall", "f1",
            ],
        )
        w.writeheader()
        for field in fields:
            row = per_field[field]
            w.writerow({
                "field": field,
                "tp": row["tp"],
                "fp": row["fp"],
                "fn": row["fn"],
                "gt_present": row["gt_present"],
                "pred_present": row["pred_present"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
            })

    print(json.dumps(summary, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
