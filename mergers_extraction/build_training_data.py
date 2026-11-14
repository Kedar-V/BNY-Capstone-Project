#!/usr/bin/env python3
"""Build GLiNER fine-tuning data from the merger ground truth.

For every span field (common.SPAN_FIELDS) with a ground-truth value:
  1. find the field's supporting quotes in the filing text,
  2. find the value inside them, allowing for formatting ("6/11/2026" -> "June 11, 2026", "$16.00 per share" -> "$16.00"),
  3. cut a ~900-character passage around it.
Every passage is labelled with all ground-truth values of that filing that occur in it, so a true value is never
left unlabelled. Pipeline windows that hold no values are added as negatives: they teach the model that defined
terms ("Buyer", "Merger Sub", "Exchange Ratio"), tickers and par values are not answers.

Filings are split into train and holdout by deal (common.assign_splits), so the filings of one deal stay together.

    python mergers_extraction/build_training_data.py
    python mergers_extraction/build_training_data.py --gt notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers_sample.csv
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import common

WINDOW = 900          # characters per training passage, as at inference
MAX_SPAN_TOKENS = 12  # GLiNER's default max_width; longer spans cannot be predicted
WORD_NUMBERS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "ten": 10.0}


def flexible(text: str, max_tokens: int = 30) -> re.Pattern:
    """Regex for text that tolerates any whitespace between words (quotes are single-spaced, filings are not)."""
    words = text.split()[:max_tokens]
    return re.compile(r"\s+".join(re.escape(w) for w in words), re.I)


def value_spans(text: str, kind: str, gold: str) -> list[tuple[int, int]]:
    """Character spans in text that express the ground-truth value."""
    spans = []
    if kind in ("name", "text"):
        candidates = {gold.strip()}
        if kind == "name":  # also "flyExclusive" for "flyExclusive, Inc."
            short = re.sub(r",?\s*" + common.NAME_SUFFIXES + r"\s*$", "", gold.strip(), flags=re.I).strip(" ,")
            if len(short) >= 4:
                candidates.add(short)
        for cand in sorted(candidates, key=len, reverse=True):
            for m in flexible(cand, 60).finditer(text):
                if not any(a <= m.start() < b for a, b in spans):
                    spans.append((m.start(), m.end()))
    elif kind == "money":
        want = common.numbers(gold)
        if want:
            for m in re.finditer(r"(?:US|C|A)?\$\s?\d[\d,]*(?:\.\d+)?|€\s?\d[\d,]*(?:\.\d+)?", text):
                got = common.numbers(m.group(0))
                if got and abs(got[0] - want[0]) < 1e-9:
                    spans.append((m.start(), m.end()))
    elif kind == "number":  # exchange ratio: "0.2236 shares of ...", "one (1) share of ...", "Exchange Ratio means 0.2236"
        want = common.numbers(gold)
        if want:
            for m in re.finditer(r"(?<![\d.$,])(\d+(?:\.\d+)?|" + "|".join(WORD_NUMBERS) + r")(?:\s*\(\d+(?:\.\d+)?\))?(?![\d.,]*%)",
                                 text, re.I):
                word = m.group(1).lower()
                value = WORD_NUMBERS.get(word, None) if word in WORD_NUMBERS else float(word)
                if value is None or abs(value - want[0]) > 1e-9:
                    continue
                shares_after = re.match(r"\s+(?:of\s+a\s+)?(?:[\w.,&'’()-]+\s+){0,8}?shares?\b", text[m.end():m.end() + 120], re.I)
                ratio_before = re.search(r"exchange\s+ratio\W{0,3}\s*(?:means|of|is|equal\s+to|shall\s+be|will\s+be)\s*$",
                                         text[max(0, m.start() - 60):m.start()], re.I)
                if shares_after or ratio_before:
                    spans.append((m.start(), m.end()))
    elif kind == "date":
        want = common.parse_dates(gold)
        if want:
            spans = [(s, e) for d, s, e in common.parse_dates(text) if d == want[0][0]]
    return spans


def window_around(text: str, start: int, end: int, width: int = WINDOW) -> tuple[int, int]:
    """A width-sized window centred on [start, end), snapped to whitespace."""
    lo = max(0, (start + end) // 2 - width // 2)
    hi = min(len(text), lo + width)
    lo = max(0, hi - width)
    if lo > 0:
        cut = text.find(" ", lo)
        lo = cut + 1 if 0 <= cut < start else lo
    if hi < len(text):
        cut = text.rfind(" ", end, hi)
        hi = cut if cut > end else hi
    return lo, hi


def to_example(text: str, lo: int, hi: int, values: list[tuple[str, str, str]], accession: str) -> dict:
    """GLiNER training example: tokens plus inclusive token spans for every value found in text[lo:hi]."""
    chunk = text[lo:hi]
    toks = list(common.TOKEN_RE.finditer(chunk))
    ner, skipped = [], 0
    seen = set()
    for field, kind, gold in values:
        label = common.SPAN_FIELDS[field][0]
        for s, e in value_spans(chunk, kind, gold):
            idx = [i for i, t in enumerate(toks) if t.start() < e and t.end() > s]
            if not idx:
                continue
            if idx[-1] - idx[0] + 1 > MAX_SPAN_TOKENS:
                skipped += 1
                continue
            key = (idx[0], idx[-1], label)
            if key not in seen:
                seen.add(key)
                ner.append([idx[0], idx[-1], label])
    return {"accession": accession, "window_start": lo, "tokenized_text": [t.group(0) for t in toks],
            "ner": sorted(ner), "skipped_long_spans": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", type=Path, default=common.GT_PATH)
    ap.add_argument("--out", type=Path, default=common.TRAINING_DATA)
    ap.add_argument("--negatives-per-filing", type=int, default=3)
    ap.add_argument("--holdout-share", type=float, default=0.2)
    args = ap.parse_args()

    gt = common.load_ground_truth(args.gt)
    args.out.mkdir(parents=True, exist_ok=True)
    gt.to_csv(args.out / "ground_truth_snapshot.csv", index=False)  # the notebook may still be writing mergers.csv
    splits = common.assign_splits(gt, args.holdout_share)
    splits.to_csv(common.SPLITS_PATH if args.out == common.TRAINING_DATA else args.out / "splits.csv", index=False)
    split_of = dict(splits[["accession_number", "split"]].values)

    stats = defaultdict(Counter)
    examples = {"train": [], "holdout": []}
    for acc, records in gt.groupby("accession_number", sort=True):
        text = common.filing_text(acc)
        # all ground-truth span values of this filing, used to label every window
        values = []
        for _, row in records.iterrows():
            for field, (_, kind) in common.SPAN_FIELDS.items():
                gold = str(row.get(field, "")).strip()
                if common.blank(gold):
                    continue
                stats[field]["records_with_value"] += 1
                if common.absence(gold):
                    stats[field]["absence_values"] += 1
                    continue
                values.append((field, kind, gold))
        values = list(dict.fromkeys(values))

        # 1-3. passages around each value, found inside the field's own quotes
        windows: list[tuple[int, int]] = []
        for _, row in records.iterrows():
            passages = common.passages_of(row)
            for field, (_, kind) in common.SPAN_FIELDS.items():
                gold = str(row.get(field, "")).strip()
                if common.blank(gold) or common.absence(gold):
                    continue
                located = False
                for q in passages.get(field) or []:
                    quote = (q or {}).get("quote") if isinstance(q, dict) else None
                    if not quote:
                        continue
                    hit = flexible(quote).search(text)
                    if not hit:
                        stats[field]["quotes_not_in_filing"] += 1
                        continue
                    q_lo, q_hi = hit.start(), min(len(text), hit.start() + len(quote) + 200)
                    for s, e in value_spans(text[q_lo:q_hi], kind, gold):
                        windows.append(window_around(text, q_lo + s, q_lo + e))
                        located = True
                stats[field]["records_located" if located else "records_not_located"] += 1

        # merge near-duplicate windows
        windows = sorted(set(windows))
        merged = []
        for lo, hi in windows:
            if merged and lo < merged[-1][0] + WINDOW // 3:
                continue
            merged.append((lo, hi))
        positives = [to_example(text, lo, hi, values, acc) for lo, hi in merged]

        # negatives: pipeline windows away from the positives
        negatives = []
        for start, chunk in common.select_windows(text, max_windows=12):
            if len(negatives) >= args.negatives_per_filing:
                break
            if any(start < hi and lo < start + len(chunk) for lo, hi in merged):
                continue
            ex = to_example(text, start, start + len(chunk), values, acc)
            (positives if ex["ner"] else negatives).append(ex)
        split = split_of[acc]
        examples[split] += positives + negatives
        stats["_all"]["positive_passages"] += sum(1 for e in positives if e["ner"])
        stats["_all"]["negative_passages"] += len(negatives)
        for e in positives:
            for _, _, label in e["ner"]:
                stats["_spans"][label] += 1

    for split, rows in examples.items():
        with (args.out / f"{split}.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    coverage = []
    for field, (label, kind) in common.SPAN_FIELDS.items():
        s = stats[field]
        usable = s["records_with_value"] - s["absence_values"]
        coverage.append({"field": field, "label": label, "records_with_value": s["records_with_value"],
                         "stated_absences": s["absence_values"], "records_located": s["records_located"],
                         "located_share": round(s["records_located"] / usable, 3) if usable else None,
                         "training_spans": stats["_spans"][label]})
    coverage = pd.DataFrame(coverage)
    coverage.to_csv(args.out / "coverage.csv", index=False)
    split_counts = splits.groupby("split").agg(filings=("accession_number", "size"), deal_groups=("deal_group", "nunique"))
    summary = {"gt": str(args.gt), "filings": int(gt["accession_number"].nunique()), "records": len(gt),
               "splits": split_counts.to_dict("index"),
               "examples": {k: len(v) for k, v in examples.items()},
               "positive_passages": stats["_all"]["positive_passages"],
               "negative_passages": stats["_all"]["negative_passages"]}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    pd.set_option("display.width", 200)
    print(coverage.to_string(index=False))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
