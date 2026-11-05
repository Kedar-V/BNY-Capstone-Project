#!/usr/bin/env python3
"""Build GLiNER fine-tune JSONL from GT passage quotes (preferred) or clean-text anchors.

Token-level format:
  {"tokenized_text": [...], "ner": [[start, end, label], ...]}  # inclusive token idxs

Labels are inference-side GLiNER labels (offer_price_amount, …) so fine-tune matches predict.
Writes data/gliner_ft/tender_spans.jsonl by default.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.tender import CORE_GT_FIELDS, GT_TO_HINT, load_gt, normalize, soft_match
from src.evaluation.tender import gt_event_ids_from_corpus
from src.preprocess.contracts import GLINER_LABELS_TO, LABEL_TO_FIELD_HINT
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

_TOKEN_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")
_WS = re.compile(r"\s+")
_DATE_CAND = re.compile(
    r"(?:"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")"
    r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?(?:\s*,?\s*(?:Eastern|New York|NYC|ET|EST|EDT)(?:\s+Time)?)?)?",
    re.I,
)
_MONEY_CAND = re.compile(
    r"\$\s*[\d,]+(?:\.\d+)?(?:\s+per\s+(?:share|Share|unit|Unit))?"
    r"|(?:net asset value|NAV)(?:\s+per\s+(?:Share|share))?(?:\s+as\s+of\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4})?",
    re.I,
)

# field_hint → GLiNER label used at inference
HINT_TO_GLINER = {
    LABEL_TO_FIELD_HINT[lab]: lab for lab in GLINER_LABELS_TO if lab in LABEL_TO_FIELD_HINT
}

# GT column → passage dict key (currency is renamed in passage blob)
PASSAGE_KEY = {c: c for c in CORE_GT_FIELDS}
PASSAGE_KEY["currency"] = "offer_price_currency"


def tokenize_text(text: str) -> list[str]:
    return _TOKEN_RE.findall(text or "")


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


def _find_token_span(tokens: list[str], needle: str) -> tuple[int, int] | None:
    """Inclusive token [start, end] for needle in tokens."""
    if not tokens or not needle or normalize(needle) == "":
        return None
    ent = tokenize_text(needle)
    if not ent:
        return None
    n = len(ent)
    ent_l = [t.lower() for t in ent]
    for i in range(len(tokens) - n + 1):
        if [t.lower() for t in tokens[i : i + n]] == ent_l:
            return i, i + n - 1
    if len(needle) > 40:
        return _find_token_span(tokens, needle[:40])
    return None


def _char_span_to_tokens(text: str, tokens: list[str], start: int, end: int) -> tuple[int, int] | None:
    """Map char [start, end) in text onto inclusive token indices."""
    if start < 0 or end <= start or end > len(text):
        return None
    # rebuild token char offsets via sequential search
    pos = 0
    spans: list[tuple[int, int]] = []
    for tok in tokens:
        idx = text.find(tok, pos)
        if idx < 0:
            return None
        spans.append((idx, idx + len(tok)))
        pos = idx + len(tok)
    t0 = t1 = None
    for i, (a, b) in enumerate(spans):
        if b <= start:
            continue
        if a >= end:
            break
        if t0 is None:
            t0 = i
        t1 = i
    if t0 is None or t1 is None:
        return None
    return t0, t1


def _find_value_in_quote(quote: str, value: str, field: str) -> str | None:
    """Return the substring of quote to annotate, or None."""
    if not quote or not value or normalize(value) == "":
        return None
    q_low = quote.lower()
    v = value.strip()
    # exact / case-insensitive
    i = q_low.find(v.lower())
    if i >= 0:
        return quote[i : i + len(v)]
    # collapsed whitespace
    v_flat = _WS.sub(" ", v).strip()
    q_flat = _WS.sub(" ", quote)
    j = q_flat.lower().find(v_flat.lower())
    if j >= 0:
        # map flat index back is hard; use flat quote as text later via tokenize match
        return v_flat if v_flat.lower() in quote.lower() else None
    # prefix for long narrative GT
    if len(v) > 48:
        prefix = v[:48].rstrip()
        i = q_low.find(prefix.lower())
        if i >= 0:
            return quote[i : i + len(prefix)]
    # soft date / money candidates inside quote
    if field in {
        "expiration_date",
        "withdrawal_deadline",
        "settlement_date",
        "effective_date",
    }:
        for m in _DATE_CAND.finditer(quote):
            if soft_match(m.group(0), v):
                return m.group(0)
    if field == "offer_price":
        for m in _MONEY_CAND.finditer(quote):
            if soft_match(m.group(0), v):
                return m.group(0)
    return None


def _gliner_label(gt_col: str) -> str | None:
    hint = GT_TO_HINT.get(gt_col)
    if not hint:
        return None
    return HINT_TO_GLINER.get(hint)


def build_from_passages(gt_rows: list[dict], *, max_quote_chars: int = 1200) -> list[dict]:
    """One example per (accession, quote) with ≥1 anchored span."""
    # (accession, quote) → list of (label, span_text)
    buckets: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    meta: dict[tuple[str, str], dict] = {}

    for row in gt_rows:
        acc = (row.get("accession_number") or "").strip()
        if not acc:
            continue
        passage = parse_passage(row.get("passage") or "")
        if not passage:
            continue
        for col in CORE_GT_FIELDS:
            label = _gliner_label(col)
            if not label:
                continue
            val = (row.get(col) or "").strip()
            if normalize(val) == "":
                continue
            pk = PASSAGE_KEY.get(col, col)
            items = passage.get(pk) or passage.get(col) or []
            if not isinstance(items, list):
                items = [items]
            for it in items:
                if not isinstance(it, dict):
                    continue
                quote = (it.get("quote") or "").strip()
                if len(quote) < 8:
                    continue
                if len(quote) > max_quote_chars:
                    # keep a window around the first hit if possible
                    hit = _find_value_in_quote(quote, val, col)
                    if hit:
                        k = quote.lower().find(hit.lower())
                        lo = max(0, k - max_quote_chars // 3)
                        hi = min(len(quote), lo + max_quote_chars)
                        quote = quote[lo:hi]
                    else:
                        quote = quote[:max_quote_chars]
                span_text = _find_value_in_quote(quote, val, col)
                if not span_text:
                    continue
                key = (acc, quote)
                buckets[key].append((label, span_text))
                meta[key] = {
                    "accession": acc,
                    "location": it.get("location"),
                    "field_seed": col,
                }

    examples: list[dict] = []
    for (acc, quote), spans in buckets.items():
        tokens = tokenize_text(quote)
        if not tokens:
            continue
        ner: list[list] = []
        seen: set[tuple[int, int, str]] = set()
        for label, span_text in spans:
            # prefer char→token when exact substring exists
            i = quote.lower().find(span_text.lower())
            tok_span = None
            if i >= 0:
                tok_span = _char_span_to_tokens(quote, tokens, i, i + len(span_text))
            if tok_span is None:
                tok_span = _find_token_span(tokens, span_text)
            if tok_span is None:
                continue
            key = (tok_span[0], tok_span[1], label)
            if key in seen:
                continue
            seen.add(key)
            ner.append([tok_span[0], tok_span[1], label])
        if not ner:
            continue
        examples.append(
            {
                "tokenized_text": tokens,
                "ner": ner,
                "accession": acc,
                "source": "passage",
                "location": (meta.get((acc, quote)) or {}).get("location"),
            }
        )
    return examples


def build_from_clean(
    gt_rows: list[dict],
    *,
    preprocess_root: Path,
    documents_parquet: Path,
    accessions: list[str] | None = None,
) -> list[dict]:
    """Legacy: string-search GT values in cleaned filing text."""
    acc_set = set(accessions) if accessions is not None else {
        (r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")
    }
    acc_to_eid: dict[str, str] = {}
    if documents_parquet.exists():
        acc_to_eid = gt_event_ids_from_corpus(acc_set, documents_parquet)
    store = ArtifactStore("tender", preprocess_root)
    by_acc: dict[str, dict] = {}
    for r in gt_rows:
        a = (r.get("accession_number") or "").strip()
        if a and a not in by_acc:
            by_acc[a] = r

    examples: list[dict] = []
    for acc in sorted(acc_set):
        eid = acc_to_eid.get(acc)
        if not eid:
            continue
        inv_path = store.inventory_path(eid)
        if not inv_path.exists():
            continue
        inv = store.read_json(inv_path)
        texts: list[str] = []
        for doc in inv.get("docs") or []:
            if (doc.get("accession") or "") != acc:
                continue
            tp = store.clean_text_path(eid, acc, doc.get("filename") or "")
            if tp.exists():
                texts.append(tp.read_text(encoding="utf-8", errors="replace"))
        if not texts:
            continue
        blob = "\n\n".join(texts)[:12000]
        tokens = tokenize_text(blob)
        row = by_acc.get(acc)
        if not row or not tokens:
            continue
        ner: list[list] = []
        for col in CORE_GT_FIELDS:
            label = _gliner_label(col)
            if not label:
                continue
            val = (row.get(col) or "").strip()
            if normalize(val) == "":
                continue
            span = _find_token_span(tokens, val)
            if not span:
                continue
            ner.append([span[0], span[1], label])
        if not ner:
            continue
        examples.append(
            {
                "tokenized_text": tokens,
                "ner": ner,
                "accession": acc,
                "event_id": eid,
                "source": "clean",
            }
        )
    return examples


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build tender GLiNER span JSONL")
    p.add_argument("--gt", type=Path, default=ROOT / "notebooks/evaluation/tender_offers.csv")
    p.add_argument("--preprocess-root", type=Path, default=DEFAULT_PREPROCESS_ROOT)
    p.add_argument("--documents-parquet", type=Path, default=ROOT / "data/processed/documents.parquet")
    p.add_argument("--out", type=Path, default=ROOT / "data/gliner_ft/tender_spans.jsonl")
    p.add_argument(
        "--source",
        choices=("passage", "clean", "both"),
        default="passage",
        help="passage=GT passage quotes (default); clean=filing text; both=concat",
    )
    p.add_argument("--holdout", type=Path, default=None, help="If set, only these accessions")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-quote-chars", type=int, default=1200)
    args = p.parse_args(argv)

    gt_rows = load_gt(args.gt)
    holdout: set[str] = set()
    if args.holdout and Path(args.holdout).exists():
        holdout = {ln.strip() for ln in Path(args.holdout).read_text().splitlines() if ln.strip()}
        gt_rows = [r for r in gt_rows if (r.get("accession_number") or "").strip() in holdout]
    if args.limit:
        # limit by unique accession order
        seen: list[str] = []
        keep = []
        for r in gt_rows:
            a = (r.get("accession_number") or "").strip()
            if a not in seen:
                if len(seen) >= args.limit:
                    continue
                seen.append(a)
            if a in seen:
                keep.append(r)
        gt_rows = keep

    examples: list[dict] = []
    if args.source in {"passage", "both"}:
        examples.extend(build_from_passages(gt_rows, max_quote_chars=args.max_quote_chars))
    if args.source in {"clean", "both"}:
        accs = sorted({(r.get("accession_number") or "").strip() for r in gt_rows if r.get("accession_number")})
        examples.extend(
            build_from_clean(
                gt_rows,
                preprocess_root=args.preprocess_root,
                documents_parquet=args.documents_parquet,
                accessions=accs,
            )
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_spans = 0
    label_counts: dict[str, int] = defaultdict(int)
    with args.out.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            n_spans += len(ex["ner"])
            for _s, _e, lab in ex["ner"]:
                label_counts[lab] += 1

    summary = {
        "out": str(args.out),
        "source": args.source,
        "n_examples": len(examples),
        "n_spans": n_spans,
        "n_accessions": len({e.get("accession") for e in examples}),
        "labels": dict(sorted(label_counts.items(), key=lambda kv: -kv[1])),
    }
    print(json.dumps(summary, indent=2))
    return 0 if examples else 1


if __name__ == "__main__":
    raise SystemExit(main())
