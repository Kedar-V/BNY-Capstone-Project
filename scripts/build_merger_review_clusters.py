#!/usr/bin/env python3
"""Create evidence-window and conditional-term review queues from saved SEC text.

Rows are review leads, not verified deals or canonical extracted values.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

TERM_PATTERNS = {
    "effective_time_context": re.compile(r"\b(?:effective time|become effective|certificate of merger)\b", re.I),
    "exchange_ratio_context": re.compile(r"\b(?:exchange ratio|closing VWAP|stock consideration)\b", re.I),
}
CONDITIONAL = re.compile(r"\b(?:upon filing|filed with|closing date|immediately following|such other time|at the time of filing)\b", re.I)
FORMULA = re.compile(r"\b(?:divided by|quotient|VWAP|volume.weighted|average trading price)\b", re.I)


def term_evidence(text: str, max_each: int = 3) -> list[dict]:
    """Return exact source substrings; patterns nominate review passages only."""
    found = []
    for term, pattern in TERM_PATTERNS.items():
        count = 0
        for match in pattern.finditer(text):
            start, end = max(0, match.start() - 180), min(len(text), match.end() + 270)
            quote = text[start:end]
            if term == "effective_time_context" and not CONDITIONAL.search(quote):
                continue
            if term == "exchange_ratio_context" and not FORMULA.search(quote):
                continue
            found.append({"term": term, "start": start, "end": end, "source_quote": quote})
            count += 1
            if count >= max_each:
                break
    return found


def cluster_rows(doc: dict) -> list[dict]:
    """Group span candidates by source window, leaving deal identity for review."""
    by_window: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for field, candidates in doc.get("candidates", {}).items():
        for candidate in candidates:
            by_window[int(candidate["window_id"])][field].append(candidate)
    rows = []
    for window_id, fields in sorted(by_window.items()):
        top = {field: max(candidates, key=lambda x: float(x.get("score") or 0))
               for field, candidates in fields.items()}
        exemplar = max(top.values(), key=lambda x: float(x.get("score") or 0))
        rows.append({
            "accession_number": doc["accession_number"], "filing_date": doc.get("filing_date", ""),
            "window_id": window_id, "deal_id": "", "review_status": "",
            "acquirer_candidates": " | ".join(dict.fromkeys(x["value"] for x in sorted(fields.get("acquirer", []), key=lambda x: -float(x["score"]))[:4])),
            "target_candidates": " | ".join(dict.fromkeys(x["value"] for x in sorted(fields.get("target", []), key=lambda x: -float(x["score"]))[:4])),
            "cash_candidates": " | ".join(dict.fromkeys(x["value"] for x in sorted(fields.get("cash_consideration", []), key=lambda x: -float(x["score"]))[:3])),
            "source_quote": exemplar.get("source_quote", ""),
            "sec_source_url": doc.get("sec_source_url", ""),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.predictions.open(encoding="utf-8") as stream:
        docs = [json.loads(line) for line in stream if line.strip()]
    windows = []
    terms = []
    counts = Counter()
    with zipfile.ZipFile(args.archive) as archive:
        for doc in docs:
            windows.extend(cluster_rows(doc))
            raw = json.loads(archive.read(doc["archive_path"]))
            text = raw.get("text") or ""
            for match in term_evidence(text):
                terms.append({"accession_number": doc["accession_number"],
                              "filing_date": doc.get("filing_date", ""),
                              "term": match["term"], "start": match["start"],
                              "end": match["end"], "source_quote": match["source_quote"],
                              "deal_id": "", "review_status": ""})
                counts[match["term"]] += 1
    for name, rows, columns in (
        ("window_review_queue.csv", windows, ("accession_number", "filing_date", "window_id", "deal_id", "review_status", "acquirer_candidates", "target_candidates", "cash_candidates", "source_quote", "sec_source_url")),
        ("conditional_term_review_queue.csv", terms, ("accession_number", "filing_date", "term", "start", "end", "source_quote", "deal_id", "review_status")),
    ):
        with (args.out_dir / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    summary = {"documents": len(docs), "window_review_rows": len(windows),
               "conditional_term_review_rows": len(terms), "by_term": dict(counts),
               "note": "Review leads only. A window is not necessarily one deal. No reference or ground-truth value was used to select evidence."}
    (args.out_dir / "review_queue_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
