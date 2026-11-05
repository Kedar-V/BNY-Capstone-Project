#!/usr/bin/env python3
"""Holdout probe: Qwen3:4b direct extraction on all core tender fields.

No GLiNER spans — only filing segment text (FAQ + priority sections).
Offline only.
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
    load_gt,
    normalize,
    soft_match,
    gt_event_ids_from_corpus,
)
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

MODEL_ID = "qwen3:4b"
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—", "unknown", "not specified", "n/a"})

SYSTEM_PROMPT = """You are an information-extraction engine for SEC tender-offer filings (SC TO / Schedule TO / offer to purchase).

Your job: read the provided filing excerpts and fill a JSON object with the requested fields. Be precise, conservative, and consistent with how corporate-action Concise Representations are labeled.

OUTPUT
- Return ONE JSON object only. No markdown, no commentary.
- Use exactly the requested keys.
- Each value is a string or null.
- If the excerpts do not support a field, use null. Do not guess.

FIELD GUIDANCE
- subject_company: the target / issuer whose securities are sought (not the bidder).
- bidder: the offeror / purchasing party making the tender offer.
- security_description: the security being tendered (class/type), not the whole deal narrative.
- cusip: CUSIP only (9-character identifier). null if absent.
- isin: ISIN only. null if absent.
- ticker: exchange ticker symbol(s) only.
- offer_price: the consideration for tendered shares. Prefer an explicit cash amount when present (e.g. "$25.00 per share"). If the deal is NAV-based with no fixed cash figure, quote the short NAV phrasing (e.g. "net asset value per Share as of …"). Do not return a bare calendar day number.
- currency: ISO-like currency of the offer price (e.g. "USD"). Infer USD from $ only when clearly the offer currency.
- expiration_date: offer expiration date/time (include time/zone if stated).
- withdrawal_deadline: deadline to withdraw tendered shares (often same as expiration; only if supported).
- settlement_date: payment / acceptance timing. Prefer "Payment: promptly" when the filing says payment will be made promptly after acceptance; otherwise an explicit pay/accept date.
- effective_date: offer commencement / effective date only if explicitly stated.
- minimum_tender_condition: use exactly "No minimum tender condition" when there is none; otherwise the threshold clause (e.g. more than 50% of shares outstanding). If the text only says a Minimum Condition was satisfied without stating the threshold, null.
- proration_terms: the oversubscription / pro-rata sentence (usually starts with "If more than …"). null if not discussed.

STYLE
- Prefer short values that would soft-match structured ground truth.
- Copy critical numbers, dates, and identifiers faithfully.
- Do not merge unrelated parties into one field.
- Do not invent CUSIP/ISIN/ticker/price/date values that are not in the excerpts.
"""


def _gt_ok(val: str | None) -> bool:
    v = (val or "").strip()
    return bool(v) and v.lower() not in _NA


def _excerpts_for_event(store: ArtifactStore, eid: str, *, max_chars: int = 100_000) -> str:
    path = store.segments_path(eid)
    if not path.exists():
        return ""
    segs = list(store.read_json(path).get("segments") or [])
    # Prefer FAQ + priority; fall back to toc headings that look like summary terms
    preferred = []
    fallback = []
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


def _user_prompt(fields: tuple[str, ...], excerpts: str) -> str:
    keys = ", ".join(f'"{f}"' for f in fields)
    return (
        f"Extract these fields into JSON with keys: {keys}.\n\n"
        f"FILING EXCERPTS:\n{excerpts if excerpts.strip() else '(no excerpts available)'}\n"
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
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}


def llm_extract(client, model: str, fields: tuple[str, ...], excerpts: str) -> tuple[dict[str, Any], str]:
    resp = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(fields, excerpts)},
        ],
        options={
            "temperature": 0.0,
            "num_predict": 900,
            "repeat_penalty": 1.12,
            "num_ctx": 32768,  # Ollama default is 4096; model supports up to 262k
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
    p = argparse.ArgumentParser(description="Qwen direct extraction on core tender fields")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument(
        "--max-chars",
        type=int,
        default=100_000,
        help="Max excerpt chars per event (fits ~32k ctx at ~3.5 chars/token; was 24k)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--write-prompt", action="store_true", help="Write system prompt to run dir and exit")
    args = p.parse_args(argv)

    import ollama

    fields = CORE_GT_FIELDS
    out_dir = args.out / "experiments" / "runs" / "qwen_direct_holdout_core"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "system_prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    if args.write_prompt:
        print(out_dir / "system_prompt.txt")
        return 0

    client = ollama.Client()
    store = ArtifactStore("tender", DEFAULT_PREPROCESS_ROOT)
    print(json.dumps({"model": args.model, "n_fields": len(fields), "max_chars": args.max_chars}, indent=2))

    gt_rows = load_gt(args.gt)
    accessions = sorted(
        {(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")}
    )
    holdout = set(ensure_holdout(args.out, accessions, n=20))
    rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    if args.limit:
        rows = rows[: args.limit]
    acc_to_eid = (
        gt_event_ids_from_corpus(holdout, args.documents_parquet)
        if args.documents_parquet.exists()
        else {}
    )
    print(f"holdout rows: {len(rows)}  mapped events: {len(set(acc_to_eid.values()))}")

    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "gt_present": 0, "pred_present": 0} for f in fields}
    details: list[dict[str, Any]] = []

    for i, row in enumerate(rows, 1):
        acc = (row.get("accession_number") or "").strip()
        eid = acc_to_eid.get(acc)
        excerpts = _excerpts_for_event(store, eid, max_chars=args.max_chars) if eid else ""
        try:
            pred_obj, raw = llm_extract(client, args.model, fields, excerpts)
        except Exception as e:  # noqa: BLE001
            pred_obj, raw = {}, str(e)

        row_d: dict[str, Any] = {
            "accession": acc,
            "event_id": eid,
            "n_excerpt_chars": len(excerpts),
            "fields": {},
            "raw_llm": (raw or "")[:1000],
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
        print(f"[{i}/{len(rows)}] {acc} chars={len(excerpts)} tp_fields={n_tp}", flush=True)

    per_field = {f: {**stats[f], **_prf(stats[f]["tp"], stats[f]["fp"], stats[f]["fn"])} for f in fields}
    tp = sum(stats[f]["tp"] for f in fields)
    fp = sum(stats[f]["fp"] for f in fields)
    fn = sum(stats[f]["fn"] for f in fields)
    summary = {
        "model": args.model,
        "mode": "qwen_direct_segments",
        "system_prompt_path": str(out_dir / "system_prompt.txt"),
        "n_rows": len(rows),
        "fields": list(fields),
        "micro": _prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_field": per_field,
        "baselines": {
            "gliner_medium_micro_f1": 0.509,
            "hybrid_gliner_qwen_micro_f1": 0.439,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    with (out_dir / "per_field.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["field", "tp", "fp", "fn", "gt_present", "pred_present", "precision", "recall", "f1"],
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
