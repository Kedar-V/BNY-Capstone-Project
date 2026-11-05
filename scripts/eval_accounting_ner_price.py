#!/usr/bin/env python3
"""Holdout probe: Minns-ai/accounting-ner on offer_price + currency.

Repo ships ONNX only (no transformers config). We run onnxruntime + tokenizer.json.
Labels: PAYER / PAYEE / AMOUNT — no CURRENCY class, so currency uses $ / lexicon
cues around AMOUNT spans.
Offline comparison only — does not change the GLiNER pipeline.
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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.experiments import ensure_holdout
from src.evaluation.tender import load_gt, soft_match, normalize

FIELDS = ("offer_price", "currency")
MODEL_ID = "Minns-ai/accounting-ner"
MAX_LEN = 128

PRICE_CUES = (
    "offer price",
    "purchase price",
    "per share",
    "consideration",
    "cash",
    "nav",
    "net asset value",
    "tender",
    "price equal",
    "will pay",
    "paying",
)
CURRENCY_CUES = (
    "currency",
    "u.s. dollar",
    "us dollar",
    "usd",
    "dollar",
    "eur",
    "euro",
    "gbp",
    "pound",
    "cad",
    "per share",
    "$",
)

# Fallback currency lexicon if model only emits AMOUNT
_CURRENCY_TOKEN = re.compile(
    r"\b(?:USD|EUR|GBP|CAD|JPY|CHF|AUD|HKD|SGD|U\.?S\.?\s*dollars?|dollars?|euros?|pounds?)\b"
    r"|\$",
    re.I,
)

_WS = re.compile(r"\s+")
_NA = frozenset({"", "n/a", "na", "none", "null", "-", "—"})
_MONEYISH = re.compile(
    r"\$\s*[\d,]+(?:\.\d+)?|\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b",
)


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


def _quotes(passage: dict, *keys: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        items = passage.get(key) or []
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if not isinstance(it, dict):
                continue
            q = (it.get("quote") or "").strip()
            if len(q) < 8:
                continue
            k = q[:220]
            if k not in seen:
                seen.add(k)
                out.append(q)
    return out


def _window(text: str, start: int, end: int, radius: int = 100) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return text[a:b].lower()


class AccountingNerOnnx:
    """Thin ONNX wrapper matching HF pipeline-ish entity dicts."""

    def __init__(self, repo_id: str = MODEL_ID) -> None:
        from huggingface_hub import hf_hub_download
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = hf_hub_download(repo_id, "onnx/model.onnx")
        tok_path = hf_hub_download(repo_id, "onnx/tokenizer.json")
        lm_path = hf_hub_download(repo_id, "onnx/label_map.json")
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(tok_path)
        self.tokenizer.enable_truncation(max_length=MAX_LEN)
        self.tokenizer.enable_padding(length=MAX_LEN)
        id2label = json.loads(Path(lm_path).read_text(encoding="utf-8"))["id2label"]
        self.id2label = {int(k): v for k, v in id2label.items()}

    def __call__(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        # Prefer a money-cue window when text is long (max 128 tokens)
        chunk = text
        if len(text) > 500:
            low = text.lower()
            anchor = -1
            for cue in ("offer price", "per share", "net asset", "purchase price", "$"):
                anchor = low.find(cue)
                if anchor >= 0:
                    break
            if anchor < 0:
                anchor = 0
            start = max(0, anchor - 80)
            chunk = text[start : start + 700]
        else:
            start = 0

        enc = self.tokenizer.encode(chunk)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention = np.array([enc.attention_mask], dtype=np.int64)
        token_types = np.array(
            [enc.type_ids if enc.type_ids else [0] * len(enc.ids)], dtype=np.int64
        )
        feeds = {}
        for inp in self.session.get_inputs():
            name = inp.name
            if "input_ids" in name:
                feeds[name] = input_ids
            elif "attention" in name:
                feeds[name] = attention
            elif "token_type" in name:
                feeds[name] = token_types
            else:
                feeds[name] = input_ids
        logits = self.session.run(None, feeds)[0]  # [1, seq, n_labels]
        pred_ids = logits[0].argmax(axis=-1)
        scores = _softmax(logits[0]).max(axis=-1)

        # Aggregate BIO AMOUNT (and other) spans via offsets
        offsets = enc.offsets  # list[(start,end)] aligned to tokens
        ents: list[dict[str, Any]] = []
        i = 0
        n = len(pred_ids)
        while i < n:
            lab = self.id2label.get(int(pred_ids[i]), "O")
            if lab.startswith("B-"):
                group = lab[2:]
                j = i + 1
                while j < n and self.id2label.get(int(pred_ids[j]), "O") == f"I-{group}":
                    j += 1
                # char span from first/last non-empty offset
                spans = [offsets[k] for k in range(i, j) if offsets[k][1] > offsets[k][0]]
                if spans:
                    cs, ce = spans[0][0], spans[-1][1]
                    word = chunk[cs:ce].strip()
                    if word:
                        ents.append(
                            {
                                "text": _WS.sub(" ", word),
                                "label": group,
                                "score": float(scores[i:j].mean()),
                                "start": start + cs,
                                "end": start + ce,
                            }
                        )
                i = j
            else:
                i += 1
        return ents


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def pick_offer_price(quotes: list[str], tagger) -> tuple[str | None, list[dict]]:
    best: tuple[float, str] | None = None
    all_amt: list[dict] = []
    for quote in quotes:
        ents = tagger(quote)
        for e in ents:
            if "AMOUNT" not in e["label"].upper():
                if not _MONEYISH.search(e["text"]):
                    continue
            all_amt.append({**e, "quote": quote[:160]})
            win = _window(quote, e["start"], e["end"])
            cues = sum(1 for c in PRICE_CUES if c in win)
            bonus = 0.2 if "$" in e["text"] else 0.0
            bonus += 0.1 if "." in e["text"] else 0.0
            score = cues * 1.0 + bonus + 0.15 * e["score"]
            if best is None or score > best[0]:
                best = (score, e["text"])
        # Regex money fallback when model misses bare numbers
        for m in _MONEYISH.finditer(quote):
            val = m.group(0).strip()
            if len(val) < 1:
                continue
            all_amt.append(
                {
                    "text": val,
                    "label": "REGEX",
                    "score": 0.4,
                    "start": m.start(),
                    "end": m.end(),
                    "quote": quote[:160],
                }
            )
            win = quote[max(0, m.start() - 100) : m.end() + 100].lower()
            cues = sum(1 for c in PRICE_CUES if c in win)
            bonus = 0.25 if "$" in val else 0.0
            score = cues * 1.0 + bonus + 0.05
            # Only let regex win if cues present (avoid random years/counts)
            if cues == 0 and "$" not in val:
                continue
            if best is None or score > best[0]:
                best = (score, val)
    return (best[1] if best else None), all_amt


def pick_currency(quotes: list[str], tagger, price_pred: str | None) -> tuple[str | None, list[dict]]:
    """No CURRENCY label in accounting-ner — lexicon + $ near AMOUNT."""
    best: tuple[float, str] | None = None
    hits: list[dict] = []
    for quote in quotes:
        for e in tagger(quote):
            if "AMOUNT" not in e["label"].upper():
                continue
            win = _window(quote, e["start"], e["end"], 60)
            lex = _CURRENCY_TOKEN.search(win)
            if lex:
                val = lex.group(0)
                # Normalize $ → USD for soft_match friendliness later
                norm = "USD" if val.strip() == "$" else val
                hits.append({**e, "text": norm, "label": "AMOUNT+LEX", "quote": quote[:160]})
                cues = sum(1 for c in CURRENCY_CUES if c in win)
                score = 0.6 + cues * 0.5
                if best is None or score > best[0]:
                    best = (score, norm)

        for m in _CURRENCY_TOKEN.finditer(quote):
            val = m.group(0)
            norm = "USD" if val.strip() == "$" else val
            hits.append(
                {
                    "text": norm,
                    "label": "LEXICON",
                    "score": 0.5,
                    "start": m.start(),
                    "end": m.end(),
                    "quote": quote[:160],
                }
            )
            win = quote[max(0, m.start() - 80) : m.end() + 80].lower()
            cues = sum(1 for c in CURRENCY_CUES if c in win)
            score = 0.4 + cues * 0.8
            if best is None or score > best[0]:
                best = (score, norm)

    if best is None and price_pred and "$" in price_pred:
        return "USD", hits
    return (best[1] if best else None), hits


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r)) else None
    return {"precision": p, "recall": r, "f1": f1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe accounting NER on offer_price + currency")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--out", type=Path, default=ROOT / "outputs/tender_eval")
    p.add_argument("--model", default=MODEL_ID)
    p.add_argument("--device", default="cpu")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    print(json.dumps({"model": args.model, "device": args.device, "backend": "onnx"}, indent=2))
    tagger = AccountingNerOnnx(args.model)

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
    span_rec = {
        "offer_price": {"hit": 0, "miss": 0, "no_quote": 0},
        "currency": {"hit": 0, "miss": 0, "no_quote": 0},
    }
    details: list[dict[str, Any]] = []

    for row in rows:
        acc = (row.get("accession_number") or "").strip()
        passage = parse_passage(row.get("passage") or "")
        price_q = _quotes(passage, "offer_price", "offer_price_currency", "currency")
        # Broaden: also pull security / subject snippets if empty
        if not price_q:
            price_q = _quotes(passage, "security_description", "subject_company")

        price_pred, amts = pick_offer_price(price_q, tagger)
        cur_pred, curs = pick_currency(price_q, tagger, price_pred)

        preds = {"offer_price": price_pred, "currency": cur_pred}
        row_d: dict[str, Any] = {"accession": acc, "fields": {}, "n_quotes": len(price_q)}

        for field in FIELDS:
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

            # Span recall: any AMOUNT/CURRENCY soft-matches gold
            span_hit = None
            span_pred = None
            if has_gt:
                if not price_q:
                    span_rec[field]["no_quote"] += 1
                else:
                    cands = amts if field == "offer_price" else curs
                    ok = False
                    for c in cands:
                        if soft_match(c["text"], gold):
                            ok = True
                            span_pred = c["text"]
                            break
                    # For currency, also check lexicon soft_match on quote text
                    if not ok and field == "currency":
                        for q in price_q:
                            for m in _CURRENCY_TOKEN.finditer(q):
                                if soft_match(m.group(0), gold):
                                    ok = True
                                    span_pred = m.group(0)
                                    break
                            if ok:
                                break
                    span_hit = ok
                    span_rec[field]["hit" if ok else "miss"] += 1

            row_d["fields"][field] = {
                "outcome": outcome,
                "gold": gold if has_gt else None,
                "pred": pred,
                "span_hit": span_hit,
                "span_pred": span_pred,
            }
        details.append(row_d)
        print(
            f"  {acc}  price={price_pred!r} cur={cur_pred!r}  "
            f"gold_p={(row.get('offer_price') or '')[:40]!r} gold_c={(row.get('currency') or '')!r}"
        )

    per_field: dict[str, Any] = {}
    for f in FIELDS:
        s = stats[f]
        m = _prf(s["tp"], s["fp"], s["fn"])
        sr = span_rec[f]
        denom = sr["hit"] + sr["miss"]
        per_field[f] = {
            **s,
            **m,
            "span_recall": (sr["hit"] / denom) if denom else None,
            "span_hit": sr["hit"],
            "span_miss": sr["miss"],
            "span_no_quote": sr["no_quote"],
        }

    tp = sum(stats[f]["tp"] for f in FIELDS)
    fp = sum(stats[f]["fp"] for f in FIELDS)
    fn = sum(stats[f]["fn"] for f in FIELDS)
    summary = {
        "model": args.model,
        "device": args.device,
        "n_rows": len(rows),
        "micro": _prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_field": per_field,
        "baseline_gliner_medium_holdout_f1": {
            "offer_price": 0.478,
            "currency": 0.167,
        },
    }

    out_dir = args.out / "experiments" / "runs" / "accounting_ner_holdout_price"
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
                "span_recall",
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
                    "span_recall": row["span_recall"],
                }
            )

    print(json.dumps(summary, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
